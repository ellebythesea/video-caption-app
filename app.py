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
            # Streamlit >= 1.30 uses st.rerun(); older versions used experimental_rerun
            try:
                st.rerun()
            except Exception:
                try:
                    st.experimental_rerun()
                except Exception:
                    pass
        else:
            st.error("Incorrect password.")
    return False

st.set_page_config(layout="wide")
st.title("Video Caption Generator")

# Force a 4-across grid on narrow screens and shrink previews
st.markdown(
    """
    <style>
      /* Keep 4 columns even on mobile */
      @media (max-width: 900px) {
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
          width: 25% !important;
          flex: 0 0 25% !important;
          padding-left: 0.25rem;
          padding-right: 0.25rem;
        }
        /* Make embedded video players small for grid previews */
        div[data-testid="column"] iframe,
        div[data-testid="column"] video {
          width: 100% !important;
          height: 180px !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# Require password before showing the uploader/actions
if not _check_password():
    st.stop()

# Initialize sheet after auth so we don't touch APIs while locked
setup_sheet_headers()

uploaded_files = st.file_uploader(
    "Upload one or more videos from your phone",
    type=["mp4", "mov", "avi"],
    accept_multiple_files=True,
)

# Keep temporary files across reruns for a single session
if "uploaded_videos" not in st.session_state:
    st.session_state["uploaded_videos"] = []  # list of {name, path}

if uploaded_files:
    existing = {v["name"] for v in st.session_state["uploaded_videos"]}
    for uf in uploaded_files:
        if uf.name in existing:
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uf.name)[1]) as tmp_file:
            tmp_file.write(uf.getvalue())
            st.session_state["uploaded_videos"].append({"name": uf.name, "path": tmp_file.name})

videos = st.session_state.get("uploaded_videos", [])

if videos:
    st.caption("Preview (4 across)")
    cols = st.columns(4)
    for i, v in enumerate(videos):
        col = cols[i % 4]
        with col:
            st.video(v["path"])
            st.text(v["name"][:40])

    if st.button("Transcribe and Add All"):
        progress = st.progress(0)
        completed = 0
        for v in videos:
            with st.spinner(f"Transcribing {v['name']}..."):
                transcript = transcribe_video(v["path"]) or ""
                if transcript:
                    ok = add_to_sheet(v["name"], transcript)
                    if not ok:
                        st.error(f"Failed to add {v['name']} to sheet.")
                else:
                    st.error(f"Transcription failed for {v['name']}")
                # Clean up temp file for this video
                try:
                    os.unlink(v["path"])
                except Exception:
                    pass
            completed += 1
            progress.progress(int(completed / max(len(videos), 1) * 100))
        st.session_state["uploaded_videos"] = []
        st.success("All uploaded videos processed.")

if st.button("Generate Captions for Pending Rows"):
    with st.spinner("Processing sheet..."):
        process_sheet_rows(process_caption)
    st.success("Processed all pending rows in the sheet!")
