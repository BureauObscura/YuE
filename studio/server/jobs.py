"""One music worker at a time, with persistent receipts and bounded cancellation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from urllib.parse import urlsplit

try:
    from .store import Store, StudioError, ACTIVE, atomic_json
except ImportError:
    from store import Store, StudioError, ACTIVE, atomic_json


def remote_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise StudioError("Remote Studio must be a localhost HTTP address reached through an SSH tunnel.") from None
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password \
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise StudioError("Remote Studio must be a localhost HTTP address reached through an SSH tunnel.")
    return value.rstrip("/")


class JobManager:
    def __init__(self, store, repo_root, runner=None):
        self.store = store
        self.repo_root = Path(repo_root)
        self.worker = Path(__file__).with_name("worker.py")
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.probe_lock = threading.Lock()
        self.process = None
        self.current = None
        self.cancelled = set()
        self.stopping = threading.Event()
        self.runner = runner or self._run_process
        self.cached_engine = None
        self.cached_at = 0
        self.thread = threading.Thread(target=self._loop, name="yue-music-queue", daemon=True)
        self.thread.start()

    def environment(self):
        env = dict(os.environ)
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUNBUFFERED="1")
        env["PYTHONPATH"] = str(self.repo_root / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return env

    def engine(self, refresh=False):
        with self.probe_lock:
            if not refresh and self.cached_engine is not None and time.monotonic() - self.cached_at < 20:
                return dict(self.cached_engine)
            settings = self.store.settings()
            report = {"ready": False, "status": "setup_needed", "message": "", "device": settings["device"],
                      "python_path": settings["python_path"], "model_cached": False, "runtime_available": False}
            if settings["mode"] == "remote":
                report.update(status="remote_workspace", remote_url=remote_url(settings["remote_url"]) if settings["remote_url"] else "",
                              message="Open the remote Studio through your SSH tunnel. Its library and GPU jobs stay on that machine.")
            else:
                interpreter = Path(settings["python_path"]).expanduser()
                if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
                    report["message"] = "Select an existing, executable Python interpreter in Engine settings."
                else:
                    try:
                        proc = subprocess.run([str(interpreter), str(self.worker), "--check", "--settings", json.dumps(settings)],
                                              cwd=self.repo_root if self.repo_root.is_dir() else self.worker.parent,
                                              env=self.environment(), capture_output=True, text=True, timeout=20)
                        lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
                        probe = json.loads(lines[-1]) if lines else {}
                        if "ready" not in probe:
                            raise ValueError("No runtime readiness report")
                        report.update(probe)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        report.update(status="runtime_error", message="The selected Python interpreter could not complete its runtime check. Choose a working Python 3.10 or newer environment.")
            self.cached_engine, self.cached_at = report, time.monotonic()
            return dict(report)

    def enqueue(self, track_id):
        with self.lock:
            if self.stopping.is_set():
                raise StudioError("Studio is closing.", 503)
            report = self.engine()
            if not report["ready"]:
                raise StudioError(report["message"], 409)
            with self.store.lock:
                outstanding = sum(t["status"] in ACTIVE for tr in self.store.state["tracks"].values() for t in tr["takes"])
                if outstanding >= 20:
                    raise StudioError("The queue is full. Finish or cancel some jobs before adding more.", 409)
                take = self.store.new_take(track_id)
            self.queue.put((track_id, take["id"]))
            return self.store.track(track_id)

    def cancel(self, track_id, take_id):
        with self.lock:
            take = self.store.take_internal(track_id, take_id)
            if take["status"] not in ACTIVE:
                return self.store.track(track_id)
            key = (track_id, take_id)
            self.cancelled.add(key)
            track = self.store.update_take(track_id, take_id, status="cancelled", stage="Cancelled", error=None)
            if key == self.current and self.process and self.process.poll() is None:
                self.process.terminate()
                threading.Thread(target=self._kill_later, args=(self.process,), daemon=True).start()
            return track

    @staticmethod
    def _kill_later(process):
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def _loop(self):
        while not self.stopping.is_set():
            try:
                key = self.queue.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                with self.lock:
                    if key in self.cancelled or self.stopping.is_set():
                        continue
                    self.current = key
                    self.store.update_take(*key, status="running", stage="Starting engine")
                self.runner(*key)
            except Exception as exc:
                with self.lock:
                    if key not in self.cancelled:
                        self.store.update_take(*key, status="failed", stage="Generation failed", error=str(exc)[:2000])
            finally:
                with self.lock:
                    self.current = None
                    self.process = None
                    self.cancelled.discard(key)
                self.queue.task_done()

    def _run_process(self, track_id, take_id):
        key = (track_id, take_id)
        take = self.store.take_internal(*key)
        settings = take["_settings"]
        directory = self.store.take_dir(*key)
        atomic_json(directory / "studio-engine.json", settings)
        output = directory / "artifacts"
        log_path = directory / "worker.log"
        receipt = None
        with open(log_path, "w", encoding="utf-8") as log:
            with self.lock:
                if key in self.cancelled or self.stopping.is_set():
                    return
                self.process = subprocess.Popen([str(Path(settings["python_path"]).expanduser()), str(self.worker),
                    "--settings", str(directory / "studio-engine.json"), "--request", str(directory / "studio-request.json"),
                    "--output", str(output)], cwd=self.repo_root if self.repo_root.is_dir() else self.worker.parent,
                    env=self.environment(), stdout=subprocess.PIPE, stderr=log, text=True)
                proc = self.process
            try:
                for line in proc.stdout:
                    # Third-party libraries may print informational lines. Only our JSON events mutate status.
                    if not line.startswith("{") or len(line) > 10000:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    with self.lock:
                        if key in self.cancelled or self.stopping.is_set():
                            continue
                        if event.get("stage"):
                            self.store.update_take(*key, stage=str(event["stage"])[:200])
                        if event.get("status") in {"complete", "failed", "cancelled"}:
                            receipt = event
                code = proc.wait()
            finally:
                proc.stdout.close()
                if proc.poll() is None:
                    proc.terminate()
                    self._kill_later(proc)
        with self.lock:
            if key in self.cancelled or self.stopping.is_set():
                return
            audio = output / "audio.flac"
            if code == 0 and receipt and receipt.get("status") == "complete" and audio.is_file() and (output / "result.json").is_file():
                truncated = bool(receipt.get("truncated"))
                digest = hashlib.sha256()
                with open(audio, "rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                self.store.update_take(*key, status="needs_review" if truncated else "complete",
                    stage="Complete, review ending" if truncated else "Complete", duration=receipt.get("duration"),
                    truncated=truncated, audio_url=self.store.media_url(audio), _audio=str(audio.relative_to(self.store.artifacts)),
                    _mime="audio/flac", _sha256=digest.hexdigest())
            else:
                error = receipt.get("error") if receipt else None
                self.store.update_take(*key, status="failed", stage="Generation failed",
                    error=error or f"The music worker exited with code {code}. Its diagnostic log is saved with this take.")

    def close(self):
        self.stopping.set()
        with self.lock:
            for track in self.store.tracks():
                for take in track["takes"]:
                    if take["status"] in ACTIVE:
                        self.cancel(track["id"], take["id"])
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self._kill_later(self.process)
        self.thread.join(timeout=4)
