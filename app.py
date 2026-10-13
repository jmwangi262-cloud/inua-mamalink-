"""Inua MamaLink: beginner-friendly, aggregate-only nutrition logistics demo.

MIT-licensed educational prototype. Not a medical device and not clinical advice.
No patient, child or household data should be entered.
"""

from datetime import date, timedelta
from io import BytesIO
import hashlib

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Inua MamaLink | Demo", page_icon="🌱", layout="wide")

REQUIRED = ["date", "ward", "group", "item", "requested", "delivered"]
WARD_CHOICES = ["Kasuku", "Mirangine", "Other area"]
GROUP_CHOICES = ["Pregnant women", "Breastfeeding mothers", "Caregivers of children under 2"]
ITEM_CHOICES = ["Nutrition product units", "Nutrition information packs", "Service referral information packs"]


def empty_data():
    return pd.DataFrame(columns=REQUIRED)


def load_example():
    # All values are fictional. Do not claim they came from an actual pilot.
    return pd.read_csv("sample_data.csv")


def checked_data(frame):
    missing = [name for name in REQUIRED if name not in frame.columns]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    frame = frame[REQUIRED].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime("%Y-%m-%d")
    for name in ["ward", "group", "item"]:
        frame[name] = frame[name].fillna("").astype(str).str.strip()
        if frame[name].eq("").any():
            raise ValueError(f"Some rows have no {name}.")
    for name in ["requested", "delivered"]:
        values = pd.to_numeric(frame[name], errors="raise")
        if values.isna().any() or (values < 0).any() or ((values % 1) != 0).any():
            raise ValueError(f"{name} must be a whole number of zero or more.")
        frame[name] = values.astype(int)
    if (frame["delivered"] > frame["requested"]).any():
        raise ValueError("Delivered must not exceed requested in any row.")
    return frame


st.title("🌱 Inua MamaLink")
st.caption("A beginner-built demonstration for aggregate maternal nutrition logistics | Inua Slice Foods Ltd")
st.warning(
    "DEMONSTRATION ONLY. Do not enter names, phone numbers, health records, "
    "pregnancy details, patient identifiers or sensitive personal information. "
    "This is not a medical device, and it does not provide medical advice."
)

mode = st.sidebar.radio("Choose workspace", ["Practice with fictional records", "Start with an empty table"])
if st.session_state.get("active_mode") != mode:
    st.session_state["active_mode"] = mode
    st.session_state["records"] = load_example() if mode.startswith("Practice") else empty_data()
    st.session_state["upload_digest"] = None

st.sidebar.markdown("**How it works**")
st.sidebar.caption("1. Practice with examples. 2. Add weekly totals. 3. Inspect the dashboard. 4. Download CSV and keep it safe.")
st.sidebar.info("Entries last only during this app session. Download your CSV before closing or refreshing the browser.")

uploaded = st.sidebar.file_uploader("Optional: import your CSV with aggregate totals only", type="csv")
if uploaded is not None:
    upload_bytes = uploaded.getvalue()
    digest = hashlib.sha256(upload_bytes).hexdigest()
    if digest != st.session_state.get("upload_digest"):
        try:
            imported = checked_data(pd.read_csv(BytesIO(upload_bytes)))
            st.session_state["records"] = imported
            st.session_state["upload_digest"] = digest
            st.sidebar.success(f"Imported {len(imported)} rows.")
        except Exception as error:
            st.sidebar.error(f"CSV could not be imported: {error}")

records = checked_data(st.session_state["records"])
page = st.sidebar.selectbox("Open page", ["Overview", "Add a weekly record", "Forecast", "Data and export", "About and limitations"])

if mode.startswith("Practice") and uploaded is None:
    st.info("PRACTICE MODE: Every record is fictional. This is not evidence of an actual community pilot.")

