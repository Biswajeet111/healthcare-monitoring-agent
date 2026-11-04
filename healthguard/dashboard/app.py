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
            timeout=20,
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


# --------------------------------------------------
# MEDICATION MANAGEMENT
# --------------------------------------------------

st.subheader("Medication Management")

if medications:

    for medication in medications:

        with st.expander(medication["name"]):

            st.write(
                "**Dosage:**",
                medication["dosage"]
            )

            st.write(
                "**Frequency:**",
                medication["frequency"]
            )

            st.write(
                "**Instructions:**",
                medication.get("instructions") or "Not specified"
            )

            adherence_response = api_request(
                "GET",
                f"/medications/{medication['id']}/adherence"
            )

            if (
                adherence_response is not None
                and adherence_response.status_code == 200
            ):

                adherence = adherence_response.json()

                percentage = adherence.get(
                    "adherence_percentage"
                )

                st.metric(
                    "Medication Adherence",
                    f"{percentage}%"
                    if percentage is not None
                    else "No data"
                )

                st.write(
                    f"Taken: {adherence['taken']} | "
                    f"Missed: {adherence['missed']} | "
                    f"Skipped: {adherence['skipped']}"
                )

else:

    st.info("No active medications recorded.")


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