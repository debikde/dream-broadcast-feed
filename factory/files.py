import shutil
from pathlib import Path
from typing import Iterable

from .paths import GENERATED_DIR, MANUAL_DIR, SELECTED_DIR, REJECTED_DIR

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp'}


def list_images(category: str, source: str) -> list[Path]:
    base = {
        'generated': GENERATED_DIR,
        'manual': MANUAL_DIR,
        'selected': SELECTED_DIR,
        'rejected': REJECTED_DIR,
    }[source]
    folder = base / category
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS])


def move_to_selected(paths: Iterable[Path], category: str):
    target = SELECTED_DIR / category
    target.mkdir(parents=True, exist_ok=True)
    for p in paths:
        shutil.move(str(p), str(target / p.name))


def move_to_rejected(paths: Iterable[Path], category: str):
    target = REJECTED_DIR / category
    target.mkdir(parents=True, exist_ok=True)
    for p in paths:
        shutil.move(str(p), str(target / p.name))


def import_manual(paths: Iterable[str], category: str):
    target = MANUAL_DIR / category
    target.mkdir(parents=True, exist_ok=True)
    for src in paths:
        p = Path(src)
        shutil.copy2(p, target / p.name)
