import streamlit as st
import tempfile
import os
from config import GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY
from logger import log_message
from gsheet import setup_sheet_headers, add_to_sheet, process_sheet_rows
from openai_utils import transcribe_video, process_caption

if not all([GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY]):
    st.error("Missing required environment variables! Set them in .env or Streamlit secrets.")
    st.stop()

setup_sheet_headers()

st.title("Video Caption Generator")

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
