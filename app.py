# PASTE THIS ENTIRE FUNCTION, REPLACING THE OLD ONE

def fetch_youtube_data(credentials, channel_id, start_date, end_date):
    """Fetches a comprehensive set of data from the YouTube Analytics API."""
    try:
        youtube_service = build('youtubeAnalytics', 'v2', credentials=credentials)
        
        # --- NEW EXPANDED METRICS LIST ---
        # This list includes a rich set of compatible metrics.
        request = youtube_service.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date.strftime("%Y-%m-%d"),
            endDate=end_date.strftime("%Y-%m-%d"),
            metrics="views,redViews,comments,likes,dislikes,shares,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
            dimensions="day",
            sort="day"
        )
        # -----------------------------------

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
