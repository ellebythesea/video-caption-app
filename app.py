import streamlit as st
import tempfile
import os
import hmac
import hashlib
import base64
from datetime import date
from config import GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY, APP_PASSWORD
from logger import log_message
from gsheet import setup_sheet_headers, add_to_sheet, process_sheet_rows, update_caption_row
from openai_utils import transcribe_video, process_caption


def _ffmpeg_thumb(video_path: str) -> str | None:
    """Try to generate a thumbnail via ffmpeg. Returns image path or None."""
    try:
        try:
            import imageio_ffmpeg  # type: ignore

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = "ffmpeg"

        # Create temp jpg
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as imgf:
            out_path = imgf.name

        # Seek a bit into the video to avoid black frames; grab 1 frame
        # Using thumbnail filter for a representative frame if possible
        cmd = (
            f'"{ffmpeg}" -y -ss 00:00:01 -i "{video_path}" '
            f'-frames:v 1 -vf "thumbnail,scale=640:-1" -q:v 4 "{out_path}"'
        )
        rc = os.system(cmd)
        if rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return out_path
        # Cleanup on failure
        try:
            os.unlink(out_path)
        except Exception:
            pass
        return None
    except Exception:
        return None

if not all([GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY]):
    st.error("Missing required environment variables! Set them in .env or Streamlit secrets.")
    st.stop()

def _today_token(secret: str) -> str:
    """Return a URL-safe token valid for today's date using HMAC-SHA256."""
    today = date.today().isoformat()
    digest = hmac.new(secret.encode("utf-8"), today.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _verify_token(token: str, secret: str) -> bool:
    try:
        expected = _today_token(secret)
        return hmac.compare_digest(token or "", expected)
    except Exception:
        return False


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

    # Check for a valid one-day token in URL query params
    try:
        params = getattr(st, "query_params", {}) or {}
        token = params.get("auth")
        if token and _verify_token(token, expected):
            st.session_state["authenticated"] = True
            return True
    except Exception:
        pass

    st.subheader("Enter Password")
    pwd = st.text_input("Password", type="password")
    if st.button("Unlock"):
        if expected and pwd == expected:
            st.session_state["authenticated"] = True
            st.success("Unlocked for this session.")
            # Also persist unlock for the rest of the day via a signed query token
            try:
                token = _today_token(expected)
                # New API (Streamlit >= 1.30)
                try:
                    st.query_params["auth"] = token
                except Exception:
                    st.experimental_set_query_params(auth=token)
            except Exception:
                pass
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

MAX_TRANSCRIBE_MB = 25.0

if uploaded_files:
    existing = {v["name"] for v in st.session_state["uploaded_videos"]}
    for uf in uploaded_files:
        if uf.name in existing:
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uf.name)[1]) as tmp_file:
            tmp_file.write(uf.getvalue())
            size_bytes = os.path.getsize(tmp_file.name)
            st.session_state["uploaded_videos"].append({
                "name": uf.name,
                "path": tmp_file.name,
                "thumb_path": None,
                "status": "queued",
                "size_mb": round(size_bytes / (1024 * 1024), 2),
            })

videos = st.session_state.get("uploaded_videos", [])

if videos:
    # Ensure thumbnails exist for display
    for v in videos:
        if not v.get("thumb_path"):
            # First try ffmpeg-based thumbnail for broader codec support
            thumb = _ffmpeg_thumb(v.get("path", ""))
            if thumb:
                v["thumb_path"] = thumb
            else:
                # Fallback to OpenCV if ffmpeg path is not available
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
                size = v.get("size_mb")
                if size is not None:
                    st.caption(f"Size: {size:.2f} MB")
                    if size > MAX_TRANSCRIBE_MB:
                        st.markdown("<span style='color:#cc0000'>Exceeds 25 MB limit; will be skipped.</span>", unsafe_allow_html=True)
                # Per-item metadata inputs
                speaker_key = f"speaker_{start}_{idx}_{v['name']}"
                footer_key = f"footer_{start}_{idx}_{v['name']}"
                speaker_val = st.text_input("Name", key=speaker_key, value=v.get("speaker", ""))
                footer_val = st.text_area("Footer", key=footer_key, value=v.get("footer", ""), height=80)
                v["speaker"] = speaker_val
                v["footer"] = footer_val

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
        skipped = 0
        for v in videos:
            with st.spinner(f"Transcribing {v['name']}..."):
                # Guard for size limit
                if v.get("size_mb", 0) > MAX_TRANSCRIBE_MB:
                    v["status"] = "too large"
                    skipped += 1
                    continue

                v["status"] = "transcribing"
                transcript = transcribe_video(v["path"]) or ""
                if transcript:
                    row_idx = add_to_sheet(v["name"], transcript, v.get("speaker", ""))
                    if not row_idx:
                        v["status"] = "sheet error"
                        st.error(f"Failed to add {v['name']} to sheet.")
                    else:
                        try:
                            combined_transcript = (v.get("speaker", "") + " " + transcript).strip() if v.get("speaker") else transcript
                            base_caption = process_caption(combined_transcript, "")
                            final_caption = base_caption + ("\n\n" + v.get("footer", "") if v.get("footer") else "")
                            if update_caption_row(int(row_idx), final_caption):
                                v["status"] = "captioned"
                            else:
                                v["status"] = "sheet error"
                        except Exception:
                            v["status"] = "caption error"
                            st.error(f"Failed to generate caption for {v['name']}")
                else:
                    v["status"] = "failed"
                    st.error(f"Transcription failed for {v['name']}")
                try:
                    os.unlink(v["path"])
                except Exception:
                    pass
            completed += 1
            progress.progress(int(completed / max(len(videos), 1) * 100))
        if skipped:
            st.warning(f"{skipped} file(s) skipped for exceeding the 25 MB limit.")
        st.success("All uploaded videos processed.")
        try:
            st.rerun()
        except Exception:
            try:
                st.experimental_rerun()
            except Exception:
                pass

# Removed the separate caption generation step; captions are generated immediately after upload/transcription.
