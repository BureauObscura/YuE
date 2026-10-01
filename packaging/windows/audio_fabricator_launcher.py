"""Bureau Obscura Audio Fabricator desktop lifecycle owner."""
from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import datetime as dt
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


APP_NAME = "Bureau Obscura Audio Fabricator"
MUSIC_PORT = 55290
STABLE_PORT = 7860
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_SUSPENDED = 0x00000004
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
ERROR_ALREADY_EXISTS = 183


def application_home() -> Path:
    override = os.environ.get("BO_AUDIO_FABRICATOR_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_HOME = application_home()
_bundled_yue = APP_HOME / "engines" / "yue"
_bundled_stable = APP_HOME / "engines" / "stable-audio-3"
YUE_ROOT = Path(os.environ.get(
    "BO_AUDIO_YUE_ROOT",
    str(_bundled_yue if _bundled_yue.is_dir() else Path(r"C:\Bureau\YuE")),
)).expanduser().resolve()
STABLE_REPO_ROOT = Path(os.environ.get(
    "BO_AUDIO_STABLE_ROOT",
    str(_bundled_stable if _bundled_stable.is_dir() else Path(r"C:\Bureau\Tools\stable-audio-3")),
)).expanduser().resolve()
STABLE_ROOT = STABLE_REPO_ROOT / "optimized" / "tflite"
_portable_yue_python = APP_HOME / "runtimes" / "yue-python" / "python.exe"
_portable_stable_python = APP_HOME / "runtimes" / "stable-python" / "python.exe"
YUE_PYTHON = Path(os.environ.get(
    "BO_AUDIO_YUE_PYTHON",
    str(_portable_yue_python if _portable_yue_python.is_file() else YUE_ROOT / ".venv" / "Scripts" / "python.exe"),
)).expanduser().resolve()
STABLE_PYTHON = Path(os.environ.get(
    "BO_AUDIO_STABLE_PYTHON",
    str(_portable_stable_python if _portable_stable_python.is_file() else STABLE_ROOT / ".venv" / "Scripts" / "python.exe"),
)).expanduser().resolve()


class UserCancelled(RuntimeError):
    pass


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.SetInformationJobObject.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateJobObject.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
ntdll = ctypes.WinDLL("ntdll")
ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
ntdll.NtResumeProcess.restype = ctypes.c_long
user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def local_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Public\AppData\Local")) / APP_NAME


def write_log(log_file, message: str) -> None:
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    log_file.write(f"[launcher {timestamp}] {message}\r\n".encode("utf-8", errors="replace"))


def browser_session_profile(data: Path) -> Path:
    """Return an isolated Edge profile so the app process cannot be handed off."""
    sessions = data / "Browser Sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    profile = sessions / f"session-{stamp}-{uuid.uuid4().hex[:8]}"
    profile.mkdir()
    return profile


def process_image_name(process_id: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name.casefold()
    finally:
        kernel32.CloseHandle(handle)


def app_windows() -> dict[int, tuple[int, str]]:
    windows: dict[int, tuple[int, str]] = {}

    @WNDENUMPROC
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if APP_NAME.casefold() not in title.casefold():
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_image_name(int(process_id.value)) == "msedge.exe":
            windows[int(hwnd)] = (int(process_id.value), title)
        return True

    user32.EnumWindows(visit, 0)
    return windows


def wait_for_app_window(
    previous: set[int],
    process: subprocess.Popen[bytes],
    lifecycle: "Lifecycle",
    log_file,
    timeout: float = 20,
) -> int:
    deadline = time.monotonic() + timeout
    process_exit_logged = False
    while time.monotonic() < deadline:
        lifecycle.ensure_running()
        windows = app_windows()
        new_handles = [handle for handle in windows if handle not in previous]
        if new_handles:
            handle = new_handles[0]
            pid, title = windows[handle]
            write_log(log_file, f"Owning Edge window HWND {handle}, PID {pid}, title {title!r}")
            return handle
        # Edge may reuse a still-visible app window. The music origin is fixed, so
        # accepting it is safe and lets an old page reconnect after a restart.
        if windows and time.monotonic() > deadline - timeout + 3:
            handle = next(iter(windows))
            pid, title = windows[handle]
            write_log(log_file, f"Owning reused Edge window HWND {handle}, PID {pid}, title {title!r}")
            return handle
        if process.poll() is not None and not process_exit_logged:
            write_log(log_file, f"Edge starter PID {process.pid} exited with code {process.returncode}; waiting for its app window")
            process_exit_logged = True
        time.sleep(0.2)
    raise RuntimeError("Microsoft Edge did not open the Audio Fabricator app window.")


def show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)


def browser_path() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    found = shutil.which("msedge.exe")
    if found:
        candidates.append(Path(found))
    return next((path for path in candidates if path.is_file()), None)


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.35)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def create_kill_job() -> int:
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        handle,
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(handle)
        raise error
    return int(handle)


