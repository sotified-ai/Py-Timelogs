import streamlit as st
import pandas as pd
import os
import glob
import html as html_lib
import requests
import plotly.express as px
import plotly.offline as pyo
from datetime import datetime
from dotenv import load_dotenv

# Dashboard Setup
# python -m streamlit run customdashboard.py

# override=True: a token refreshed in .env always wins over any stale value
# already sitting in the OS environment.
load_dotenv(override=True)

st.set_page_config(page_title="Team Timesheet Dashboard", layout="wide")

# --- CONFIGURATION ---
SOURCE_FOLDER = r'D:\Code-Projects\Code-Projects\Timesheet\project-file'

# --- API DOWNLOAD CONFIGURATION ---
# Add more project ids here to pull additional projects' reports.
PROJECT_IDS = ["21127"]

TASK_LISTING_URL = "https://apiss.kualitee.com/api/v2/task/listing"
API_ORIGIN = "https://kualitatem_pmo.kualitee.com"
API_TOKEN_ENV_VAR = "KUALITEE_API_TOKEN"

# Fixed request shape captured from the portal's own export call — the
# server uses the "columns" list to know what to put in the export, so it
# must match what the UI sends; only project_id varies per call.
_TASK_LISTING_COLUMNS = [
    {"position": 0, "id": "id", "title": "ID", "data": "id", "canHide": False, "display": "id", "defaultShow": True, "isSortingDisable": False},
    {"position": 1, "id": "taskname", "title": "Task Name", "data": "taskname", "canHide": True, "display": "taskname", "defaultShow": True, "isSortingDisable": False},
    {"position": 2, "id": "parent_task", "title": "Parent Task", "data": "parent_task", "canHide": True, "display": "parent_task", "defaultShow": True, "isSortingDisable": True},
    {"position": 3, "id": "startdate", "title": "Start Date", "data": "startdate", "canHide": True, "display": "startdate", "defaultShow": True, "isSortingDisable": False},
    {"position": 4, "id": "enddate", "title": "End Date", "data": "enddate", "canHide": True, "display": "enddate", "defaultShow": True, "isSortingDisable": False},
    {"position": 5, "id": "module", "title": "Assign Task", "data": "module", "canHide": True, "display": "module", "defaultShow": True, "isSortingDisable": False},
    {"position": 6, "id": "priority", "title": "Priority", "data": "priority", "canHide": True, "display": "priority", "defaultShow": True, "isSortingDisable": False},
    {"position": 7, "id": "column_name", "title": "Status", "data": "column_name", "canHide": True, "display": "column_name", "defaultShow": True, "isSortingDisable": True},
    {"position": 8, "id": "users", "title": "Assign To", "data": "users", "canHide": True, "display": "users", "defaultShow": True, "isSortingDisable": True},
    {"position": 9, "id": "created_on", "title": "Created Date", "data": "created_on", "canHide": True, "display": "created_on", "defaultShow": True, "isSortingDisable": False},
]


def _task_listing_payload(project_id):
    return {
        "project_id": project_id,
        "draw": 1,
        "length": 20,
        "order": [{"column": 9, "dir": "desc"}],
        "start": 0,
        "search": {"value": "", "regex": False},
        "columns": _TASK_LISTING_COLUMNS,
        "module_name": None,
        "priority": None,
        "assignedto": None,
        "loggedBy": None,
        "save_filter": False,
        "export": "yes",
    }

# --- REPORT PALETTE (fixed categorical order — never cycled by rank) ---
CATEGORICAL_COLORS = [
    '#2a78d6', '#eb6834', '#1baf7a', '#eda100',
    '#e87ba4', '#008300', '#4a3aa7', '#e34948',
]
SEQUENTIAL_BLUE = ['#cde2fb', '#9ec5f4', '#5598e7', '#2a78d6', '#184f95']

def _parse_assigned_users(value):
    if pd.isna(value):
        return []
    return [u.strip() for u in str(value).split(',') if u.strip()]


def clear_downloaded_reports(folder_path):
    """Delete previously downloaded *.xlsx/*.csv directly in folder_path
    (not subfolders, e.g. 'old data') so re-downloading doesn't leave stale
    duplicates alongside the fresh files."""
    for pattern in ("*.xlsx", "*.csv"):
        for f in glob.glob(os.path.join(folder_path, pattern)):
            if not os.path.basename(f).startswith("~$"):
                os.remove(f)


