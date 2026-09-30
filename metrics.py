"""
Step 3: Turn the raw CSVs into delivery KPIs.

Every function takes DataFrames and returns DataFrames/numbers, so the
Streamlit app, the status report and the forecast all share one source of truth.
"""
import json
import os

import numpy as np
import pandas as pd

from config import (DATA_DIR, RECENT_WEEKS, BASELINE_WEEKS, AMBER_CHANGE,
                    RED_CHANGE, STALE_PR_DAYS)

DATE_COLS = {
    "prs": ["created_at", "updated_at", "closed_at", "merged_at"],
    "reviews": ["first_review_at"],
    "issues": ["created_at", "closed_at"],
    "releases": ["published_at"],
}


# ---------------- loading ----------------

def as_of(d):
    """Analysis date = when the data was collected (not today), so old data still charts correctly."""
    ts = d.get("meta", {}).get("collected_at")
    return pd.Timestamp(ts).tz_convert("UTC") if ts else pd.Timestamp.now(tz="UTC")


def load(data_dir=DATA_DIR):
    d = {}
    for name, cols in DATE_COLS.items():
        path = os.path.join(data_dir, f"{name}.csv")
        df = pd.read_csv(path) if os.path.exists(path) and os.path.getsize(path) > 1 else pd.DataFrame()
        for c in cols:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
        d[name] = df
    meta_path = os.path.join(data_dir, "meta.json")
    d["meta"] = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    return d


def pr_table(prs, reviews, include_bots=False):
    """One row per PR with cycle time (days) and first-review time (hours)."""
    df = prs.copy()
    if not include_bots:
        df = df[~df["author_is_bot"].astype(bool)]
    if not reviews.empty:
        df = df.merge(reviews, on="number", how="left")
    else:
        df["first_review_at"] = pd.NaT
    df["cycle_days"] = (df["merged_at"] - df["created_at"]).dt.total_seconds() / 86400
    df["review_hours"] = (df["first_review_at"] - df["created_at"]).dt.total_seconds() / 3600
    # a "review" before the PR was opened is a data glitch; drop it
    df.loc[df["review_hours"] < 0, "review_hours"] = np.nan
    return df


# ---------------- weekly series ----------------

def _week(s):
    """Monday-start week label, timezone dropped for clean charts."""
    return s.dt.tz_convert(None).dt.to_period("W-SUN").dt.start_time


def week_index(end):
    """All week starts in the analysis window, so empty weeks show as 0, not gaps."""
    end = pd.Timestamp(end).tz_convert(None) if pd.Timestamp(end).tzinfo else pd.Timestamp(end)
    # the current week is still in progress, so stop at the last COMPLETE week
    last = end.to_period("W-SUN").start_time - pd.Timedelta(days=7)
    return pd.date_range(end=last, periods=52, freq="W-MON")


def weekly_flow(pt, end):
    """Throughput, median/p85 cycle time and median review time per week."""
    weeks = week_index(end)
    merged = pt.dropna(subset=["merged_at"]).copy()
    merged["week"] = _week(merged["merged_at"])
    g = merged.groupby("week")
    out = pd.DataFrame(index=weeks)
    out["merged_prs"] = g.size().reindex(weeks, fill_value=0)
    out["cycle_median_days"] = g["cycle_days"].median().reindex(weeks)
    out["cycle_p85_days"] = g["cycle_days"].quantile(0.85).reindex(weeks)

    rv = pt.dropna(subset=["first_review_at"]).copy()
    rv["week"] = _week(rv["created_at"])
    out["review_median_hours"] = rv.groupby("week")["review_hours"].median().reindex(weeks)
    out.index.name = "week"
    return out.reset_index()


