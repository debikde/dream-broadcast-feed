import json
import shutil
import time
import zipfile
from pathlib import Path

from .config import load_settings
from .paths import SELECTED_DIR, MANUAL_DIR, PACKS_DIR, PUBLISH

SETTINGS = load_settings()


def build_version() -> str:
    return time.strftime("%Y-%m-%d-%H%M%S")


def ensure_dirs() -> None:
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISH.mkdir(parents=True, exist_ok=True)
    (PUBLISH / "packs").mkdir(parents=True, exist_ok=True)


def retry_file_op(func, *args, retries: int = 8, delay: float = 0.35, **kwargs):
    last_exc = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except PermissionError as e:
            last_exc = e
            time.sleep(delay)
        except OSError as e:
            # WinError 32 и похожие блокировки
            last_exc = e
            time.sleep(delay)
    raise last_exc


def safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    retry_file_op(shutil.copy2, src, dst)


def collect_files(category: str) -> list[Path]:
    files = []
    seen_names = set()

    for base in [SELECTED_DIR / category, MANUAL_DIR / category]:
        if not base.exists():
            continue

        for p in sorted(base.iterdir()):
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue

            # чтобы одинаковые имена из selected/manual не дублировались
            if p.name in seen_names:
                continue

            files.append(p)
            seen_names.add(p.name)

    return files


def create_pack(
    title: str = "",
    mode: str = "blend",
    weight: float | None = None,
    ttl_days: int | None = None,
    replace_policy: str | None = None,
) -> tuple[Path, Path]:
    ensure_dirs()

    version = build_version()
    pack_dir = PACKS_DIR / f"pack_{version}"
    pack_dir.mkdir(parents=True, exist_ok=True)

    targets = {}

    for category in SETTINGS["categories"]:
        files = collect_files(category)
        if not files:
            continue

        target_dir = pack_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        targets[category] = []

        for src in files:
            dst = target_dir / src.name
            safe_copy(src, dst)
            targets[category].append(f"{category}/{src.name}")

    manifest = {
        "version": version,
        "title": title or f"Pack {version}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": mode,
        "weight": weight if weight is not None else SETTINGS["pack_weight"],
        "ttl_days": ttl_days if ttl_days is not None else SETTINGS["pack_ttl_days"],
        "replace_policy": replace_policy or SETTINGS["replace_policy"],
        "targets": targets,
    }

    manifest_path = pack_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Пишем сначала во временный zip
    tmp_zip_path = PACKS_DIR / f"pack_{version}.tmp.zip"
    final_zip_path = PACKS_DIR / f"pack_{version}.zip"

    with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in pack_dir.rglob("*"):
            zf.write(item, item.relative_to(pack_dir))

    # Небольшая пауза, чтобы Windows отпустил файл
    time.sleep(0.3)

    # Если вдруг старый zip уже есть
    if final_zip_path.exists():
        retry_file_op(final_zip_path.unlink)

    retry_file_op(tmp_zip_path.rename, final_zip_path)

    publish_manifest = PUBLISH / "manifest.json"
    published_pack = PUBLISH / "packs" / final_zip_path.name

    # Если publish и packs_dir пересекаются, не копируем файл сам в себя
    if final_zip_path.resolve() != published_pack.resolve():
        safe_copy(final_zip_path, published_pack)

    with open(publish_manifest, "w", encoding="utf-8") as f:
        json.dump(
            {
                "latest_version": version,
                "latest_pack": f"packs/{final_zip_path.name}",
                "manifest": manifest,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return final_zip_path, publish_manifest