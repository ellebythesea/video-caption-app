import os
import base64
import tempfile
from datetime import datetime

import gspread
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials

from config import GOOGLE_SHEET_ID
from logger import log_message

# Google Sheets configuration
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
WORKSHEET_NAME = "IGCaptionLog"
HEADERS = [
    "Timestamp",
    "Filename",
    "Transcript",
    "Footer",
    "Caption",
    "Error",
]


def _load_credentials():
    """Load Google service account credentials.

    Prefers a local credentials.json file. Falls back to Streamlit secrets
    (GOOGLE_CREDENTIALS_BASE64) if present during deployment.
    """
    cred_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    if os.path.exists(cred_path):
        return ServiceAccountCredentials.from_json_keyfile_name(cred_path, SCOPE)

    # Try Streamlit secrets
    google_credentials_base64 = None
    try:
        # st.secrets may not be available outside Streamlit, so guard access
        google_credentials_base64 = st.secrets.get("GOOGLE_CREDENTIALS_BASE64")
    except Exception:
        google_credentials_base64 = os.getenv("GOOGLE_CREDENTIALS_BASE64")

    if google_credentials_base64:
        cred_content = base64.b64decode(google_credentials_base64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            tmp_file.write(cred_content)
            temp_path = tmp_file.name
        try:
            return ServiceAccountCredentials.from_json_keyfile_name(temp_path, SCOPE)
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    raise FileNotFoundError(
        "No credentials.json found and no GOOGLE_CREDENTIALS_BASE64 secret set."
    )


def _get_client():
    creds = _load_credentials()
    return gspread.authorize(creds)


def _get_worksheet():
    """Return the target worksheet, creating it if needed."""
    client = _get_client()
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = sheet.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS))
    return ws


def setup_sheet_headers():
    """Ensure the worksheet exists and has the expected headers in row 1."""
    try:
        ws = _get_worksheet()
        existing = ws.row_values(1)
        if existing != HEADERS:
            # Ensure headers are written starting at column A
            ws.resize(rows=1000, cols=len(HEADERS))
            ws.update("A1", [HEADERS])
        return True
    except Exception as e:
        log_message(f"Error setting up sheet headers: {e}")
        return False


def add_to_sheet(filename, transcript, speaker: str = "", footer: str = ""):
    """Append a new row starting at column A.

    Stores Transcript as "[speaker] [transcript]" when a speaker is provided,
    and saves `footer` in its own column for later concatenation with Caption.
    """
    try:
        ws = _get_worksheet()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        transcript_text = transcript or ""
        if speaker:
            transcript_text = f"{speaker} {transcript_text}".strip()
        row = [timestamp, filename, transcript_text, footer or "", "", ""]
        # Force appends to start from column A of the table
        ws.append_row(row, value_input_option="RAW", table_range="A1")
        # Return the 1-based row index of the appended row
        last_row = len(ws.get_all_values())
        return last_row
    except Exception as e:
        log_message(f"Error adding to sheet: {e}")
        return None


def update_caption_row(row_index: int, caption_text: str):
    """Write caption_text into the Caption column for the given 1-based row."""
    try:
        ws = _get_worksheet()
        # Ensure headers mapping; Caption is the 5th column in HEADERS (1-based index 5)
        # But in case of header drift, calculate dynamically
        header = ws.row_values(1)
        try:
            col_idx = header.index("Caption") + 1
        except ValueError:
            # Repair headers and try again
            setup_sheet_headers()
            header = ws.row_values(1)
            col_idx = header.index("Caption") + 1
        ws.update_cell(row_index, col_idx, caption_text)
        return True
    except Exception as e:
        log_message(f"Error updating caption for row {row_index}: {e}")
        return False


def process_sheet_rows(process_caption_fn):
    """Process rows with Status 'pending' by generating captions.

    Expects a function `process_caption_fn(transcript, prompt)` that returns the
    generated caption (string). On success, sets Status to 'done' and writes the
    caption. On failure, sets Status to 'error' and writes the error message.
    """
    ws = _get_worksheet()
    # Read all values at once
    values = ws.get_all_values()
    if not values:
        return

    # Map header indexes
    header = values[0]
    index = {name: i for i, name in enumerate(header)}
    required = ["Transcript", "Footer", "Caption", "Error"]
    if not all(col in index for col in required):
        # Attempt to repair headers
        setup_sheet_headers()
        values = ws.get_all_values()
        header = values[0] if values else HEADERS
        index = {name: i for i, name in enumerate(header)}

    # Iterate rows (1-based in Sheets; skip header which is row 1)
    for r, row in enumerate(values[1:], start=2):
        try:
            transcript = row[index.get("Transcript", 0)] if len(row) > index.get("Transcript", 0) else ""
            footer = row[index.get("Footer", 0)] if len(row) > index.get("Footer", 0) else ""
            caption_existing = row[index.get("Caption", 0)] if len(row) > index.get("Caption", 0) else ""

            if not transcript:
                continue
            # Pending if caption is blank
            if caption_existing:
                continue

            # Generate caption and append footer in the same cell
            base_caption = process_caption_fn(transcript, "")
            final_caption = f"{base_caption}\n\n{footer}" if footer else base_caption

            # Write back results
            ws.update_cell(r, index.get("Caption", 4) + 1, final_caption)
        except Exception as e:
            log_message(f"Error processing row {r}: {e}")
            try:
                ws.update_cell(r, index.get("Error", 5) + 1, str(e))
            except Exception:
                pass