class Splash:
    def __init__(self) -> None:
        import tkinter as tk

        self.cancelled = False
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg="#050805")
        self.root.resizable(False, False)
        width, height = 470, 250
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self._cancel)
        tk.Label(self.root, text="◉", bg="#050805", fg="#7ee87e", font=("Consolas", 27)).pack(pady=(29, 3))
        tk.Label(self.root, text="BUREAU OBSCURA", bg="#050805", fg="#98e598", font=("Consolas", 18, "bold")).pack()
        tk.Label(self.root, text="A U D I O   F A B R I C A T O R", bg="#050805", fg="#6ba86b", font=("Consolas", 9)).pack(pady=(7, 28))
        self.status_label = tk.Label(self.root, text="Preparing local engines…", bg="#050805", fg="#7ee87e", font=("Consolas", 10))
        self.status_label.pack()
        self.root.update_idletasks()

    def _cancel(self) -> None:
        self.cancelled = True

    def status(self, message: str) -> None:
        self.status_label.configure(text=message)
        self.pump()

    def pump(self) -> None:
        if self.cancelled:
            raise UserCancelled()
        self.root.update()

    def close(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass


class Lifecycle:
    def __init__(self, log_file) -> None:
        self.log_file = log_file
        self.job = create_kill_job()
        self.processes: list[subprocess.Popen[bytes]] = []
        self.closed = False

    def start(self, command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self.log_file,
            stderr=self.log_file,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED,
        )
        if not kernel32.AssignProcessToJobObject(self.job, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error())
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
            raise RuntimeError(f"Could not attach a local engine to the shutdown group: {error}")
        status = ntdll.NtResumeProcess(int(process._handle))
        if status < 0:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass
            raise RuntimeError(f"Could not resume a local audio engine (NTSTATUS 0x{status & 0xffffffff:08x}).")
        self.processes.append(process)
        return process

    def ensure_running(self) -> None:
        for process in self.processes:
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"A local audio engine exited unexpectedly with code {code}.")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.job:
            kernel32.TerminateJobObject(self.job, 0)
            kernel32.CloseHandle(self.job)
            self.job = 0
        for process in self.processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    check=False,
                )


def wait_ready(url: str, process: subprocess.Popen[bytes], splash: Splash | None, timeout: float, identity: str | None = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"A local engine stopped during startup (exit code {process.returncode}).")
        if splash:
            splash.pump()
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                body = response.read(350_000)
                if response.status == 200 and (identity is None or identity.encode("utf-8") in body):
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}")


