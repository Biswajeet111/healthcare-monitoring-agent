import streamlit as st
import requests
import pandas as pd
import plotly.express as px

# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="HealthGuard AI",
    page_icon="❤️",
    layout="wide"
)

st.title("❤️ HealthGuard AI")
st.caption("Agentic AI-Powered Personal Healthcare Intelligence Platform")


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

st.sidebar.title("Settings")

API_URL = st.sidebar.text_input(
    "Backend API URL",
    "http://127.0.0.1:8000"
).rstrip("/")


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

if "access_token" not in st.session_state:
    st.session_state.access_token = None

if "user_profile" not in st.session_state:
    st.session_state.user_profile = None


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

def login():

    st.subheader("Welcome Back")

    st.markdown("### Login to HealthGuard AI")

    with st.form("login_form"):

        email = st.text_input(
            "Email Address",
            placeholder="Enter your registered email"
        )

        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password"
        )

        submitted = st.form_submit_button(
            "Login",
            use_container_width=True
        )

        if submitted:

            if not email or not password:
                st.warning("Please enter email and password.")
                return

            try:
                response = requests.post(
                    f"{API_URL}/auth/login",
                    json={
                        "email": email,
                        "password": password
                    },
                    timeout=15
                )

                if response.status_code == 200:

                    token = response.json()["access_token"]

                    st.session_state.access_token = token

                    st.success("Login successful!")

                    st.rerun()

                elif response.status_code == 401:
                    st.error("Invalid email or password.")

                else:
                    st.error(
                        f"Login failed: {response.text}"
                    )

            except requests.exceptions.RequestException as error:

                st.error(
                    f"Cannot connect to backend: {error}"
                )


# --------------------------------------------------
# API REQUEST HELPER
# --------------------------------------------------

def api_request(method, endpoint, **kwargs):

    token = st.session_state.get("access_token")

    if not token:
        return None

    headers = kwargs.pop("headers", {})

    headers["Authorization"] = f"Bearer {token}"

    try:

        response = requests.request(
            method,
            f"{API_URL}{endpoint}",
            headers=headers,
            timeout=200,
            **kwargs
        )

        if response.status_code == 401:

            st.session_state.access_token = None
            st.session_state.user_profile = None

            st.warning("Session expired. Please login again.")

            st.rerun()

        return response

    except requests.exceptions.RequestException as error:

        st.error(f"Backend connection error: {error}")

        return None


# --------------------------------------------------
# GET AUTHENTICATED USER PROFILE
# --------------------------------------------------

if not st.session_state.access_token:

    login()
    st.stop()


if st.session_state.user_profile is None:

    profile_response = api_request(
        "GET",
        "/auth/me"
    )

    if profile_response is None:
        st.stop()

    if profile_response.status_code != 200:

        st.error("Unable to retrieve user profile.")
        st.stop()

    st.session_state.user_profile = profile_response.json()


user_profile = st.session_state.user_profile

user_id = user_profile["id"]


# --------------------------------------------------
# SIDEBAR USER INFORMATION
# --------------------------------------------------

st.sidebar.divider()

st.sidebar.subheader("Account")

st.sidebar.write(
    f"**Name:** {user_profile['full_name']}"
)

st.sidebar.write(
    f"**Email:** {user_profile['email']}"
)

st.sidebar.caption(
    f"User ID: {user_id}"
)

if st.sidebar.button(
    "Logout",
    use_container_width=True
):

    st.session_state.access_token = None
    st.session_state.user_profile = None

    st.rerun()


# ============================================================
# PHASE 3.4.5 — IN-APP NOTIFICATION CENTER
# ============================================================

notification_base = f"/users/{user_id}/notifications"
notification_summary_response = api_request("GET", f"{notification_base}/summary")

if notification_summary_response is not None and notification_summary_response.status_code == 200:
    notification_summary = notification_summary_response.json()
    unread_count = notification_summary.get("unread", 0)
    total_notifications = notification_summary.get("total_notifications", 0)
    acknowledged_count = notification_summary.get("acknowledged", 0)
    notification_summary_available = True
else:
    unread_count = None
    total_notifications = None
    acknowledged_count = None
    notification_summary_available = False

st.sidebar.divider()
st.sidebar.subheader("🔔 Notifications")
if notification_summary_available:
    st.sidebar.metric("Unread notifications", unread_count)
else:
    st.sidebar.caption("Notification count unavailable")

with st.expander(
    f"🔔 Notification Center ({unread_count} unread)"
    if notification_summary_available
    else "🔔 Notification Center",
    expanded=False,
):
    st.caption(
        "In-app notifications are statistical observations, not medical "
        "diagnoses or indications of clinical urgency."
    )

    if not notification_summary_available:
        st.warning("Notification summary is temporarily unavailable.")
    else:
        nc1, nc2, nc3 = st.columns(3)
        nc1.metric("Total notifications", total_notifications)
        nc2.metric("Unread", unread_count)
        nc3.metric("Acknowledged", acknowledged_count)

    filter_col, size_col, page_col = st.columns([2, 1, 1])
    with filter_col:
        notification_view = st.selectbox(
            "Show",
            ["Unread", "All"],
            key="notification_center_view",
        )
    with size_col:
        notification_page_size = st.selectbox(
            "Per page", [10, 25, 50],
            key="notification_center_page_size",
        )
    with page_col:
        notification_page = st.number_input(
            "Page", min_value=1, step=1,
            key="notification_center_page",
        )

    if st.button("Refresh notifications", key="refresh_notifications"):
        st.rerun()

    notification_response = api_request(
        "GET",
        notification_base,
        params={
            "limit": int(notification_page_size),
            "offset": (int(notification_page) - 1) * int(notification_page_size),
            "unread_only": notification_view == "Unread",
        },
    )

    if notification_response is None:
        st.warning("Could not connect to the notification feed.")
    elif notification_response.status_code != 200:
        st.warning(
            "Could not load notifications "
            f"(HTTP {notification_response.status_code})."
        )
    else:
        feed_data = notification_response.json()
        feed_total = feed_data.get("total", 0)
        notifications = feed_data.get("notifications", [])
        max_notification_page = max(
            1, (feed_total + int(notification_page_size) - 1)
            // int(notification_page_size)
        )
        st.caption(
            f"Page {int(notification_page)} of {max_notification_page} "
            f"· {feed_total} matching notifications"
        )

        if not notifications:
            st.info(
                "No unread notifications." if notification_view == "Unread"
                else "No published notifications yet."
            )

        for notification in notifications:
            event_id = notification.get("id")
            metric_label = str(notification.get("metric_type", "Unknown")).replace("_", " ").title()
            event_label = str(notification.get("event_type", "Unknown")).replace("_", " ").title()
            is_acknowledged = bool(notification.get("is_acknowledged"))
            status_label = "Acknowledged" if is_acknowledged else "Unread"

            with st.container(border=True):
                st.markdown(f"**{metric_label} — {event_label}** · {status_label}")
                st.write(notification.get("message") or "No observation message available.")
                st.caption(
                    f"Published (UTC): {notification.get('notified_at') or 'Unknown'} "
                    f"· Monitoring priority: {notification.get('monitoring_priority') or 'Unknown'}"
                )
                if not is_acknowledged and event_id is not None:
                    if st.button(
                        "Acknowledge",
                        key=f"notification_ack_{user_id}_{event_id}",
                    ):
                        ack_response = api_request(
                            "PATCH",
                            f"/users/{user_id}/monitoring/events/{event_id}/acknowledge",
                        )
                        if ack_response is None:
                            st.error("Could not connect to the acknowledgment service.")
                        elif ack_response.status_code == 200:
                            st.success("Notification acknowledged.")
                            st.rerun()
                        else:
                            st.error(
                                "Acknowledgment failed "
                                f"(HTTP {ack_response.status_code})."
                            )

st.divider()


# --------------------------------------------------
# DASHBOARD DATA
# --------------------------------------------------

summary_response = api_request(
    "GET",
    f"/users/{user_id}/metrics/summary"
)

medications_response = api_request(
    "GET",
    f"/users/{user_id}/medications"
)


if summary_response is None:
    st.stop()

if summary_response.status_code != 200:

    st.error("Unable to load health summary.")
    st.stop()

summary = summary_response.json()

medications = (
    medications_response.json()
    if medications_response is not None
    and medications_response.status_code == 200
    else []
)


# --------------------------------------------------
# AGENTIC AI HEALTH OVERVIEW (PHASE 8)
# --------------------------------------------------

st.header("🤖 Agentic Health Overview")
st.caption(
    "Coordinated multi-agent intelligence evaluating monitoring rules, "
    "risk patterns, medication adherence, verified medical knowledge, and safety escalations."
)

