# config.py
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
APP_PASSWORD = os.getenv("APP_PASSWORD")
LOG_PATH = os.getenv("LOG_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "chatgpt_enhancement_log.txt"))

# Audio preprocessing options
# Whether to trim leading/trailing silence during audio extraction
TRIM_SILENCE = os.getenv("TRIM_SILENCE", "false").lower() in {"1", "true", "yes", "y"}
# Target sample rate (Hz), channels, and bitrate for extracted audio
AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "32k")

# Caption generation options
CAPTION_MODEL = os.getenv("CAPTION_MODEL", "gpt-4o")
CAPTION_TEMPERATURE = float(os.getenv("CAPTION_TEMPERATURE", "0.5"))
CAPTION_MAX_TOKENS = int(os.getenv("CAPTION_MAX_TOKENS", "800"))
# Force two paragraphs when caption exceeds this length (in characters)
CAPTION_SPLIT_THRESHOLD = int(os.getenv("CAPTION_SPLIT_THRESHOLD", "400"))
