import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_SHEET_ID
from logger import log_message
from datetime import datetime

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Use the local credentials.json file directly
cred_path = os.path.join(os.path.dirname(__file__), "credentials.json")
creds = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scope)

client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID)
log_worksheet = sheet.worksheet("IGCaptionLog")

def setup_sheet_headers():
    try:
        first_row = log_worksheet.row_values(1)
        expected_headers = ["Timestamp", "File Name", "Transcript", "Prompt", "ChatGPT Result"]
        if len(first_row) < 5 or first_row != expected_headers:
            log_worksheet.update('A1:E1', [expected_headers])
            log_message("Updated sheet headers")
    except Exception as e:
        log_message(f"Error setting up headers: {str(e)}")

def add_to_sheet(file_name, transcript, prompt=""):
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Attempting to add: {timestamp}, {file_name}, {transcript[:50]}...")  # Debug print
        log_worksheet.append_row([timestamp, file_name, transcript, prompt, ""])
        log_message(f"Added new row for {file_name}")
        return True
    except Exception as e:
        log_message(f"Error adding to sheet: {str(e)}")
        return False

def process_sheet_rows(process_func):
    try:
        all_values = log_worksheet.get_all_values()
        if len(all_values) <= 1:
            return
        for row_idx, row in enumerate(all_values[1:], start=2):
            if len(row) < 4: continue
            timestamp, file_name, transcript, prompt, existing_result = row[0], row[1], row[2], row[3], row[4] if len(row) > 4 else ""
            if not transcript or existing_result: continue
            log_message(f"Processing row {row_idx}: {file_name}")
            result = process_func(transcript, prompt)
            log_worksheet.update_cell(row_idx, 5, result)
            log_message(f"Successfully updated row {row_idx}")
    except Exception as e:
        log_message(f"Error accessing sheet: {str(e)}")