def validate_installation() -> tuple[Path, Path, Path, Path]:
    web = YUE_ROOT / "studio" / "web" / "dist"
    yue_server = YUE_ROOT / "studio" / "server" / "server.py"
    stable_server = STABLE_ROOT / "scripts" / "sa3_gradio.py"
    browser = browser_path()
    required = (
        YUE_PYTHON,
        web / "index.html",
        yue_server,
        YUE_ROOT / "models" / "YuE2-3B" / "model.safetensors",
        YUE_ROOT / "models" / "YuE2-Vae" / "model.safetensors",
        STABLE_PYTHON,
        stable_server,
        STABLE_ROOT / "models" / "tflite" / "sa3-sm-sfx" / "dit_fp32.tflite",
        STABLE_ROOT / "models" / "tflite" / "same-s" / "dec_fp32.tflite",
        STABLE_ROOT / "models" / "tflite" / "t5gemma" / "encoder_fp16.tflite",
        STABLE_ROOT / "models" / "tokenizer.model",
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("The local audio installation is incomplete:\n\n" + "\n".join(str(path) for path in missing))
    if browser is None:
        raise RuntimeError("Microsoft Edge is required for the desktop app window.")
    return web, yue_server, stable_server, browser


def write_self_test(path: Path, *, ok: bool, message: str, music_port: int | None = None) -> None:
    path.write_text(json.dumps({"ok": ok, "message": message, "music_port": music_port, "sound_port": STABLE_PORT}, indent=2), encoding="utf-8")


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    mutex = kernel32.CreateMutexW(None, False, r"Local\BureauObscuraAudioFabricator")
    if not mutex:
        show_error("Could not create the desktop-app lock.")
        return 1
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        show_error("Audio Fabricator is already running.")
        kernel32.CloseHandle(mutex)
        return 0

    self_test = "--self-test" in sys.argv
    data = local_data()
    logs = data / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    result_path = data / "self-test.json"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    log_path = logs / f"audio-fabricator-{stamp}-{uuid.uuid4().hex[:8]}.log"
    splash: Splash | None = None
    lifecycle: Lifecycle | None = None
    log_file = None
    try:
        web, yue_server, stable_server, browser = validate_installation()
        if port_open(MUSIC_PORT):
            raise RuntimeError(
                f"Music port {MUSIC_PORT} is already in use. Close the existing Audio Fabricator process, then open it again."
            )
        if port_open(STABLE_PORT):
            raise RuntimeError(
                "Sound port 7860 is already in use. Close the existing Stable Audio window or process, then open Audio Fabricator again."
            )
        if not self_test:
            splash = Splash()
        log_file = log_path.open("ab", buffering=0)
        lifecycle = Lifecycle(log_file)
        atexit.register(lifecycle.close)

        music_port = MUSIC_PORT
        music_url = f"http://127.0.0.1:{music_port}"
        environment = os.environ.copy()
        environment.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1", YUE_STUDIO_REPO=str(YUE_ROOT))
        environment.pop("PYTHONPATH", None)
        bundled_ffmpeg = APP_HOME / "tools" / "ffmpeg" / "bin"
        if bundled_ffmpeg.is_dir():
            environment["PATH"] = str(bundled_ffmpeg) + os.pathsep + environment.get("PATH", "")

        if splash:
            splash.status("Starting YuE music workspace…")
        music = lifecycle.start(
            [
                str(YUE_PYTHON), "-u", str(yue_server), "--host", "127.0.0.1", "--port", str(music_port),
                "--data-dir", str(Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Public\AppData\Local")) / "YuE Studio"),
                "--web-dir", str(web), "--no-open",
            ],
            YUE_ROOT,
            environment,
        )

        if splash:
            splash.status("Starting Stable Audio sound workspace…")
        sound = lifecycle.start(
            [
                str(STABLE_PYTHON), "-u", str(stable_server), "--dit", "sm-sfx", "--decoder", "same-s",
                "--precision", "fp32", "--default-seconds", "20", "--default-steps", "8", "--threads", "8",
                "--port", str(STABLE_PORT), "--no-share",
            ],
            STABLE_ROOT,
            environment,
        )

        if splash:
            splash.status("Checking music engine…")
        wait_ready(music_url + "/api/bootstrap", music, splash, 60)
        if splash:
            splash.status("Checking sound engine…")
        wait_ready(f"http://127.0.0.1:{STABLE_PORT}/config", sound, splash, 150, APP_NAME)
        lifecycle.ensure_running()

        if self_test:
            write_self_test(result_path, ok=True, message="Both local services became ready and were attached to the shutdown job.", music_port=music_port)
            time.sleep(2)
            return 0

        if splash:
            splash.status("Opening Audio Fabricator…")
        app_url = music_url + f"/?theme=dark&session={uuid.uuid4().hex[:8]}"
        # Chromium reuses a process that already owns the same user-data directory.
        # In that case Popen returns a short-lived handoff process; treating its exit
        # as the window closing shuts down both local APIs while the page is visible.
        # A unique session profile gives this launcher a real browser lifetime to own.
        profile = browser_session_profile(data)
        previous_windows = set(app_windows())
        write_log(log_file, f"Opening Edge app at {app_url} with isolated profile {profile}")
        app = subprocess.Popen(
            [
                str(browser), f"--app={app_url}", f"--user-data-dir={profile}", "--new-window",
                "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
                "--disable-sync", "--disable-features=msEdgeFirstRunExperience", "--start-maximized",
            ],
            cwd=str(data),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        write_log(log_file, f"Edge app process started with PID {app.pid}")
        app_window = wait_for_app_window(previous_windows, app, lifecycle, log_file)
        if splash:
            splash.close()
            splash = None
        while user32.IsWindow(wintypes.HWND(app_window)):
            lifecycle.ensure_running()
            time.sleep(0.5)
        write_log(log_file, f"Edge app window HWND {app_window} closed; stopping local engines")
        return 0
    except UserCancelled:
        return 0
    except Exception as error:
        if self_test:
            try:
                write_self_test(result_path, ok=False, message=str(error))
            except Exception:
                pass
        else:
            show_error(f"{error}\n\nDetails were written to:\n{log_path}")
        return 1
    finally:
        if splash:
            splash.close()
        if lifecycle:
            lifecycle.close()
        if log_file:
            log_file.close()
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    raise SystemExit(main())