def download_reports_from_api(project_ids, token, folder_path):
    """For each project id: ask task/listing to build an export, then
    download the resulting file link into folder_path. Clears whatever was
    previously downloaded there first."""
    clear_downloaded_reports(folder_path)

    json_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": API_ORIGIN,
        "token": token,
    }
    file_headers = {"Accept": "*/*", "token": token}

    results = []
    for project_id in project_ids:
        try:
            listing_response = requests.post(
                TASK_LISTING_URL, headers=json_headers,
                json=_task_listing_payload(project_id), timeout=60
            )
            listing_response.raise_for_status()
            export_link = listing_response.json().get("link")
            if not export_link:
                raise ValueError("Response did not include an export link")

            file_response = requests.get(export_link, headers=file_headers, timeout=60)
            file_response.raise_for_status()

            filename = os.path.basename(export_link)
            with open(os.path.join(folder_path, filename), "wb") as f:
                f.write(file_response.content)
            results.append((project_id, True, filename))
        except Exception as e:
            results.append((project_id, False, str(e)))
    return results

@st.cache_data(ttl=3600)
def load_data(folder_path):
    files = glob.glob(os.path.join(folder_path, "*.xlsx")) + glob.glob(os.path.join(folder_path, "*.csv"))
    # Exclude Excel temp files
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    all_data = []
    # Project -> set of resources ever assigned to a task on that project
    # (built from ALL rows, including ones with no logged time, so resources
    # who never logged anything are still known to be allocated to the project)
    project_assigned_users = {}

    for file in files:
        try:
            if file.endswith('.xlsx'):
                df = pd.read_excel(file)
            else:
                df = pd.read_csv(file)

            df.columns = df.columns.str.strip()

            if 'Assigned User' in df.columns and 'Project Name' in df.columns:
                for proj, assigned in zip(df['Project Name'], df['Assigned User']):
                    if pd.isna(proj):
                        continue
                    users = _parse_assigned_users(assigned)
                    if users:
                        project_assigned_users.setdefault(proj, set()).update(users)

            df['Start Log Date'] = pd.to_datetime(df['Start Log Date'])

            # Include Activities from the source file — it already has the correct values
            relevant_cols = ['Project Name', 'Time Log User', 'Time Spend', 'Start Log Date', 'Task Description', 'Activities']
            existing_cols = [c for c in relevant_cols if c in df.columns]

            df = df[existing_cols].dropna(subset=['Time Spend', 'Start Log Date'])

            # --- MODULE: parse from Task Description (split on '_') ---
            if 'Task Description' in df.columns:
                splits = df['Task Description'].astype(str).str.split('_', n=1, expand=True)
                # Module = part before '_'; if no '_', use full Task Description
                df['Module'] = splits[0].str.strip()
            else:
                df['Module'] = 'Unknown'

            # --- ACTIVITIES: use the column from the file if present, else 'General' ---
            if 'Activities' not in df.columns:
                df['Activities'] = 'General'
            else:
                df['Activities'] = df['Activities'].astype(str).str.strip().replace('nan', 'General').fillna('General')

            all_data.append(df)
        except Exception as e:
            st.error(f"Error reading {file}: {e}")

    if not all_data:
        return pd.DataFrame(), project_assigned_users

    return pd.concat(all_data, ignore_index=True), project_assigned_users


def add_zero_hour_allocations(filtered_df, project_assigned_users, selected_projects, selected_users, date_range):
    """Add a 0-hour row for every resource assigned to a selected project who
    has no logged time in the current filtered view, so idle allocations are
    visible instead of silently missing from the summaries."""
    existing_pairs = set(zip(filtered_df['Project Name'], filtered_df['Time Log User']))

    if len(date_range) == 2:
        anchor_date = pd.Timestamp(date_range[1])
    elif len(date_range) == 1:
        anchor_date = pd.Timestamp(date_range[0])
    else:
        anchor_date = pd.NaT

    zero_rows = []
    for proj in selected_projects:
        for user in project_assigned_users.get(proj, set()):
            if user not in selected_users or (proj, user) in existing_pairs:
                continue
            zero_rows.append({
                'Project Name': proj,
                'Time Log User': user,
                'Time Spend': 0.0,
                'Start Log Date': anchor_date,
                'Task Description': '',
                'Module': 'No Activity',
                'Activities': 'No Activity Logged',
            })

    if not zero_rows:
        return filtered_df

    return pd.concat([filtered_df, pd.DataFrame(zero_rows)], ignore_index=True)


