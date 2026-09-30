pip install -r requirements.txt# Engineering Delivery Health Dashboard

A program-management dashboard that tracks how an open-source engineering team
ships software: speed, review responsiveness, throughput, bug backlog and
release cadence. It flags each area Red / Amber / Green, writes a weekly
stakeholder status report, and forecasts delivery dates with Monte Carlo.

Data source: the public GitHub repository of **Velero** (`velero-io/velero`),
a Kubernetes backup and restore tool - chosen because it sits in the
backup/storage domain. Change `REPO` in `config.py` to track any other repo.

## KPIs

| KPI | Definition | Why a program manager cares |
|---|---|---|
| PR cycle time | Days from PR opened to merged (median and 85th percentile) | Speed of delivery |
| Time to first review | Hours from PR opened to first review by someone other than the author | Hand-off delays |
| Throughput | PRs merged per week | Team capacity |
| Open bug backlog | Bugs open at the end of each week | Quality trend |
| Bug resolution time | Days from bug opened to closed | Support responsiveness |
| Release cadence | Days between stable releases | Predictability |

**Health rule:** each KPI's last 4 weeks are compared with the 12 weeks before.
10% worse = Amber, 25% worse = Red. The current, unfinished week is excluded.
Bot PRs (e.g. dependabot) are excluded by default because they distort cycle time.

## Project structure

```
config.py       settings (repo, window, RAG thresholds)
collect.py      pulls PRs, reviews, issues, releases from the GitHub API -> data/*.csv
metrics.py      turns raw data into weekly KPIs, RAG health and the forecast
report.py       builds the weekly status report (markdown)
app.py          Streamlit dashboard
.github/workflows/refresh-data.yml   weekly automatic data refresh
```

## Run it

1. Create a GitHub token: GitHub > Settings > Developer settings > Personal access
   tokens > Fine-grained token, "Public repositories (read-only)" is enough.
2. Install and collect:
   ```
   pip install -r requirements.txt
   export GITHUB_TOKEN=your_token          # Windows: set GITHUB_TOKEN=your_token
   python collect.py                       # takes ~10-20 min (one API call per PR for reviews)
   streamlit run app.py
   ```
3. Deploy: push to GitHub **with the data/ folder committed**, then deploy `app.py`
   on Streamlit Community Cloud. Add a `GH_PAT` repository secret so the weekly
   GitHub Action can refresh the data.

## Known limitations

- Bugs are detected by any label containing "bug"; repos that do not label bugs will show an empty backlog.
- Throughput counts PRs, not effort; a one-line fix and a large feature count the same.
- The forecast assumes the next weeks look like the last 12.
