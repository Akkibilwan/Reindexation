import streamlit as st
import os
import gspread
import pandas as pd
import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# --- Page Configuration ---
st.set_page_config(
    page_title="YouTube Analytics Dashboard",
    page_icon="📊",
    layout="wide"
)

# --- Google API Configuration ---
# These scopes need to be authorized by the user
SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/spreadsheets"
]

# --- Secrets Management ---
# Load secrets from Streamlit's secrets management
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
    YOUTUBE_CHANNEL_ID = st.secrets["YOUTUBE_CHANNEL_ID"]
    GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
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
    creds_dict = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    st.session_state.credentials = creds_dict

# PASTE THIS ENTIRE FUNCTION, REPLACING THE OLD ONE

def fetch_youtube_data(credentials, channel_id, start_date, end_date):
    """Fetches data from the YouTube Analytics API and returns a DataFrame."""
    try:
        youtube_service = build('youtubeAnalytics', 'v2', credentials=credentials)
        
        # --- THIS LINE IS THE FIX ---
        # We have removed 'impressions' and 'ctr' as they are not compatible 
        # in the same query with the other metrics.
        request = youtube_service.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date.strftime("%Y-%m-%d"),
            endDate=end_date.strftime("%Y-%m-%d"),
            metrics="views,comments,likes,shares,estimatedMinutesWatched,averageViewDuration",
            dimensions="day",
            sort="day"
        )
        # ---------------------------

        response = request.execute()
        
        if 'rows' in response:
            column_headers = [header['name'] for header in response['columnHeaders']]
            df = pd.DataFrame(response['rows'], columns=column_headers)
            return df
        else:
            return pd.DataFrame() # Return empty dataframe if no data
    except Exception as e:
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

# --- Main Application Logic ---
st.title("📊 YouTube Analytics Dashboard")
st.write("This app fetches your YouTube channel data and updates a Google Sheet.")

creds = get_credentials_from_session()

if creds is None:
    # --- Authentication Flow ---
    st.subheader("Step 1: Authenticate with Google")
    
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=st.secrets["REDIRECT_URI"]
    )
    
    auth_url, _ = flow.authorization_url(prompt='consent')
    
    st.link_button("Authorize with Google", auth_url, help="Click to grant access to your YouTube and Google Sheets data.")

    # Check for the authorization code in the URL query parameters
    auth_code = st.query_params.get("code")
    if auth_code:
        try:
            flow.fetch_token(code=auth_code)
            save_credentials_to_session(flow.credentials)
            st.success("Authentication successful! The page will now reload.")
            # Clear query params and rerun to reflect authenticated state
            st.rerun() 
        except Exception as e:
            st.error(f"Authentication failed: {e}")

else:
    # --- Main App Interface (Authenticated) ---
    st.success("✅ You are authenticated!")
    st.sidebar.info(f"Channel ID: {YOUTUBE_CHANNEL_ID}")
    st.sidebar.info(f"Sheet ID: {GOOGLE_SHEET_ID}")
    
    st.subheader("Step 2: Fetch Data and Update Sheet")
    
    # Date range selector
    end_date = datetime.date.today() - datetime.timedelta(days=1)
    start_date = st.date_input("Select start date", end_date - datetime.timedelta(days=7))
    st.date_input("End date (fixed to yesterday)", end_date, disabled=True)

    if st.button("Fetch & Update Now", type="primary"):
        with st.spinner("Fetching data from YouTube..."):
            df = fetch_youtube_data(creds, YOUTUBE_CHANNEL_ID, start_date, end_date)
        
        if df is not None and not df.empty:
            st.success("Data fetched successfully!")
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
