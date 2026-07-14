import streamlit as st
import pandas as pd
import os
import glob
import plotly.express as px
from datetime import date, timedelta

# Dashboard Setup
# python -m streamlit run customdashboard.py

st.set_page_config(page_title="Team Timesheet Dashboard", layout="wide")
st.title("📊 Teams Productivity Dashboard")

# --- CONFIGURATION ---
SOURCE_FOLDER = r'D:\Code-Projects\Code-Projects\Timesheet\project-file'

@st.cache_data(ttl=3600)
def load_data(folder_path):
    files = glob.glob(os.path.join(folder_path, "*.xlsx")) + glob.glob(os.path.join(folder_path, "*.csv"))
    # Exclude Excel temp files
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    all_data = []
    
    for file in files:
        try:
            if file.endswith('.xlsx'):
                df = pd.read_excel(file)
            else:
                df = pd.read_csv(file)
            
            df.columns = df.columns.str.strip()
            df['Start Log Date'] = pd.to_datetime(df['Start Log Date'])
            
            # We no longer strictly need the old 'Activities' column since we parse it from Task Description
            relevant_cols = ['Project Name', 'Time Log User', 'Time Spend', 'Start Log Date', 'Task Description']
            existing_cols = [c for c in relevant_cols if c in df.columns]
            
            df = df[existing_cols].dropna(subset=['Time Spend', 'Start Log Date'])
            
            # --- PARSING TASK DESCRIPTION ---
            if 'Task Description' in df.columns:
                # Split by the first underscore
                splits = df['Task Description'].astype(str).str.split('_', n=1, expand=True)
                
                # Assign the first part to Module
                df['Module'] = splits[0].str.strip()
                
                # Assign the second part to Activities. If no underscore existed, fallback to 'General'
                if splits.shape[1] > 1:
                    df['Activities'] = splits[1].str.strip().fillna('General')
                else:
                    df['Activities'] = 'General'
            else:
                df['Module'] = 'Unknown'
                df['Activities'] = 'Unknown'

            all_data.append(df)
        except Exception as e:
            st.error(f"Error reading {file}: {e}")
            
    if not all_data:
        return pd.DataFrame()
    
    return pd.concat(all_data, ignore_index=True)

# Load the data
df = load_data(SOURCE_FOLDER)

if df.empty:
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

    project_list = sorted(df['Project Name'].unique())
    selected_projects = st.sidebar.multiselect("Select Projects", project_list, default=project_list)
    
    # NEW: Module Filter
    module_list = sorted(df['Module'].unique())
    selected_modules = st.sidebar.multiselect("Select Modules", module_list, default=module_list)

    user_list = sorted(df['Time Log User'].unique())
    selected_users = st.sidebar.multiselect("Select Team Members", user_list, default=user_list)

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

    # --- KPI METRICS ---
    total_hrs = filtered_df['Time Spend'].sum()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Hours Logged", f"{total_hrs:.2f} hrs")
    col2.metric("Filtered Projects", filtered_df['Project Name'].nunique())
    col3.metric("Team Members Shown", filtered_df['Time Log User'].nunique())

    # --- CHARTS ---
    st.markdown("---")
    c1, c2 = st.columns([2, 1])

    with c1:
        user_totals = filtered_df.groupby('Time Log User')['Time Spend'].sum().sort_values(ascending=True).reset_index()
        fig_user = px.bar(user_totals, x='Time Spend', y='Time Log User', orientation='h',
                          title="Hours per Member", color='Time Spend', template="plotly_white",
                          text='Time Spend')
        fig_user.update_traces(texttemplate='%{text:.2f}', textposition='inside')
        st.plotly_chart(fig_user, use_container_width=True)

    with c2:
        proj_totals = filtered_df.groupby('Project Name')['Time Spend'].sum().reset_index()
        fig_proj = px.pie(proj_totals, values='Time Spend', names='Project Name', title="Time by Project")
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
        st.subheader(f"Resource Utilization (Based on {capacity_hours} hrs Capacity)")

        # --- SELECTED PERIOD: PROJECT % VS CAPACITY ---
        # Build a period label from the active date filter
        if len(date_range) == 2:
            period_label = f"{date_range[0].strftime('%d %b %Y')} – {date_range[1].strftime('%d %b %Y')}"
        elif len(date_range) == 1:
            period_label = date_range[0].strftime('%d %b %Y')
        else:
            period_label = "Selected Period"

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



                                       