def weekly_bugs(issues, end):
    """Open-bug backlog at each week end, plus bugs opened/closed that week."""
    weeks = week_index(end)
    bugs = issues[issues["is_bug"].astype(bool)] if not issues.empty else issues
    rows = []
    for w in weeks:
        w_end = (w + pd.Timedelta(days=7)).tz_localize("UTC")
        w_start = w.tz_localize("UTC")
        if bugs.empty:
            rows.append((w, 0, 0, 0))
            continue
        open_now = ((bugs["created_at"] < w_end) &
                    (bugs["closed_at"].isna() | (bugs["closed_at"] >= w_end))).sum()
        opened = bugs["created_at"].between(w_start, w_end, inclusive="left").sum()
        closed = bugs["closed_at"].between(w_start, w_end, inclusive="left").sum()
        rows.append((w, int(open_now), int(opened), int(closed)))
    return pd.DataFrame(rows, columns=["week", "open_bugs", "bugs_opened", "bugs_closed"])


def bug_resolution_days(issues):
    if issues.empty:
        return pd.Series(dtype=float)
    b = issues[issues["is_bug"].astype(bool) & issues["closed_at"].notna()]
    return (b["closed_at"] - b["created_at"]).dt.total_seconds() / 86400


def release_gaps(releases, stable_only=True):
    if releases.empty:
        return releases
    r = releases.dropna(subset=["published_at"])
    if stable_only:
        r = r[~r["prerelease"].astype(bool)]
    r = r.sort_values("published_at").copy()
    r["days_since_prev"] = r["published_at"].diff().dt.total_seconds() / 86400
    return r


def stale_prs(pt, now):
    open_prs = pt[(pt["state"] == "open") & (~pt["draft"].astype(bool))].copy()
    open_prs["idle_days"] = (now - open_prs["updated_at"]).dt.total_seconds() / 86400
    open_prs["age_days"] = (now - open_prs["created_at"]).dt.total_seconds() / 86400
    return open_prs[open_prs["idle_days"] >= STALE_PR_DAYS].sort_values("idle_days", ascending=False)


# ---------------- health (RAG) ----------------

def _compare(series, higher_is_worse=True):
    """Last RECENT_WEEKS vs the BASELINE_WEEKS before them -> (recent, baseline, change, status)."""
    recent = series.iloc[-RECENT_WEEKS:]
    base = series.iloc[-(RECENT_WEEKS + BASELINE_WEEKS):-RECENT_WEEKS]
    r, b = recent.median(), base.median()
    if pd.isna(r) or pd.isna(b) or b == 0:
        return r, b, np.nan, "Grey"
    change = (r - b) / b
    worse = change if higher_is_worse else -change
    status = "Red" if worse >= RED_CHANGE else "Amber" if worse >= AMBER_CHANGE else "Green"
    return r, b, change, status


def health(flow, bugs):
    """One row per KPI area with its RAG status."""
    rows = [
        ("Delivery speed", "Median PR cycle time (days)", *_compare(flow["cycle_median_days"], True)),
        ("Review responsiveness", "Median time to first review (hours)", *_compare(flow["review_median_hours"], True)),
        ("Throughput", "PRs merged per week", *_compare(flow["merged_prs"].astype(float), False)),
        ("Quality", "Open bug backlog", *_compare(bugs["open_bugs"].astype(float), True)),
    ]
    return pd.DataFrame(rows, columns=["area", "kpi", "recent", "baseline", "change", "status"])


def overall_status(h):
    s = set(h["status"])
    return "Red" if "Red" in s else "Amber" if "Amber" in s else "Green" if "Green" in s else "Grey"


# ---------------- forecast (links to the Risk Simulator idea) ----------------

def forecast_weeks(flow, backlog, runs=10000, history_weeks=12, seed=42):
    """
    Monte Carlo: how many weeks to merge `backlog` PRs, sampling weekly
    throughput from the last `history_weeks` of real data.
    Returns the array of simulated week counts.
    """
    hist = flow["merged_prs"].iloc[-history_weeks:].to_numpy()
    if backlog <= 0 or hist.sum() == 0:
        return np.array([])
    rng = np.random.default_rng(seed)
    cap = 520  # 10 years: safety stop
    samples = rng.choice(hist, size=(runs, cap))
    done = np.cumsum(samples, axis=1) >= backlog
    weeks = done.argmax(axis=1) + 1
    weeks[~done.any(axis=1)] = cap
    return weeks