if page == "Overview":
    st.header("Nutrition supply overview")
    if records.empty:
        st.info("Your table is empty. Select 'Add a weekly record' to enter aggregate counts.")
    else:
        requested = int(records["requested"].sum())
        delivered = int(records["delivered"].sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Units requested", f"{requested:,}")
        c2.metric("Units delivered", f"{delivered:,}")
        c3.metric("Fulfilment", f"{delivered / requested:.1%}" if requested else "N/A")
        c4.metric("Areas covered", records["ward"].nunique())
        display = records.copy()
        display["week"] = pd.to_datetime(display["date"]).dt.to_period("W-SUN").apply(lambda v: v.start_time)
        weekly = display.groupby("week", as_index=True)[["requested", "delivered"]].sum().sort_index()
        st.subheader("Weekly request and delivery totals")
        st.line_chart(weekly)
        st.subheader("Requests by location")
        st.bar_chart(records.groupby("ward")["requested"].sum().sort_values(ascending=False))
        st.caption("These are quantities of supply requests, not counts of unique women, children or clinical cases.")

elif page == "Add a weekly record":
    st.header("Record weekly totals — no personal information")
    st.write("Enter the total number of units requested and delivered for a location, population group and supply category.")
    with st.form("record_form", clear_on_submit=True):
        reporting_date = st.date_input("Reporting date", value=date.today())
        ward = st.selectbox("Location/ward", WARD_CHOICES)
        group = st.selectbox("Population group served", GROUP_CHOICES)
        item = st.selectbox("Supply category", ITEM_CHOICES)
        requested = st.number_input("Units requested", min_value=0, step=1, value=10)
        delivered = st.number_input("Units delivered", min_value=0, step=1, value=7)
        submit = st.form_submit_button("Save aggregate record")
    if submit:
        if delivered > requested:
            st.error("Delivered cannot exceed requested. Correct the numbers and try again.")
        else:
            row = {"date": reporting_date.isoformat(), "ward": ward, "group": group,
                   "item": item, "requested": int(requested), "delivered": int(delivered)}
            st.session_state["records"] = pd.concat(
                [records, pd.DataFrame([row])], ignore_index=True
            )
            st.success("Record added to this session. Download the CSV from 'Data and export' to save it.")
    st.write("Current rows:", len(st.session_state["records"]))

elif page == "Forecast":
    st.header("Simple weekly demand forecast")
    st.write("The prototype estimates next-week requests using the average of the last four observed weeks. It is a transparent baseline, not AI medical advice.")
    if records.empty:
        st.info("Add some records to see a forecast.")
    else:
        ward = st.selectbox("Forecast location", ["All areas"] + sorted(records["ward"].unique().tolist()))
        data = records if ward == "All areas" else records[records["ward"] == ward]
        df = data.copy()
        df["week"] = pd.to_datetime(df["date"]).dt.to_period("W-SUN").apply(lambda v: v.start_time)
        weekly = df.groupby("week")["requested"].sum().sort_index()
        complete_week_index = pd.date_range(weekly.index.min(), weekly.index.max(), freq="W-MON")
        weekly = weekly.reindex(complete_week_index, fill_value=0)
        baseline = float(weekly.tail(4).mean())
        st.metric("Estimated units requested per week", f"{baseline:,.1f}")
        st.caption("Method: mean weekly requested quantity over the latest 4 recorded calendar weeks, including empty weeks between first and last observed week.")
        future_dates = [weekly.index[-1] + timedelta(weeks=i) for i in range(1, 5)]
        prediction = pd.DataFrame({"week": future_dates, "estimated_requests": [round(baseline)] * 4})
        st.subheader("Next four calendar weeks")
        st.dataframe(prediction, hide_index=True, use_container_width=True)
        st.line_chart(weekly.rename("Observed requests"))
        if len(weekly) < 4:
            st.warning("Fewer than four weeks of data: this forecast is especially unreliable.")
        st.warning("Do not use these estimates for patient care, clinical triage or critical health supply decisions. Verify with responsible staff.")

elif page == "Data and export":
    st.header("Review and download")
    st.dataframe(records, hide_index=True, use_container_width=True)
    st.download_button(
        "Download your full aggregate CSV",
        data=records.to_csv(index=False).encode("utf-8"),
        file_name="inua_mamalink_aggregate_records.csv", mime="text/csv"
    )
    if not records.empty:
        summary = records.groupby(["ward", "group", "item"], as_index=False)[["requested", "delivered"]].sum()
        st.subheader("Aggregated reporting data")
        st.dataframe(summary, hide_index=True, use_container_width=True)
        st.download_button(
            "Download summary CSV",
            data=summary.to_csv(index=False).encode("utf-8"),
            file_name="inua_mamalink_summary.csv", mime="text/csv"
        )
    st.caption("No automatic storage, real-time data pipeline, authentication, or access controls are included in this learning prototype.")

else:
    st.header("About the prototype")
    st.markdown("""
    **Current capabilities:** record non-identifying area-level weekly totals, track fulfilment,
    view a dashboard, forecast weekly supply requests with a simple average, and download CSVs.

    **Not implemented:** automated WhatsApp integration, secure user accounts, persistent database,
    real-time reporting, machine learning, clinical risk assessment, health records, or referrals.

    **Next development priorities:** validate data definitions with women and health workers;
    obtain appropriate approvals for a voluntary field test; test forecast accuracy against observed demand;
    use a secure database with access controls for any operational deployment; implement transparent, safe,
    aggregate-only reporting; and consider advanced forecasting only when enough quality data is available.

    **Licence:** MIT (see LICENSE in the source code). This demonstration is not associated with or endorsed by UNICEF.
    """)
