#!/usr/bin/env python3
"""Launch YuE Studio in a dedicated Windows browser window and own its service."""
from __future__ import annotations

import ctypes
import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

STUDIO = Path(__file__).resolve().parents[1]


def data_directory() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "YuE Studio"


def browser_path() -> Path | None:
    candidates = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.extend((Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe"))
    for name in ("msedge.exe", "chrome.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def show_error(message: str) -> None:
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "YuE Studio", 0x10)
    except (AttributeError, OSError):
        pass


def main() -> int:
    web = STUDIO / "web" / "dist"
    server_script = STUDIO / "server" / "server.py"
    browser = browser_path()
    if not (web / "index.html").is_file() or not server_script.is_file():
        show_error("YuE Studio has not been built. Run npm ci and npm run build in studio\\web.")
        return 1
    if browser is None:
        show_error("YuE Studio needs Microsoft Edge or Google Chrome for its Windows app window.")
        return 1

    data = data_directory()
    logs = data / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    log_path = logs / f"studio-windows-{stamp}-{uuid.uuid4().hex[:8]}.log"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    environment = os.environ.copy()
    environment.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", YUE_STUDIO_REPO=str(STUDIO.parent))
    environment.pop("PYTHONPATH", None)
    url = f"http://127.0.0.1:{port}"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with log_path.open("ab") as log:
        service = subprocess.Popen([
            sys.executable, "-u", str(server_script), "--host", "127.0.0.1", "--port", str(port),
            "--data-dir", str(data), "--web-dir", str(web), "--no-open",
        ], cwd=data, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
           creationflags=creation_flags)

        def interrupted(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        for name in ("SIGINT", "SIGTERM"):
            signal.signal(getattr(signal, name), interrupted)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if service.poll() is not None:
                    raise RuntimeError(f"The local service exited. See {log_path}")
                try:
                    with urllib.request.urlopen(url + "/api/bootstrap", timeout=5) as response:
                        if response.status == 200 and isinstance(json.load(response), dict):
                            break
                except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                    time.sleep(0.3)
            else:
                raise RuntimeError(f"The service did not become ready within 45 seconds. See {log_path}")

            app = subprocess.Popen([
                str(browser), f"--app={url}", f"--user-data-dir={data / 'Browser Profile'}",
                "--no-first-run", "--disable-background-mode", "--start-maximized",
            ], cwd=data, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return app.wait()
        except KeyboardInterrupt:
            return 0
        except RuntimeError as error:
            show_error(str(error))
            return 1
        finally:
            if service.poll() is None:
                service.terminate()
                try:
                    service.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    service.kill()
                    service.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
