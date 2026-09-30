"""Targeted persistence, queue, upload, export, and localhost security checks.

Run with: python3 -m unittest discover -s studio/tests -p 'test_*.py'
No model imports, model downloads, or paid provider calls occur.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
import zipfile

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))
from server import Studio, StudioHTTPServer, default_data_dir
from store import Store, StudioError, audio_type, image_type, decode_upload
from jobs import JobManager, remote_url
from worker import cached_model


def wav_bytes():
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x01" * 800)
    return data.getvalue()


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


class FakeJobs:
    def __init__(self, *_):
        pass

    def engine(self, refresh=False):
        return {"ready": False, "status": "setup_needed", "message": "No model installed", "device": "auto",
                "python_path": sys.executable, "model_cached": False, "runtime_available": False}

    def close(self):
        pass


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows defaults")
    def test_windows_defaults_use_local_app_data_and_venv(self):
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "Local"
            repo = Path(temp) / "repo"
            interpreter = repo / ".venv" / "Scripts" / "python.exe"
            interpreter.parent.mkdir(parents=True)
            interpreter.touch()
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                self.assertEqual(default_data_dir(), local / "YuE Studio")
            store = Store(Path(temp) / "library", repo)
            self.assertEqual(Path(store.settings()["python_path"]), interpreter)

    def test_draft_persists_and_requests_are_frozen(self):
        track = self.store.create({"title": "First", "style": "quiet piano", "lyrics": "Original words", "seed": 12})
        take = self.store.new_take(track["id"])
        self.store.update(track["id"], {"lyrics": "Revised words"})
        frozen = self.store.take_internal(track["id"], take["id"])
        self.assertEqual(frozen["_request"]["lyrics"], "Original words")
        restarted = Store(self.tmp.name)
        saved = restarted.track(track["id"])
        self.assertEqual(saved["lyrics"], "Revised words")
        self.assertEqual(saved["takes"][0]["status"], "failed")
        self.assertIn("Studio stopped", saved["takes"][0]["error"])

    def test_audio_import_signature_and_original_hash(self):
        track = self.store.create({})
        data = wav_bytes()
        result = self.store.import_audio(track["id"], {"filename": "recording.wav", "data": base64.b64encode(data).decode()})
        take = self.store.take_internal(track["id"], result["selected_take_id"])
        path, mime = self.store.media_path(take["_audio"])
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(take["_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(take["duration"], .1)
        self.assertEqual(mime, "audio/wav")

    def test_bad_filenames_and_signatures_do_not_create_takes(self):
        track = self.store.create({})
        for filename, data in (("../../bad.wav", wav_bytes()), ("bad.wav", b"text pretending to be a WAV"),
                               ("bad.mp3", b"ID3" + b"\0" * 100)):
            with self.assertRaises(StudioError):
                self.store.import_audio(track["id"], {"filename": filename, "data": base64.b64encode(data).decode()})
        self.assertEqual(self.store.track(track["id"])["takes"], [])
        with self.assertRaises(StudioError):
            decode_upload("data:audio/wav;base64,xxx", 100)
        with self.assertRaises(StudioError):
            decode_upload(base64.b64encode(b"12345").decode(), 4)

    def test_cover_replacement_keeps_original_file_and_rejects_svg(self):
        track = self.store.create({})
        first = self.store.put_cover(track["id"], PNG)
        old = self.store.artifacts / first["cover_url"].removeprefix("/media/")
        self.store._track(track["id"])["_cover_metadata"] = {"model": "old-model", "prompt": "old-prompt"}
        second = self.store.put_cover(track["id"], PNG)
        self.assertNotEqual(first["cover_url"], second["cover_url"])
        self.assertTrue(old.is_file())
        self.assertIsNone(self.store._track(track["id"])["_cover_metadata"])
        with self.assertRaises(StudioError):
            self.store.put_cover(track["id"], b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')

    def test_paths_and_immutable_fields_rejected(self):
        track = self.store.create({})
        for fields in ({"id": "../bad"}, {"takes": []}, {"seed": float("nan")}, {"seed": True}, {"selected_take_id": "missing"}):
            with self.assertRaises(StudioError):
                self.store.update(track["id"], fields)
        with self.assertRaises(StudioError):
            self.store.media_path("../../studio.json")
        with self.assertRaises(StudioError):
            self.store.take_dir(track["id"], "../bad")

    def test_settings_never_persist_token(self):
        self.store.update_settings({"remote_token": "test-secret", "device": "mps"})
        self.assertNotIn("test-secret", self.store.path.read_text())
        self.assertNotIn("remote_token", self.store.settings())
        self.assertEqual(self.store.remote_token, "test-secret")
        with self.assertRaisesRegex(StudioError, "pre-downloaded"):
            self.store.update_settings({"offline": False})

    def test_active_track_cannot_be_deleted(self):
        track = self.store.create({"style": "piano", "lyrics": "hello"})
        self.store.new_take(track["id"])
        with self.assertRaises(StudioError) as error:
            self.store.delete(track["id"])
        self.assertEqual(error.exception.status, 409)

    def test_local_cache_requires_all_weight_shards_and_tokenizer(self):
        path = Path(self.tmp.name) / "model"
        path.mkdir()
        (path / "config.json").write_text('{"model_type":"yue2"}')
        (path / "qwen.tiktoken").write_text("fake tokenizer")
        (path / "model.safetensors.index.json").write_text('{"weight_map":{"a":"first.safetensors","b":"second.safetensors"}}')
        (path / "first.safetensors").write_bytes(b"a" * 20)
        self.assertIsNone(cached_model(str(path), tokenizer=True))
        (path / "second.safetensors").write_bytes(b"b" * 20)
        self.assertEqual(cached_model(str(path), tokenizer=True), path.resolve())


class QueueTests(unittest.TestCase):
    def test_owned_worker_failure_and_running_cancellation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "data")
            track = store.create({"style": "piano", "lyrics": "hello"})
            fake = Path(temp) / "fake_worker.py"
            fake.write_text('import json\nprint(json.dumps({"stage":"Planning score"}),flush=True)\n'
                            'print(json.dumps({"status":"failed","error":"Simulated memory exhaustion"}),flush=True)\n'
                            'raise SystemExit(1)\n')
            manager = JobManager(store, SERVER_DIR.parents[1])
            manager.worker = fake
            manager.engine = lambda *a, **kw: {"ready": True}
            try:
                failed_id = manager.enqueue(track["id"])["selected_take_id"]
                manager.queue.join()
                failed = store.take_internal(track["id"], failed_id)
                self.assertEqual(failed["status"], "failed")
                self.assertEqual(failed["error"], "Simulated memory exhaustion")
                self.assertIsNone(failed["audio_url"])
                fake.write_text('import json,time\nprint(json.dumps({"stage":"Generating song"}),flush=True)\ntime.sleep(30)\n')
                active_id = manager.enqueue(track["id"])["selected_take_id"]
                deadline = time.monotonic() + 3
                while manager.process is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertIsNotNone(manager.process)
                process = manager.process
                manager.cancel(track["id"], active_id)
                process.wait(timeout=5)
                manager.queue.join()
                self.assertEqual(store.take_internal(track["id"], active_id)["status"], "cancelled")
                self.assertIsNotNone(process.returncode)
            finally:
                manager.close()

    def test_single_worker_queued_cancel_and_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            track = store.create({"style": "piano", "lyrics": "hello"})
            entered, release = threading.Event(), threading.Event()
            visited = []

            def runner(tid, take_id):
                visited.append(take_id)
                entered.set()
                release.wait(timeout=3)
                store.update_take(tid, take_id, status="complete", stage="Complete")

            manager = JobManager(store, SERVER_DIR.parents[1], runner=runner)
            manager.engine = lambda *args, **kwargs: {"ready": True}
            try:
                first = manager.enqueue(track["id"])["selected_take_id"]
                self.assertTrue(entered.wait(timeout=2))
                second = manager.enqueue(track["id"])["selected_take_id"]
                manager.cancel(track["id"], second)
                with self.assertRaises(StudioError):
                    store.update_settings({"device": "mps"})
                release.set()
                manager.queue.join()
                takes = store.track(track["id"])["takes"]
                self.assertEqual(visited, [first])
                self.assertEqual([t["status"] for t in takes], ["complete", "cancelled"])
            finally:
                release.set()
                manager.close()

    def test_unconfigured_engine_creates_no_take(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            track = store.create({"style": "piano", "lyrics": "hello"})
            manager = JobManager(store, SERVER_DIR.parents[1])
            manager.engine = lambda *a, **kw: {"ready": False, "message": "Install weights first"}
            try:
                with self.assertRaises(StudioError) as error:
                    manager.enqueue(track["id"])
                self.assertEqual(error.exception.status, 409)
                self.assertEqual(store.track(track["id"])["takes"], [])
            finally:
                manager.close()

    def test_remote_url_only_accepts_loopback_tunnels(self):
        self.assertEqual(remote_url("http://127.0.0.1:8767/"), "http://127.0.0.1:8767")
        for value in ("https://example.com", "http://localhost.evil:22", "http://user:pass@localhost", "file:///tmp/foo", "http://localhost:80/path"):
            with self.assertRaises(StudioError):
                remote_url(value)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        web = Path(self.tmp.name) / "web"
        web.mkdir()
        (web / "index.html").write_text("<html>Studio test</html>")
        self.studio = Studio(Path(self.tmp.name) / "data", web, jobs_factory=FakeJobs)
        self.server = StudioHTTPServer(("127.0.0.1", 0), self.studio)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = "127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.studio.close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        hs = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, payload, hs)
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, data

    def test_bootstrap_and_write_token(self):
        status, headers, data = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        token = json.loads(data)["csrf"]
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("POST", "/api/tracks", {})[0], 403)
        result = self.request("POST", "/api/tracks", {"title": "Hello"}, {"X-Studio-Token": token})
        self.assertEqual(result[0], 201)
        self.assertEqual(json.loads(result[2])["track"]["title"], "Hello")

    def test_host_origin_and_path_attacks_blocked(self):
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("GET", "/api/bootstrap", headers=headers)[0], 403)
        self.assertEqual(self.request("GET", "/media/%2e%2e/studio.json")[0], 400)
        self.assertEqual(self.request("GET", "/assets/missing.js")[0], 404)

    def test_forwarded_port_requires_explicit_allowlist_and_matching_origin(self):
        forwarded = "127.0.0.1:18767"
        self.assertEqual(self.request("GET", "/api/bootstrap", headers={"Host": forwarded})[0], 403)
        self.server.allowed_ports.add(18767)
        self.assertEqual(self.request("GET", "/api/bootstrap", headers={"Host": forwarded, "Origin": "http://" + forwarded})[0], 200)
        self.assertEqual(self.request("GET", "/api/bootstrap", headers={"Host": "evil.example:18767"})[0], 403)
        self.assertEqual(self.request("GET", "/api/bootstrap", headers={"Host": forwarded, "Origin": "http://localhost:18767"})[0], 403)

    def test_real_audio_range_and_invalid_range(self):
        track = self.studio.store.create({})
        track = self.studio.store.import_audio(track["id"], {"filename": "sample.wav", "data": base64.b64encode(wav_bytes()).decode()})
        url = track["takes"][0]["audio_url"]
        status, headers, data = self.request("GET", url, headers={"Range": "bytes=0-11"})
        self.assertEqual(status, 206)
        self.assertEqual(data, wav_bytes()[:12])
        self.assertTrue(headers["Content-Range"].startswith("bytes 0-11/"))
        self.assertEqual(self.request("GET", url, headers={"Range": "bytes=999999-"})[0], 416)
        self.assertEqual(self.request("GET", url, headers={"Range": "bytes=0-1,5-6"})[0], 416)
        self.assertEqual(self.request("GET", url, headers={"Range": "bytes=-10"})[2], wav_bytes()[-10:])

    def test_export_uses_selected_take_original_and_frozen_lyrics(self):
        track = self.studio.store.create({"title": "First title", "lyrics": "Recorded words"})
        track = self.studio.store.import_audio(track["id"], {"filename": "sample.wav", "data": base64.b64encode(wav_bytes()).decode()})
        self.studio.store.put_cover(track["id"], PNG)
        self.studio.store.update(track["id"], {"lyrics": "New draft lyrics"})
        status, headers, data = self.request("GET", "/api/tracks/" + track["id"] + "/export")
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.read("originals/audio.wav"), wav_bytes())
            self.assertEqual(archive.read("lyrics.txt").decode(), "Recorded words")
            self.assertEqual(archive.read("cover.png"), PNG)
            metadata = json.loads(archive.read("metadata.json"))
            self.assertEqual(metadata["original_sha256"], hashlib.sha256(wav_bytes()).hexdigest())
            self.assertFalse(metadata["artwork_embedded_in_delivery_copy"])
        self.assertEqual(list(self.studio.store.root.glob("yue-export-*.zip")), [])

    def test_artwork_independent_and_key_never_saved(self):
        key = "private-test-key"
        entered, release = threading.Event(), threading.Event()

        def fake_artwork(prompt, api_key, cancelled=None):
            self.assertEqual(api_key, key)
            entered.set()
            release.wait(timeout=3)
            return PNG, "image/png", {"provider": "test", "prompt": prompt, "untrusted_key": api_key}

        self.studio.artwork_generator = fake_artwork
        track = self.studio.store.create({})
        status, _, _ = self.request("POST", f"/api/tracks/{track['id']}/artwork", {"prompt": "A gray room", "api_key": key}, {"X-Studio-Token": self.studio.csrf})
        self.assertEqual(status, 202)
        self.assertTrue(entered.wait(timeout=2))
        self.assertEqual(self.studio.store.track(track["id"])["cover_status"], "running")
        release.set()
        deadline = time.monotonic() + 3
        while track["id"] in self.studio.artwork_jobs and time.monotonic() < deadline:
            time.sleep(.01)
        saved = self.studio.store.track(track["id"])
        self.assertEqual(saved["cover_status"], "complete")
        self.assertEqual(saved["takes"], [])
        for path in self.studio.store.root.rglob("*.json"):
            self.assertNotIn(key, path.read_text())


if __name__ == "__main__":
    unittest.main()