def _df_to_html_table(df, numeric_cols=None, date_cols=None):
    """Render a DataFrame as a styled HTML table (tabular-nums on numeric cols)."""
    d = df.copy()
    for c in (date_cols or []):
        if c in d.columns:
            d[c] = pd.to_datetime(d[c]).dt.strftime('%d %b %Y')
    for c in (numeric_cols or []):
        if c in d.columns:
            d[c] = d[c].map(lambda v: f"{v:,.2f}" if pd.notna(v) else "")
    return d.to_html(index=False, border=0, classes='dtable', escape=True, na_rep='')


def _fig_div(fig, include_js=False):
    return pyo.plot(fig, include_plotlyjs=include_js, output_type='div',
                     config={'responsive': True, 'displaylogo': False})


def build_html_report(filtered_df, project_breakdown, lw_proj, sum1, sum2, sum3,
                       fig_user, fig_proj, kpis, filt, project_color_map):
    """Assemble a single self-contained HTML report scoped to the currently
    selected filters (project/date/module/member) — sharable in place of a
    dashboard screenshot."""

    projects_label = ("All Projects" if set(filt['projects']) == set(filt['all_projects'])
                       else ", ".join(filt['projects']) if filt['projects'] else "None selected")
    modules_label = ("All Modules" if set(filt['modules']) == set(filt['all_modules'])
                      else ", ".join(filt['modules']) if filt['modules'] else "None selected")
    report_title = (f"📊 {filt['projects'][0]} Team Productivity Report"
                     if len(filt['projects']) == 1 else "📊 Team Productivity Report")

    plotly_js = f"<script>{pyo.get_plotlyjs()}</script>"
    user_chart_div = _fig_div(fig_user)
    proj_chart_div = _fig_div(fig_proj)

    def section(title, inner_html):
        return f'<section class="card"><h2>{html_lib.escape(title)}</h2>{inner_html}</section>'

    utilization_html = ""
    if lw_proj is not None:
        utilization_html += section(
            "🗓️ Project Utilization vs Target Capacity",
            f'<p class="muted">Capacity per resource: {filt["capacity_hours"]:.0f} hrs '
            f'&nbsp;|&nbsp; Team Capacity = {filt["capacity_hours"]:.0f} × Team Size</p>' +
            _df_to_html_table(lw_proj[['Project Name', 'Resources', 'Hours Logged',
                                        'Total Team Capacity (hrs)', '% of Target Capacity']])
        )
    if sum1 is not None:
        utilization_html += section("Project & User Summary", _df_to_html_table(sum1))
    if sum2 is not None:
        utilization_html += section("Project, Activity & User Summary", _df_to_html_table(sum2))
    if sum3 is not None:
        utilization_html += section("Project & Activity Summary", _df_to_html_table(sum3))
    if lw_proj is None and sum1 is None:
        utilization_html = section("Utilization Summary", '<p class="muted">No data for the selected filters.</p>')

    detail_table = _df_to_html_table(
        filtered_df.sort_values(by='Start Log Date', ascending=False),
        numeric_cols=['Time Spend'], date_cols=['Start Log Date']
    )

    generated_at = filt['generated_at'].strftime('%d %b %Y, %I:%M %p')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Timesheet Report — {html_lib.escape(projects_label)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
{plotly_js}
<style>
  :root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --muted:          #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --muted:          #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  header {{ margin-bottom: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
  h2 {{ margin: 0 0 12px; font-size: 1.05rem; }}
  .muted {{ color: var(--muted); font-size: 0.85rem; }}
  .filters {{ color: var(--text-secondary); font-size: 0.9rem; line-height: 1.6; }}
  .card {{
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px; margin-bottom: 20px;
  }}
  .kpi-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .kpi {{ flex: 1 1 180px; }}
  .kpi .value {{ font-size: 2rem; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .kpi .label {{ color: var(--text-secondary); font-size: 0.85rem; }}
  .charts {{ display: flex; gap: 20px; flex-wrap: wrap; }}
  .charts .card {{ flex: 1 1 420px; }}
  table.dtable {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; overflow-x: auto; display: block; }}
  table.dtable thead th {{
    text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--gridline);
    color: var(--text-secondary); font-weight: 600; white-space: nowrap;
  }}
  table.dtable tbody td {{
    padding: 6px 10px; border-bottom: 1px solid var(--gridline);
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }}
  table.dtable tbody tr:hover {{ background: color-mix(in srgb, var(--text-primary) 4%, transparent); }}
  details summary {{ cursor: pointer; font-weight: 600; padding: 4px 0; }}
  footer {{ color: var(--muted); font-size: 0.8rem; margin-top: 24px; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{html_lib.escape(report_title)}</h1>
    <div class="filters">
      <strong>Projects:</strong> {html_lib.escape(projects_label)}<br>
      <strong>Period:</strong> {html_lib.escape(filt['period_label'])}<br>
      <strong>Modules:</strong> {html_lib.escape(modules_label)}<br>
      <strong>Team Members:</strong> {len(filt['members'])} selected
    </div>
  </header>

  <div class="kpi-row">
    <div class="card kpi"><div class="value">{kpis['total_hrs']:.2f} hrs</div><div class="label">Total Hours Logged</div></div>
    <div class="card kpi"><div class="value">{kpis['utilization_pct']:.1f}%</div><div class="label">Resource Utilization (vs Target Capacity)</div></div>
    <div class="card kpi"><div class="value">{kpis['projects']}</div><div class="label">Filtered Projects</div></div>
    <div class="card kpi"><div class="value">{kpis['members']}</div><div class="label">Team Members Shown</div></div>
    <div class="card kpi"><div class="value">{kpis['avg_hrs_member']:.2f} hrs</div><div class="label">Avg Hours / Member</div></div>
    <div class="card kpi"><div class="value">{html_lib.escape(str(kpis['top_activity']))}</div><div class="label">Top Activity ({kpis['top_activity_hrs']:.1f} hrs)</div></div>
  </div>

  <div class="charts">
    <div class="card">{user_chart_div}</div>
    <div class="card">{proj_chart_div}</div>
  </div>

  {section("Breakdown by Project, Module & Activity", _df_to_html_table(project_breakdown, numeric_cols=['Time Spend']))}

  {utilization_html}

  <details>
    <summary>📄 Detailed Activity Log ({len(filtered_df)} rows)</summary>
    {detail_table}
  </details>

  <footer>Generated {generated_at} · Team Timesheet Dashboard</footer>
</div>
</body>
</html>"""


# Load the data
df, project_assigned_users = load_data(SOURCE_FOLDER)

# --- REFRESH REPORTS FROM API ---
st.sidebar.subheader("🔄 Refresh Data")
if st.sidebar.button("Download Latest Reports from API"):
    api_token = os.environ.get(API_TOKEN_ENV_VAR)
    if not api_token:
        st.sidebar.error(f"Set the {API_TOKEN_ENV_VAR} environment variable before downloading.")
    else:
        with st.spinner(f"Downloading reports for {len(PROJECT_IDS)} project(s)..."):
            download_results = download_reports_from_api(PROJECT_IDS, api_token, SOURCE_FOLDER)
        for project_id, success, info in download_results:
            if success:
                st.sidebar.success(f"Project {project_id}: downloaded {info}")
            else:
                st.sidebar.error(f"Project {project_id}: failed — {info}")
        load_data.clear()
        st.rerun()
st.sidebar.markdown("---")

if df.empty:
    st.title("📊 Teams Productivity Dashboard")
    st.warning(f"No data found in {SOURCE_FOLDER}. Please check the path.")
else:
    # --- SIDEBAR FILTERS ---
    st.sidebar.header("Filter Options")

    min_date = df['Start Log Date'].min().date()
    max_date = df['Start Log Date'].max().date()

    date_range = st.sidebar.date_input(
        "Select Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )

    # Period label derived from the active date filter — used both in the
    # on-page caption below and in the Utilization tab / HTML report
    if len(date_range) == 2:
        period_label = f"{date_range[0].strftime('%d %b %Y')} – {date_range[1].strftime('%d %b %Y')}"
    elif len(date_range) == 1:
        period_label = date_range[0].strftime('%d %b %Y')
    else:
        period_label = "Selected Period"

    project_list = sorted(df['Project Name'].unique())
    selected_projects = st.sidebar.multiselect("Select Projects", project_list, default=project_list)

    single_project_selected = len(selected_projects) == 1
    if not selected_projects or set(selected_projects) == set(project_list):
        st.title("📊 Teams Productivity Dashboard")
    elif single_project_selected:
        st.title(f"📊 {selected_projects[0]} Team Productivity Dashboard")
    else:
        st.title("📊 Teams Productivity Dashboard — Multiple Projects")

    st.caption(f"📅 Period: {period_label}")

    # Fixed color per project (identity), stable regardless of filter/selection
    project_color_map = {
        proj: CATEGORICAL_COLORS[i % len(CATEGORICAL_COLORS)]
        for i, proj in enumerate(project_list)
    }

    # NEW: Module Filter
    module_list = sorted(df['Module'].unique())
    selected_modules = st.sidebar.multiselect("Select Modules", module_list, default=module_list)

    # Fixed color per activity (identity), used for the single-project pie breakdown
    activity_list = sorted(set(df['Activities'].dropna().unique()) | {'No Activity Logged'})
    activity_color_map = {
        act: CATEGORICAL_COLORS[i % len(CATEGORICAL_COLORS)]
        for i, act in enumerate(activity_list)
    }

    # Include resources who are allocated (assigned to tasks) but have never logged
    # any time at all, so they can still be picked in the filter and shown at 0 hrs
    all_assigned_users = set().union(*project_assigned_users.values()) if project_assigned_users else set()
    user_list = sorted(set(df['Time Log User'].dropna().unique()) | all_assigned_users)

    # Select All / Clear All make both directions cheap: clear then pick a
    # few, or keep everyone and unselect a few — without a mode switch.
    if "team_members_selection" not in st.session_state:
        st.session_state.team_members_selection = user_list

    btn_col1, btn_col2 = st.sidebar.columns(2)
    if btn_col1.button("Select All", use_container_width=True):
        st.session_state.team_members_selection = user_list
    if btn_col2.button("Clear All", use_container_width=True):
        st.session_state.team_members_selection = []

    selected_users = st.sidebar.multiselect(
        "Select Team Members", user_list, key="team_members_selection"
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("⚙️ Utilization Settings")
    capacity_hours = st.sidebar.number_input(
        "Target Capacity (Hours)", 
        min_value=1.0, 
        value=40.0, 
        step=20.0,
        help="Enter the baseline capacity hours to calculate utilization"
    )

    # --- TEAM SIZE: auto-detect from FULL dataset (ignores date filter) ---
    # Respects Project & User sidebar filters but NOT the date range
    full_mask = (
        df['Project Name'].isin(selected_projects) &
        df['Time Log User'].isin(selected_users)
    )
    auto_team_sizes = (
        df[full_mask]
        .groupby('Project Name')['Time Log User']
        .nunique()
        .to_dict()
    )

    # Per-project override expander
    with st.sidebar.expander("👥 Override Team Size per Project", expanded=False):
        st.caption("Auto-detected from full history. Edit to override.")
        team_size_override = {}
        for proj in sorted(selected_projects):
            auto_val = int(auto_team_sizes.get(proj, 1))
            team_size_override[proj] = st.number_input(
                proj,
                min_value=1,
                value=auto_val,
                step=1,
                key=f"team_size_{proj}"
            )

    # --- APPLY FILTERS ---
    mask = (df['Project Name'].isin(selected_projects)) & (df['Time Log User'].isin(selected_users)) & (df['Module'].isin(selected_modules))
    
    if len(date_range) == 2:
        start_date, end_date = date_range
        mask = mask & (df['Start Log Date'].dt.date >= start_date) & (df['Start Log Date'].dt.date <= end_date)
    elif len(date_range) == 1:
        single_date = date_range[0]
        mask = mask & (df['Start Log Date'].dt.date == single_date)
    
    filtered_df = df[mask]
    filtered_df = add_zero_hour_allocations(
        filtered_df, project_assigned_users, selected_projects, selected_users, date_range
    )

    # --- KPI METRICS ---
    total_hrs = filtered_df['Time Spend'].sum()
    n_projects = filtered_df['Project Name'].nunique()
    n_members = filtered_df['Time Log User'].nunique()

    # Team size for averaging = the Auto-detected/overridden team size (sidebar
    # "Override Team Size per Project"), NOT nunique(Time Log User) in the
    # filtered view. The sheet's Assigned User history can carry resources who
    # were assigned to a project in the past and have since moved to another
    # one — they still show up as a 0-hr allocation row, which would otherwise
    # silently inflate the member count and drag the average down.
    total_team_size = sum(team_size_override.get(p, 1) for p in selected_projects)
    avg_hrs_member = (total_hrs / total_team_size) if total_team_size else 0.0

    # Resource Utilization = hours logged / total team capacity, for the
    # currently selected project(s) — single project or all projects alike
    total_capacity = total_team_size * capacity_hours
    utilization_pct = (total_hrs / total_capacity * 100) if total_capacity else 0.0

    if not filtered_df.empty:
        act_hrs = filtered_df.groupby('Activities')['Time Spend'].sum().sort_values(ascending=False)
        top_activity, top_activity_hrs = act_hrs.index[0], act_hrs.iloc[0]
    else:
        top_activity, top_activity_hrs = "—", 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Hours Logged", f"{total_hrs:.2f} hrs")
    col2.metric("Resource Utilization", f"{utilization_pct:.1f}%",
                help="Hours Logged ÷ Total Team Capacity (Team Size × Target Capacity Hours) "
                     "for the currently selected project(s).")
    col3.metric("Filtered Projects", n_projects)
    col4.metric("Team Members Shown", n_members)

    col5, col6 = st.columns(2)
    col5.metric("Avg Hours / Member", f"{avg_hrs_member:.2f} hrs")
    col6.metric("Top Activity", top_activity, delta=f"{top_activity_hrs:.1f} hrs", delta_color="off")

    # --- CHARTS ---
    st.markdown("---")
    c1, c2 = st.columns([2, 1])

    with c1:
        user_totals = filtered_df.groupby('Time Log User')['Time Spend'].sum().sort_values(ascending=True).reset_index()
        fig_user = px.bar(user_totals, x='Time Spend', y='Time Log User', orientation='h',
                          title="Hours per Member", color='Time Spend', template="plotly_white",
                          color_continuous_scale=SEQUENTIAL_BLUE, text='Time Spend')
        fig_user.update_traces(texttemplate='%{text:.2f}', textposition='inside')
        fig_user.update_coloraxes(showscale=False)
        st.plotly_chart(fig_user, use_container_width=True)

    with c2:
        if single_project_selected:
            # A single project always fills 100% of "time by project" — that pie
            # is trivial. Break down by Activity instead, so the chart says
            # something about how that project's team actually spent its time.
            act_totals = filtered_df.groupby('Activities')['Time Spend'].sum().reset_index()
            fig_proj = px.pie(act_totals, values='Time Spend', names='Activities',
                              title=f"{selected_projects[0]}: Time by Activity",
                              color='Activities', color_discrete_map=activity_color_map, template="plotly_white")
        else:
            proj_totals = filtered_df.groupby('Project Name')['Time Spend'].sum().reset_index()
            fig_proj = px.pie(proj_totals, values='Time Spend', names='Project Name', title="Time by Project",
                              color='Project Name', color_discrete_map=project_color_map, template="plotly_white")
        fig_proj.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_proj, use_container_width=True)

    # --- THE TABS ---
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📄 Detailed Activity Log", "📊 Project & Module Breakdown", "📈 Utilization Summary"])
    
    with tab1:
        st.subheader("Log Entries (Date-wise)")
        st.dataframe(filtered_df.sort_values(by='Start Log Date', ascending=False), width="stretch")
    
    with tab2:
        st.subheader("Breakdown by Project, Module, and Activity")
        # Updated to include the new Module breakdown
        project_breakdown = filtered_df.groupby(['Project Name', 'Module', 'Activities'])['Time Spend'].sum().reset_index()
        st.dataframe(project_breakdown, width="stretch")

    with tab3:
        lw_proj = sum1 = sum2 = sum3 = None
        st.subheader(f"Resource Utilization (Based on {capacity_hours} hrs Capacity)")

        st.markdown("##### 🗓️ Selected Period: Project Utilization % vs Target Capacity")

        if not filtered_df.empty:
            lw_proj = filtered_df.groupby('Project Name')['Time Spend'].sum().reset_index()
            lw_proj.rename(columns={'Time Spend': 'Hours Logged'}, inplace=True)

            # Use override team sizes (auto-detected from full history, user can edit in sidebar)
            lw_proj['Resources'] = lw_proj['Project Name'].map(team_size_override).fillna(1).astype(int)

            # Total Team Capacity = capacity_hours × team size
            lw_proj['Total Team Capacity (hrs)'] = (lw_proj['Resources'] * capacity_hours).round(2)
            lw_proj['Hours Logged'] = lw_proj['Hours Logged'].round(2)

            # Utilization % = Hours Logged / Total Team Capacity × 100
            lw_proj['% of Target Capacity'] = (
                lw_proj['Hours Logged'] / lw_proj['Total Team Capacity (hrs)'] * 100
            ).round(2).astype(str) + '%'

            lw_proj = lw_proj.sort_values('Hours Logged', ascending=False).reset_index(drop=True)
            st.caption(
                f"Period: {period_label}  |  "
                f"Capacity per resource: {capacity_hours:.0f} hrs  |  "
                f"Team Capacity = {capacity_hours:.0f} × Team Size   (edit team sizes in sidebar \u2039👥\u203a)"
            )
            st.dataframe(lw_proj[['Project Name', 'Resources', 'Hours Logged',
                                   'Total Team Capacity (hrs)', '% of Target Capacity']],
                         use_container_width=True)

        else:
            st.info("No data for the selected filters. Adjust your date range or project/member filters.")

        st.markdown("---")
        
        if not filtered_df.empty:
            # 1. Project & User Summary
            st.markdown("##### 1. Project & User Summary")
            proj_user_df = filtered_df.groupby(['Project Name', 'Time Log User'])['Time Spend'].sum().reset_index()
            proj_user_df.rename(columns={'Time Spend': 'Total Hours'}, inplace=True)
            
            proj_total_df = filtered_df.groupby('Project Name')['Time Spend'].sum().reset_index()
            proj_total_df.rename(columns={'Time Spend': 'Project Total Hours'}, inplace=True)
            
            sum1 = pd.merge(proj_user_df, proj_total_df, on='Project Name')
            sum1['% of Project Total'] = sum1['Total Hours'] / sum1['Project Total Hours'] * 100
            sum1['Utilization % (vs Capacity)'] = sum1['Total Hours'] / capacity_hours * 100
            
            sum1['Total Hours'] = sum1['Total Hours'].round(2)
            sum1['Project Total Hours'] = sum1['Project Total Hours'].round(2)
            sum1['% of Project Total'] = sum1['% of Project Total'].round(2).astype(str) + '%'
            sum1['Utilization % (vs Capacity)'] = sum1['Utilization % (vs Capacity)'].round(2).astype(str) + '%'
            st.dataframe(sum1, width="stretch")

            # 2. Project, Activity, & User Summary
            st.markdown("##### 2. Project, Activity, & User Summary")
            # Using our new parsed 'Activities'
            act_user_df = filtered_df.groupby(['Project Name', 'Activities', 'Time Log User'])['Time Spend'].sum().reset_index()
            act_user_df.rename(columns={'Time Spend': 'User Activity Hours'}, inplace=True)
            
            act_total_df = filtered_df.groupby(['Project Name', 'Activities'])['Time Spend'].sum().reset_index()
            act_total_df.rename(columns={'Time Spend': 'Activity Total Hours'}, inplace=True)
            
            sum2 = pd.merge(act_user_df, act_total_df, on=['Project Name', 'Activities'])
            sum2['% of Activity Total'] = sum2['User Activity Hours'] / sum2['Activity Total Hours'] * 100
            sum2['Utilization % (vs Capacity)'] = sum2['User Activity Hours'] / capacity_hours * 100
            
            sum2['User Activity Hours'] = sum2['User Activity Hours'].round(2)
            sum2['Activity Total Hours'] = sum2['Activity Total Hours'].round(2)
            sum2['% of Activity Total'] = sum2['% of Activity Total'].round(2).astype(str) + '%'
            sum2['Utilization % (vs Capacity)'] = sum2['Utilization % (vs Capacity)'].round(2).astype(str) + '%'
            st.dataframe(sum2, width="stretch")

            # 3. New View: Project + Activity Summary
            st.markdown("##### 3. Project & Activity Summary (% of Project Total)")
            sum3 = pd.merge(act_total_df, proj_total_df, on='Project Name')
            sum3['Activity %'] = sum3['Activity Total Hours'] / sum3['Project Total Hours'] * 100
            
            sum3['Activity Total Hours'] = sum3['Activity Total Hours'].round(2)
            sum3['Project Total Hours'] = sum3['Project Total Hours'].round(2)
            sum3['Activity %'] = sum3['Activity %'].round(2).astype(str) + '%'
            st.dataframe(sum3, width="stretch")
        else:
            st.info("No data available to calculate utilization. Please adjust your filters.")

    # --- EXPORT ---
    st.sidebar.markdown("---")
    if st.sidebar.button("Generate Excel Export"):
        output_name = "Filtered_Timesheet_Report.xlsx"
        with pd.ExcelWriter(output_name, engine='openpyxl') as writer:
            # Sheet 1: Detailed Activity Log
            filtered_df.sort_values(by='Start Log Date', ascending=False).to_excel(
                writer, sheet_name='Detailed Activity Log', index=False)
            
            # Sheet 2: Project & Module Breakdown
            project_breakdown = filtered_df.groupby(['Project Name', 'Module', 'Activities'])['Time Spend'].sum().reset_index()
            project_breakdown.to_excel(writer, sheet_name='Project & Module Breakdown', index=False)
            
            # Sheet 3: Utilization Summary
            if not filtered_df.empty:
                proj_user_df = filtered_df.groupby(['Project Name', 'Time Log User'])['Time Spend'].sum().reset_index()
                proj_user_df.rename(columns={'Time Spend': 'Total Hours'}, inplace=True)
                proj_total_df = filtered_df.groupby('Project Name')['Time Spend'].sum().reset_index()
                proj_total_df.rename(columns={'Time Spend': 'Project Total Hours'}, inplace=True)
                sum1 = pd.merge(proj_user_df, proj_total_df, on='Project Name')
                sum1['% of Project Total'] = (sum1['Total Hours'] / sum1['Project Total Hours'] * 100).round(2)
                sum1['Utilization % (vs Capacity)'] = (sum1['Total Hours'] / capacity_hours * 100).round(2)
                sum1['Total Hours'] = sum1['Total Hours'].round(2)
                sum1['Project Total Hours'] = sum1['Project Total Hours'].round(2)
                sum1.to_excel(writer, sheet_name='Utilization Summary', index=False)
            else:
                pd.DataFrame({'Note': ['No data available for utilization summary']}).to_excel(
                    writer, sheet_name='Utilization Summary', index=False)
        
        with open(output_name, "rb") as f:
            st.sidebar.download_button("📥 Download Report", data=f, file_name=output_name,
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if st.sidebar.button("Generate HTML Report"):
        if set(selected_projects) == set(project_list):
            report_label = "All_Projects"
        elif len(selected_projects) == 1:
            report_label = selected_projects[0]
        else:
            report_label = "Multiple_Projects"
        safe_label = "".join(c for c in report_label if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        html_output_name = f"Timesheet_Report_{safe_label}.html"

        project_breakdown_export = filtered_df.groupby(
            ['Project Name', 'Module', 'Activities'])['Time Spend'].sum().reset_index()

        report_html = build_html_report(
            filtered_df=filtered_df,
            project_breakdown=project_breakdown_export,
            lw_proj=lw_proj, sum1=sum1, sum2=sum2, sum3=sum3,
            fig_user=fig_user, fig_proj=fig_proj,
            kpis={'total_hrs': total_hrs,
                  'utilization_pct': utilization_pct,
                  'projects': filtered_df['Project Name'].nunique(),
                  'members': filtered_df['Time Log User'].nunique(),
                  'avg_hrs_member': avg_hrs_member,
                  'top_activity': top_activity,
                  'top_activity_hrs': top_activity_hrs},
            filt={'projects': selected_projects, 'all_projects': project_list,
                  'modules': selected_modules, 'all_modules': module_list, 'members': selected_users,
                  'period_label': period_label, 'capacity_hours': capacity_hours,
                  'generated_at': datetime.now()},
            project_color_map=project_color_map,
        )

        with open(html_output_name, "w", encoding="utf-8") as f:
            f.write(report_html)

        with open(html_output_name, "rb") as f:
            st.sidebar.download_button("📥 Download HTML Report", data=f, file_name=html_output_name,
                                       mime="text/html")



                                       