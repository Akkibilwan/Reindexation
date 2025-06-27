import streamlit as st
import gspread
import pandas as pd
import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Page Configuration ---
st.set_page_config(page_title="YouTube Video Performance Dashboard", page_icon="🚀", layout="wide")

# --- Google API Configuration ---
SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# --- Secrets Management ---
try:
    CLIENT_CONFIG = { "web": { "client_id": st.secrets["GOOGLE_CLIENT_ID"], "project_id": st.secrets.get("GOOGLE_PROJECT_ID", ""), "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"], "redirect_uris": [st.secrets["REDIRECT_URI"]] } }
    TARGET_CHANNEL_ID = st.secrets["YOUTUBE_CHANNEL_ID"].strip()
    GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"].strip()
except KeyError as e:
    st.error(f"🔴 Critical Error: Missing secret key - {e}.")
    st.stop()
    
# --- Authentication State ---
if 'credentials' not in st.session_state: st.session_state.credentials = None

# --- Helper Functions ---
def get_credentials_from_session():
    if st.session_state.credentials: return Credentials.from_authorized_user_info(st.session_state.credentials)
    return None

def save_credentials_to_session(credentials):
    st.session_state.credentials = { 'token': credentials.token, 'refresh_token': credentials.refresh_token, 'token_uri': credentials.token_uri, 'client_id': credentials.client_id, 'client_secret': credentials.client_secret, 'scopes': credentials.scopes }

def get_video_details(credentials, video_ids):
    """Gets video titles and thumbnails for a list of video IDs."""
    try:
        youtube_service = build('youtube', 'v3', credentials=credentials)
        # YouTube API allows fetching details for up to 50 videos at a time
        video_details = []
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i+50]
            request = youtube_service.videos().list(part="snippet", id=",".join(chunk))
            response = request.execute()
            for item in response.get("items", []):
                video_details.append({
                    'video': item['id'], # Use 'video' as the key to merge later
                    'title': item['snippet']['title'],
                    'thumbnail': item['snippet']['thumbnails']['default']['url']
                })
        return pd.DataFrame(video_details)
    except HttpError as e:
        st.error(f"Could not fetch video details: {e}")
        return pd.DataFrame()

def fetch_video_analytics(credentials, channel_id, start_date, end_date):
    """Fetches analytics dimensioned by video."""
    try:
        youtube_service = build('youtubeAnalytics', 'v2', credentials=credentials)
        request = youtube_service.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date.strftime("%Y-%m-%d"),
            endDate=end_date.strftime("%Y-%m-%d"),
            metrics="views,comments,likes,dislikes,shares,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
            dimensions="video", # Changed dimension from 'day' to 'video'
            sort="-views" # Sort by most views
        )
        response = request.execute()
        if 'rows' not in response: return pd.DataFrame()

        column_headers = [header['name'] for header in response['columnHeaders']]
        metrics_df = pd.DataFrame(response['rows'], columns=column_headers)
        
        # Get video details (titles, thumbnails) for the video IDs
        video_ids = metrics_df['video'].tolist()
        if not video_ids: return metrics_df # Return early if no videos found
        
        details_df = get_video_details(credentials, video_ids)
        
        # Merge metrics with video details
        if not details_df.empty:
            final_df = pd.merge(details_df, metrics_df, on='video', how='inner')
            return final_df
        else:
            return metrics_df

    except HttpError as e:
        st.error(f"An error occurred while fetching YouTube analytics: {e}")
        return None

def write_to_sheet(credentials, sheet_id, dataframe):
    # This function remains the same
    try:
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_key(sheet_id).sheet1
        sheet.clear()
        sheet.update([dataframe.columns.values.tolist()] + dataframe.values.tolist(), 'A1')
        return True
    except Exception as e:
        st.error(f"An error occurred while writing to Google Sheets: {e}")
        return False

# --- Main Application UI ---
st.title("🚀 YouTube Video Performance Dashboard")
creds = get_credentials_from_session()

if creds is None:
    # --- Authentication Flow ---
    st.header("Step 1: Authenticate with Google")
    flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES, redirect_uri=st.secrets["REDIRECT_URI"])
    auth_url, _ = flow.authorization_url(prompt='consent')
    st.link_button("Authorize with Google", auth_url)
    auth_code = st.query_params.get("code")
    if auth_code:
        try:
            flow.fetch_token(code=auth_code)
            save_credentials_to_session(flow.credentials)
            st.rerun()
        except Exception as e: st.error(f"Authentication failed: {e}")
else:
    # --- Main App Interface ---
    st.success("✅ You are authenticated!")
    st.header("Fetch Video Performance Analytics")
    
    end_date = datetime.date.today()
    start_date = st.date_input("Select start date", end_date - datetime.timedelta(days=30))
    st.date_input("End date (fixed to today)", end_date, disabled=True)

    if st.button("Fetch Video Data", type="primary"):
        with st.spinner("Fetching performance data for all videos... This may take a moment."):
            df = fetch_video_analytics(creds, TARGET_CHANNEL_ID, start_date, end_date)
        
        if df is not None and not df.empty:
            st.balloons()
            st.write(f"### Analytics for {len(df)} Videos")
            # Reorder columns for better presentation
            cols_to_show = ['thumbnail', 'title', 'views', 'likes', 'comments', 'subscribersGained', 'estimatedMinutesWatched', 'averageViewDuration']
            display_cols = [col for col in cols_to_show if col in df.columns]
            st.dataframe(df[display_cols])
            
            with st.spinner("Writing data to Google Sheet..."):
                if write_to_sheet(creds, GOOGLE_SHEET_ID, df):
                    st.success("Google Sheet updated successfully!")
                    st.markdown(f"**[View your Google Sheet](https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID})**")
        elif df is not None: st.warning("No video data found for the selected date range.")
        else: st.error("Failed to fetch data.")
