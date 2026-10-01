"""Atomic project storage. Draft changes never overwrite recorded takes."""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import struct
import sys
import threading
from datetime import datetime, timezone
import wave


ACTIVE = {"queued", "running"}
ID = re.compile(r"[a-f0-9]{32}\Z")
TEXT_LIMITS = {"title": 240, "artist": 240, "album": 240, "style": 6000,
               "lyrics": 60000, "abc": 120000, "cover_prompt": 12000,
               "edit_direction": 4000}
TARGET_DURATIONS = {30, 60, 90, 120, 180}
OPERATIONS = {"new", "remix", "extend"}


class StudioError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with open(temporary, "x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def decode_upload(data, limit):
    if not isinstance(data, str) or len(data) > ((limit + 2) // 3) * 4:
        raise StudioError("Upload exceeds the allowed size.", 413)
    try:
        result = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise StudioError("The upload is not valid base64.") from None
    if not result or len(result) > limit:
        raise StudioError("The uploaded file is empty or too large.", 413)
    return result


def validate_filename(name):
    if not isinstance(name, str) or not name or len(name) > 255 or name in {".", ".."} or any(
            c in name for c in ("/", "\\", "\0", "\r", "\n")):
        raise StudioError("Use a plain filename without directory components.")


def audio_type(data):
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE" and len(data) >= 44:
        # Checking the container also rejects a renamed text file with only a magic prefix.
        position, fmt, audio = 12, False, False
        while position + 8 <= len(data):
            kind, size = data[position:position + 4], int.from_bytes(data[position+4:position+8], "little")
            if position + 8 + size > len(data):
                raise StudioError("The WAV file is incomplete.")
            fmt |= kind == b"fmt " and size >= 16
            audio |= kind == b"data" and size > 0
            position += 8 + size + (size % 2)
        if not fmt or not audio:
            raise StudioError("The WAV file has no audio data.")
        return ".wav", "audio/wav"
    if data[:4] == b"fLaC" and len(data) > 42 and data[4] & 0x7f == 0 and data[5:8] == b"\0\0\x22":
        return ".flac", "audio/flac"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        size = int.from_bytes(data[:4], "big")
        if 16 <= size <= len(data) and any(brand in data[8:size] for brand in (b"M4A ", b"mp42", b"isom", b"M4B ")):
            return ".m4a", "audio/mp4"
    start = 0
    if data[:3] == b"ID3" and len(data) >= 10 and all(b < 128 for b in data[6:10]):
        start = 10 + sum(data[6+i] << (7 * (3-i)) for i in range(4))
        if data[5] & 0x10:
            start += 10
    # MPEG audio must contain a valid frame header, not merely an ID3 tag.
    for offset in range(start, min(start + 4096, len(data) - 3)):
        a, b, c = data[offset:offset+3]
        if a == 255 and b & 0xe0 == 0xe0 and (b >> 3) & 3 != 1 and (b >> 1) & 3 != 0 \
                and (c >> 4) not in {0, 15} and (c >> 2) & 3 != 3:
            return ".mp3", "audio/mpeg"
    raise StudioError("This is not a supported audio file. Use WAV, FLAC, MP3, or M4A.")


def image_type(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 45 and data[12:16] == b"IHDR" and b"IEND" in data[-16:]:
        width, height = struct.unpack(">II", data[16:24])
        if 0 < width <= 32768 and 0 < height <= 32768:
            return ".png", "image/png"
    if len(data) > 16 and data[:3] == b"\xff\xd8\xff" and data[-2:] == b"\xff\xd9":
        return ".jpg", "image/jpeg"
    if len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}:
        if int.from_bytes(data[4:8], "little") + 8 <= len(data):
            return ".webp", "image/webp"
    raise StudioError("This is not a supported cover image. Use PNG, JPEG, or WebP.")


def duration_seconds(data, ext):
    try:
        if ext == ".wav":
            with wave.open(io.BytesIO(data)) as audio:
                return round(audio.getnframes() / audio.getframerate(), 3)
        if ext == ".flac":
            value = int.from_bytes(data[18:26], "big")
            rate, samples = value >> 44, value & ((1 << 36) - 1)
            return round(samples / rate, 3) if rate else None
    except (wave.Error, EOFError, ZeroDivisionError):
        pass
    return None


class Store:
    def __init__(self, data_dir, repo_root=None):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifacts = self.root / "tracks"
        self.artifacts.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.path = self.root / "studio.json"
        repo = Path(repo_root or Path(__file__).resolve().parents[2])
        python = repo / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        fallback_python = Path(sys.executable)
        if os.name == "nt" and fallback_python.name.lower() == "pythonw.exe":
            fallback_python = fallback_python.with_name("python.exe")
        self.defaults = {"python_path": str(python if python.is_file() else fallback_python),
                         "device": "auto", "memory_budget_gib": 12 if sys.platform == "darwin" else 24,
                         "model": str(repo / "models/YuE2-3B") if (repo / "models/YuE2-3B").is_dir() else "m-a-p/YuE2-3B",
                         "vae": str(repo / "models/YuE2-Vae") if (repo / "models/YuE2-Vae").is_dir() else "m-a-p/YuE2-Vae",
                         "offline": True, "mode": "local", "remote_url": ""}
        self.remote_token = ""
        if self.path.is_file():
            try:
                self.state = json.loads(self.path.read_text())
                if self.state.get("version") != 1 or not isinstance(self.state.get("tracks"), dict):
                    raise ValueError("Unsupported data format")
                self.state["settings"] = {**self.defaults, **self.state.get("settings", {})}
                self.state["settings"].pop("remote_token", None)
                for tid, track in self.state["tracks"].items():
                    if not ID.fullmatch(tid) or track.get("id") != tid:
                        raise ValueError("Invalid saved track")
                    for take in track["takes"]:
                        if not ID.fullmatch(take["id"]):
                            raise ValueError("Invalid saved take")
                        if take["status"] in ACTIVE:
                            take.update(status="failed", stage="Interrupted", error="Studio stopped before this take finished. Generate a new take to retry.")
                    if track.get("cover_status") in {"queued", "running"}:
                        track.update(cover_status="failed", cover_error="Studio stopped during artwork generation. Try again.")
                    track.setdefault("instrumental", False)
                    track.setdefault("target_duration_seconds", None)
                    track.setdefault("operation", "new")
                    track.setdefault("reference_take_id", None)
                    track.setdefault("edit_direction", "")
            except (ValueError, TypeError, KeyError) as exc:
                raise RuntimeError(f"Cannot read Studio library at {self.path}. The original file was preserved: {exc}") from exc
        else:
            self.state = {"version": 1, "settings": dict(self.defaults), "tracks": {}}
        self.save()

    def save(self):
        with self.lock:
            atomic_json(self.path, self.state)

    def settings(self):
        with self.lock:
            return copy.deepcopy(self.state["settings"])

    def update_settings(self, fields):
        if not isinstance(fields, dict) or set(fields) - set(self.defaults) - {"remote_token"}:
            raise StudioError("Unknown settings fields.")
        with self.lock:
            if any(t["status"] in ACTIVE for track in self.state["tracks"].values() for t in track["takes"]):
                raise StudioError("Finish or cancel queued music jobs before changing the engine.", 409)
            value = {**self.state["settings"], **{k: v for k, v in fields.items() if k != "remote_token"}}
            for key in ("python_path", "model", "vae", "remote_url"):
                if not isinstance(value[key], str) or len(value[key]) > 4096 or "\0" in value[key]:
                    raise StudioError(f"Invalid {key}.")
            if not Path(value["python_path"]).expanduser().is_absolute():
                raise StudioError("Python path must be an absolute path to an interpreter.")
            if value["device"] not in {"auto", "cpu", "mps", "cuda"}:
                raise StudioError("Device must be auto, cpu, mps, or cuda.")
            if value["mode"] not in {"local", "remote"} or type(value["offline"]) is not bool:
                raise StudioError("Invalid engine mode or offline setting.")
            if not value["offline"]:
                raise StudioError("Studio uses pre-downloaded model files only. Download weights separately, then select their folders; automatic downloads are not enabled.")
            budget = value["memory_budget_gib"]
            if type(budget) not in (int, float) or not math.isfinite(budget) or not 4 <= budget <= 256:
                raise StudioError("Memory budget must be between 4 and 256 GiB.")
            if not value["model"].strip() or not value["vae"].strip():
                raise StudioError("Model and decoder locations are required.")
            token = fields.get("remote_token", self.remote_token)
            if not isinstance(token, str) or len(token) > 8192:
                raise StudioError("Invalid remote token.")
            self.remote_token = token
            self.state["settings"] = value
            self.save()
            return self.settings()

    def _track(self, track_id):
        if not ID.fullmatch(track_id) or track_id not in self.state["tracks"]:
            raise StudioError("Track not found.", 404)
        return self.state["tracks"][track_id]

    def _take(self, track, take_id):
        for take in track["takes"]:
            if take["id"] == take_id:
                return take
        raise StudioError("Take not found.", 404)

    def public(self, track):
        result = {k: copy.deepcopy(v) for k, v in track.items() if not k.startswith("_")}
        result["takes"] = [{k: copy.deepcopy(v) for k, v in t.items() if not k.startswith("_")} for t in track["takes"]]
        return result

    def tracks(self):
        with self.lock:
            return [self.public(t) for t in sorted(self.state["tracks"].values(), key=lambda t: t["updated_at"], reverse=True)]

    def track(self, track_id):
        with self.lock:
            return self.public(self._track(track_id))

    def _validate_draft(self, fields, track):
        extra = {"cot", "seed", "favorite", "selected_take_id", "instrumental",
                 "target_duration_seconds", "operation", "reference_take_id"}
        if not isinstance(fields, dict) or set(fields) - set(TEXT_LIMITS) - extra:
            raise StudioError("Unknown or immutable track fields.")
        result = dict(fields)
        for key, limit in TEXT_LIMITS.items():
            if key in result and (not isinstance(result[key], str) or len(result[key]) > limit or "\0" in result[key]):
                raise StudioError(f"{key.replace('_', ' ').capitalize()} must be text of at most {limit:,} characters.")
        if "cot" in result and result["cot"] not in {"full", "melody", "off"}:
            raise StudioError("Score mode must be full, melody, or off.")
        if "seed" in result and result["seed"] is not None and (type(result["seed"]) is not int or not 0 <= result["seed"] < 2**53):
            raise StudioError("Seed must be a nonnegative integer below 2^53, or empty for random.")
        if "favorite" in result and type(result["favorite"]) is not bool:
            raise StudioError("Favorite must be true or false.")
        if "instrumental" in result and type(result["instrumental"]) is not bool:
            raise StudioError("Instrumental must be true or false.")
        if "target_duration_seconds" in result and result["target_duration_seconds"] not in TARGET_DURATIONS | {None}:
            raise StudioError("Choose an approximate duration of 30, 60, 90, 120, or 180 seconds, or Auto.")
        if "operation" in result and result["operation"] not in OPERATIONS:
            raise StudioError("Generation mode must be new, remix, or extend.")
        if result.get("reference_take_id") is not None:
            self._take(track, result["reference_take_id"])
        if result.get("selected_take_id") is not None:
            self._take(track, result["selected_take_id"])
        return result

    def create(self, fields):
        with self.lock:
            track_id, stamp = secrets.token_hex(16), now()
            track = {"id": track_id, "title": "Untitled track", "artist": "", "album": "", "style": "", "lyrics": "",
                      "cot": "full", "seed": None, "abc": "", "cover_prompt": "", "cover_url": None,
                      "cover_status": "empty", "cover_error": None, "favorite": False, "created_at": stamp,
                      "updated_at": stamp, "selected_take_id": None, "takes": [], "instrumental": False,
                      "target_duration_seconds": None, "operation": "new", "reference_take_id": None,
                      "edit_direction": ""}
            track.update(self._validate_draft(fields, track))
            self.state["tracks"][track_id] = track
            self.save()
            return self.public(track)

    def update(self, track_id, fields):
        with self.lock:
            track = self._track(track_id)
            track.update(self._validate_draft(fields, track))
            track["updated_at"] = now()
            self.save()
            return self.public(track)

    def delete(self, track_id):
        with self.lock:
            track = self._track(track_id)
            if any(t["status"] in ACTIVE for t in track["takes"]) or track["cover_status"] in {"queued", "running"}:
                raise StudioError("Cancel or finish active jobs before deleting this track.", 409)
            del self.state["tracks"][track_id]
            self.save()
            folder = self.artifacts / track_id
            if folder.exists():
                shutil.rmtree(folder)

    def take_dir(self, track_id, take_id):
        if not ID.fullmatch(track_id) or not ID.fullmatch(take_id):
            raise StudioError("Invalid artifact path.")
        path = self.artifacts / track_id / "takes" / take_id
        if not path.resolve().is_relative_to(self.artifacts):
            raise StudioError("Invalid artifact path.")
        return path

    def take_score(self, track_id, take_id):
        with self.lock:
            self._take(self._track(track_id), take_id)
            path = self.take_dir(track_id, take_id) / "artifacts" / "score.abc"
            if path.is_symlink() or not path.is_file():
                raise StudioError("This reference has no YuE score. Import or paste an ABC score before remixing it.", 409)
            text = path.read_text(encoding="utf-8")
            if not text.strip() or len(text) > TEXT_LIMITS["abc"]:
                raise StudioError("The saved reference score is unavailable or invalid.", 409)
            return text

    def new_take(self, track_id, status="queued", imported=False):
        with self.lock:
            track = self._track(track_id)
            request = {k: track[k] for k in ("style", "lyrics", "cot", "seed", "abc")}
            if not imported:
                instrumental = track["instrumental"]
                operation = track["operation"]
                if not request["style"].strip() or (not instrumental and not request["lyrics"].strip()):
                    raise StudioError("Add a musical style and lyrics before generating, or enable Instrumental / no vocals.")
                if instrumental and request["cot"] == "off":
                    raise StudioError("Instrumental mode needs Melody or Melody & chords planning so Studio can remove the vocal voice.")
                if request["cot"] == "off" and request["abc"].strip():
                    raise StudioError("Choose a score mode to use your ABC score, or clear the score.")
                reference = None
                source_score = None
                if operation != "new":
                    if not track["reference_take_id"]:
                        raise StudioError("Choose a completed local recording as the remix reference.")
                    reference = self._take(track, track["reference_take_id"])
                    if reference["status"] not in {"complete", "needs_review"} or not reference.get("_audio"):
                        raise StudioError("The remix reference must be a completed local recording.", 409)
                    score_path = self.take_dir(track_id, reference["id"]) / "artifacts" / "score.abc"
                    if score_path.is_file() and not score_path.is_symlink():
                        source_score = score_path.read_text(encoding="utf-8")
                    if operation == "remix" and not request["abc"].strip() and source_score:
                        request["abc"] = source_score
                    if not request["abc"].strip():
                        raise StudioError("Raw audio is stored locally, but YuE2 cannot condition on it directly. Import or paste its ABC score to remix it.", 409)
                    if operation == "extend" and source_score and request["abc"].strip() == source_score.strip():
                        raise StudioError("Extend the reference score in the Score tab before generating. YuE2 cannot continue directly from audio.", 409)
                    if request["cot"] == "off":
                        raise StudioError("Score-guided remix and extension require Melody or Melody & chords planning.")
                # A saved remix note must not silently change a later, unrelated
                # composition after the user switches the mode back to New.
                direction = track["edit_direction"].strip() if operation != "new" else ""
                additions = []
                if instrumental:
                    additions.append("Instrumental only: no singing, spoken word, vocal chops, choir, or other vocal sounds.")
                    if not request["lyrics"].strip():
                        request["lyrics"] = "[Intro]\n\n[Verse]\n\n[Outro]\n"
                if track["target_duration_seconds"]:
                    additions.append(f"Aim for a complete form with a natural ending near {track['target_duration_seconds']} seconds.")
                if operation == "remix":
                    additions.append("Render a score-conditioned remix of the supplied composition.")
                elif operation == "extend":
                    additions.append("Render the supplied user-extended score as one complete recording.")
                if direction:
                    additions.append("Edit direction: " + direction)
                if additions:
                    request["style"] = request["style"].rstrip() + "\n" + " ".join(additions)
                studio = {"instrumental": instrumental, "target_duration_seconds": track["target_duration_seconds"],
                          "operation": operation, "edit_direction": direction, "reference_take_id": track["reference_take_id"]}
                if reference:
                    studio["reference"] = {"take_id": reference["id"], "audio_sha256": reference.get("_sha256"),
                                           "duration": reference.get("duration"), "source": reference.get("_source")}
                request["_studio"] = studio
            request["abc"] = request["abc"] if request["abc"].strip() else None
            request["seed"] = request["seed"] if request["seed"] is not None else secrets.randbelow(2**32)
            take_id = secrets.token_hex(16)
            request["id"] = take_id
            take = {"id": take_id, "status": status, "stage": "Imported" if imported else "Waiting in queue",
                    "created_at": now(), "duration": None, "audio_url": None, "error": None, "truncated": False,
                    "_request": request, "_settings": self.settings(), "_source": "import" if imported else "yue2",
                    "_metadata": {k: track[k] for k in ("title", "artist", "album")}}
            folder = self.take_dir(track_id, take_id)
            folder.mkdir(parents=True, mode=0o700)
            atomic_json(folder / "studio-request.json", request)
            track["takes"].append(take)
            track["selected_take_id"] = take_id
            track["updated_at"] = now()
            self.save()
            return copy.deepcopy(take)

    def take_internal(self, track_id, take_id):
        with self.lock:
            return copy.deepcopy(self._take(self._track(track_id), take_id))

    def update_take(self, track_id, take_id, **fields):
        with self.lock:
            track = self._track(track_id)
            take = self._take(track, take_id)
            take.update(fields)
            track["updated_at"] = now()
            self.save()
            return self.public(track)

    def import_audio(self, track_id, payload):
        validate_filename(payload.get("filename"))
        data = decode_upload(payload.get("data"), 80 * 1024 * 1024)
        ext, mime = audio_type(data)
        with self.lock:
            take = self.new_take(track_id, "complete", imported=True)
            path = self.take_dir(track_id, take["id"]) / ("original" + ext)
            try:
                with open(path, "xb") as stream:
                    stream.write(data)
                return self.update_take(track_id, take["id"], audio_url=self.media_url(path),
                                        duration=duration_seconds(data, ext), _audio=path.relative_to(self.artifacts).as_posix(),
                                        _mime=mime, _sha256=hashlib.sha256(data).hexdigest())
            except OSError:
                self.update_take(track_id, take["id"], status="failed", stage="Import failed", error="Unable to save imported audio.")
                raise

    def media_url(self, path):
        return "/media/" + path.relative_to(self.artifacts).as_posix()

    def put_cover(self, track_id, data):
        ext, mime = image_type(data)
        with self.lock:
            track = self._track(track_id)
            folder = self.artifacts / track_id / "covers"
            if folder.is_symlink() or not folder.resolve().is_relative_to(self.artifacts):
                raise StudioError("Invalid artwork storage path.")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / (secrets.token_hex(16) + ext)
            with open(path, "xb") as stream:
                stream.write(data)
            track.update(cover_url=self.media_url(path), cover_status="complete", cover_error=None,
                         _cover=path.relative_to(self.artifacts).as_posix(), _cover_mime=mime, _cover_metadata=None, updated_at=now())
            self.save()
            return self.public(track)

    def import_cover(self, track_id, payload):
        validate_filename(payload.get("filename"))
        return self.put_cover(track_id, decode_upload(payload.get("data"), 12 * 1024 * 1024))

    def set_cover_state(self, track_id, status, error=None, prompt=None):
        with self.lock:
            track = self._track(track_id)
            track.update(cover_status=status, cover_error=error, updated_at=now())
            if prompt is not None:
                track["cover_prompt"] = prompt
            self.save()
            return self.public(track)

    def media_path(self, relative):
        with self.lock:
            allowed = {}
            for track in self.state["tracks"].values():
                if track.get("_cover"):
                    allowed[track["_cover"]] = track["_cover_mime"]
                for take in track["takes"]:
                    if take.get("_audio"):
                        allowed[take["_audio"]] = take["_mime"]
            if relative not in allowed:
                raise StudioError("Asset not found.", 404)
            path = self.artifacts / relative
            if path.is_symlink() or not path.resolve().is_relative_to(self.artifacts) or not path.is_file():
                raise StudioError("Asset not found.", 404)
            return path, allowed[relative]
