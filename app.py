"""Inua MamaLink v2.1: aggregate-only nutrition supply coordination.

Optional private Google Sheet storage with server-side editor authentication.
Educational prototype only; no patient or identifying personal information.
"""

from datetime import date, timedelta
from io import BytesIO
import hashlib
import hmac
import json

import gspread

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



# CLOUD CONNECTION: keys must be kept in Streamlit Community Cloud > App settings > Secrets.
# Never store credentials or editor passwords in a public GitHub repository.
def cloud_settings():
    try:
        needed = ("google_sheet_id", "google_credentials_json", "editor_password")
        found = {key: st.secrets.get(key, "") for key in needed}
        if not all(found.values()):
            return None
        return found
    except (FileNotFoundError, KeyError):
        return None


class SetupProblem(Exception):
    """An intentionally non-sensitive diagnostic shown to the app operator."""


SETUP_HINTS = {
    "JSON_FORMAT": "The pasted Google credential JSON is not complete or has changed formatting. Recopy the ENTIRE downloaded JSON file into the Streamlit secret, including opening { and closing }.",
    "KEY_FIELDS": "The Google credential JSON is missing required fields or its private key is invalid. Recopy the ENTIRE JSON file into Streamlit Secrets. If still failing, create a new key in Google Cloud and replace the old credential securely.",
    "SERVICE_ACCOUNT": "Google could not read the service-account private key. Recopy the full JSON file, including the long private_key value, without editing it. If it still fails, create a replacement JSON key in Google Cloud and update the secret.",
    "SHEET_ACCESS": "Google cannot access this spreadsheet. Confirm the Sheet ID and share the correct spreadsheet with the service-account email as Editor. Keep General access Restricted.",
    "SHEET_API": "Google rejected the spreadsheet request. Check the Google Sheets API, service-account sharing and spreadsheet ID.",
    "SHEET_HEADER": "Check Row 1 of the FIRST worksheet tab. It must contain these six headings in order: date, ward, group, item, requested, delivered. Uppercase is fine.",
    "SHEET_ROWS": "The spreadsheet was found, but at least one data row has invalid values. Keep only the six headings while testing, or review dates, blanks and requested/delivered numbers.",
}


