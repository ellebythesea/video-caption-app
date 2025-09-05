import time
from config import GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY
from logger import log_message
from gsheet import setup_sheet_headers, process_sheet_rows
from openai_utils import process_caption

if __name__ == "__main__":
    log_message("=== ChatGPT Enhancement Script Started ===")
    if not all([GOOGLE_SHEET_ID, OPENAI_API_KEY, SERPER_API_KEY]):
        log_message("Missing required environment variables!")
        exit(1)
    setup_sheet_headers()
    process_sheet_rows(process_caption)
    log_message("=== ChatGPT Enhancement Script Completed ===")