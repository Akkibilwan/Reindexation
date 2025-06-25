import streamlit as st
import pandas as pd
import datetime, json, requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread

# --- Page Config ---
st.set_page_config(page_title="YouTube Analytics Monitor", layout="wide")

# --- Load & Validate Secrets ---
secrets = getattr(st, "secrets", {})
required = [
    "CHANNEL_ID",
    "SPREADSHEET_ID",
    "SLACK_WEBHOOK_URL",
    "DEVIATION_THRESHOLD",
    "YT_API_KEY",
    "SHEETS_CREDS_JSON",
]
missing = [k for k in required if not secrets.get(k)]
if missing:
    st.error(f"Missing secrets: {', '.join(missing)}.\nPlease add them to secrets.toml and redeploy.")
    st.stop()

# --- Config ---
CHANNEL_ID = secrets["CHANNEL_ID"]
SPREADSHEET_ID = secrets["SPREADSHEET_ID"]
SLACK_WEBHOOK_URL = secrets["SLACK_WEBHOOK_URL"]
DEVIATION_THRESHOLD = float(secrets["DEVIATION_THRESHOLD"])
YT_API_KEY = secrets["YT_API_KEY"]
SHEETS_CREDS_JSON = secrets["SHEETS_CREDS_JSON"]

# --- Initialize API Clients ---
@st.cache_resource
def init_clients():
    # YouTube Analytics via API key
    yt_service = build(
        "youtubeAnalytics", "v2", developerKey=YT_API_KEY
    )
    # Google Sheets via service account JSON
    info = json.loads(SHEETS_CREDS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sheets_client = gspread.authorize(creds)
    return yt_service, sheets_client

yt_service, sheets_client = init_clients()

# --- Data Fetching ---
def fetch_channel_metrics():
    """Fetch last-hour metrics: views, impressions, CTR, VPH, engagement rate."""
    now = datetime.datetime.utcnow()
    start = now - datetime.timedelta(hours=1)
    resp = yt_service.reports().query(
        ids=f"channel=={CHANNEL_ID}",
        startDate=start.date().isoformat(),
        endDate=now.date().isoformat(),
        metrics="views,estimatedMinutesWatched,averageViewDuration,impressions,impressionClickThroughRate",
        dimensions="day,hour",
        sort="day,hour"
    ).execute()
    rows = resp.get("rows", [])
    data = []
    for day, hour, views, minutes, avg_dur, impressions, ctr in rows:
        ts = datetime.datetime.strptime(f"{day} {hour}", "%Y-%m-%d %H")
        vph = views
        er = (minutes / (views * avg_dur)) if views and avg_dur else 0
        data.append({
            "timestamp": ts,
            "views": int(views),
            "impressions": int(impressions),
            "ctr": float(ctr),
            "vph": float(vph),
            "engagement_rate": float(er),
        })
    return pd.DataFrame(data)

# --- Google Sheets Storage ---
def append_to_sheet(df, worksheet_name="Channel Metrics"):
    sheet = sheets_client.open_by_key(SPREADSHEET_ID)
    try:
        ws = sheet.worksheet(worksheet_name)
    except Exception:
        ws = sheet.add_worksheet(title=worksheet_name, rows="1000", cols="20")
    for rec in df.to_records(index=False):
        ws.append_row(list(rec))

# --- Deviation Check ---
def check_deviation(df, metric):
    if len(df) < 8:
        return None
    last = df[metric].iloc[-1]
    avg7 = df[metric].iloc[-8:-1].mean()
    if avg7 == 0:
        return None
    dev = abs(last - avg7) / avg7
    if dev > DEVIATION_THRESHOLD:
        return f"*{metric}* deviated by {dev:.2%} (latest={last:.2f}, avg7={avg7:.2f})"
    return None

# --- Slack Notification ---
def send_slack(alerts):
    for msg in alerts:
        requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": f"⚠️ YouTube Analytics Alert:\n{msg}"},
        )

# --- Streamlit UI ---
st.title("📈 YouTube Analytics Monitor")
if st.button("Run Now"):
    df = fetch_channel_metrics()
    if df.empty:
        st.warning("No data returned for the past hour.")
    else:
        st.dataframe(df.tail(5))
        append_to_sheet(df)
        alerts = [
            check_deviation(df, m)
            for m in ["views", "impressions", "ctr", "vph", "engagement_rate"]
        ]
        alerts = [a for a in alerts if a]
        if alerts:
            send_slack(alerts)
            st.warning(f"Sent {len(alerts)} alert(s) to Slack.")
        else:
            st.success("All metrics within threshold.")

st.markdown("---")
st.write(
    "This app fetches hourly YouTube metrics via API key, stores them in Google Sheets, "
    "and alerts Slack on deviations."
)
