import json
import random
import time
from pathlib import Path
from .paths import PROMPTS_DIR

BASE_TEMPLATES = {
    'ads': {
        'subjects': ['promise of comfort', 'synthetic family warmth', 'obedient happiness', 'soft domestic safety', 'dreamlike consumer trust'],
        'styles': ['uncanny tv commercial', 'pastel retro broadcast', 'glossy children television ad', 'warm but eerie product promo'],
        'details': ['no readable brand', 'soft glow', 'staged interior', 'overfriendly tone', 'television framing']
    },
    'news': {
        'subjects': ['emotional weather report', 'domestic anxiety bulletin', 'collective memory event', 'internal crisis headline', 'sleep transmission report'],
        'styles': ['cold television news still', 'broadcast newsroom graphic', 'late evening report aesthetic'],
        'details': ['ticker graphics', 'no readable logo', 'studio light', 'muted palette', 'archival feeling']
    },
    'cartoons': {
        'subjects': ['gentle cartoon landscape', 'toy-like dream world', 'friendly surreal animals', 'childhood signal garden'],
        'styles': ['flat 2D animation frame', 'television cartoon still', 'soft cel animation'],
        'details': ['simple shapes', 'clean outlines', 'pastel colors', 'slight unease', 'broadcast softness']
    },
    'daytime': {
        'subjects': ['boring educational program', 'domestic lifestyle segment', 'slow studio diagram', 'instructional television set'],
        'styles': ['public access tv frame', 'daytime broadcast still', 'studio explainer aesthetic'],
        'details': ['charts', 'neutral colors', 'slow pacing', 'clean geometry', 'television graphics']
    },
    'night': {
        'subjects': ['late-night broadcast void', 'sleep channel residue', 'signal decay dream', 'after-hours television field'],
        'styles': ['dark ambient broadcast frame', 'glitched nocturnal transmission', 'silent tv night aesthetic'],
        'details': ['scanlines', 'deep blacks', 'faint glow', 'residual image', 'electronic haze']
    }
}


def build_prompt(category: str, custom_prefix: str = '', seed: int | None = None) -> str:
    rng = random.Random(seed or time.time_ns())
    t = BASE_TEMPLATES[category]
    parts = [
        custom_prefix.strip(),
        rng.choice(t['subjects']),
        rng.choice(t['styles']),
        rng.choice(t['details']),
        'for art installation, no text'
    ]
    return ', '.join([p for p in parts if p])


def generate_prompt_batch(category: str, count: int, custom_prefix: str = '') -> list[str]:
    return [build_prompt(category, custom_prefix=custom_prefix) for _ in range(count)]


def save_prompt_batch(category: str, prompts: list[str]) -> Path:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    path = PROMPTS_DIR / f'{category}_{ts}.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'category': category, 'prompts': prompts}, f, ensure_ascii=False, indent=2)
    return path