def connected_worksheet(settings):
    try:
        info = json.loads(settings["google_credentials_json"])
    except (ValueError, TypeError):
        raise SetupProblem("JSON_FORMAT") from None
    if not isinstance(info, dict) or not all(info.get(k) for k in ("type", "client_email", "private_key", "token_uri")):
        raise SetupProblem("KEY_FIELDS") from None
    if info.get("type") != "service_account":
        raise SetupProblem("KEY_FIELDS") from None
    try:
        client = gspread.service_account_from_dict(
            info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
    except (ValueError, TypeError, KeyError):
        raise SetupProblem("SERVICE_ACCOUNT") from None
    try:
        return client.open_by_key(settings["google_sheet_id"]).sheet1
    except gspread.exceptions.SpreadsheetNotFound:
        raise SetupProblem("SHEET_ACCESS") from None
    except gspread.exceptions.APIError:
        raise SetupProblem("SHEET_API") from None
    except ValueError:
        raise SetupProblem("SHEET_ACCESS") from None


def read_cloud_data(settings):
    try:
        rows = connected_worksheet(settings).get_all_values()
    except gspread.exceptions.APIError:
        raise SetupProblem("SHEET_API") from None
    if not rows:
        raise SetupProblem("SHEET_HEADER") from None
    headers = [value.strip().lower() for value in rows[0]]
    if headers[:len(REQUIRED)] != REQUIRED:
        raise SetupProblem("SHEET_HEADER") from None
    data_rows = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        data_rows.append((row + [""] * len(REQUIRED))[:len(REQUIRED)])
    try:
        return checked_data(pd.DataFrame(data_rows, columns=REQUIRED))
    except (ValueError, TypeError, KeyError):
        raise SetupProblem("SHEET_ROWS") from None


def save_cloud_record(settings, record):
    # append_row adds a new record; it does not overwrite other rows.
    data = [record[name] for name in REQUIRED]
    connected_worksheet(settings).append_row(data, value_input_option="RAW")

st.title("🌱 Inua MamaLink")
st.caption("Digital Maternal and Child Nutrition Supply Intelligence | Inua Slice Foods Ltd")
st.For aggregate supply records only. Do not enter personal or medical information.

settings = cloud_settings()
choices = ["Practice with fictional records", "Start with an empty table", "Connected Google Sheet"]
mode = st.sidebar.radio("Choose workspace", choices)
connected = mode == "Connected Google Sheet"
if st.session_state.get("active_mode") != mode:
    st.session_state["active_mode"] = mode
    st.session_state["records"] = load_example() if mode.startswith("Practice") else empty_data()
    st.session_state["upload_digest"] = None
    st.session_state["editor_unlocked"] = False

st.sidebar.markdown("**How it works**")
st.sidebar.caption("Use fictional examples first. Save non-sensitive aggregate totals only.")
if connected:
    if settings is None:
        st.sidebar.warning("Google Sheet not configured yet. Set the 3 credentials in Streamlit Cloud Secrets.")
        st.info("To connect your Google Sheet, configure **google_sheet_id**, **google_credentials_json**, and **editor_password** in Streamlit Cloud app settings → Secrets.")
        st.stop()
    st.sidebar.info("Private Google Sheet workspace selected. Connection check in progress.")
    if st.session_state.get("editor_unlocked", False):
        st.sidebar.success("Editing unlocked for this browser session")
        if st.sidebar.button("Lock editing"):
            st.session_state["editor_unlocked"] = False
            st.rerun()
    else:
        with st.sidebar.form("editor_login"):
            entered_password = st.text_input("Editing password", type="password")
            unlock = st.form_submit_button("Unlock editing")
        if unlock:
            if hmac.compare_digest(entered_password, settings["editor_password"]):
                st.session_state["editor_unlocked"] = True
                st.rerun()
            else:
                st.sidebar.error("Incorrect password")
    try:
        records = read_cloud_data(settings)
    except SetupProblem as error:
        st.error("Google Sheets connection needs a correction.")
        st.info(SETUP_HINTS[str(error)])
        with st.expander("Safe diagnostic code (no keys or passwords)"):
            st.code(str(error))
        st.stop()
    except Exception as error:
        st.error("An unexpected problem occurred while opening the Google Sheet.")
        with st.expander("Safe diagnostic (no keys or passwords)"):
            st.code(type(error).__name__)
        st.stop()
    st.sidebar.success("Google Sheets connected — data loaded successfully.")
    uploaded = None
else:
    st.sidebar.info("In this workspace, entries are temporary. Download your CSV before closing.")
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
    if connected and not st.session_state.get("editor_unlocked", False):
        st.info("This is a public website with **read-only** access for visitors. Enter the editing password in the sidebar to save to your private spreadsheet.")
    with st.form("record_form", clear_on_submit=True):
        reporting_date = st.date_input("Reporting date", value=date.today())
        ward = st.selectbox("Location/ward", WARD_CHOICES)
        group = st.selectbox("Population group served", GROUP_CHOICES)
        item = st.selectbox("Supply category", ITEM_CHOICES)
        requested = st.number_input("Units requested", min_value=0, step=1, value=10)
        delivered = st.number_input("Units delivered", min_value=0, step=1, value=7)
        submit = st.form_submit_button("Save aggregate record", disabled=connected and not st.session_state.get("editor_unlocked", False))
    if submit:
        if delivered > requested:
            st.error("Delivered cannot exceed requested. Correct the numbers and try again.")
        else:
            row = {"date": reporting_date.isoformat(), "ward": ward, "group": group,
                   "item": item, "requested": int(requested), "delivered": int(delivered)}
            if connected:
                if not st.session_state.get("editor_unlocked", False):
                    st.error("Unlock editing using the password in the sidebar first.")
                else:
                    try:
                        save_cloud_record(settings, row)
                        st.success("Record permanently saved to your private Google Sheet.")
                        st.rerun()
                    except Exception as error:
                        st.error("Save failed. Your record was NOT added. Check Google Sheets permissions and try again.")
                        st.caption(f"Error type: {type(error).__name__}")
            else:
                st.session_state["records"] = pd.concat(
                    [records, pd.DataFrame([row])], ignore_index=True
                )
                st.success("Record added to this session. Download the CSV from 'Data and export' to save it.")
    st.write("Current rows:", len(records) if connected else len(st.session_state["records"]))

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
    if connected:
        st.caption("Connected workspace: aggregate records are read directly from your private Google Sheet. Viewing is public; writing is protected by a basic editor password. This is NOT secure patient-data storage or production authentication.")
    else:
        st.caption("Practice workspace: records are stored only in this browser session until you download a CSV.")

else:
    st.header("About the prototype")
    st.markdown("""
    **Current capabilities:** record non-identifying area-level weekly totals, track fulfilment,
    view a dashboard, forecast weekly supply requests with a simple average, and download CSVs.

    **Optional cloud workspace:** persistent storage of aggregate totals in a private Google Sheet,
    with a basic password gate for writes. Public viewers can see aggregate totals; this is not
    production-grade access control or a secure medical record system.

    **Not implemented:** automated WhatsApp integration, user-level authentication, machine learning,
    clinical risk assessment, personal health records, or referrals.

    **Next development priorities:** validate data definitions with women and health workers;
    obtain appropriate approvals for a voluntary field test; test forecast accuracy against observed demand;
    use a secure database with access controls for any operational deployment; implement transparent, safe,
    aggregate-only reporting; and consider advanced forecasting only when enough quality data is available.

    **Licence:** MIT (see LICENSE in the source code). This demonstration is not associated with or endorsed by UNICEF.
    """)
