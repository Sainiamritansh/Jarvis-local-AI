"""Safe, registry-based launcher for common Windows applications."""
from dataclasses import dataclass
from difflib import get_close_matches
import os
import platform
import shutil
try:
    import winreg
except ImportError:
    winreg = None

@dataclass(frozen=True)
class AppEntry:
    name: str
    aliases: tuple[str, ...]
    executables: tuple[str, ...]
    known_paths: tuple[str, ...] = ()
    uri: str | None = None

APP_REGISTRY = [
    AppEntry("Microsoft Edge", ("edge", "ms edge"), ("msedge.exe",), (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")),
    AppEntry("Google Chrome", ("chrome", "google chrome"), ("chrome.exe",), (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")),
    AppEntry("File Explorer", ("explorer", "file explorer"), ("explorer.exe",)),
    AppEntry("Notepad", ("notepad", "note pad"), ("notepad.exe",)),
    AppEntry("Calculator", ("calculator", "calc"), ("calc.exe",)),
    AppEntry("Windows Settings", ("settings", "windows settings"), (), uri="ms-settings:"),
    AppEntry("Task Manager", ("task manager", "taskmgr"), ("taskmgr.exe",)),
    AppEntry("Command Prompt", ("command prompt", "cmd"), ("cmd.exe",)),
    AppEntry("Visual Studio Code", ("visual studio code", "vs code", "vscode"), ("code.exe",), (r"C:\Program Files\Microsoft VS Code\Code.exe",)),
    AppEntry("WhatsApp", ("whatsapp", "whats app"), (), uri="whatsapp:"),
    AppEntry("Antigravity", ("antigravity", "anti gravity", "antigravity ide"), ("antigravity.exe",)),
    AppEntry("ChatGPT", ("chatgpt", "chat gpt"), ()),
]

def _key(value): return "".join(value.lower().split())

def resolve_app(spoken_name):
    words = [word for word in spoken_name.lower().split() if word not in {"app", "the", "my"}]
    candidate = _key(" ".join(words))
    names = {_key(name): entry for entry in APP_REGISTRY for name in (entry.name, *entry.aliases)}
    if candidate in names: return names[candidate]
    matches = get_close_matches(candidate, names.keys(), n=1, cutoff=0.8)
    return names[matches[0]] if matches else None

def _app_path(executable):
    if winreg is None: return None
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable}") as key:
                value, _ = winreg.QueryValueEx(key, None)
                return value.strip('"')
        except OSError: continue
    return None

def _find_target(entry):
    if entry.uri: return entry.uri
    for executable in entry.executables:
        target = _app_path(executable) or shutil.which(executable)
        if target: return target
    return next((path for path in entry.known_paths if os.path.exists(path)), None)

def _launch(target): os.startfile(target)

def launch_app(spoken_name):
    if platform.system() != "Windows": return "Opening apps is only available on Windows."
    entry = resolve_app(spoken_name)
    if entry is None: return f"I don't know the app {spoken_name}."
    target = _find_target(entry)
    if not target: return f"{entry.name} is not installed."
    try: _launch(target)
    except OSError: return f"Couldn't open {entry.name}."
    return f"Opening {entry.name}"
