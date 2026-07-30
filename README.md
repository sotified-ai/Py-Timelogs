# Team Timesheet Dashboard

A Streamlit dashboard for tracking team time logs across projects — hours per
member, utilization vs. target capacity, module/activity breakdowns, and
Excel/HTML report exports. Reports can be pulled automatically from the
Kualitee PMO API, and access is gated behind a simple local login with two
roles: **admin** (full access) and **project lead** (locked to one project).

## Requirements

- Python 3.x
- `streamlit`, `pandas`, `plotly`, `requests`, `python-dotenv`, `openpyxl`

Install with:

```
pip install streamlit pandas plotly requests python-dotenv openpyxl
```

## Project layout

```
teamdashboard.py     Main Streamlit app — run this
.env                 Local secrets (API token) — not committed
users.csv            Login credentials (username, password, role, project)
project-file/         Timesheet reports (.xlsx / .csv) the dashboard reads
    old data/          Archived reports, not scanned by the app
```

## Setup

### 1. API token (`.env`)

Create a `.env` file in the project root (same folder as `teamdashboard.py`)
with:

```
KUALITEE_API_TOKEN=<your-kualitee-api-token>
```

The app reads this on every run (`load_dotenv(override=True)`), so rotating
an expired token is just editing this file — no restart needed.

### 2. Login credentials (`users.csv`)

`users.csv` lives in the project root and holds one row per account:

| Column   | Meaning                                                                 |
|----------|--------------------------------------------------------------------------|
| username | Login name                                                                |
| password | Plaintext password (local-only tool — see **Security note** below)       |
| role     | `admin` or `lead`                                                        |
| project  | Exact `Project Name` value the lead is scoped to (blank/ignored for admin) |

Edit this file directly to add/remove people or change passwords — changes
take effect on the next login attempt, no restart required. This repo ships
a template with placeholder accounts; **replace the placeholder
usernames/passwords with real ones before handing the app to anyone.**

A `project` value must match a `Project Name` exactly as it appears in the
downloaded report files, or that lead will see no data.

### 3. Report source (`project-file/`)

Drop `.xlsx`/`.csv` timesheet exports into `project-file/`. Expected columns:
`Project Name`, `Time Log User`, `Time Spend`, `Start Log Date`,
`Task Description`, `Activities`, and optionally `Assigned User`.

Files can be dropped in manually, or fetched automatically — see below.

## Running the app

```
streamlit run teamdashboard.py
```

Opens in the browser (default `http://localhost:8501`). Log in with an
account from `users.csv`.

## Roles

- **Admin** — sees the full project multiselect, every project's data, and
  the "🔄 Refresh Data" sidebar section to fetch new reports from the API.
- **Project lead** — locked to the single project listed for their account
  in `users.csv`. No project picker, no API refresh section. Excel/HTML
  report export is still available, scoped to their project.

## Fetching reports from the API (admin only)

`PROJECT_IDS` near the top of `teamdashboard.py` lists the Kualitee project
ids to pull reports for:

```python
PROJECT_IDS = ["21127", "19429", ...]
```

Add or remove ids here as projects change. Clicking **"Download Latest
Reports from API"** in the sidebar:

1. Clears the `.xlsx`/`.csv` files currently in `project-file/` (the
   `old data/` subfolder is left untouched).
2. For each project id, calls the portal's `task/listing` export endpoint,
   then downloads the resulting file link, saving it under the server's own
   filename.
3. Reloads the dashboard with the fresh data.

Results are shown in a persistent "📋 Last download" panel in the sidebar
(succeeded / failed / skipped per project id). If the token is expired or
invalid, the first failure stops the remaining calls immediately and tells
you to update `.env`, rather than repeating the same failure for every
project id.

## Features

- Sidebar filters: date range, projects, modules, team members (with
  Select All / Clear All).
- KPIs: total hours, utilization %, filtered projects/members, avg hours per
  member, top activity.
- Charts: hours per member, time by project (or by activity when a single
  project is selected).
- Tabs: detailed activity log, project/module/activity breakdown,
  utilization summary (vs. a configurable target-capacity and per-project
  team size override).
- Export: Excel report (multi-sheet) and a self-contained HTML report,
  both scoped to the current filters.

## Security note

This is built for trusted, local-machine use by a small internal team.
`users.csv` stores passwords in plaintext — fine for that scenario, but if
this ever moves to a shared server or network-accessible deployment,
switch to hashed passwords (and consider a real auth solution) before that
happens.
