#!/usr/bin/env python3
"""Start the local browser interface, owning only this launcher’s service process."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

STUDIO = Path(__file__).resolve().parents[1]


def main() -> int:
    web = STUDIO / "web" / "dist"
    script = STUDIO / "server" / "server.py"
    if not (web / "index.html").is_file() or not script.is_file():
        print("The Studio interface or service is missing. In studio/web, run npm install and npm run build first.")
        return 1
    data = Path.home() / "Library" / "Application Support" / "YuE Studio"
    logs = data / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    log_path = logs / f"studio-browser-{stamp}-{uuid.uuid4().hex[:8]}.log"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["YUE_STUDIO_REPO"] = str(STUDIO.parent)
    environment.pop("PYTHONPATH", None)
    url = f"http://127.0.0.1:{port}"
    with log_path.open("ab") as log:
        process = subprocess.Popen([
            sys.executable, "-u", str(script), "--host", "127.0.0.1", "--port", str(port),
            "--data-dir", str(data), "--web-dir", str(web), "--no-open",
        ], cwd=data, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)

        def interrupted(_signum: int, _frame: object) -> None:
            raise KeyboardInterrupt

        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            signal.signal(getattr(signal, name), interrupted)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"The local service exited. See {log_path}")
                try:
                    with urllib.request.urlopen(url + "/api/bootstrap", timeout=25) as response:
                        if response.status == 200 and isinstance(json.load(response), dict):
                            break
                except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                    time.sleep(0.3)
            else:
                raise RuntimeError(f"The service did not become ready within 45 seconds. See {log_path}")
            print(f"YuE Studio is running at {url}")
            print(f"Library: {data}\nLog: {log_path}")
            print("Keep this Terminal window open. Press Control-C to stop YuE Studio.")
            webbrowser.open(url)
            return process.wait()
        except KeyboardInterrupt:
            print("\nStopping YuE Studio…")
            return 0
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1
        finally:
            # Never stop another studio, unrelated Python processes, or remote engines.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
