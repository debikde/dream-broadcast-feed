from pathlib import Path
from .config import load_settings

SETTINGS = load_settings()
ROOT = Path(SETTINGS['_root'])
WORKSPACE = ROOT / SETTINGS['workspace_dir']
PUBLISH = ROOT / SETTINGS['publish_dir']
LOGS = ROOT / SETTINGS['logs_dir']

PROMPTS_DIR = WORKSPACE / 'prompts'
GENERATED_DIR = WORKSPACE / 'generated'
MANUAL_DIR = WORKSPACE / 'manual'
SELECTED_DIR = WORKSPACE / 'selected'
REJECTED_DIR = WORKSPACE / 'rejected'
PACKS_DIR = PUBLISH / 'packs'


def ensure_dirs():
    for p in [WORKSPACE, PUBLISH, LOGS, PROMPTS_DIR, GENERATED_DIR, MANUAL_DIR, SELECTED_DIR, REJECTED_DIR, PACKS_DIR]:
        p.mkdir(parents=True, exist_ok=True)
    for cat in SETTINGS['categories']:
        for base in [GENERATED_DIR, MANUAL_DIR, SELECTED_DIR, REJECTED_DIR]:
            (base / cat).mkdir(parents=True, exist_ok=True)
