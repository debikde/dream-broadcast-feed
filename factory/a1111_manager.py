import subprocess
import time
from pathlib import Path

import requests

from .config import load_settings
from .logger import log

SETTINGS = load_settings()


class A1111Manager:
    def __init__(self):
        self.base_url = SETTINGS["automatic1111_url"].rstrip("/")
        self.workdir = Path(SETTINGS["automatic1111_workdir"])
        self.launch_script = SETTINGS["automatic1111_launch_script"]
        self.start_timeout = int(SETTINGS.get("automatic1111_start_timeout", 300))
        self.process = None
        self.started_by_factory = False

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/sdapi/v1/options", timeout=5)
            return r.ok
        except Exception:
            return False

    def is_running(self) -> bool:
        if self.ping():
            return True

        if self.process is not None and self.process.poll() is None:
            return True

        return False

    def ensure_running(self) -> bool:
        if self.ping():
            log("A1111 уже запущен")
            return True

        if self.process is None or self.process.poll() is not None:
            self.start()

        return self.wait_until_ready()

    def start(self) -> None:
        if self.ping():
            log("A1111 уже доступен, запуск не требуется")
            return

        script_path = self.workdir / self.launch_script
        if not script_path.exists():
            raise RuntimeError(f"Не найден launch script: {script_path}")

        log(f"Запуск A1111: {script_path}")

        self.process = subprocess.Popen(
            [str(script_path)],
            cwd=str(self.workdir),
            shell=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        self.started_by_factory = True

    def wait_until_ready(self) -> bool:
        started = time.time()
        while time.time() - started < self.start_timeout:
            if self.ping():
                log("A1111 готов к работе")
                return True

            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError("A1111 завершился во время запуска")

            time.sleep(2)

        raise RuntimeError("A1111 не поднялся за отведённое время")

    def stop(self) -> None:
        if not self.started_by_factory:
            log("A1111 не был запущен фабрикой, останавливать не будем")
            return

        if self.process is None:
            return

        if self.process.poll() is not None:
            return

        log("Остановка A1111...")
        try:
            self.process.terminate()
            self.process.wait(timeout=20)
            log("A1111 остановлен")
        except Exception:
            try:
                self.process.kill()
                log("A1111 принудительно завершён")
            except Exception as e:
                log(f"Не удалось остановить A1111: {e}")