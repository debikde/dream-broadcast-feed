import time
from pathlib import Path
from .paths import LOGS

LOG_FILE = LOGS / 'factory.log'


def log(msg: str):
    LOGS.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    return line
