"""
Step 5a: Weekly status report - the text a program manager would send to stakeholders.
Run on its own:  python report.py   (writes data/status_report.md)
"""
import pandas as pd

import metrics as m
from config import DATA_DIR

ARROW = {True: "up", False: "down"}


def _fmt(x, unit, nd=1):
    return "n/a" if pd.isna(x) else f"{x:.{nd}f} {unit}"


def build_report(d, now=None, top_n=5):
    now = now or m.as_of(d)
    pt = m.pr_table(d["prs"], d["reviews"])
    flow = m.weekly_flow(pt, now)
    bugs = m.weekly_bugs(d["issues"], now)
    h = m.health(flow, bugs)
    overall = m.overall_status(h)
    stale = m.stale_prs(pt, now)
    rel = m.release_gaps(d["releases"])
    last = flow.iloc[-1]
    prev4 = flow.iloc[-5:-1]

    lines = [
        f"# Weekly engineering status - {d['meta'].get('repo', '')}",
        f"Week of {flow['week'].iloc[-1]:%d %b %Y}  |  Overall health: **{overall}**",
        "",
        "## Summary",
        f"- Merged {int(last['merged_prs'])} PRs this week "
        f"(4-week average: {prev4['merged_prs'].mean():.1f}).",
        f"- Median PR cycle time: {_fmt(last['cycle_median_days'], 'days')}.",
        f"- Median time to first review: {_fmt(last['review_median_hours'], 'hours')}.",
        f"- Open bugs: {int(bugs['open_bugs'].iloc[-1])} "
        f"({int(bugs['bugs_opened'].iloc[-1])} opened, {int(bugs['bugs_closed'].iloc[-1])} closed this week).",
    ]
    if not rel.empty:
        latest = rel.iloc[-1]
        lines.append(f"- Latest stable release: {latest['tag']} on {latest['published_at']:%d %b %Y}.")

    lines += ["", "## Health by area (last 4 weeks vs previous 12)"]
    for _, r in h.iterrows():
        chg = "no data" if pd.isna(r["change"]) else f"{ARROW[r['change'] > 0]} {abs(r['change']):.0%}"
        lines.append(f"- {r['area']}: **{r['status']}** - {r['kpi']} {chg}")

    lines += ["", f"## Risks and asks ({len(stale)} stale PRs)"]
    red = h[h["status"] == "Red"]
    for _, r in red.iterrows():
        lines.append(f"- {r['area']} is Red: {r['kpi']} moved {abs(r['change']):.0%} the wrong way. Owner to review.")
    for _, r in stale.head(top_n).iterrows():
        lines.append(f"- PR #{int(r['number'])} idle {r['idle_days']:.0f} days: {r['title']}")
    if red.empty and stale.empty:
        lines.append("- No blocking risks this week.")
    return "\n".join(lines)


if __name__ == "__main__":
    text = build_report(m.load())
    open(f"{DATA_DIR}/status_report.md", "w").write(text)
    print(text)
