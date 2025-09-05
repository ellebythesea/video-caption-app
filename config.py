# config.py
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
LOG_PATH = os.getenv("LOG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatgpt_enhancement_log.txt"))
