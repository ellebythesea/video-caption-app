import streamlit as st
import tempfile
import os
from config import GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY, APP_PASSWORD
from logger import log_message
from gsheet import setup_sheet_headers, add_to_sheet, process_sheet_rows
from openai_utils import transcribe_video, process_caption

if not all([GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY]):
    st.error("Missing required environment variables! Set them in .env or Streamlit secrets.")
    st.stop()

def _check_password():
    """Gate the app behind a one-per-session password.

    Returns True if authenticated, else renders a password prompt and returns False.
    """
    if st.session_state.get("authenticated", False):
        return True

    # Prefer .env, fall back to Streamlit secrets
    try:
        expected = APP_PASSWORD or st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected = APP_PASSWORD or ""
    if not expected:
        st.warning("Admin has not configured APP_PASSWORD. Uploads are disabled.")
        return False
    st.subheader("Enter Password")
    pwd = st.text_input("Password", type="password")
    if st.button("Unlock"):
        if expected and pwd == expected:
            st.session_state["authenticated"] = True
            st.success("Unlocked for this session.")
            st.experimental_rerun()
        else:
            st.error("Incorrect password.")
    return False

setup_sheet_headers()

st.title("Video Caption Generator")

# Require password before showing the uploader/actions
if not _check_password():
    st.stop()

uploaded_file = st.file_uploader("Upload a video from your phone", type=["mp4", "mov", "avi"])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        video_path = tmp_file.name

    st.video(video_path)

    if st.button("Transcribe and Add to Sheet"):
        with st.spinner("Transcribing video..."):
            transcript = transcribe_video(video_path)
            if transcript:
                if add_to_sheet(uploaded_file.name, transcript):
                    st.success(f"Added {uploaded_file.name} to Google Sheet!")
                else:
                    st.error("Failed to add to sheet.")
            else:
                st.error("Transcription failed.")
        os.unlink(video_path)

if st.button("Generate Captions for Pending Rows"):
    with st.spinner("Processing sheet..."):
        process_sheet_rows(process_caption)
    st.success("Processed all pending rows in the sheet!")
