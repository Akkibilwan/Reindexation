import streamlit as st
import pandas as pd
import datetime
import requests

from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread

# --- Streamlit Page Config ---
st.set_page_config(page_title="YouTube Analytics Monitor", layout="wide")

# --- Sidebar Configuration ---
st.sidebar.header("⚙️ Configuration")
CHANNEL_ID = st.sidebar.text_input("YouTube Channel ID", help="Your channel's ID, e.g. UC_x5XG1OV2P6uZZ5FSM9Ttw")
SPREADSHEET_ID = st.sidebar.text_input("Google Sheet ID", help="The ID from your sheet URL")
SLACK_WEBHOOK_URL = st.sidebar.text_input("Slack Webhook URL", type="password")
threshold_pct = st.sidebar.slider("Deviation threshold (%)", min_value=0.1, max_value=10.0, value=1.0)
DEVIATION_THRESHOLD = threshold_pct / 100
YT_CREDS_FILE = st.sidebar.text_input("Path to YouTube SA JSON", "yt_service_account.json")
SHEETS_CREDS_FILE = st.sidebar.text_input("Path to Sheets SA JSON", "sheets_service_account.json")

# --- Cached Clients ---
@st.experimental_singleton
def get_yt_service():
    creds = service_account.Credentials.from_service_account_file(
        YT_CREDS_FILE,
        scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"]
    )
    return build("youtubeAnalytics", "v2", credentials=creds)

@st.experimental_singleton
def get_sheets_client():
    creds = service_account.Credentials.from_service_account_file(
        SHEETS_CREDS_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

# --- Data Fetching ---
def fetch_channel_metrics():
    """
    Pulls last-hour metrics for the entire channel.
    Returns a DataFrame with timestamp, views, impressions, ctr, vph, engagement_rate.
    """
    yt = get_yt_service()
    now = datetime.datetime.utcnow()
    start = now - datetime.timedelta(hours=1)
    response = yt.reports().query(
        ids=f"channel=={CHANNEL_ID}",
        startDate=start.date().isoformat(),
        endDate=now.date().isoformat(),
        metrics="views,estimatedMinutesWatched,averageViewDuration,impressions,impressionClickThroughRate",
        dimensions="day,hour",
        sort="day,hour"
    ).execute()
    rows = response.get("rows", [])
    records = []
    for day, hour, views, minutes_watched, avg_dur, impressions, ctr in rows:
        ts = datetime.datetime.strptime(f"{day} {hour}", "%Y-%m-%d %H")
        vph = views  # since it's per-hour block
        engagement_rate = (minutes_watched / (views * avg_dur)) if views else 0
        records.append({
            "timestamp": ts.isoformat(),
            "views": int(views),
            "impressions": int(impressions),
            "ctr": float(ctr),
            "vph": float(vph),
            "engagement_rate": float(engagement_rate)
        })
    return pd.DataFrame(records)

# --- Google Sheets Storage ---
def append_to_sheet(df: pd.DataFrame, worksheet_name: str):
    """
    Appends all rows from df to the given worksheet in the configured spreadsheet.
    Creates the worksheet if it doesn't exist.
    """
    client = get_sheets_client()
    sheet = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = sheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=worksheet_name, rows="1000", cols="20")
    for _, row in df.iterrows():
        ws.append_row([
            row["timestamp"], row["views"], row["impressions"],
            row["ctr"], row["vph"], row["engagement_rate"]
        ])

# --- Alert Logic ---
def check_deviation(df: pd.DataFrame, metric: str):
    """
    Returns a Slack-alertable message if the latest metric deviates > threshold from last 7 entries.
    """
    if df.shape[0] < 8:
        return None
    last = df[metric].iloc[-1]
    avg7 = df[metric].iloc[-8:-1].mean()
    if avg7 == 0:
        return None
    deviation = abs(last - avg7) / avg7
    if deviation > DEVIATION_THRESHOLD:
        return f"*{metric}* deviated by {deviation:.2%} (latest={last:.2f}, avg7={avg7:.2f})"
    return None

# --- Slack Notification ---
def send_slack(messages: list[str]):
    """
    Posts each message in `messages` to the configured Slack webhook.
    """
    for msg in messages:
        payload = {"text": f"⚠️ YouTube Analytics Alert:\n{msg}"}
        requests.post(SLACK_WEBHOOK_URL, json=payload)

# --- Main Monitor Routine ---
def run_monitor():
    st.info("Fetching channel metrics...")
    df = fetch_channel_metrics()
    st.write(df.tail(3))
    append_to_sheet(df, "Channel Metrics")
    alerts = []
    for m in ["views", "impressions", "ctr", "vph", "engagement_rate"]:
        msg = check_deviation(df, m)
        if msg:
            alerts.append(msg)
    if alerts:
        send_slack(alerts)
        st.warning(f"Sent {len(alerts)} alert(s) to Slack.")
    else:
        st.success("All metrics within threshold.")

# --- Streamlit UI ---
st.title("📈 YouTube Analytics Monitor")
if st.button("▶️ Run Now"):
    if not (CHANNEL_ID and SPREADSHEET_ID and SLACK_WEBHOOK_URL):
        st.error("Please fill in all configuration fields.")
    else:
        run_monitor()

st.markdown("---")
st.write("Configure inputs in the sidebar, then click **Run Now** to fetch metrics, store them, and fire alerts if any metric deviates by more than your threshold.")
