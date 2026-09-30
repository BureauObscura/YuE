#!/usr/bin/env python3
"""Run YuE Studio locally without installing model or web-server dependencies."""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import sys
import tempfile
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser
import zipfile

try:
    from .store import Store, StudioError, atomic_json
    from .jobs import JobManager, remote_url
    from .artwork import generate_artwork, ArtworkError, ArtworkCancelled
except ImportError:
    from store import Store, StudioError, atomic_json
    from jobs import JobManager, remote_url
    try:
        from artwork import generate_artwork, ArtworkError, ArtworkCancelled
    except ImportError:
        generate_artwork = None
        ArtworkError = ArtworkCancelled = RuntimeError


MAX_BODY = 114 * 1024 * 1024


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Studio:
    def __init__(self, data_dir, web_dir, repo_root=None, jobs_factory=JobManager, artwork_generator=generate_artwork):
        self.repo_root = Path(repo_root or os.environ.get("YUE_STUDIO_REPO", Path(__file__).resolve().parents[2])).expanduser().resolve()
        self.store = Store(data_dir, self.repo_root)
        self.web_dir = Path(web_dir).resolve()
        self.csrf = secrets.token_urlsafe(32)
        self.jobs = jobs_factory(self.store, self.repo_root)
        self.artwork_generator = artwork_generator
        self.art_lock = threading.RLock()
        self.artwork_jobs = {}

    def bootstrap(self):
        return {"csrf": self.csrf, "tracks": self.store.tracks(), "settings": self.store.settings(), "engine": self.jobs.engine()}

    def artwork(self, track_id, payload):
        prompt, api_key = payload.get("prompt"), payload.get("api_key")
        if self.artwork_generator is None:
            raise StudioError("The artwork provider module is unavailable.", 503)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 6000:
            raise StudioError("Write an artwork prompt of 1 to 6,000 characters.")
        if not isinstance(api_key, str) or not api_key or len(api_key) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
            raise StudioError("Enter a valid BFL API key to generate artwork.")
        with self.art_lock:
            self.store.track(track_id)
            if track_id in self.artwork_jobs:
                raise StudioError("Artwork is already being generated for this track.", 409)
            event = threading.Event()
            self.artwork_jobs[track_id] = event
            self.store.set_cover_state(track_id, "running", prompt=prompt.strip())

            def run():
                try:
                    data, mime, metadata = self.artwork_generator(prompt, api_key, cancelled=event.is_set)
                    if event.is_set():
                        return
                    with self.store.lock:
                        self.store.put_cover(track_id, data)
                        track = self.store._track(track_id)
                        # The provider module returns sanitized metadata, never signed URLs or keys.
                        safe_keys = {"provider", "model", "request_id", "width", "height", "prompt", "prompt_upsampling", "mime", "sha256", "created_at"}
                        safe = {k: v for k, v in metadata.items() if k in safe_keys}
                        track["_cover_metadata"] = safe
                        self.store.save()
                        path = self.store.artifacts / track["_cover"]
                        atomic_json(path.with_suffix(".json"), safe)
                except ArtworkCancelled as exc:
                    self.store.set_cover_state(track_id, "failed", str(exc))
                except ArtworkError as exc:
                    self.store.set_cover_state(track_id, "failed", str(exc))
                except Exception:
                    self.store.set_cover_state(track_id, "failed", "Artwork could not be saved. Check your BFL dashboard before generating again.")
                finally:
                    with self.art_lock:
                        self.artwork_jobs.pop(track_id, None)

            threading.Thread(target=run, name="yue-cover-" + track_id[:8], daemon=True).start()
            return self.store.track(track_id)

    def export(self, track_id, take_id=None):
        # Snapshot under the storage lock; deletion cannot race an export read.
        with self.store.lock:
            track = self.store._track(track_id)
            take_id = take_id or track["selected_take_id"]
            if not take_id:
                raise StudioError("Select a recorded take to export.", 409)
            take = self.store._take(track, take_id)
            if take["status"] not in {"complete", "needs_review"} or not take.get("_audio"):
                raise StudioError("This take has no completed recording to export.", 409)
            audio, mime = self.store.media_path(take["_audio"])
            cover = self.store.media_path(track["_cover"])[0] if track.get("_cover") else None
            request = take["_request"]
            target = tempfile.NamedTemporaryFile(prefix="yue-export-", suffix=".zip", dir=self.store.root, delete=False)
            target.close()
            destination = Path(target.name)
            try:
                with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(audio, "originals/audio" + audio.suffix)
                    if cover:
                        archive.write(cover, "cover" + cover.suffix)
                    archive.writestr("lyrics.txt", request["lyrics"])
                    archive.writestr("request.json", json.dumps(request, ensure_ascii=False, indent=2))
                    artifact_dir = self.store.take_dir(track_id, take_id) / "artifacts"
                    score = artifact_dir / "score.abc"
                    if score.is_file() and not score.is_symlink():
                        archive.write(score, "score.abc")
                    elif request.get("abc"):
                        archive.writestr("score.abc", request["abc"])
                    for name in ("result.json", "config.json", "plan.json", "plan_manifest.json"):
                        file = artifact_dir / name
                        if file.is_file() and not file.is_symlink():
                            archive.write(file, "generation/" + name)
                    embedded = self._tag_export_copy(archive, audio, cover, track)
                    metadata = {"track": {k: track[k] for k in ("id", "title", "artist", "album", "created_at")},
                                "take": {k: v for k, v in take.items() if not k.startswith("_")},
                                "recorded_metadata": take["_metadata"], "source": take["_source"],
                                "original_sha256": sha256_file(audio), "artwork_embedded_in_delivery_copy": embedded,
                                "cover": track.get("_cover_metadata"), "request": request}
                    archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
                    archive.writestr("README.txt", "YuE Studio export\n\nThe originals folder contains the unchanged recording.\n"
                        "Lyrics and request belong to the selected take, even if the current draft has changed.\n"
                        + ("A delivery copy with embedded artwork is included in delivery/.\n" if embedded else
                           "Artwork is provided as a separate image. Embedded artwork was not created; it requires a supported audio format and the optional mutagen package in the Studio Python environment.\n")
                        + "Generated result.json hashes refer to the full original generation directory, retained in the Studio library.\n")
                return destination
            except Exception:
                destination.unlink(missing_ok=True)
                raise

    @staticmethod
    def _tag_export_copy(archive, audio, cover, track):
        if cover is None or cover.suffix.lower() not in {".png", ".jpg"} or audio.suffix.lower() not in {".flac", ".mp3", ".m4a"}:
            return False
        try:
            import mutagen
            from mutagen.flac import FLAC, Picture
            from mutagen.id3 import ID3, APIC, ID3NoHeaderError, TIT2, TPE1, TALB
            from mutagen.mp4 import MP4, MP4Cover
        except ImportError:
            return False
        try:
            with tempfile.TemporaryDirectory(prefix="yue-delivery-") as temporary:
                target = Path(temporary) / ("audio" + audio.suffix)
                shutil.copyfile(audio, target)
                picture = cover.read_bytes()
                mime = "image/png" if cover.suffix == ".png" else "image/jpeg"
                if target.suffix == ".flac":
                    tags = FLAC(target)
                    p = Picture()
                    p.data, p.type, p.mime = picture, 3, mime
                    tags.clear_pictures()
                    tags.add_picture(p)
                    for key in ("title", "artist", "album"):
                        tags[key] = track[key]
                    tags.save()
                elif target.suffix == ".mp3":
                    try:
                        tags = ID3(target)
                    except ID3NoHeaderError:
                        tags = ID3()
                    tags.delall("APIC")
                    tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=picture))
                    for cls, key in ((TIT2, "title"), (TPE1, "artist"), (TALB, "album")):
                        tags.add(cls(encoding=3, text=track[key]))
                    tags.save(target)
                else:
                    tags = MP4(target)
                    tags["covr"] = [MP4Cover(picture, imageformat=MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG)]
                    for field, key in (("\xa9nam", "title"), ("\xa9ART", "artist"), ("\xa9alb", "album")):
                        tags[field] = [track[key]]
                    tags.save()
                archive.write(target, "delivery/" + target.name)
                return True
        except Exception:
            # Original recording and standalone cover still export if optional tagging fails.
            return False

    def close(self):
        with self.art_lock:
            for event in self.artwork_jobs.values():
                event.set()
        self.jobs.close()


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, studio, forwarded_ports=()):
        self.studio = studio
        super().__init__(address, Handler)
        self.allowed_ports = {self.server_address[1], *forwarded_ports}


