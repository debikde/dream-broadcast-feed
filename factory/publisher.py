import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from .config import load_settings
from .logger import log
from .paths import (
    RELEASE_FEED_REPO,
    DOCS_DIR,
    DOCS_PACKS_DIR,
    DOCS_INDEX_JSON,
    DOCS_INDEX_HTML,
    DOCS_NOJEKYLL,
)

SETTINGS = load_settings()


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )


def _ensure_feed_structure() -> None:
    if not RELEASE_FEED_REPO.exists():
        raise RuntimeError(
            f"Не найден репозиторий feed: {RELEASE_FEED_REPO}\n"
            f"Проверь settings.json -> release_feed_repo_dir"
        )

    if not (RELEASE_FEED_REPO / ".git").exists():
        raise RuntimeError(
            f"Папка {RELEASE_FEED_REPO} существует, но это не git-репозиторий"
        )

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_PACKS_DIR.mkdir(parents=True, exist_ok=True)

    if not DOCS_INDEX_HTML.exists():
        DOCS_INDEX_HTML.write_text(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Dream Broadcast Feed</title>
</head>
<body>
  <h1>Dream Broadcast Feed</h1>
  <p>Static update feed for the gallery installation.</p>
</body>
</html>
""",
            encoding="utf-8",
        )

    if not DOCS_NOJEKYLL.exists():
        DOCS_NOJEKYLL.write_text("", encoding="utf-8")

    if not DOCS_INDEX_JSON.exists():
        with open(DOCS_INDEX_JSON, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "channel": SETTINGS.get("release_channel", "main"),
                    "latest_version": None,
                    "published_at": None,
                    "packs": [],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )


def _load_index() -> dict:
    _ensure_feed_structure()
    with open(DOCS_INDEX_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(index_data: dict) -> None:
    tmp = DOCS_INDEX_JSON.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    if DOCS_INDEX_JSON.exists():
        DOCS_INDEX_JSON.unlink()
    tmp.rename(DOCS_INDEX_JSON)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_pack_to_docs(zip_path: Path) -> Path:
    DOCS_PACKS_DIR.mkdir(parents=True, exist_ok=True)
    dst = DOCS_PACKS_DIR / zip_path.name
    shutil.copy2(zip_path, dst)
    return dst


def _load_pack_manifest(manifest_path: Path) -> dict:
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _upsert_pack_entry(index_data: dict, pack_entry: dict) -> dict:
    packs = index_data.get("packs", [])
    version = pack_entry["version"]

    replaced = False
    for i, existing in enumerate(packs):
        if existing.get("version") == version:
            packs[i] = pack_entry
            replaced = True
            break

    if not replaced:
        packs.append(pack_entry)

    packs = sorted(packs, key=lambda x: x.get("version", ""))
    index_data["packs"] = packs
    index_data["latest_version"] = version
    index_data["published_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    index_data["channel"] = SETTINGS.get("release_channel", "main")
    return index_data


def _git_has_changes(repo_dir: Path) -> bool:
    result = _run_git(["status", "--porcelain"], repo_dir)
    if result.returncode != 0:
        raise RuntimeError(f"git status failed:\n{result.stderr}")
    return bool(result.stdout.strip())


def _git_commit_and_push(repo_dir: Path, version: str) -> None:
    add_result = _run_git(["add", "docs/index.json", "docs/packs", "docs/index.html", "docs/.nojekyll"], repo_dir)
    if add_result.returncode != 0:
        raise RuntimeError(f"git add failed:\n{add_result.stderr}")

    if not _git_has_changes(repo_dir):
        log("Git: нет изменений для коммита")
        return

    commit_message = f'{SETTINGS.get("git_commit_prefix", "Publish pack")} {version}'

    commit_result = _run_git(["commit", "-m", commit_message], repo_dir)
    if commit_result.returncode != 0:
        raise RuntimeError(f"git commit failed:\n{commit_result.stderr}\n{commit_result.stdout}")

    if SETTINGS.get("git_auto_push", True):
        push_result = _run_git(["push", SETTINGS.get("git_remote_name", "origin"), SETTINGS.get("git_branch", "main")], repo_dir)
        if push_result.returncode != 0:
            raise RuntimeError(f"git push failed:\n{push_result.stderr}\n{push_result.stdout}")


def publish_pack(zip_path: Path, manifest_path: Path) -> dict:
    """
    Берёт локально собранный pack.zip и его manifest.json,
    публикует в GitHub Pages feed repo/docs и пушит в git.
    """
    _ensure_feed_structure()

    if not zip_path.exists():
        raise RuntimeError(f"ZIP не найден: {zip_path}")
    if not manifest_path.exists():
        raise RuntimeError(f"Manifest не найден: {manifest_path}")

    manifest = _load_pack_manifest(manifest_path)
    version = manifest["version"]

    published_zip = _copy_pack_to_docs(zip_path)
    sha256 = _sha256_of_file(published_zip)
    size = published_zip.stat().st_size

    relative_zip_url = f"packs/{published_zip.name}"

    index_data = _load_index()

    pack_entry = {
        "version": version,
        "url": relative_zip_url,
        "sha256": sha256,
        "size": size,
        "manifest": manifest,
    }

    index_data = _upsert_pack_entry(index_data, pack_entry)
    _save_index(index_data)

    _git_commit_and_push(RELEASE_FEED_REPO, version)

    base_url = SETTINGS.get("github_pages_base_url", "").rstrip("/")
    public_index_url = f"{base_url}/index.json" if base_url else ""
    public_pack_url = f"{base_url}/{relative_zip_url}" if base_url else ""

    result = {
        "version": version,
        "published_zip": str(published_zip),
        "index_json": str(DOCS_INDEX_JSON),
        "public_index_url": public_index_url,
        "public_pack_url": public_pack_url,
        "sha256": sha256,
        "size": size,
    }

    log(f"Pack published to GitHub feed: {version}")
    return result