with st.container():
    orch_col1, orch_col2 = st.columns([3, 1])
    with orch_col1:
        st.info(
            "The Agentic Orchestrator coordinates specialized autonomous agents to produce "
            "explainable, grounded clinical assessments while strictly enforcing safety guardrails."
        )
    with orch_col2:
        run_assessment_btn = st.button(
            "⚡ Run Agentic Assessment",
            key="btn_run_agentic_assessment",
            type="primary",
            use_container_width=True,
        )

# Fetch latest summary or trigger assessment
if run_assessment_btn or "agentic_summary" not in st.session_state:
    with st.spinner("Agents coordinating health assessment..."):
        summary_resp = api_request(
            "GET",
            f"/orchestration/summary?user_id={user_id}&primary_metric=blood_glucose",
        )
        if summary_resp and summary_resp.status_code == 200:
            st.session_state.agentic_summary = summary_resp.json()
        elif "agentic_summary" not in st.session_state:
            st.session_state.agentic_summary = None

agentic_data = st.session_state.get("agentic_summary")

if agentic_data:
    state_val = agentic_data.get("orchestration_state", "completed")
    state_color = {
        "completed": "🟢 Normal / Complete",
        "escalated": "🚨 URGENT SAFETY ESCALATION",
        "degraded": "🟡 Degraded (Offline Knowledge Service)",
        "in_progress": "🔵 In Progress",
    }.get(state_val, f"Status: {state_val}")

    if state_val == "escalated":
        st.error(f"### {state_color}")
        esc_info = agentic_data.get("safety_escalation") or {}
        st.warning(f"**Emergency Guidance:** {esc_info.get('urgent_reason', 'Critical condition detected.')}")
        st.info(esc_info.get("guidance", "Please seek professional medical assistance immediately."))
    else:
        st.markdown(
            f"**Orchestration Status:** `{state_color}` | "
            f"Generated: `{agentic_data.get('generated_at', '')[:19]}` | "
            f"Execution Time: `{agentic_data.get('duration_ms', 0)}ms`"
        )

    # 4 Quadrants
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        st.markdown("#### 🩺 Monitoring")
        mon = agentic_data.get("monitoring") or {}
        st.metric(
            label=f"{mon.get('metric_type', 'Metric').replace('_', ' ').title()}",
            value=f"{mon.get('latest_value', 'N/A')} {mon.get('unit', '')}",
            delta=mon.get("statistical_status", "routine").replace("_", " "),
        )
        st.caption(mon.get("summary", "No monitoring observations."))

    with q2:
        st.markdown("#### 💊 Adherence")
        med = agentic_data.get("medication") or {}
        adh_pct = med.get("overall_adherence_percentage")
        st.metric(
            label="Adherence Rate",
            value=f"{adh_pct}%" if adh_pct is not None else "N/A",
            delta=f"{med.get('overdue_doses_count', 0)} overdue doses",
            delta_color="inverse",
        )
        st.caption(
            f"{med.get('active_medications_count', 0)} active meds, "
            f"{len(med.get('pending_reminders', []))} pending reminder(s)."
        )

    with q3:
        st.markdown("#### ⚠️ Risk Indicators")
        risk = agentic_data.get("risk_assessment") or {}
        r_level = risk.get("risk_level", "low").upper()
        st.metric(label="Assessed Risk Level", value=r_level)
        findings = risk.get("rule_based_findings", [])
        if findings:
            st.caption(f"Validated findings: {len(findings)} trend observation(s).")
        ml_est = risk.get("experimental_ml_estimates", [])
        if ml_est:
            st.warning("Contains experimental ML estimates (research demonstration only).")

    with q4:
        st.markdown("#### 🔔 Notifications")
        notifs = agentic_data.get("notifications") or {}
        notif_list = notifs.get("notifications_created", [])
        st.metric(label="Delivered Alerts", value=len(notif_list))
        st.caption(f"{notifs.get('suppressed_count', 0)} duplicate alerts suppressed.")

    # Supporting Grounded Knowledge
    know = agentic_data.get("medical_knowledge") or {}
    citations = know.get("citations", [])
    if citations:
        with st.expander(f"📚 Grounded Medical References ({len(citations)} sources cited)", expanded=False):
            st.markdown(f"**Agent Explanation:**\n{know.get('explanation', '')}")
            st.markdown("---")
            for idx, cite in enumerate(citations, 1):
                st.markdown(
                    f"**[{idx}] {cite.get('title', 'Reference Document')}** — "
                    f"*{cite.get('source_organization', 'Health Authority')}*"
                )
                if cite.get("source_url"):
                    st.caption(f"Source URL: {cite.get('source_url')}")
                st.markdown(f"> {cite.get('excerpt', '')}")

    # Agent Audit Trail
    with st.expander("📜 Agent Coordination History & Audit Logs", expanded=False):
        history_resp = api_request("GET", f"/orchestration/history?user_id={user_id}&limit=10")
        if history_resp and history_resp.status_code == 200:
            hist_records = history_resp.json()
            if hist_records:
                hist_df = pd.DataFrame(hist_records)
                cols = [c for c in ["created_at", "workflow_type", "status", "duration_ms", "summary"] if c in hist_df.columns]
                hist_df = hist_df[cols]
                st.dataframe(hist_df, use_container_width=True)
            else:
                st.caption("No agent activity recorded yet.")
        else:
            st.caption("Agent execution history currently unavailable.")

st.divider()

# --------------------------------------------------
# HEALTH OVERVIEW
# --------------------------------------------------

st.header("Health Overview")

col1, col2, col3 = st.columns(3)

col1.metric(
    "Total Readings",
    summary.get("total_readings", 0)
)

col2.metric(
    "Metric Categories",
    summary.get("total_metric_groups", 0)
)

col3.metric(
    "Active Medications",
    len(medications)
)

st.divider()


# --------------------------------------------------
# HEALTH METRICS
# --------------------------------------------------

st.subheader("Health Metrics")

summaries = summary.get("summaries", [])