class Handler(BaseHTTPRequestHandler):
    server_version = "YuEStudio/1.0"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        # Bodies, API keys, and private lyrics never enter HTTP logs.
        return

    @property
    def studio(self):
        return self.server.studio

    def _security(self, write=False):
        allowed_hosts = {host for port in self.server.allowed_ports for host in
                         (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")}
        if 80 in self.server.allowed_ports:
            allowed_hosts |= {"127.0.0.1", "localhost", "[::1]"}
        host = self.headers.get("Host", "").lower()
        if host not in allowed_hosts or len(self.headers.get_all("Host", [])) != 1:
            raise StudioError("This Studio accepts requests only through its localhost address.", 403)
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            raise StudioError("Cross-origin requests are not allowed.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise StudioError("Cross-site requests are not allowed.", 403)
        token = self.headers.get("X-Studio-Token", "")
        if write and (not token.isascii() or not secrets.compare_digest(token, self.studio.csrf)):
            raise StudioError("Studio session expired. Refresh the page before trying again.", 403)

    def _headers(self, status, mime, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def json(self, body, status=200):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(raw))
        if self.command != "HEAD":
            self.wfile.write(raw)

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise StudioError("Chunked request bodies are not supported.", 400)
        if len(self.headers.get_all("Content-Length", [])) != 1:
            raise StudioError("A single Content-Length header is required.", 411)
        try:
            length = int(self.headers["Content-Length"])
        except ValueError:
            raise StudioError("Invalid request length.") from None
        if length < 0 or length > MAX_BODY:
            raise StudioError("Request exceeds the upload size limit.", 413)
        if self.headers.get_content_type() != "application/json":
            raise StudioError("Send a JSON request body.", 415)
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete body")
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise StudioError("The JSON request could not be read.") from None
        if not isinstance(value, dict):
            raise StudioError("Request body must be a JSON object.")
        return value

    def file(self, path, mime, extra=None):
        size = path.stat().st_size
        begin, end, status = 0, size - 1, 200
        headers = {"Accept-Ranges": "bytes", **(extra or {})}
        value = self.headers.get("Range")
        if value:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
            if not match or not any(match.groups()):
                self._headers(416, mime, 0, {"Content-Range": f"bytes */{size}"})
                return
            left, right = match.groups()
            if left:
                begin = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                begin = max(0, size - int(right))
            if begin > end or begin >= size:
                self._headers(416, mime, 0, {"Content-Range": f"bytes */{size}"})
                return
            status = 206
            headers["Content-Range"] = f"bytes {begin}-{end}/{size}"
        self._headers(status, mime, max(0, end - begin + 1), headers)
        if self.command == "HEAD":
            return
        with open(path, "rb") as stream:
            stream.seek(begin)
            remaining = end - begin + 1
            while remaining > 0:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        self.dispatch()

    def do_HEAD(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PATCH(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()

    def dispatch(self):
        try:
            self._security(write=self.command not in {"GET", "HEAD"})
            self.route()
        except StudioError as exc:
            self.json({"error": str(exc)}, exc.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout):
            return
        except Exception:
            self.json({"error": "Studio could not complete this request. Your saved recordings have been preserved."}, 500)

    def route(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if "\0" in path or "\\" in path or any(part == ".." for part in path.split("/")):
            raise StudioError("Invalid request path.", 400)
        get = self.command in {"GET", "HEAD"}
        store = self.studio.store
        if path == "/api/bootstrap" and get:
            return self.json(self.studio.bootstrap())
        if path == "/api/engine" and get:
            return self.json(self.studio.jobs.engine(refresh=True))
        if path == "/api/settings" and self.command == "PATCH":
            fields = self.body()
            if fields.get("remote_url"):
                fields["remote_url"] = remote_url(fields["remote_url"])
            settings = store.update_settings(fields)
            return self.json({"settings": settings, "engine": self.studio.jobs.engine(refresh=True)})
        if path == "/api/tracks":
            if get:
                return self.json({"tracks": store.tracks()})
            if self.command == "POST":
                return self.json({"track": store.create(self.body())}, 201)
        match = re.fullmatch(r"/api/tracks/([a-f0-9]{32})(?:/(.*))?", path)
        if match:
            track_id, action = match.groups()
            if action is None:
                if get:
                    return self.json({"track": store.track(track_id)})
                if self.command == "PATCH":
                    return self.json({"track": store.update(track_id, self.body())})
                if self.command == "DELETE":
                    store.delete(track_id)
                    return self.json({"ok": True})
            if action == "generate" and self.command == "POST":
                self.body()
                return self.json({"track": self.studio.jobs.enqueue(track_id)}, 202)
            if action == "audio" and self.command == "POST":
                return self.json({"track": store.import_audio(track_id, self.body())}, 201)
            if action == "cover" and self.command == "POST":
                payload = self.body()
                with self.studio.art_lock:
                    if track_id in self.studio.artwork_jobs:
                        raise StudioError("Wait for the current artwork job to finish before replacing its cover.", 409)
                    return self.json({"track": store.import_cover(track_id, payload)}, 201)
            if action == "artwork" and self.command == "POST":
                return self.json({"track": self.studio.artwork(track_id, self.body())}, 202)
            cancel = re.fullmatch(r"takes/([a-f0-9]{32})/cancel", action or "")
            if cancel and self.command == "POST":
                self.body()
                return self.json({"track": self.studio.jobs.cancel(track_id, cancel[1])})
            if action == "export" and get:
                destination = self.studio.export(track_id, parse_qs(parsed.query).get("take", [None])[0])
                try:
                    return self.file(destination, "application/zip", {"Content-Disposition": 'attachment; filename="YuE-Studio-track.zip"'})
                finally:
                    destination.unlink(missing_ok=True)
        if path.startswith("/api/"):
            raise StudioError("API endpoint not found.", 404)
        if not get:
            raise StudioError("Method not allowed.", 405)
        if path.startswith("/media/"):
            file, mime = store.media_path(path[len("/media/"):])
            return self.file(file, mime)
        file = self.studio.web_dir / path.lstrip("/")
        if not file.resolve().is_relative_to(self.studio.web_dir) or file.is_symlink():
            raise StudioError("File not found.", 404)
        if not file.is_file():
            if path.startswith("/assets/") or Path(path).suffix:
                raise StudioError("File not found.", 404)
            file = self.studio.web_dir / "index.html"
        if not file.is_file():
            raise StudioError("The Studio interface has not been built. Run the documented web build, then reopen Studio.", 503)
        return self.file(file, mimetypes.guess_type(file.name)[0] or "application/octet-stream")


def default_data_dir():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/YuE Studio"
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return (Path(local_app_data) if local_app_data else Path.home() / "AppData/Local") / "YuE Studio"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "yue-studio"


def main(argv=None):
    parser = argparse.ArgumentParser(description="YuE Studio: local music library and generation interface")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost"), default="127.0.0.1", help="Loopback only; use an SSH tunnel for remote GPUs")
    parser.add_argument("--forwarded-port", type=int, action="append", default=[],
                        help="Also accept this explicit localhost port in Host headers for an SSH tunnel; repeat for multiple tunnels")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--web-dir", type=Path, default=Path(__file__).resolve().parents[1] / "web/dist")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    if any(not 1 <= port <= 65535 for port in args.forwarded_port):
        parser.error("Forwarded ports must be between 1 and 65535.")
    args.data_dir = args.data_dir.expanduser().resolve()
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Two app instances must not overwrite the same JSON library.
    lockfile = open(args.data_dir / ".studio.lock", "a+b")
    lock_kind = None
    try:
        if os.name == "nt":
            import msvcrt
            if lockfile.tell() == 0:
                lockfile.write(b"\0")
                lockfile.flush()
            lockfile.seek(0)
            msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
            lock_kind = "windows"
        else:
            import fcntl
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_kind = "posix"
    except (ImportError, BlockingIOError, OSError):
        print("This Studio library is already open, or file locking is unavailable. Close the other instance before reopening.", file=sys.stderr)
        lockfile.close()
        return 1
    studio = Studio(args.data_dir, args.web_dir)
    try:
        server = StudioHTTPServer((args.host, args.port), studio, forwarded_ports=args.forwarded_port)
    except OSError as exc:
        studio.close()
        print(f"Studio could not bind {args.host}:{args.port}: {exc}. If the port is occupied, choose another port or close the existing Studio.", file=sys.stderr)
        return 1
    url = "http://127.0.0.1:" + str(server.server_address[1])
    stopping = threading.Event()

    def stop(*_):
        if not stopping.is_set():
            stopping.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("YuE Studio is ready at " + url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        studio.close()
        server.server_close()
        if lock_kind == "windows":
            lockfile.seek(0)
            msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
        elif lock_kind == "posix":
            fcntl.flock(lockfile, fcntl.LOCK_UN)
        lockfile.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
