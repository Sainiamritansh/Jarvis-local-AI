"""Config-driven local desktop modes.  Modes never use browser automation."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse
import ctypes

import app_launcher

CONFIG_PATH = Path(__file__).with_name("modes.json")
STATE_PATH = Path(__file__).with_name("modes_state.json")
_active_modes = set()
_mode_windows = {}
_mode_already_open = {}
_chatgpt_appid = None
_chatgpt_looked_up = False

WM_CLOSE = 0x0010
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080


def _list_windows():
    """Return eligible top-level windows as dictionaries; empty off Windows."""
    if os.name != "nt":
        return []
    windows = []
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        pid = ctypes.c_ulong()
        kernel32.GetLastError()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.append({"hwnd": int(hwnd), "pid": pid.value, "title": title.value})
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return windows


def _window_exists(hwnd):
    return bool(os.name == "nt" and ctypes.windll.user32.IsWindow(hwnd))


def _window_pid(hwnd):
    if os.name != "nt":
        return None
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _close_window(hwnd):
    if os.name == "nt":
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _mode_key(name):
    return _normalize(name)


def _save_state():
    payload = {
        "active_modes": sorted(_active_modes),
        "windows": _mode_windows,
        "already_open": _mode_already_open,
    }
    try:
        STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")
        print(f"[modes] state saved: {sorted(_active_modes)}")
    except OSError:
        print("[modes] state save failed")


def _load_state():
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid state")
        active = {_mode_key(name) for name in payload.get("active_modes", []) if isinstance(name, str)}
        saved_windows = payload.get("windows", {})
        saved_already = payload.get("already_open", {})
        if not isinstance(saved_windows, dict) or not isinstance(saved_already, dict):
            raise ValueError("invalid state")
        _active_modes.clear()
        _mode_windows.clear()
        _mode_already_open.clear()
        for name in active:
            records = []
            for record in saved_windows.get(name, []):
                if not isinstance(record, dict):
                    continue
                hwnd, pid = record.get("hwnd"), record.get("pid")
                if isinstance(hwnd, int) and isinstance(pid, int) and _window_exists(hwnd) and _window_pid(hwnd) == pid:
                    records.append(record)
            _active_modes.add(name)
            _mode_windows[name] = records
            _mode_already_open[name] = [label for label in saved_already.get(name, []) if isinstance(label, str)]
        print(f"[modes] state loaded: {sorted(_active_modes)}")
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        print("[modes] state loaded: []")


def _record_new_windows(snapshot, expected_pid, label):
    """Collect windows born during this action, waiting briefly for them to settle."""
    before = {item["hwnd"] for item in snapshot}
    deadline, latest, stable_since = time.monotonic() + 6, [], None
    while time.monotonic() < deadline:
        fresh = [item for item in _list_windows() if item["hwnd"] not in before]
        matching = [item for item in fresh if expected_pid and item["pid"] == expected_pid]
        current = matching or fresh
        if current:
            identifiers = [(item["hwnd"], item["pid"]) for item in current]
            if identifiers != [(item["hwnd"], item["pid"]) for item in latest]:
                latest, stable_since = current, time.monotonic()
            elif time.monotonic() - stable_since >= 1:
                break
        time.sleep(0.25)
    return [{**item, "action_label": label} for item in latest]


def _load_config():
    try:
        with CONFIG_PATH.open(encoding="utf-8") as source:
            config = json.load(source)
        if not isinstance(config, dict):
            raise ValueError("root is not an object")
        return config, None
    except FileNotFoundError:
        return {}, "I couldn't find the modes configuration."
    except (OSError, ValueError, json.JSONDecodeError):
        return {}, "The modes configuration is invalid."


def _mode_entries(config):
    return {name: spec for name, spec in config.items() if name != "settings" and isinstance(spec, dict)}


def _normalize(value):
    return " ".join(value.lower().split())


_load_state()


def _find_mode(text, config):
    request = _normalize(text)
    request = _normalize(re.sub(r"^(?:open|start|turn on)\s+", "", request))
    for name, spec in _mode_entries(config).items():
        names = [name, *spec.get("aliases", [])]
        if any(request == _normalize(candidate) for candidate in names if isinstance(candidate, str)):
            return name, spec
    return None, None


def is_mode_command(text):
    config, error = _load_config()
    if error:
        return bool(re.search(r"\bmode(?:s)?\b", text))
    normalized = _normalize(text)
    if normalized in {"list modes", "what modes do i have"}:
        return True
    if re.match(r"^(?:turn off|end|disable)\s+.+", normalized):
        return True
    name, _spec = _find_mode(normalized, config)
    return name is not None or bool(re.match(r"^(?:open|start|turn on)\s+.+\s+mode$", normalized))


def _chrome_path(settings):
    configured = settings.get("chrome_path", "") if isinstance(settings, dict) else ""
    candidates = [configured] if isinstance(configured, str) and os.path.isfile(configured) else []
    if app_launcher.winreg is not None:
        path = app_launcher._app_path("chrome.exe")
        if path:
            candidates.append(path)
    which = shutil.which("chrome")
    if which:
        candidates.append(which)
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")):
        candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return next((candidate for candidate in candidates if candidate and os.path.isfile(candidate)), None)


def _exe_in_folder(folder, value):
    if not os.path.isdir(folder):
        return None
    wanted = f"{value}.exe".lower()
    files = [entry for entry in os.listdir(folder) if entry.lower().endswith(".exe")]
    exact = next((entry for entry in files if entry.lower() == wanted), None)
    matching = exact or next((entry for entry in files if value.lower() in entry.lower()), None)
    return os.path.join(folder, matching) if matching else None


def _chatgpt_id():
    global _chatgpt_appid, _chatgpt_looked_up
    if not _chatgpt_looked_up:
        _chatgpt_looked_up = True
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-StartApps | Where-Object Name -like '*ChatGPT*' | Select-Object -First 1 -ExpandProperty AppID"],
                capture_output=True, text=True, timeout=10,
            )
            _chatgpt_appid = result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            _chatgpt_appid = None
    return _chatgpt_appid


def _launch_action(action, settings):
    kind, value = action.get("type"), action.get("value")
    if not value:
        return None, None, None
    if kind == "url":
        urls = value if isinstance(value, list) else [value]
        if not urls or not all(isinstance(url, str) and urlparse(url).scheme in {"http", "https"} for url in urls):
            return None, f"I couldn't open {value}.", None
        chrome = _chrome_path(settings)
        if not chrome:
            return None, "I couldn't find Google Chrome.", None
        process = subprocess.Popen([chrome, "--new-window", *urls], shell=False)
        label = "Claude" if any("claude.ai" in url for url in urls) else urls[0]
        return label, None, getattr(process, "pid", None)
    if kind == "folder":
        if not os.path.isdir(value):
            return None, f"I couldn't find folder {value}.", None
        os.startfile(value)
        return "your project folder", None, None
    if kind == "file":
        if not os.path.isfile(value):
            return None, f"I couldn't find file {value}.", None
        os.startfile(value)
        return os.path.basename(value), None, None
    if kind != "app":
        return None, f"I don't understand the {kind} action.", None

    appid, configured_path = action.get("appid"), action.get("path")
    if appid:
        process = subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + appid], shell=False)
        return value.title(), None, getattr(process, "pid", None)
    if configured_path:
        exe = configured_path if configured_path.lower().endswith(".exe") and os.path.isfile(configured_path) else _exe_in_folder(configured_path, value)
        if not exe:
            return None, f"I couldn't find {value} there.", None
        args = action.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            return None, f"I couldn't open {value}.", None
        process = subprocess.Popen([exe, *args], shell=False)
        return value.title(), None, getattr(process, "pid", None)
    if value.lower() == "chatgpt":
        appid = _chatgpt_id()
        if not appid:
            return None, "I couldn't find the ChatGPT app.", None
        process = subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + appid], shell=False)
        return "ChatGPT", None, getattr(process, "pid", None)
    entry = app_launcher.resolve_app(value)
    if not entry:
        return None, f"I couldn't find {value}.", None
    target = app_launcher._find_target(entry)
    if not target:
        return None, f"I couldn't find {entry.name}.", None
    process = subprocess.Popen([target], shell=False)
    return entry.name, None, getattr(process, "pid", None)


def _run_mode(name, spec, settings, result):
    opened, failures, windows, already_open = [], [], [], []
    for action in spec.get("actions", []):
        if not isinstance(action, dict):
            failures.append("I don't understand that mode action.")
            continue
        snapshot = _list_windows()
        try:
            label, error, pid = _launch_action(action, settings)
        except (OSError, ValueError, TypeError) as exc:
            label, error, pid = None, f"I couldn't open {action.get('value', 'that')}.", None
        if label:
            opened.append(label)
            found = _record_new_windows(snapshot, pid, label)
            if found:
                windows.extend(found)
            else:
                already_open.append(label)
        if error:
            failures.append(error)
        time.sleep(1.5)
    result.update(opened=opened, failures=failures, windows=windows, already_open=already_open)


def _run_mode_and_finalize(key, name, spec, settings, result):
    _run_mode(name, spec, settings, result)
    if result.get("opened"):
        _mode_windows[key] = result.get("windows", [])
        _mode_already_open[key] = result.get("already_open", [])
    else:
        _active_modes.discard(key)
        _mode_windows.pop(key, None)
        _mode_already_open.pop(key, None)
    _save_state()


def handle_command(text):
    config, error = _load_config()
    if error:
        return error
    normalized = _normalize(text)
    modes = _mode_entries(config)
    if normalized in {"list modes", "what modes do i have"}:
        return "Available modes: " + ", ".join(modes) + "." if modes else "I don't have any modes configured."
    if re.match(r"^(?:turn off|end|disable)\s+", normalized):
        name, _spec = _find_mode(re.sub(r"^(?:turn off|end|disable)\s+", "", normalized), config)
        if name:
            key = _mode_key(name)
            print(f"[modes] turn off: {sorted(_active_modes)}")
            if key not in _active_modes:
                return f"{name.title()} isn't on."
            closed, still_open, left_alone = [], [], list(_mode_already_open.get(key, []))
            records = _mode_windows.get(key, [])
            for record in records:
                hwnd, pid = record["hwnd"], record["pid"]
                if _window_exists(hwnd) and _window_pid(hwnd) == pid:
                    _close_window(hwnd)
                    closed.append(record)
            deadline = time.monotonic() + 5
            while closed and time.monotonic() < deadline:
                remaining = [record for record in closed if _window_exists(record["hwnd"])]
                if not remaining:
                    break
                time.sleep(0.25)
            still_open = [record for record in closed if _window_exists(record["hwnd"])]
            _active_modes.discard(key)
            _mode_windows.pop(key, None)
            _mode_already_open.pop(key, None)
            _save_state()
            if not records or not closed:
                return f"{name.title()} is off. I didn't close anything."
            closed_labels = [record["action_label"] for record in closed if record not in still_open]
            reply = f"{name.title()} is off."
            if closed_labels:
                reply += " Closed " + ", ".join(dict.fromkeys(closed_labels)) + "."
            if left_alone:
                reply += " " + ", ".join(dict.fromkeys(left_alone)) + " was already open, so I left it alone."
            if still_open:
                reply += " The " + ", ".join(dict.fromkeys(record["action_label"] for record in still_open)) + " window is still open, it may be asking to save."
            return reply
        return "I don't have that mode."
    name, spec = _find_mode(normalized, config)
    if not name:
        requested = re.sub(r"^(?:open|start|turn on)\s+", "", normalized)
        return f"I don't have a mode called {requested}."
    key = _mode_key(name)
    if key in _active_modes:
        return f"{name.title()} is already on. Say turn off {name} first."
    result = {}
    _active_modes.add(key)
    _mode_windows[key] = []
    _mode_already_open[key] = []
    print(f"[modes] start: {sorted(_active_modes)}")
    _save_state()
    worker = threading.Thread(target=_run_mode_and_finalize, args=(key, name, spec, config.get("settings", {}), result), daemon=True)
    worker.start()
    worker.join(10)
    if worker.is_alive():
        return f"{name.title()} is starting."
    opened, failures = result.get("opened", []), result.get("failures", [])
    if not opened:
        return failures[0] if failures else f"{name.title()} couldn't start."
    already_open = result.get("already_open", [])
    newly_opened = [label for label in opened if label not in already_open]
    reply = f"{name.title()} is on."
    if newly_opened:
        reply += " Opened " + ", ".join(newly_opened) + "."
    if already_open:
        reply += " " + ", ".join(dict.fromkeys(already_open)) + " was already open."
    return reply + (" " + failures[0] if failures else "")
