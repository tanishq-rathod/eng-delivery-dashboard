"""Project settings. Change REPO to track a different GitHub project."""

REPO = "velero-io/velero"      # Kubernetes backup & restore tool (storage domain)
WINDOW_DAYS = 365              # how far back to pull PRs and issues
DATA_DIR = "data"

# Health (RAG) rules: compare the last 4 weeks against the 12 weeks before them.
RECENT_WEEKS = 4
BASELINE_WEEKS = 12
AMBER_CHANGE = 0.10            # 10% worse than baseline -> Amber
RED_CHANGE = 0.25              # 25% worse than baseline -> Red

STALE_PR_DAYS = 14             # open PR with no activity for this long = stale
