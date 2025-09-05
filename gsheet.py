import os
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import GOOGLE_SHEET_ID
from logger import log_message
from datetime import datetime
import streamlit as st
import tempfile

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Prefer local credentials.json, fall back to Streamlit secret for deployment
cred_path = os.path.join(os.path.dirname(__file__), "credentials.json")
if os.path.exists(cred_path):
    creds = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scope)
else:
    google_credentials_base64 = st.secrets.get("GOOGLE_CREDENTIALS_BASE64")
    if google_credentials_base64:
        cred_content = base64.b64decode(google_credentials_base64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            tmp_file.write(cred_content)
            cred_path = tmp_file.name
        creds = ServiceAccountCredentials.from_json_keyfile_name(cred_path, scope)
        os.unlink(cred_path)
    else:
        raise FileNotFoundError("No credentials.json found and no GOOGLE_CREDENTIALS_BASE64 secret set.")

client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID)
log_worksheet = sheet.worksheet("IGCaptionLog")