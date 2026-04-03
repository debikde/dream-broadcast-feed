import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / 'settings.json'


def load_settings() -> dict:
    with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data['_root'] = str(ROOT)
    return data
