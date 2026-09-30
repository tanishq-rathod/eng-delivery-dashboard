"""
Step 4: Engineering Delivery Health dashboard.
Run:  streamlit run app.py
"""
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import metrics as m
import report
from config import DATA_DIR, RECENT_WEEKS, BASELINE_WEEKS

st.set_page_config(page_title="Engineering Delivery Health", page_icon="\U0001F6A6", layout="wide")

INK, STEEL, MIST = "#1B2A41", "#2F5D8A", "#9FB3C8"
RAG = {"Green": "#2E7D5B", "Amber": "#C98A1B", "Red": "#B8413A", "Grey": "#8A96A3"}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stMetric { font-family: 'IBM Plex Sans', sans-serif; }
.health { border-radius: 6px; padding: 14px 16px; color: #fff; min-height: 118px; }
.health .area { font-size: 0.95rem; font-weight: 500; opacity: 0.92; }
.health .status { font-size: 1.7rem; font-weight: 600; line-height: 1.2; margin: 2px 0 6px; }
.health .kpi { font-size: 0.85rem; opacity: 0.92; }
</style>
""", unsafe_allow_html=True)


def style(fig, y_title):
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320, plot_bgcolor="white",
                      paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK), legend_title_text="",
                      yaxis_title=y_title, xaxis_title="")
    fig.update_yaxes(gridcolor="#E3E8EE")
    return fig


# ---------------- data ----------------
if not os.path.exists(os.path.join(DATA_DIR, "prs.csv")):
    st.title("Engineering Delivery Health")
    st.info("No data yet. Run `python collect.py` to pull data from GitHub, then refresh this page.")
    st.stop()

d = m.load()
now = m.as_of(d)

with st.sidebar:
    st.subheader("Data")
    st.write(f"Repository: **{d['meta'].get('repo', 'unknown')}**")
    st.write(f"Collected: {now:%d %b %Y, %H:%M} UTC")
    include_bots = st.toggle("Include bot PRs (e.g. dependabot)", value=False,
                             help="Bot PRs merge fast and make cycle time look better than it is.")
    st.caption(f"Health = last {RECENT_WEEKS} weeks vs the {BASELINE_WEEKS} weeks before. "
               "10% worse = Amber, 25% worse = Red.")

pt = m.pr_table(d["prs"], d["reviews"], include_bots)
flow = m.weekly_flow(pt, now)
bugs = m.weekly_bugs(d["issues"], now)
h = m.health(flow, bugs)
overall = m.overall_status(h)

# ---------------- header + health strip ----------------
st.title("Engineering Delivery Health")
st.write(f"{d['meta'].get('repo', '')} | last complete week starting "
         f"{flow['week'].iloc[-1]:%d %b %Y} | overall: **{overall}**")

cols = st.columns(len(h))
for col, (_, r) in zip(cols, h.iterrows()):
    if pd.isna(r["change"]):
        detail = "Not enough data"
    else:
        direction = "up" if r["change"] > 0 else "down"
        detail = f"{r['kpi']}: {r['recent']:.1f} ({direction} {abs(r['change']):.0%} vs baseline)"
    col.markdown(
        f"<div class='health' style='background:{RAG[r['status']]}'>"
        f"<div class='area'>{r['area']}</div><div class='status'>{r['status']}</div>"
        f"<div class='kpi'>{detail}</div></div>", unsafe_allow_html=True)

st.write("")
tab_flow, tab_quality, tab_rel, tab_stale, tab_report, tab_fc = st.tabs(
    ["Flow", "Quality", "Releases", "Stale PRs", "Status report", "Forecast"])

# ---------------- flow ----------------
with tab_flow:
    c1, c2 = st.columns(2)
    fig = px.bar(flow, x="week", y="merged_prs", color_discrete_sequence=[STEEL])
    c1.markdown("**Throughput** - PRs merged per week")
    c1.plotly_chart(style(fig, "PRs merged"), use_container_width=True)

    long = flow.melt(id_vars="week", value_vars=["cycle_median_days", "cycle_p85_days"],
                     var_name="measure", value_name="days")
    long["measure"] = long["measure"].map({"cycle_median_days": "Median", "cycle_p85_days": "85th percentile"})
    fig = px.line(long, x="week", y="days", color="measure", color_discrete_sequence=[STEEL, MIST])
    c2.markdown("**PR cycle time** - days from opened to merged")
    c2.plotly_chart(style(fig, "Days"), use_container_width=True)

    c3, c4 = st.columns(2)
    fig = px.line(flow, x="week", y="review_median_hours", color_discrete_sequence=[STEEL], markers=True)
    c3.markdown("**Time to first review** - median hours, by week the PR was opened")
    c3.plotly_chart(style(fig, "Hours"), use_container_width=True)

    merged = pt.dropna(subset=["cycle_days"])
    fig = px.histogram(merged, x="cycle_days", nbins=40, color_discrete_sequence=[STEEL])
    c4.markdown(f"**Cycle time distribution** - {len(merged)} merged PRs")
    c4.plotly_chart(style(fig, "PRs").update_xaxes(title="Days"), use_container_width=True)

# ---------------- quality ----------------
with tab_quality:
    c1, c2 = st.columns(2)
    fig = px.area(bugs, x="week", y="open_bugs", color_discrete_sequence=[RAG["Red"]])
    c1.markdown("**Open bug backlog** - at the end of each week")
    c1.plotly_chart(style(fig, "Open bugs"), use_container_width=True)

    fig = go.Figure([go.Bar(x=bugs["week"], y=bugs["bugs_opened"], name="Opened", marker_color=RAG["Red"]),
                     go.Bar(x=bugs["week"], y=bugs["bugs_closed"], name="Closed", marker_color=RAG["Green"])])
    c2.markdown("**Bugs opened vs closed** - backlog grows when red beats green")
    c2.plotly_chart(style(fig, "Bugs"), use_container_width=True)

    res = m.bug_resolution_days(d["issues"])
    if len(res):
        a, b, c = st.columns(3)
        a.metric("Median bug resolution", f"{res.median():.0f} days")
        b.metric("85th percentile", f"{res.quantile(0.85):.0f} days")
        c.metric("Bugs closed in window", f"{len(res)}")
    else:
        st.info("No closed bugs found. The repo may label bugs differently; see is_bug in collect.py.")

# ---------------- releases ----------------
with tab_rel:
    stable_only = st.toggle("Stable releases only", value=True)
    rel = m.release_gaps(d["releases"], stable_only)
    if rel.empty:
        st.info("No releases found for this repository.")
    else:
        recent = rel[rel["published_at"] >= now - pd.Timedelta(days=365)]
        a, b, c = st.columns(3)
        a.metric("Releases in last 12 months", len(recent))
        b.metric("Median gap between releases", f"{recent['days_since_prev'].median():.0f} days"
                 if recent["days_since_prev"].notna().any() else "n/a")
        c.metric("Latest", rel.iloc[-1]["tag"])
        fig = px.scatter(recent, x="published_at", y="days_since_prev", text="tag",
                         color_discrete_sequence=[STEEL])
        fig.update_traces(textposition="top center")
        st.markdown("**Release cadence** - days since the previous release")
        st.plotly_chart(style(fig, "Days since previous"), use_container_width=True)

# ---------------- stale PRs ----------------
with tab_stale:
    stale = m.stale_prs(pt, now)
    st.markdown(f"**{len(stale)} open PRs with no activity for 14+ days.** "
                "These are the first things to raise in a triage meeting.")
    if not stale.empty:
        st.dataframe(
            stale[["number", "title", "author", "age_days", "idle_days", "url"]].round(0),
            hide_index=True, use_container_width=True,
            column_config={"url": st.column_config.LinkColumn("Link"),
                           "age_days": "Age (days)", "idle_days": "Idle (days)"})

# ---------------- status report ----------------
with tab_report:
    text = report.build_report(d, now)
    st.download_button("Download report (.md)", text, file_name="weekly_status.md")
    st.markdown(text)

# ---------------- forecast ----------------
with tab_fc:
    st.markdown("**How long to clear the open PR queue?** Monte Carlo on the last 12 weeks "
                "of real throughput (same method as the Release Schedule Risk Simulator).")
    open_count = int(((pt["state"] == "open") & (~pt["draft"].astype(bool))).sum())
    backlog = st.number_input("PRs to merge", min_value=1, value=max(open_count, 1), step=5)
    weeks = m.forecast_weeks(flow, backlog)
    if len(weeks) == 0:
        st.info("Not enough recent throughput to forecast.")
    else:
        s = pd.Series(weeks)
        a, b, c = st.columns(3)
        a.metric("50% confidence", f"{s.quantile(0.5):.0f} weeks")
        b.metric("85% confidence", f"{s.quantile(0.85):.0f} weeks")
        c.metric("95% confidence", f"{s.quantile(0.95):.0f} weeks")
        fig = px.histogram(s, nbins=min(30, s.nunique()), color_discrete_sequence=[STEEL])
        fig.update_layout(showlegend=False)
        st.plotly_chart(style(fig, "Simulations").update_xaxes(title="Weeks"), use_container_width=True)
    st.download_button("Download weekly throughput (.csv) for the simulator",
                       flow[["week", "merged_prs"]].to_csv(index=False), file_name="weekly_throughput.csv")
