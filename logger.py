<<<<<<< Updated upstream
from datetime import datetime
from config import LOG_PATH

def log_message(message):
    with open(LOG_PATH, "a") as log:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f"[{timestamp}] {message}\n")
=======
# logger.py
from datetime import datetime
from config import LOG_PATH

def log_message(message):
    with open(LOG_PATH, "a") as log:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f"[{timestamp}] {message}\n")
>>>>>>> Stashed changes
