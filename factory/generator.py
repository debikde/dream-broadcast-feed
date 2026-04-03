import base64
import io
import json
import time
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw

from .config import load_settings
from .logger import log
from .paths import GENERATED_DIR


def _get_settings():
    return load_settings()


class Automatic1111Backend:
    def __init__(self, base_url: str | None = None):
        settings = _get_settings()
        self.base_url = (base_url or settings["automatic1111_url"]).rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        self.default_headers = {"Accept": "application/json"}

    def _is_local_url(self) -> bool:
        hostname = (urlparse(self.base_url).hostname or "").lower()
        return hostname in {"127.0.0.1", "localhost", "::1"}

    def _request(self, method: str, path: str, *, timeout: int, **kwargs) -> requests.Response:
        headers = dict(self.default_headers)
        headers.update(kwargs.pop("headers", {}))

        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=timeout,
                headers=headers,
                **kwargs,
            )
        except requests.RequestException as e:
            hint = ""
            if self._is_local_url():
                hint = " Проверь, что A1111 запущен с флагом --api и доступен по этому адресу напрямую."
            raise RuntimeError(f"Не удалось подключиться к Automatic1111 ({self.base_url}): {e}.{hint}") from e

        if response.status_code == 404 and path == "/sdapi/v1/options":
            raise RuntimeError(
                "Automatic1111 отвечает, но endpoint /sdapi/v1/options не найден. "
                "Скорее всего webui запущен без --api."
            )

        if response.status_code == 502 and self._is_local_url():
            raise RuntimeError(
                "Получен 502 Bad Gateway при обращении к локальному Automatic1111. "
                "Обычно это следствие proxy или промежуточного шлюза между приложением и localhost. "
                "Теперь запросы идут напрямую без proxy; если ошибка повторится, проверь переменные HTTP_PROXY/HTTPS_PROXY."
            )

        return response

    def ping(self) -> bool:
        try:
            response = self._request("GET", "/sdapi/v1/options", timeout=5)
            return response.ok
        except Exception as e:
            log(f"A1111 ping failed: {e}")
            return False

    def get_samplers(self) -> list[str]:
        try:
            response = self._request("GET", "/sdapi/v1/samplers", timeout=10)
            response.raise_for_status()
            data = response.json()
            return [item.get("name", "") for item in data if isinstance(item, dict)]
        except Exception as e:
            log(f"Не удалось получить список sampler-ов из A1111: {e}")
            return []

    def _normalize_image_b64(self, img_b64: str) -> bytes:
        if "," in img_b64 and img_b64.startswith("data:"):
            img_b64 = img_b64.split(",", 1)[1]
        return base64.b64decode(img_b64)

    def generate(
        self,
        prompt: str,
        out_path: Path,
        *,
        negative_prompt: str = "",
        width: int = 768,
        height: int = 768,
        steps: int = 24,
        cfg_scale: float = 6.5,
        sampler_name: str = "Euler a",
    ) -> Path:
        available_samplers = self.get_samplers()
        if available_samplers and sampler_name not in available_samplers:
            sampler_name = available_samplers[0]

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "sampler_name": sampler_name,
            "batch_size": 1,
            "n_iter": 1,
        }

        log(
            f"A1111 txt2img request: url={self.base_url}/sdapi/v1/txt2img, "
            f"sampler={payload['sampler_name']}, size={width}x{height}, steps={steps}, cfg={cfg_scale}"
        )

        response = self._request(
            "POST",
            "/sdapi/v1/txt2img",
            json=payload,
            timeout=300,
        )

        if not response.ok:
            try:
                err_json = response.json()
                err_text = json.dumps(err_json, ensure_ascii=False, indent=2)
            except Exception:
                err_text = response.text
            raise RuntimeError(f"Automatic1111 вернул ошибку {response.status_code}:\n{err_text}")

        try:
            data = response.json()
        except Exception as e:
            raise RuntimeError(f"API вернул невалидный JSON: {e}\nТекст ответа: {response.text[:1000]}") from e

        if "images" not in data or not data["images"]:
            raise RuntimeError(
                f"API не вернул изображений. Ответ:\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}"
            )

        img_b64 = data["images"][0]

        try:
            image_bytes = self._normalize_image_b64(img_b64)
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as e:
            raise RuntimeError(f"Не удалось декодировать изображение из ответа API: {e}") from e

        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)
        log(f"A1111 image saved: {out_path}")
        return out_path


class MockBackend:
    def generate(self, prompt: str, out_path: Path, **kwargs) -> Path:
        im = Image.new(
            "RGB",
            (kwargs.get("width", 768), kwargs.get("height", 768)),
            (25, 20, 40),
        )
        d = ImageDraw.Draw(im)
        d.rectangle((40, 40, im.width - 40, im.height - 40), outline=(180, 140, 255), width=3)
        d.text((60, 80), "MOCK GENERATION", fill=(240, 240, 255))
        d.text((60, 140), prompt[:180], fill=(200, 200, 220))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path)
        return out_path


def get_backend(name: str):
    if name == "automatic1111":
        return Automatic1111Backend()
    return MockBackend()


def generate_batch(
    category: str,
    prompts: Sequence[str],
    backend_name: str,
    custom_negative: str = "",
) -> list[Path]:
    settings = _get_settings()

    out_dir = GENERATED_DIR / category
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = get_backend(backend_name)
    results = []
    ts = time.strftime("%Y%m%d_%H%M%S")

    for idx, prompt in enumerate(prompts, start=1):
        out_path = out_dir / f"{category}_{ts}_{idx:03d}.png"

        backend.generate(
            prompt,
            out_path,
            negative_prompt=custom_negative or settings["default_negative_prompt"],
            width=settings["default_width"],
            height=settings["default_height"],
            steps=settings["default_steps"],
            cfg_scale=settings["default_cfg_scale"],
            sampler_name=settings["default_sampler"],
        )

        meta = out_path.with_suffix(".json")
        with open(meta, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "prompt": prompt,
                    "category": category,
                    "backend": backend_name,
                    "negative_prompt": custom_negative or settings["default_negative_prompt"],
                    "width": settings["default_width"],
                    "height": settings["default_height"],
                    "steps": settings["default_steps"],
                    "cfg_scale": settings["default_cfg_scale"],
                    "sampler_name": settings["default_sampler"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        results.append(out_path)

    return results
