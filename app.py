import streamlit as st
import gspread
import pandas as pd
import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Page Configuration ---
st.set_page_config(page_title="YouTube Analytics Dashboard", page_icon="📊", layout="wide")

# --- Google API Configuration ---
# These are the permissions our app will ask for.
SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/youtube.readonly" # Added for channel verification
]

# --- Secrets Management ---
# Loads credentials from Streamlit's secrets management
try:
    CLIENT_CONFIG = {
        "web": {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "project_id": st.secrets.get("GOOGLE_PROJECT_ID", ""), # Optional
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "redirect_uris": [st.secrets["REDIRECT_URI"]]
        }
    }
    # We add .strip() to remove any accidental invisible spaces from the secrets
    TARGET_CHANNEL_ID = st.secrets["YOUTUBE_CHANNEL_ID"].strip()
    GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"].strip()
except KeyError as e:
    st.error(f"🔴 Critical Error: Missing secret key - {e}. Please configure your secrets in the Streamlit app settings.")
    st.stop()
    
# --- Authentication State ---
if 'credentials' not in st.session_state:
    st.session_state.credentials = None

# --- Helper Functions ---
def get_credentials_from_session():
    """Retrieves credentials from Streamlit's session state."""
    if st.session_state.credentials:
        return Credentials.from_authorized_user_info(st.session_state.credentials)
    return None

def save_credentials_to_session(credentials):
    """Saves credentials to Streamlit's session state."""
    st.session_state.credentials = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

def get_accessible_channels(credentials):
    """Uses the YouTube Data API v3 to list channels accessible by the user."""
    try:
        youtube_service = build('youtube', 'v3', credentials=credentials)
        request = youtube_service.channels().list(
            part="snippet",
            mine=True
        )
        response = request.execute()
        return response.get("items", [])
    except HttpError as e:
        st.error(f"An error occurred while checking accessible channels: {e}")
        return None

def fetch_youtube_data(credentials, channel_id, start_date, end_date):
    """Fetches a comprehensive set of data from the YouTube Analytics API."""
    try:
        youtube_service = build('youtubeAnalytics', 'v2', credentials=credentials)
        
        # This is the new, expanded list of metrics to make it more like YT Studio
        request = youtube_service.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date.strftime("%Y-%m-%d"),
            endDate=end_date.strftime("%Y-%m-%d"),
            metrics="views,redViews,comments,likes,dislikes,shares,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
            dimensions="day",
            sort="day"
        )

        response = request.execute()
        
        if 'rows' in response:
            column_headers = [header['name'] for header in response['columnHeaders']]
            df = pd.DataFrame(response['rows'], columns=column_headers)
            return df
        else:
            return pd.DataFrame()
    except HttpError as e:
        if e.resp.status == 403:
            st.error(f"🛑 HTTP 403 Forbidden Error: The authenticated user does not have permission for the requested channel ({channel_id}). This is an issue with the channel's permissions on YouTube's side.")
        else:
            st.error(f"An error occurred while fetching YouTube data: {e}")
        return None

def write_to_sheet(credentials, sheet_id, dataframe):
    """Writes a Pandas DataFrame to the specified Google Sheet."""
    try:
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_key(sheet_id).sheet1
        
        existing_headers = sheet.get_all_values()
        if not existing_headers:
            sheet.update([dataframe.columns.values.tolist()], 'A1')
            
        sheet.append_rows(dataframe.values.tolist(), value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        st.error(f"An error occurred while writing to Google Sheets: {e}")
        return False

# --- Main Application UI ---
st.title("📊 YouTube Analytics Dashboard")
creds = get_credentials_from_session()

if creds is None:
    # --- Authentication Flow ---
    st.header("Step 1: Authenticate with Google")
    st.write("Click the button below to grant access to your YouTube Analytics and Google Sheets data.")
    
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=st.secrets["REDIRECT_URI"]
    )
    auth_url, _ = flow.authorization_url(prompt='consent')
    
    st.link_button("Authorize with Google", auth_url, help="You will be redirected to a Google login page.")

    # Check for the authorization code in the URL query parameters
    auth_code = st.query_params.get("code")
    if auth_code:
        try:
            flow.fetch_token(code=auth_code)
            save_credentials_to_session(flow.credentials)
            st.success("Authentication successful! Reloading...")
            st.rerun() 
        except Exception as e:
            st.error(f"Authentication failed: {e}")
else:
    # --- Main App Interface (Authenticated) ---
    st.success("✅ Step 1 Complete: You are authenticated!")
    st.header("Step 2: Verify Channel Access & Fetch Data")

    with st.spinner("Checking which channels your account can access..."):
        accessible_channels = get_accessible_channels(creds)
    
    if accessible_channels is not None:
        accessible_ids = [ch['id'] for ch in accessible_channels]
        if TARGET_CHANNEL_ID in accessible_ids:
            st.success(f"✅ Permission Confirmed! You can now fetch data for the channel: {TARGET_CHANNEL_ID}")
            
            end_date = datetime.date.today() - datetime.timedelta(days=1)
            start_date = st.date_input("Select start date", end_date - datetime.timedelta(days=7))

            if st.button("Fetch & Update Now", type="primary"):
                with st.spinner("Fetching data from YouTube..."):
                    df = fetch_youtube_data(creds, TARGET_CHANNEL_ID, start_date, end_date)
                
                if df is not None and not df.empty:
                    st.balloons()
                    st.write("### Fetched Data")
                    st.dataframe(df)
                    
                    with st.spinner("Writing data to Google Sheet..."):
                        success = write_to_sheet(creds, GOOGLE_SHEET_ID, df)
                    
                    if success:
                        st.success("Google Sheet updated successfully!")
                        sheet_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}"
                        st.markdown(f"**[View your Google Sheet]({sheet_url})**")
                elif df is not None and df.empty:
                    st.warning("No data found for the selected date range.")
                else:
                    st.error("Failed to fetch data.")
        else:
            st.error(f"❌ PERMISSION MISMATCH: The Target Channel ID from your secrets (`{TARGET_CHANNEL_ID}`) was NOT found in the list of channels your personal account can manage.")
            st.write("Your personal account has API access to the following channels:")
            channel_data = {
                "Channel Name": [ch['snippet']['title'] for ch in accessible_channels],
                "Channel ID": [ch['id'] for ch in accessible_channels]
            }
            st.dataframe(pd.DataFrame(channel_data))
            st.warning("To fix this, either grant 'Manager' access to the target channel or update the `YOUTUBE_CHANNEL_ID` in your secrets to match one of the channels listed above.")