if summaries:

    for metric in summaries:

        st.markdown(
            f"### {metric['metric_type'].replace('_', ' ').title()}"
        )

        c1, c2, c3, c4 = st.columns(4)

        latest = metric.get("latest_reading", {})

        c1.metric(
            "Latest",
            f"{latest.get('value', 'N/A')} {metric['unit']}"
        )

        c2.metric(
            "Average",
            f"{metric['average']} {metric['unit']}"
        )

        c3.metric(
            "Minimum",
            f"{metric['minimum']} {metric['unit']}"
        )

        c4.metric(
            "Maximum",
            f"{metric['maximum']} {metric['unit']}"
        )

        daily_data = metric.get("daily_averages", [])

        if daily_data:

            df = pd.DataFrame(daily_data)

            fig = px.line(
                df,
                x="date",
                y="average",
                markers=True,
                title="Daily Average Trend"
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

        st.divider()

else:

    st.info("No health metrics recorded yet.")


# --------------------------------------------------
# HEALTH TREND INSIGHTS — DATABASE-CONNECTED
# --------------------------------------------------

st.subheader("Health Trend Insights")
st.caption(
    "Descriptive changes in recorded measurements, not a medical assessment. "
    "The direction compares the first and last selected readings; "
    "it does not establish a sustained trend."
)

trend_metric_labels = {
    "blood_glucose": "Blood Glucose",
    "heart_rate": "Heart Rate",
    "blood_pressure_systolic": "Blood Pressure — Systolic",
    "blood_pressure_diastolic": "Blood Pressure — Diastolic",
    "weight": "Weight",
    "height": "Height",
    "steps": "Steps",
    "sleep_duration": "Sleep Duration",
}

available_trend_types = sorted({
    item.get("metric_type")
    for item in summaries
    if item.get("metric_type") in trend_metric_labels
})

if not available_trend_types:
    st.info("Record health measurements to view trend insights.")
else:
    trend_col1, trend_col2 = st.columns([3, 1])
    with trend_col1:
        selected_trend_type = st.selectbox(
            "Measurement",
            options=available_trend_types,
            format_func=lambda value: trend_metric_labels[value],
            key="trend_metric_selection",
        )
    with trend_col2:
        trend_limit = st.number_input(
            "Recent readings",
            min_value=2,
            max_value=500,
            value=100,
            step=1,
            key="trend_reading_limit",
        )

    trend_response = api_request(
        "GET",
        f"/users/{user_id}/metrics/{selected_trend_type}/trend",
        params={"limit": int(trend_limit)},
    )

    if trend_response is None:
        st.warning("Trend insights are temporarily unavailable.")
    elif trend_response.status_code != 200:
        st.warning(
            "Could not load trend insights "
            f"(HTTP {trend_response.status_code})."
        )
    else:
        trend_data = trend_response.json()
        unit_trends = trend_data.get("unit_trends", [])

        if not unit_trends:
            st.info(
                "At least two recorded measurements with the same unit "
                "are needed to calculate a change."
            )
        else:
            for trend in unit_trends:
                unit = trend.get("unit", "")
                st.markdown(f"**Unit: {unit}**")
                tc1, tc2, tc3, tc4 = st.columns(4)
                tc1.metric("Latest", f"{trend['latest_value']:g} {unit}")
                tc2.metric("Average", f"{trend['mean']:g} {unit}")
                tc3.metric("Minimum", f"{trend['minimum']:g} {unit}")
                tc4.metric("Maximum", f"{trend['maximum']:g} {unit}")

                percent = trend.get("percentage_change")
                percent_text = (
                    f"{percent:+.2f}%" if percent is not None
                    else "Not available (first reading was zero)"
                )
                st.write(
                    f"**First-to-last change:** {trend['absolute_change']:+g} "
                    f"{unit} ({percent_text}) · "
                    f"**Direction:** {trend['direction']} · "
                    f"**Readings:** {trend['count']}"
                )
                st.caption(
                    f"From {trend['first_recorded_at']} "
                    f"to {trend['latest_recorded_at']} (UTC)."
                )

            # Fetch actual observations to plot, rather than drawing an
            # invented straight line between the first and last values.
            history_response = api_request(
                "GET",
                f"/users/{user_id}/metrics",
                params={
                    "metric_type": selected_trend_type,
                    "limit": int(trend_limit),
                },
            )
            if history_response is not None and history_response.status_code == 200:
                history = history_response.json()
                if history:
                    history_df = pd.DataFrame(history)
                    history_df["recorded_at"] = pd.to_datetime(
                        history_df["recorded_at"], utc=True, errors="coerce"
                    )
                    history_df = history_df.dropna(subset=["recorded_at", "value"])
                    history_df = history_df.sort_values(["recorded_at", "id"])
                    if not history_df.empty:
                        chart = px.line(
                            history_df,
                            x="recorded_at",
                            y="value",
                            color="unit",
                            markers=True,
                            title=f"Recorded {trend_metric_labels[selected_trend_type]} Measurements",
                            labels={
                                "recorded_at": "Recorded at (UTC)",
                                "value": "Measured value",
                                "unit": "Unit",
                            },
                        )
                        st.plotly_chart(chart, use_container_width=True)
            else:
                st.caption("Historical chart is currently unavailable.")

            st.caption(
                trend_data.get(
                    "disclaimer",
                    "Recorded measurements are informational and not a diagnosis.",
                )
            )

st.divider()


# --------------------------------------------------
# BLOOD PRESSURE HISTORY
# --------------------------------------------------

st.subheader("Blood Pressure History")

bp_response = api_request(
    "GET",
    f"/users/{user_id}/metrics/blood-pressure/history"
)

if bp_response is not None and bp_response.status_code == 200:

    bp_data = bp_response.json()

    if bp_data.get("history"):

        bp_df = pd.DataFrame(bp_data["history"])

        bp_df = bp_df.sort_values("recorded_at")

        fig = px.line(
            bp_df,
            x="recorded_at",
            y=["systolic", "diastolic"],
            markers=True,
            title="Blood Pressure Trends",
            labels={
                "recorded_at": "Date",
                "value": "Blood Pressure (mmHg)",
                "variable": "Reading"
            }
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

    else:

        st.info("No paired blood pressure readings available.")

else:

    st.warning("Unable to retrieve blood pressure history.")


# ============================================================
# PHASE 6 — COMPLETE MEDICATION MANAGEMENT SYSTEM
# ============================================================

st.subheader("💊 Medication Management & Adherence")
st.caption(
    "Manage prescribed medications, configure structured dose schedules, "
    "record dose outcomes, view adherence analytics, and track reminders."
)

med_tab1, med_tab2, med_tab3, med_tab4 = st.tabs([
    "📅 Today's Doses",
    "📋 Medications & Schedules",
    "📊 Adherence Analytics & Timeline",
    "🔔 Medication Reminders",
])

# ------------------------------------------------------------
# TAB 1: TODAY'S DOSES & CONFIRMATION
# ------------------------------------------------------------
with med_tab1:
    today_response = api_request("GET", f"/medications/user/{user_id}/today")
    if today_response is not None and today_response.status_code == 200:
        today_data = today_response.json()
        doses = today_data.get("doses", [])
        st.write(f"**Date:** {today_data.get('date')} · **Scheduled Doses Today:** {today_data.get('total', 0)}")

        if not doses:
            st.info("No medication doses scheduled for today.")
        else:
            taken_count = sum(1 for d in doses if d["status"] == "taken")
            due_count = sum(1 for d in doses if d["status"] == "due")
            overdue_count = sum(1 for d in doses if d["status"] == "overdue")
            upcoming_count = sum(1 for d in doses if d["status"] == "upcoming")
            skipped_count = sum(1 for d in doses if d["status"] == "skipped")

            m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
            m_col1.metric("Taken", taken_count)
            m_col2.metric("Due Now", due_count)
            m_col3.metric("Overdue", overdue_count)
            m_col4.metric("Upcoming", upcoming_count)
            m_col5.metric("Skipped", skipped_count)

            st.divider()

            for dose in doses:
                occ_id = dose["occurrence_id"]
                med_name = dose["medication_name"]
                sched_time = dose["scheduled_at"]
                status = dose["status"]

                status_badges = {
                    "taken": "🟢 Taken",
                    "due": "🟡 Due Now",
                    "overdue": "🔴 Overdue",
                    "upcoming": "⚪ Upcoming",
                    "skipped": "🟠 Skipped",
                    "missed": "❌ Missed",
                }

                with st.container(border=True):
                    sc1, sc2 = st.columns([3, 2])
                    with sc1:
                        st.markdown(f"**{med_name}** — {status_badges.get(status, status)}")
                        st.caption(f"Scheduled at: {sched_time}")
                        if dose.get("taken_at"):
                            st.caption(f"Confirmed taken at: {dose['taken_at']}")
                        if dose.get("notes"):
                            st.caption(f"Notes: {dose['notes']}")

                    with sc2:
                        note_input = st.text_input(
                            "Notes (optional)",
                            key=f"note_occ_{occ_id}",
                            placeholder="e.g. taken with breakfast",
                        )
                        b_col1, b_col2 = st.columns(2)
                        with b_col1:
                            if st.button("Mark Taken", key=f"btn_taken_{occ_id}", use_container_width=True):
                                confirm_resp = api_request(
                                    "PATCH",
                                    f"/medications/occurrences/{occ_id}",
                                    json={"status": "taken", "notes": note_input or None},
                                )
                                if confirm_resp is not None and confirm_resp.status_code == 200:
                                    st.success(f"{med_name} marked as taken!")
                                    st.rerun()
                                else:
                                    st.error("Failed to update dose status.")
                        with b_col2:
                            if st.button("Mark Skipped", key=f"btn_skip_{occ_id}", use_container_width=True):
                                skip_resp = api_request(
                                    "PATCH",
                                    f"/medications/occurrences/{occ_id}",
                                    json={"status": "skipped", "notes": note_input or None},
                                )
                                if skip_resp is not None and skip_resp.status_code == 200:
                                    st.info(f"{med_name} marked as skipped.")
                                    st.rerun()
                                else:
                                    st.error("Failed to update dose status.")
    else:
        st.warning("Could not load today's scheduled doses.")


# ------------------------------------------------------------
# TAB 2: MEDICATIONS & SCHEDULE CONFIGURATION
# ------------------------------------------------------------
with med_tab2:
    all_meds_resp = api_request("GET", f"/medications/user/{user_id}/all?include_inactive=true")
    all_medications = all_meds_resp.json() if all_meds_resp and all_meds_resp.status_code == 200 else []

    st.markdown("### Prescribed Medications")
    if not all_medications:
        st.info("No medications added yet. Use the form below to add your first medication.")
    else:
        for med in all_medications:
            med_id = med["id"]
            is_active = med.get("is_active", True)
            status_text = "Active" if is_active else "Inactive (Deactivated)"

            with st.expander(f"{med['name']} ({med['dosage']}) — {status_text}"):
                st.write(f"**Frequency:** {med['frequency']}")
                st.write(f"**Instructions:** {med.get('instructions') or 'None specified'}")
                st.write(f"**Start Date:** {med['start_date'][:10]}")
                if med.get("end_date"):
                    st.write(f"**End Date:** {med['end_date'][:10]}")

                # Schedule details
                sched_resp = api_request("GET", f"/medications/{med_id}/schedule")
                sched_data = sched_resp.json().get("schedule") if sched_resp and sched_resp.status_code == 200 else None

                if sched_data:
                    st.markdown("**Structured Schedule:**")
                    st.write(f"• **Type:** {sched_data.get('schedule_type')}")
                    st.write(f"• **Dose Times:** {', '.join(sched_data.get('times', []))}")
                    if sched_data.get("schedule_type") == "weekly":
                        days_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                        active_days = [days_map[d] for d in sched_data.get("weekdays", []) if d < 7]
                        st.write(f"• **Weekdays:** {', '.join(active_days)}")
                    st.write(f"• **Timezone:** {sched_data.get('timezone', 'UTC')}")
                else:
                    st.caption("No structured schedule configured yet for this medication.")

                st.divider()

                # Schedule Configuration Form
                if is_active:
                    st.markdown("#### Update / Configure Schedule")
                    with st.form(f"schedule_form_{med_id}"):
                        sch_type = st.selectbox(
                            "Schedule Type",
                            ["daily", "weekly", "as_needed"],
                            key=f"sch_type_{med_id}",
                        )
                        sch_times_input = st.text_input(
                            "Times of Day (comma-separated HH:MM)",
                            value="08:00, 20:00" if not sched_data else ", ".join(sched_data.get("times", [])),
                            key=f"sch_times_{med_id}",
                            help="Example: 08:00, 14:00, 20:00",
                        )
                        selected_weekdays = []
                        if sch_type == "weekly":
                            st.write("Select Days of Week:")
                            wd_cols = st.columns(7)
                            day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                            for d_idx, d_name in enumerate(day_labels):
                                with wd_cols[d_idx]:
                                    if st.checkbox(d_name, value=True, key=f"wd_{med_id}_{d_idx}"):
                                        selected_weekdays.append(d_idx)

                        timezone_choice = st.selectbox(
                            "User Timezone",
                            ["Asia/Kolkata", "UTC", "America/New_York", "Europe/London"],
                            key=f"tz_{med_id}",
                        )

                        save_sch_btn = st.form_submit_button("Save Schedule")
                        if save_sch_btn:
                            times_list = [t.strip() for t in sch_times_input.split(",") if t.strip()]
                            schedule_payload = {
                                "schedule_type": sch_type,
                                "times": times_list,
                                "weekdays": selected_weekdays if sch_type == "weekly" else [],
                                "timezone": timezone_choice,
                            }
                            res = api_request(
                                "POST",
                                f"/medications/{med_id}/schedule",
                                json=schedule_payload,
                            )
                            if res is not None and res.status_code == 200:
                                st.success("Schedule configured and upcoming occurrences generated!")
                                st.rerun()
                            else:
                                st.error(f"Schedule configuration failed: {res.text if res else 'Unknown error'}")

                    # Deactivate button
                    if st.button("Deactivate Medication", key=f"deact_btn_{med_id}"):
                        deact_resp = api_request("DELETE", f"/medications/{med_id}/deactivate")
                        if deact_resp is not None and deact_resp.status_code == 200:
                            st.success("Medication deactivated.")
                            st.rerun()
                        else:
                            st.error("Failed to deactivate medication.")

    st.divider()
    st.markdown("### Add New Medication")
    with st.form("add_medication_form"):
        new_name = st.text_input("Medication Name *", placeholder="e.g. Metformin")
        new_dosage = st.text_input("Dosage *", placeholder="e.g. 500 mg")
        new_freq = st.text_input("Frequency *", placeholder="e.g. Twice daily with meals")
        new_instr = st.text_area("Instructions", placeholder="e.g. Take with water after food")
        new_start = st.date_input("Start Date *")
        has_end = st.checkbox("Has End Date?")
        new_end = st.date_input("End Date") if has_end else None

        submit_new_med = st.form_submit_button("Add Medication", use_container_width=True)
        if submit_new_med:
            if not new_name or not new_dosage or not new_freq:
                st.warning("Please fill in all required fields (Name, Dosage, Frequency).")
            else:
                med_payload = {
                    "name": new_name.strip(),
                    "dosage": new_dosage.strip(),
                    "frequency": new_freq.strip(),
                    "instructions": new_instr.strip() if new_instr else None,
                    "start_date": new_start.isoformat(),
                    "end_date": new_end.isoformat() if new_end else None,
                }
                add_resp = api_request(
                    "POST",
                    f"/medications?user_id={user_id}",
                    json=med_payload,
                )
                if add_resp is not None and add_resp.status_code in (200, 201):
                    st.success("Medication added! You can now configure its schedule above.")
                    st.rerun()
                else:
                    st.error(f"Failed to add medication: {add_resp.text if add_resp else 'Connection error'}")


# ------------------------------------------------------------
# TAB 3: ADHERENCE ANALYTICS & TIMELINE
# ------------------------------------------------------------
with med_tab3:
    active_meds = [m for m in all_medications if m.get("is_active", True)]
    if not active_meds:
        st.info("No active medications found to compute adherence.")
    else:
        selected_med_id = st.selectbox(
            "Select Medication for Adherence & Timeline",
            options=[m["id"] for m in active_meds],
            format_func=lambda x: next((m["name"] for m in active_meds if m["id"] == x), str(x)),
            key="adh_med_select",
        )

        adh_resp = api_request("GET", f"/medications/{selected_med_id}/adherence-v2")
        if adh_resp is not None and adh_resp.status_code == 200:
            adh_data = adh_resp.json()
            st.markdown(f"### Adherence Summary: {adh_data.get('medication_name')}")

            overall = adh_data.get("overall", {})
            week = adh_data.get("last_7_days", {})
            month = adh_data.get("last_30_days", {})
            today_adh = adh_data.get("today", {})

            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Overall Adherence", f"{overall.get('adherence_percentage')}%" if overall.get('adherence_percentage') is not None else "N/A")
            a2.metric("Last 7 Days", f"{week.get('adherence_percentage')}%" if week.get('adherence_percentage') is not None else "N/A")
            a3.metric("Last 30 Days", f"{month.get('adherence_percentage')}%" if month.get('adherence_percentage') is not None else "N/A")
            a4.metric("Today", f"{today_adh.get('adherence_percentage')}%" if today_adh.get('adherence_percentage') is not None else "N/A")

            st.write(
                f"**Dose Counts (Overall):** Confirmed Taken: {overall.get('taken', 0)} | "
                f"Confirmed Skipped: {overall.get('skipped', 0)} | "
                f"Overdue / Unconfirmed: {overall.get('overdue_unconfirmed', 0)} | "
                f"Upcoming: {overall.get('upcoming', 0)}"
            )
            st.caption(adh_data.get("disclaimer", ""))

            # Timeline
            st.markdown("#### Chronological Dose Timeline")
            tl_resp = api_request("GET", f"/medications/{selected_med_id}/timeline?days_back=7&days_ahead=3")
            if tl_resp is not None and tl_resp.status_code == 200:
                tl_data = tl_resp.json()
                timeline_entries = tl_data.get("timeline", [])
                if timeline_entries:
                    tl_df = pd.DataFrame(timeline_entries)
                    st.dataframe(
                        tl_df[["scheduled_at", "status", "taken_at", "notes"]],
                        use_container_width=True,
                    )
                else:
                    st.caption("No dose events recorded in this time window.")
        else:
            st.warning("Could not calculate schedule-based adherence. Configure a schedule first.")


# ------------------------------------------------------------
# TAB 4: MEDICATION REMINDERS
# ------------------------------------------------------------
with med_tab4:
    st.markdown("### Active Medication Reminders")
    st.caption("Reminders are generated on the server for due and overdue scheduled doses.")

    rem_resp = api_request("GET", "/reminders/medications?status=pending")
    if rem_resp is not None and rem_resp.status_code == 200:
        rem_data = rem_resp.json()
        pending_reminders = rem_data.get("reminders", [])
        if not pending_reminders:
            st.success("🎉 You have no pending medication reminders!")
        else:
            for rem in pending_reminders:
                rem_id = rem["id"]
                with st.container(border=True):
                    rc1, rc2 = st.columns([4, 1])
                    with rc1:
                        st.markdown(f"**{rem['message']}**")
                        st.caption(f"Created: {rem['created_at']}")
                    with rc2:
                        if st.button("Acknowledge", key=f"ack_rem_{rem_id}", use_container_width=True):
                            ack_res = api_request("PATCH", f"/reminders/medications/{rem_id}/acknowledge")
                            if ack_res is not None and ack_res.status_code == 200:
                                st.success("Acknowledged!")
                                st.rerun()
    else:
        st.warning("Could not retrieve medication reminders.")

st.divider()


# ============================================================
# LONGITUDINAL HEALTH MONITORING
# ============================================================

st.divider()
st.header("Longitudinal Health Monitoring")

st.caption(
    "Compare recent measurements against your historical baseline "
    "and identify statistical deviations."
)

LONGITUDINAL_METRICS = {
    "Blood Glucose": "blood_glucose",
    "Heart Rate": "heart_rate",
    "Systolic Blood Pressure": "blood_pressure_systolic",
    "Diastolic Blood Pressure": "blood_pressure_diastolic",
    "Weight": "weight",
    "Height": "height",
    "Steps": "steps",
    "Sleep Duration": "sleep_duration",
}

with st.container():

    col1, col2, col3 = st.columns(3)

    with col1:
        selected_metric = st.selectbox(
            "Health Metric",
            options=list(LONGITUDINAL_METRICS.keys()),
            key="longitudinal_metric",
        )

    with col2:
        baseline_window = st.number_input(
            "Historical Baseline Readings",
            min_value=2,
            max_value=100,
            value=5,
            step=1,
            key="longitudinal_baseline",
        )

    with col3:
        recent_window = st.number_input(
            "Recent Readings",
            min_value=1,
            max_value=100,
            value=3,
            step=1,
            key="longitudinal_recent",
        )

    anomaly_threshold = st.slider(
        "Statistical Deviation Threshold",
        min_value=1.0,
        max_value=5.0,
        value=2.0,
        step=0.5,
        key="longitudinal_threshold",
    )

    analyze_clicked = st.button(
        "Analyze Longitudinal Health",
        use_container_width=True,
        key="run_longitudinal_analysis",
    )

if analyze_clicked:

    metric_type = LONGITUDINAL_METRICS[selected_metric]

    with st.spinner("Analyzing historical measurements..."):

        response = api_request(
            "GET",
            f"/users/{user_id}/metrics/{metric_type}/longitudinal",
            params={
                "baseline_window": int(baseline_window),
                "recent_window": int(recent_window),
                "anomaly_threshold": float(anomaly_threshold),
                "limit": 200,
            },
        )

    if response is None:
        st.error("Unable to connect to the analysis service.")

    elif response.status_code == 200:

        data = response.json()

        analyses = data.get("unit_analyses", [])

        if not analyses:
            st.info(
                data.get("message")
                or "Not enough compatible measurements for analysis."
            )

        else:

            for analysis in analyses:

                unit = analysis["unit"]

                st.subheader(
                    f"{selected_metric} — {unit}"
                )

                baseline = analysis["baseline"]
                recent = analysis["recent"]
                comparison = analysis["comparison"]
                anomaly = analysis["anomaly"]

                c1, c2, c3, c4 = st.columns(4)

                c1.metric(
                    "Historical Baseline",
                    f"{baseline['mean']:.2f} {unit}",
                )

                c2.metric(
                    "Recent Average",
                    f"{recent['mean']:.2f} {unit}",
                )

                c3.metric(
                    "Latest Reading",
                    f"{recent['latest_value']:.2f} {unit}",
                )

                percentage_change = comparison.get(
                    "percentage_change"
                )

                c4.metric(
                    "Change vs Baseline",
                    (
                        f"{percentage_change:+.2f}%"
                        if percentage_change is not None
                        else "N/A"
                    ),
                )

                st.write(
                    "**Observed Direction:**",
                    comparison["direction"].title(),
                )

                st.write(
                    "**Baseline Standard Deviation:**",
                    baseline["standard_deviation"],
                )

                st.subheader("Rolling Average")

                rolling_data = analysis.get(
                    "rolling_averages", []
                )

                if rolling_data:

                    rolling_df = pd.DataFrame(rolling_data)

                    rolling_df["recorded_at"] = pd.to_datetime(
                        rolling_df["recorded_at"],
                        utc=True,
                    )

                    rolling_df = rolling_df.sort_values(
                        "recorded_at"
                    )

                    fig = px.line(
                        rolling_df,
                        x="recorded_at",
                        y="average",
                        markers=True,
                        title=f"{selected_metric} Rolling Average",
                        labels={
                            "recorded_at": "Date",
                            "average": f"Average ({unit})",
                        },
                    )

                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                    )

                st.subheader("Statistical Deviation Analysis")

                anomaly_status = anomaly.get("status")

                if anomaly_status == "statistical_deviation_detected":

                    st.warning(
                        "A statistical deviation from the historical "
                        "baseline was detected. This does not necessarily "
                        "indicate a medical problem."
                    )

                elif anomaly_status == "within_configured_threshold":

                    st.success(
                        "The latest measurement is within the "
                        "configured statistical threshold. "
                        "This does not establish medical safety."
                    )

                elif anomaly_status == "insufficient_baseline_variability":

                    st.info(
                        "The historical baseline has no variation, "
                        "so a standard z-score cannot be calculated."
                    )

                z_score = anomaly.get("z_score")

                if z_score is not None:
                    st.metric(
                        "Statistical Z-Score",
                        f"{z_score:.3f}",
                    )

                st.caption(
                    analysis.get(
                        "disclaimer",
                        "Statistical analysis only. Not a medical diagnosis.",
                    )
                )

                st.divider()

    elif response.status_code == 422:
        st.error(
            "Invalid analysis parameters. "
            "Check the selected windows and threshold."
        )

    else:
        st.error(
            f"Longitudinal analysis failed "
            f"(HTTP {response.status_code})."
        )
# ============================================================
# HEALTH MONITORING AGENT DASHBOARD
# PHASE 3.2.5
# ============================================================

st.divider()

st.header("HealthGuard AI — Monitoring Agent")

st.caption(
    "AI-assisted statistical monitoring of recorded health "
    "measurements. Monitoring priorities indicate data-review "
    "attention, not medical urgency."
)

MONITORING_METRICS = {
    "Blood Glucose": "blood_glucose",
    "Heart Rate": "heart_rate",
    "Systolic Blood Pressure": "blood_pressure_systolic",
    "Diastolic Blood Pressure": "blood_pressure_diastolic",
    "Weight": "weight",
    "Height": "height",
    "Steps": "steps",
    "Sleep Duration": "sleep_duration",
}

# ------------------------------------------------------------
# MONITORING CONFIGURATION
# ------------------------------------------------------------

with st.container():

    monitor_col1, monitor_col2, monitor_col3 = st.columns(3)

    with monitor_col1:

        monitoring_metric = st.selectbox(
            "Select Health Metric",
            options=list(MONITORING_METRICS.keys()),
            key="monitoring_agent_metric",
        )

    with monitor_col2:

        monitoring_baseline = st.number_input(
            "Baseline Readings",
            min_value=2,
            max_value=100,
            value=5,
            step=1,
            key="monitoring_agent_baseline",
        )

    with monitor_col3:

        monitoring_recent = st.number_input(
            "Recent Readings",
            min_value=1,
            max_value=100,
            value=3,
            step=1,
            key="monitoring_agent_recent",
        )

    monitoring_threshold = st.slider(
        "Statistical Deviation Threshold",
        min_value=1.0,
        max_value=5.0,
        value=2.0,
        step=0.5,
        key="monitoring_agent_threshold",
    )

    run_monitoring = st.button(
        "Run Health Monitoring Agent",
        use_container_width=True,
        key="run_health_monitoring_agent",
    )


# ------------------------------------------------------------
# EXECUTE MONITORING AGENT
# ------------------------------------------------------------

if run_monitoring:

    selected_monitoring_metric = MONITORING_METRICS[
        monitoring_metric
    ]

    with st.spinner("Running HealthGuard monitoring pipeline..."):

        try:

            monitoring_response = api_request(
                "GET",
                (
                    f"/users/{user_id}/metrics/"
                    f"{selected_monitoring_metric}/monitoring"
                ),
                params={
                    "baseline_window": int(monitoring_baseline),
                    "recent_window": int(monitoring_recent),
                    "anomaly_threshold": float(monitoring_threshold),
                    "limit": 200,
                },
            )

        except requests.RequestException:

            monitoring_response = None

    if monitoring_response is None:

        st.error(
            "Unable to connect to the HealthGuard monitoring service."
        )

    elif monitoring_response.status_code == 200:

        monitoring_data = monitoring_response.json()

        monitoring_reports = monitoring_data.get("reports", [])

        if not monitoring_reports:

            st.info(
                monitoring_data.get("message")
                or "Not enough compatible measurements for monitoring."
            )

            for insufficient in monitoring_data.get(
                "insufficient_units", []
            ):

                st.caption(
                    f"{insufficient['unit']}: "
                    f"{insufficient['available_readings']} available, "
                    f"{insufficient['required_readings']} required."
                )

        else:

            for report in monitoring_reports:

                decision = report["monitoring_decision"]

                longitudinal = report["longitudinal_analysis"]

                safety = report["safety_validation"]

                unit = report["unit"]

                st.subheader(
                    f"{monitoring_metric} — {unit}"
                )

                # --------------------------------------------
                # MONITORING PRIORITY
                # --------------------------------------------

                priority = decision.get(
                    "monitoring_priority",
                    "unknown",
                )

                if priority == "review_recommended":

                    st.warning(
                        "Statistical Review Recommended"
                    )

                elif priority == "more_data_needed":

                    st.info(
                        "More Data Needed"
                    )

                elif priority == "routine_tracking":

                    st.success(
                        "Routine Statistical Tracking"
                    )

                else:

                    st.error(
                        "Unknown monitoring priority."
                    )

                st.caption(
                    "This priority describes statistical "
                    "data-review attention, not clinical urgency."
                )

                # --------------------------------------------
                # STATISTICAL EVIDENCE
                # --------------------------------------------

                baseline = longitudinal["baseline"]

                recent = longitudinal["recent"]

                comparison = longitudinal["comparison"]

                anomaly = longitudinal["anomaly"]

                evidence_col1, evidence_col2, evidence_col3 = (
                    st.columns(3)
                )

                evidence_col1.metric(
                    "Baseline Average",
                    f"{baseline['mean']:.2f} {unit}",
                )

                evidence_col2.metric(
                    "Recent Average",
                    f"{recent['mean']:.2f} {unit}",
                )

                evidence_col3.metric(
                    "Latest Measurement",
                    f"{recent['latest_value']:.2f} {unit}",
                )

                st.write(
                    "**Observed Direction:**",
                    comparison["direction"].title(),
                )

                percentage_change = comparison.get(
                    "percentage_change"
                )

                if percentage_change is not None:

                    st.write(
                        "**Change From Baseline:**",
                        f"{percentage_change:+.2f}%",
                    )

                st.write(
                    "**Baseline Standard Deviation:**",
                    baseline["standard_deviation"],
                )

                z_score = anomaly.get("z_score")

                if z_score is not None:

                    st.metric(
                        "Statistical Z-Score",
                        f"{z_score:.3f}",
                    )

                else:

                    st.info(
                        "Z-score unavailable because the "
                        "baseline has insufficient variability."
                    )

                # --------------------------------------------
                # AGENT EXPLANATION
                # --------------------------------------------

                st.subheader("Monitoring Agent Explanation")

                st.write(
                    decision.get(
                        "summary",
                        "No explanation available.",
                    )
                )

                # --------------------------------------------
                # RECOMMENDED ACTIONS
                # --------------------------------------------

                st.subheader("Recommended Data-Review Actions")

                actions = decision.get(
                    "recommended_actions", []
                )

                for index, action in enumerate(actions, start=1):

                    st.write(
                        f"{index}. {action}"
                    )

                # --------------------------------------------
                # ROLLING AVERAGE CHART
                # --------------------------------------------

                rolling_data = longitudinal.get(
                    "rolling_averages", []
                )

                if rolling_data:

                    st.subheader(
                        "Historical Rolling Average"
                    )

                    monitoring_df = pd.DataFrame(
                        rolling_data
                    )

                    monitoring_df["recorded_at"] = (
                        pd.to_datetime(
                            monitoring_df["recorded_at"],
                            utc=True,
                        )
                    )

                    monitoring_df = monitoring_df.sort_values(
                        "recorded_at"
                    )

                    monitoring_fig = px.line(
                        monitoring_df,
                        x="recorded_at",
                        y="average",
                        markers=True,
                        title=(
                            f"{monitoring_metric} "
                            f"Rolling Average"
                        ),
                        labels={
                            "recorded_at": "Date",
                            "average": f"Average ({unit})",
                        },
                    )

                    st.plotly_chart(
                        monitoring_fig,
                        use_container_width=True,
                    )

                # --------------------------------------------
                # SAFETY VALIDATION
                # --------------------------------------------

                st.subheader("Agent Safety Validation")

                if safety.get("safe") is True:

                    st.success(
                        "Monitoring decision passed "
                        "the configured safety checks."
                    )

                else:

                    st.error(
                        "Monitoring decision failed safety validation."
                    )

                with st.expander(
                    "View Safety Validation Details"
                ):

                    checks = safety.get("checks", {})

                    for check_name, check_status in checks.items():

                        readable_name = (
                            check_name.replace("_", " ").title()
                        )

                        st.write(
                            f"**{readable_name}:** "
                            f"{check_status}"
                        )

                    st.caption(
                        safety.get(
                            "limitations",
                            "Safety validation has limitations.",
                        )
                    )

                # --------------------------------------------
                # DISCLAIMERS
                # --------------------------------------------

                st.caption(
                    decision.get(
                        "disclaimer",
                        "Statistical monitoring only.",
                    )
                )

                st.divider()

            st.caption(
                monitoring_data.get(
                    "disclaimer",
                    "Monitoring results are not medical diagnoses.",
                )
            )

    elif monitoring_response.status_code == 401:

        st.error(
            "Your session has expired. Please log in again."
        )

    elif monitoring_response.status_code == 403:

        st.error(
            "You do not have permission to access "
            "these monitoring records."
        )

    elif monitoring_response.status_code == 422:

        st.error(
            "Monitoring analysis could not be completed. "
            "Check the selected parameters and recorded measurements."
        )

    else:

        st.error(
            "Health monitoring failed "
            f"(HTTP {monitoring_response.status_code})."
        )
# ============================================================
# MONITORING EVENT HISTORY & ACKNOWLEDGMENT — PHASE 3.3.6
# ============================================================

st.divider()
st.header("Monitoring Events")
st.caption(
    "Persisted statistical monitoring observations. Review priority is "
    "not clinical urgency; acknowledgment does not mean notification delivery."
)

monitoring_events_base = f"/users/{user_id}/monitoring/events"

summary_event_response = api_request("GET", f"{monitoring_events_base}/summary")

if summary_event_response is None:
    st.warning("Monitoring event summary is temporarily unavailable.")
elif summary_event_response.status_code != 200:
    st.warning(
        "Could not load monitoring event summary "
        f"(HTTP {summary_event_response.status_code})."
    )
else:
    event_summary = summary_event_response.json()
    es1, es2, es3 = st.columns(3)
    es1.metric("Total Events", event_summary.get("total_events", 0))
    es2.metric("Unacknowledged", event_summary.get("unacknowledged", 0))
    es3.metric("Acknowledged", event_summary.get("acknowledged", 0))

    with st.expander("Event counts by category"):
        st.write("**Event types:**", event_summary.get("by_event_type", {}))
        st.write(
            "**Notification statuses:**",
            event_summary.get("by_notification_status", {}),
        )

st.subheader("Event History")

filter_col1, filter_col2, filter_col3 = st.columns(3)
with filter_col1:
    event_type_filter = st.selectbox(
        "Event type",
        [
            "All",
            "statistical_deviation",
            "insufficient_baseline_variability",
            "routine_monitoring",
        ],
        key="event_history_type_filter",
    )
with filter_col2:
    notification_filter = st.selectbox(
        "Notification status",
        ["All", "pending", "suppressed", "delivered", "failed"],
        key="event_history_notification_filter",
    )
with filter_col3:
    acknowledgment_filter = st.selectbox(
        "Acknowledgment",
        ["All", "Unacknowledged", "Acknowledged"],
        key="event_history_ack_filter",
    )

page_col1, page_col2 = st.columns(2)
with page_col1:
    event_page_size = st.selectbox(
        "Events per page", [10, 25, 50, 100], index=1,
        key="event_history_page_size",
    )
with page_col2:
    event_page = st.number_input(
        "Page", min_value=1, value=1, step=1,
        key="event_history_page_number",
    )

if st.button("Refresh event history", key="refresh_event_history"):
    st.rerun()

events_response = api_request(
    "GET",
    monitoring_events_base,
    params={
        "limit": int(event_page_size),
        "offset": (int(event_page) - 1) * int(event_page_size),
    },
)

if events_response is None:
    st.warning("Monitoring event history is temporarily unavailable.")
elif events_response.status_code != 200:
    st.warning(
        "Could not load monitoring event history "
        f"(HTTP {events_response.status_code})."
    )
else:
    event_history_data = events_response.json()
    all_page_events = event_history_data.get("events", [])
    total_events = event_history_data.get("total", 0)
    max_page = max(1, (total_events + int(event_page_size) - 1) // int(event_page_size))
    st.caption(
        f"Page {int(event_page)} of {max_page} · {total_events} stored events. "
        "Filters apply to the current page only."
    )

    visible_events = [
        item for item in all_page_events
        if (event_type_filter == "All" or item.get("event_type") == event_type_filter)
        and (
            notification_filter == "All"
            or item.get("notification_status") == notification_filter
        )
        and (
            acknowledgment_filter == "All"
            or bool(item.get("is_acknowledged"))
            == (acknowledgment_filter == "Acknowledged")
        )
    ]

    if not visible_events:
        st.info("No events match these filters on the selected page.")

    for event_item in visible_events:
        event_id = event_item.get("id")
        metric_label = str(event_item.get("metric_type", "Unknown")).replace("_", " ").title()
        event_label = str(event_item.get("event_type", "Unknown")).replace("_", " ").title()
        ack_label = "Acknowledged" if event_item.get("is_acknowledged") else "Unacknowledged"

        with st.expander(
            f"#{event_id} · {metric_label} · {event_label} · {ack_label}"
        ):
            st.write("**Observation:**", event_item.get("message", "Not available"))
            st.write("**Unit:**", event_item.get("unit", "Not available"))
            st.write("**Event level:**", event_item.get("event_level", "Not available"))
            st.write(
                "**Monitoring priority:**",
                event_item.get("monitoring_priority", "Not available"),
            )
            st.write(
                "**Statistical status:**",
                event_item.get("statistical_status", "Not available"),
            )
            st.write(
                "**Notification status:**",
                event_item.get("notification_status", "Not available"),
            )
            st.write("**Created (UTC):**", event_item.get("created_at") or "Not available")
            st.write("**Notified (UTC):**", event_item.get("notified_at") or "Not delivered")
            st.write(
                "**Acknowledged (UTC):**",
                event_item.get("acknowledged_at") or "Not acknowledged",
            )
            st.caption(
                event_item.get("disclaimer")
                or "Statistical observation only; not a medical diagnosis."
            )

            if not event_item.get("is_acknowledged"):
                if st.button(
                    "Acknowledge event",
                    key=f"ack_monitoring_event_{user_id}_{event_id}",
                ):
                    ack_response = api_request(
                        "PATCH", f"{monitoring_events_base}/{event_id}/acknowledge"
                    )
                    if ack_response is None:
                        st.error("Could not reach the acknowledgment service.")
                    elif ack_response.status_code == 200:
                        st.success("Event acknowledged.")
                        st.rerun()
                    else:
                        st.error(
                            "Acknowledgment failed "
                            f"(HTTP {ack_response.status_code})."
                        )

# ============================================================
# EXPERIMENTAL DIABETES SCREENING — V3
# ============================================================

st.divider()
st.header("Diabetes Screening — Research Demonstration")
st.warning(
    "Experimental research model only. Not a diagnostic test or a validated "
    "clinical screening tool. Do not use the result to make medical decisions."
)
st.info(
    "Training-data population: Pima Indian women aged 21 or older. "
    "The model is not validated for men, people under 21, or the general public. "
    "Even within the training-data population, it has not been clinically validated."
)

with st.expander("About the model and required measurements"):
    st.write("Model: Logistic Regression | Version: experimental-v3-candidate")
    st.write("Classification threshold: 0.30")
    st.write(
        "Eight features are required. Pregnancies means the number of times "
        "the person has been pregnant, including pregnancies without a live birth."
    )
    st.write(
        "Glucose, diastolic blood pressure, triceps skinfold thickness, "
        "2-hour serum insulin, BMI, diabetes pedigree function, and age must "
        "be supplied from actual measurements or records. Do not guess values."
    )
    st.write(
        "Diabetes pedigree function is a dataset-specific family-history score; "
        "it cannot be inferred from a simple yes/no family-history answer."
    )
    st.caption(
        "The model score is not a clinically validated probability of diabetes."
    )

with st.form("diabetes_v3_screening_form"):
    st.subheader("Patient Measurements")
    population_applicable = st.checkbox(
        "I confirm these measurements are for a woman aged 21 or older "
        "and understand that the model is experimental.",
        key="v3_population_applicable",
    )
    st.caption(
        "Use actual recorded values. Leave unknown measurements blank; "
        "do not substitute zeros or made-up numbers."
    )
    col1, col2 = st.columns(2)
    with col1:
        pregnancies = st.number_input(
            "Pregnancies", min_value=0, max_value=25, value=0,
            step=1, key="v3_pregnancies",
        )
        glucose = st.number_input(
            "Glucose (mg/dL)", min_value=1.0, max_value=600.0,
            value=None, key="v3_glucose",
        )
        blood_pressure = st.number_input(
            "Diastolic Blood Pressure (mmHg)", min_value=1.0,
            max_value=250.0, value=None, key="v3_blood_pressure",
        )
        skin_thickness = st.number_input(
            "Triceps Skinfold Thickness (mm)", min_value=1.0,
            max_value=100.0, value=None, key="v3_skin_thickness",
        )
    with col2:
        insulin = st.number_input(
            "2-hour Serum Insulin (µU/mL)", min_value=1.0,
            max_value=1000.0, value=None, key="v3_insulin",
        )
        bmi = st.number_input(
            "BMI (kg/m²)", min_value=0.1, max_value=100.0,
            value=None, key="v3_bmi",
        )
        diabetes_pedigree = st.number_input(
            "Diabetes Pedigree Function (dataset-specific score)",
            min_value=0.0, max_value=5.0, value=None, key="v3_pedigree",
        )
        age = st.number_input(
            "Age (years)", min_value=1, max_value=120,
            value=None, step=1, key="v3_age",
        )
    submitted = st.form_submit_button(
        "Run Experimental Screening", use_container_width=True,
    )

if submitted:
    # Always clear previous output, including after an invalid submission.
    st.session_state.pop("diabetes_v3_result", None)
    measurements = {
        "Pregnancies": pregnancies,
        "Glucose": glucose,
        "BloodPressure": blood_pressure,
        "SkinThickness": skin_thickness,
        "Insulin": insulin,
        "BMI": bmi,
        "DiabetesPedigreeFunction": diabetes_pedigree,
        "Age": age,
    }
    missing_fields = [
        name for name, value in measurements.items() if value is None
    ]
    if not population_applicable:
        st.error("Confirm the training-population limitation before proceeding.")
    elif age is None or age < 21:
        st.error("This research model is restricted to ages 21 and above.")
    elif missing_fields:
        st.error("Required measurements missing: " + ", ".join(missing_fields))
    else:
        with st.spinner("Running experimental model..."):
            response = api_request(
                "POST", "/ml/diabetes/predict-v3", json=measurements,
            )
        if response is None:
            st.error("Screening unavailable. Check the backend connection.")
        elif response.status_code == 200:
            try:
                result_data = response.json()
                if not isinstance(result_data, dict):
                    raise ValueError("Expected a JSON object")
                st.session_state["diabetes_v3_result"] = result_data
            except ValueError:
                st.error("Backend returned an invalid response.")
        elif response.status_code == 422:
            st.error("Invalid measurements. Review all values.")
        elif response.status_code == 503:
            st.error("The experimental model is temporarily unavailable.")
        else:
            st.error(
                "Screening could not be completed "
                f"(HTTP {response.status_code})."
            )

result = st.session_state.get("diabetes_v3_result")
if result is not None:
    st.subheader("Experimental Screening Result")
    st.caption(
        "Research population: Pima Indian women aged 21+. "
        "This result is not clinically validated."
    )
    prediction = result.get("prediction")
    score = result.get("model_score")
    threshold = result.get("threshold")
    if (
        type(prediction) is not int or prediction not in (0, 1)
        or type(score) not in (int, float)
        or type(threshold) not in (int, float)
        or not (0 <= score <= 1)
        or not (0 <= threshold <= 1)
    ):
        st.error("The backend returned an invalid model result.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Model Score (not clinical risk)", f"{score:.4f}")
        c2.metric("Decision Threshold", f"{threshold:.2f}")
        if prediction == 1:
            st.warning("Positive experimental model classification.")
        else:
            st.info("Negative experimental model classification.")
        st.write("**Model:**", result.get("model", "Unknown"))
        st.write("**Version:**", result.get("model_version", "Unknown"))
        st.caption(result.get("disclaimer", "Not a medical diagnosis."))
        st.info(
            "A positive result does not diagnose diabetes, and a negative "
            "result does not rule it out. For actual screening, consult a "
            "qualified healthcare professional about appropriate lab tests."
        )


# ============================================================
# PHASE 7 — MEDICAL KNOWLEDGE & RAG ASSISTANT
# ============================================================

st.divider()
st.header("🧠 Medical Intelligence & RAG Assistant")
st.caption(
    "Evidence-grounded medical assistance connecting approved clinical guidelines (WHO, AHA), "
    "your private medical records, and your longitudinal health measurements. "
    "Does not diagnose conditions or prescribe treatments."
)

rag_tab1, rag_tab2, rag_tab3, rag_tab4 = st.tabs([
    "💬 Medical Assistant",
    "📄 My Medical Documents",
    "📚 Clinical Knowledge Base",
    "🔍 Semantic Search Explorer",
])

# ------------------------------------------------------------
# TAB 1: MEDICAL ASSISTANT (CHAT / Q&A)
# ------------------------------------------------------------
with rag_tab1:
    rag_status_resp = api_request("GET", "/rag/status")
    if rag_status_resp is not None and rag_status_resp.status_code == 200:
        rag_status = rag_status_resp.json()
        status_col1, status_col2 = st.columns([1, 1])
        with status_col1:
            if rag_status.get("ollama_available"):
                st.success(f"🟢 Local LLM Online ({', '.join(rag_status.get('available_models', [])) or 'Ollama'})")
            else:
                st.info("ℹ️ Local LLM (Ollama) offline. Semantic retrieval and citation matching remain fully operational.")
        with status_col2:
            st.caption("🔒 Vector Search: Active · Local Isolation: Enforced")

    st.markdown("#### Ask a Medical or Health History Question")

    # Quick prompt shortcuts
    st.write("**Quick Topics:**")
    qc1, qc2, qc3 = st.columns(3)
    preset_q = ""
    with qc1:
        if st.button("AHA Blood Pressure Targets", key="qp1", use_container_width=True):
            preset_q = "What is the recommended blood pressure target according to AHA guidelines?"
    with qc2:
        if st.button("My 30-Day BP History", key="qp2", use_container_width=True):
            preset_q = "How has my blood pressure changed over the last month?"
    with qc3:
        if st.button("My Medication Adherence", key="qp3", use_container_width=True):
            preset_q = "Show my medication adherence for the past week."

    with st.form("medical_rag_form"):
        question_text = st.text_area(
            "Your Question",
            value=preset_q,
            placeholder="e.g. What does HbA1c measure, and how does it relate to blood glucose monitoring?",
            height=90,
            key="rag_question_input",
        )

        filter_c1, filter_c2 = st.columns(2)
        with filter_c1:
            inc_global = st.checkbox("Include Approved Clinical Guidelines (WHO, AHA)", value=True)
        with filter_c2:
            inc_user = st.checkbox("Include My Uploaded Documents & Records", value=True)

        ask_submitted = st.form_submit_button("Ask HealthGuard AI", use_container_width=True)

    if ask_submitted:
        if not question_text or len(question_text.strip()) < 3:
            st.warning("Please enter a question.")
        else:
            with st.spinner("Retrieving verified clinical evidence and personal context..."):
                payload = {
                    "question": question_text.strip(),
                    "include_global_knowledge": inc_global,
                    "include_user_documents": inc_user,
                    "n_results": 5,
                }
                rag_resp = api_request("POST", "/rag/ask", json=payload)

            if rag_resp is None:
                st.error("Could not connect to the Medical Assistant service.")
            elif rag_resp.status_code == 200:
                result = rag_resp.json()

                if result.get("is_emergency"):
                    st.error(result.get("emergency_guidance"))

                st.markdown("### Answer")
                st.write(result.get("answer") or "No response could be generated.")

                sources = result.get("sources", [])
                if sources:
                    with st.expander(f"📚 Retrieved Clinical References ({len(sources)} references)"):
                        for s_idx, src in enumerate(sources, 1):
                            st.markdown(f"**{s_idx}. {src.get('document_title', 'Untitled')}**")
                            if src.get("source_organization"):
                                st.caption(f"Organization: {src['source_organization']}")
                            st.caption(f"Chunk ID: `{src.get('chunk_id')}` · Relevance Distance: `{src.get('relevance_distance')}`")
                            st.divider()

                limitations = result.get("limitations", [])
                if limitations:
                    with st.expander("⚠️ Context & Data Limitations"):
                        for lim in limitations:
                            st.caption(f"• {lim}")

                st.info(result.get("disclaimer", "Educational information only; not medical advice."))
            elif rag_resp.status_code == 503:
                err_detail = rag_resp.json().get("detail", "Service unavailable")
                st.warning(f"Medical Assistant: {err_detail}")
                st.info("Tip: You can start Ollama locally (`ollama serve`) to enable language model generation. In the meantime, use the 'Semantic Search Explorer' tab to retrieve relevant clinical evidence directly.")
            else:
                st.error(f"Error {rag_resp.status_code}: {rag_resp.text}")


# ------------------------------------------------------------
# TAB 2: MY MEDICAL DOCUMENTS & INDEXING
# ------------------------------------------------------------
with rag_tab2:
    st.markdown("### Upload Medical Reports (PDF)")
    st.caption("Uploaded documents are stored privately for your account only and indexed for medical Q&A.")

    uploaded_file = st.file_uploader("Upload Medical PDF", type=["pdf"], key="rag_doc_uploader")
    if uploaded_file is not None:
        if st.button("Process & Upload Document", key="btn_upload_pdf"):
            with st.spinner("Extracting text and indexing document..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                token = st.session_state.get("access_token")
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                try:
                    up_resp = requests.post(f"{API_URL}/documents/upload", files=files, headers=headers, timeout=30)
                    if up_resp.status_code in (200, 201):
                        st.success(f"Uploaded and indexed '{uploaded_file.name}' successfully!")
                        st.rerun()
                    else:
                        st.error(f"Upload failed: {up_resp.text}")
                except Exception as up_exc:
                    st.error(f"Upload error: {up_exc}")

    st.divider()
    st.markdown("### My Uploaded Documents")
    user_docs_resp = api_request("GET", "/rag/documents")
    if user_docs_resp is not None and user_docs_resp.status_code == 200:
        docs_data = user_docs_resp.json().get("documents", [])
        if not docs_data:
            st.info("No documents uploaded yet.")
        else:
            for doc in docs_data:
                doc_id = doc["id"]
                with st.container(border=True):
                    dc1, dc2 = st.columns([3, 1])
                    with dc1:
                        st.markdown(f"**{doc['filename']}**")
                        st.caption(
                            f"Size: {doc['file_size'] // 1024} KB · "
                            f"Uploaded: {doc['uploaded_at'][:10]} · "
                            f"Status: `{doc.get('index_status', 'unknown')}` · "
                            f"Chunks: {doc.get('chunk_count') or 0}"
                        )
                    with dc2:
                        del_btn = st.button("Delete Document", key=f"del_doc_{doc_id}", use_container_width=True)
                        if del_btn:
                            del_resp = api_request("DELETE", f"/documents/{doc_id}")
                            if del_resp is not None and del_resp.status_code == 200:
                                st.success("Document and its vector embeddings deleted.")
                                st.rerun()
                            else:
                                st.error("Failed to delete document.")
    else:
        st.warning("Could not load uploaded documents.")


# ------------------------------------------------------------
# TAB 3: APPROVED CLINICAL KNOWLEDGE BASE
# ------------------------------------------------------------
with rag_tab3:
    st.markdown("### Approved Clinical Reference Documents")
    st.caption("These vetted guidelines from global health bodies (WHO, AHA) ground the AI's medical knowledge.")

    kb_resp = api_request("GET", "/rag/knowledge/documents")
    if kb_resp is not None and kb_resp.status_code == 200:
        kb_docs = kb_resp.json().get("documents", [])
        if not kb_docs:
            st.info("No clinical reference documents ingested yet.")
        else:
            for kb in kb_docs:
                with st.container(border=True):
                    st.markdown(f"**{kb['title']}**")
                    st.caption(
                        f"Organization: {kb.get('source_organization') or 'Clinical Standard'} · "
                        f"Type: {kb.get('document_type') or 'Guideline'} · "
                        f"Status: `{kb.get('index_status')}`"
                    )
    else:
        st.warning("Could not load knowledge documents.")


# ------------------------------------------------------------
# TAB 4: SEMANTIC SEARCH EXPLORER
# ------------------------------------------------------------
with rag_tab4:
    st.markdown("### Semantic Vector Search")
    st.caption("Search across the vector database to inspect indexed clinical evidence without text generation.")

    with st.form("semantic_search_form"):
        search_query = st.text_input("Search Clinical Knowledge", placeholder="e.g. hypertension treatment stages")
        search_source = st.selectbox("Search Target", ["global", "user", "both"], format_func=lambda x: {
            "global": "Approved Clinical Guidelines Only",
            "user": "My Uploaded Documents Only",
            "both": "Both Guidelines & My Documents",
        }[x])
        search_btn = st.form_submit_button("Search Evidence")

    if search_btn and search_query:
        with st.spinner("Searching semantic index..."):
            s_resp = api_request("GET", f"/rag/search?query={search_query}&source={search_source}&n_results=5")
        if s_resp is not None and s_resp.status_code == 200:
            s_data = s_resp.json()
            st.write(f"**Found {s_data.get('total_results', 0)} relevant evidence passages:**")
            for r_idx, res in enumerate(s_data.get("results", []), 1):
                with st.expander(f"Result {r_idx} (Distance: {res['distance']:.4f})"):
                    st.write(res["text"])
                    st.caption(f"Source: {res.get('source_type')} · Title: {res.get('metadata', {}).get('title', 'Unknown')}")
        else:
            st.error("Search failed.")


# --------------------------------------------------
# FOOTER
# --------------------------------------------------

st.divider()

st.caption(
    "HealthGuard AI | Personal Healthcare Intelligence Platform"
)

st.caption(
    "Health information is intended for tracking and informational "
    "purposes, not as a substitute for professional medical advice."
)