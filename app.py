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

# Force a 3-across grid on narrow screens and shrink image previews
st.markdown(
    """
    <style>
      /* Keep 3 columns even on mobile */
      @media (max-width: 900px) {
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
          width: 33.3333% !important;
          flex: 0 0 33.3333% !important;
          padding-left: 0.25rem;
          padding-right: 0.25rem;
        }
        /* Make images compact for grid previews */
        div[data-testid="column"] img {
          width: 100% !important;
          height: 160px !important;
          object-fit: cover;
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
            st.session_state["uploaded_videos"].append({
                "name": uf.name,
                "path": tmp_file.name,
                "thumb_path": None,
                "status": "queued",
            })

videos = st.session_state.get("uploaded_videos", [])

if videos:
    # Ensure thumbnails exist for display
    for v in videos:
        if not v.get("thumb_path"):
            try:
                import cv2  # type: ignore
                cap = cv2.VideoCapture(v["path"])
                if cap.isOpened():
                    frame_count = int(max(cap.get(cv2.CAP_PROP_FRAME_COUNT), 1))
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 2)
                    ok, frame = cap.read()
                    if not ok:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, frame = cap.read()
                    cap.release()
                    if ok:
                        ok2, buf = cv2.imencode('.jpg', frame)
                        if ok2:
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as imgf:
                                imgf.write(buf.tobytes())
                                v["thumb_path"] = imgf.name
            except Exception:
                pass

    st.caption("Queued files (3 across previews)")
    # Render a true 3-across grid by chunking into rows
    for start in range(0, len(videos), 3):
        row_items = videos[start:start+3]
        cols = st.columns(3)
        for idx, v in enumerate(row_items):
            with cols[idx]:
                if v.get("thumb_path") and os.path.exists(v["thumb_path"]):
                    st.image(v["thumb_path"], use_container_width=True)
                else:
                    st.write("[no preview]")
                st.text(v["name"][:60])
                st.caption(f"Status: {v.get('status', 'queued').capitalize()}")

    c1, c2 = st.columns([1,1])
    clear_clicked = c2.button("Clear queued list")
    process_clicked = c1.button("Transcribe and Add All")
    if clear_clicked:
        for v in videos:
            for p in (v.get("path"), v.get("thumb_path")):
                try:
                    if p and os.path.exists(p):
                        os.unlink(p)
                except Exception:
                    pass
        st.session_state["uploaded_videos"] = []
        try:
            st.rerun()
        except Exception:
            pass

    if process_clicked:
        progress = st.progress(0)
        completed = 0
        for v in videos:
            with st.spinner(f"Transcribing {v['name']}..."):
                v["status"] = "transcribing"
                transcript = transcribe_video(v["path"]) or ""
                if transcript:
                    ok = add_to_sheet(v["name"], transcript)
                    if not ok:
                        v["status"] = "sheet error"
                        st.error(f"Failed to add {v['name']} to sheet.")
                    else:
                        v["status"] = "transcribed"
                else:
                    v["status"] = "failed"
                    st.error(f"Transcription failed for {v['name']}")
                try:
                    os.unlink(v["path"])
                except Exception:
                    pass
            completed += 1
            progress.progress(int(completed / max(len(videos), 1) * 100))
        st.success("All uploaded videos processed.")
        try:
            st.rerun()
        except Exception:
            try:
                st.experimental_rerun()
            except Exception:
                pass

if st.button("Generate Captions for Pending Rows"):
    with st.spinner("Processing sheet..."):
        process_sheet_rows(process_caption)
    st.success("Processed all pending rows in the sheet!")
