"""
Step 2: Pull raw delivery data from the GitHub REST API and save it as CSVs.

Usage:
    export GITHUB_TOKEN=ghp_xxx        # Windows: set GITHUB_TOKEN=ghp_xxx
    python collect.py

Outputs (in data/):
    prs.csv, reviews.csv, issues.csv, releases.csv
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from config import REPO, WINDOW_DAYS, DATA_DIR

API = "https://api.github.com"


def make_session():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("Set the GITHUB_TOKEN environment variable first (see README).")
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return s


def get(session, url, params=None):
    """GET with automatic wait when the rate limit is hit."""
    while True:
        r = session.get(url, params=params, timeout=30)
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - time.time(), 0) + 5
            print(f"  rate limit hit, waiting {wait:.0f}s ...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r


def paginate(session, url, params=None, stop=None):
    """Yield items page by page. `stop(item)` returning True ends the loop early."""
    params = dict(params or {}, per_page=100)
    while url:
        r = get(session, url, params)
        for item in r.json():
            if stop and stop(item):
                return
            yield item
        url = r.links.get("next", {}).get("url")
        params = None  # the "next" link already carries the query string


def is_bot(user):
    if not user:
        return True
    return user.get("type") == "Bot" or user.get("login", "").endswith("[bot]")


# ---------- row builders (kept separate so they are easy to test) ----------

def pr_row(pr):
    return {
        "number": pr["number"],
        "title": pr["title"],
        "author": (pr.get("user") or {}).get("login"),
        "author_is_bot": is_bot(pr.get("user")),
        "state": pr["state"],
        "draft": pr.get("draft", False),
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"],
        "closed_at": pr["closed_at"],
        "merged_at": pr["merged_at"],
        "labels": ";".join(l["name"] for l in pr.get("labels", [])),
        "url": pr["html_url"],
    }


def first_review_row(pr_number, pr_author, reviews):
    """Earliest review by a human who is not the PR author."""
    times = [
        rv["submitted_at"] for rv in reviews
        if rv.get("submitted_at")
        and not is_bot(rv.get("user"))
        and (rv.get("user") or {}).get("login") != pr_author
    ]
    return {"number": pr_number, "first_review_at": min(times) if times else None,
            "review_count": len(times)}


def issue_row(issue):
    labels = [l["name"] for l in issue.get("labels", [])]
    return {
        "number": issue["number"],
        "title": issue["title"],
        "state": issue["state"],
        "created_at": issue["created_at"],
        "closed_at": issue["closed_at"],
        "labels": ";".join(labels),
        "is_bug": any("bug" in l.lower() for l in labels),
        "url": issue["html_url"],
    }


def release_row(rel):
    return {
        "tag": rel["tag_name"],
        "name": rel.get("name") or rel["tag_name"],
        "published_at": rel["published_at"],
        "prerelease": rel["prerelease"],
        "url": rel["html_url"],
    }


# ---------- collectors ----------

def collect_prs(s, since):
    base = f"{API}/repos/{REPO}/pulls"
    too_old = lambda pr: pr["created_at"] < since
    # 1) every PR created inside the window (newest first, stop at the window edge)
    recent = paginate(s, base, {"state": "all", "sort": "created", "direction": "desc"}, stop=too_old)
    rows = {pr["number"]: pr_row(pr) for pr in recent}
    # 2) older PRs that are still open (needed for the stale-PR list)
    for pr in paginate(s, base, {"state": "open"}):
        rows.setdefault(pr["number"], pr_row(pr))
    return pd.DataFrame(rows.values())


def collect_reviews(s, prs):
    out = []
    targets = prs[~prs["author_is_bot"]]
    for i, (num, author) in enumerate(zip(targets["number"], targets["author"]), 1):
        reviews = list(paginate(s, f"{API}/repos/{REPO}/pulls/{num}/reviews"))
        out.append(first_review_row(num, author, reviews))
        if i % 50 == 0:
            print(f"  reviews fetched for {i}/{len(targets)} PRs")
    return pd.DataFrame(out, columns=["number", "first_review_at", "review_count"])


def collect_issues(s, since):
    base = f"{API}/repos/{REPO}/issues"
    rows = {}
    # issues touched inside the window + every issue still open
    for params in ({"state": "all", "since": since}, {"state": "open"}):
        for it in paginate(s, base, params):
            if "pull_request" in it:       # the issues API also returns PRs; skip them
                continue
            rows.setdefault(it["number"], issue_row(it))
    return pd.DataFrame(rows.values())


def collect_releases(s):
    rels = [r for r in paginate(s, f"{API}/repos/{REPO}/releases") if not r.get("draft")]
    return pd.DataFrame([release_row(r) for r in rels])


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    s = make_session()
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Collecting {REPO} since {since[:10]}")

    prs = collect_prs(s, since)
    print(f"  {len(prs)} PRs")
    if prs.empty:
        sys.exit("No PRs found. Check REPO in config.py.")
    reviews = collect_reviews(s, prs)
    issues = collect_issues(s, since)
    print(f"  {len(issues)} issues ({int(issues['is_bug'].sum()) if not issues.empty else 0} bugs)")
    releases = collect_releases(s)
    print(f"  {len(releases)} releases")

    prs.to_csv(f"{DATA_DIR}/prs.csv", index=False)
    reviews.to_csv(f"{DATA_DIR}/reviews.csv", index=False)
    issues.to_csv(f"{DATA_DIR}/issues.csv", index=False)
    releases.to_csv(f"{DATA_DIR}/releases.csv", index=False)
    pd.Series({"repo": REPO, "collected_at": datetime.now(timezone.utc).isoformat()}) \
        .to_json(f"{DATA_DIR}/meta.json")
    print("Done. Now run:  streamlit run app.py")


if __name__ == "__main__":
    main()
