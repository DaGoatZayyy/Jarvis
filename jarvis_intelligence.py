"""Local desktop intelligence and persistent context for J.A.R.V.I.S."""
from __future__ import annotations

import html
import ctypes
from ctypes import wintypes
import base64
import io
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import webbrowser
from html.parser import HTMLParser
from pathlib import Path

import psutil
import mss
from PIL import Image
from jarvis_plugins import execute_plugin, plugin_tools
from jarvis_desktop import (discover_apps, launch_discovered_app, close_discovered_app, close_last_opened_app, run_project_python, resolve_spoken_python_path, save_skill, forget_skill, load_skills)
from jarvis_features import search_local_files, read_clipboard_text, create_reminder, list_reminders, cancel_reminder

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "jarvis_history.json"
MEMORY_FILE = ROOT / "jarvis_memory.json"
MAX_HISTORY_MESSAGES = 80


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def load_history():
    data = _read_json(HISTORY_FILE, [])
    if not isinstance(data, list):
        return []
    return [m for m in data if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)][-MAX_HISTORY_MESSAGES:]


def save_history(messages):
    clean = [m for m in messages if m.get("role") in ("user", "assistant")][-MAX_HISTORY_MESSAGES:]
    _write_json(HISTORY_FILE, clean)


def load_memory():
    data = _read_json(MEMORY_FILE, [])
    return [str(item) for item in data if isinstance(item, str)] if isinstance(data, list) else []


def save_memory(items):
    clean = []
    for item in items:
        fact = " ".join(str(item).split())[:500]
        if fact and fact.casefold() not in {saved.casefold() for saved in clean}:
            clean.append(fact)
    _write_json(MEMORY_FILE, clean[-100:])
    return len(clean[-100:])


def remember_fact(fact: str):
    fact = " ".join(str(fact).split())[:500]
    if not fact:
        return "I need a non-empty fact to remember."
    items = load_memory()
    if any(str(item).casefold() == fact.casefold() for item in items):
        return "That fact is already saved."
    items.append(fact)
    _write_json(MEMORY_FILE, items[-100:])
    return "Saved to JARVIS memory."


def recall_memory():
    items = load_memory()
    if not items:
        return "No saved memories yet."
    return "\n".join(f"- {item}" for item in items[-30:])


def forget_memory(fact: str):
    target = " ".join(str(fact).split()).casefold()
    items = load_memory()
    kept = [item for item in items if target not in str(item).casefold()]
    removed = len(items) - len(kept)
    _write_json(MEMORY_FILE, kept)
    return f"Removed {removed} matching memory item(s)." if removed else "No matching memory was found."


def system_status():
    cpu = psutil.cpu_percent(interval=0.35)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
    battery = psutil.sensors_battery()
    net = psutil.net_io_counters()
    parts = [
        f"CPU usage: {cpu:.0f}%",
        f"RAM: {memory.percent:.0f}% used ({memory.used / (1024**3):.1f} GB of {memory.total / (1024**3):.1f} GB)",
        f"System drive: {disk.percent:.0f}% used ({disk.free / (1024**3):.1f} GB free)",
        f"Network totals: {net.bytes_sent / (1024**2):.1f} MB sent, {net.bytes_recv / (1024**2):.1f} MB received",
    ]
    if battery:
        parts.append(f"Battery: {battery.percent:.0f}%" + (" (charging)" if battery.power_plugged else ""))
    # NVIDIA telemetry is optional; no shell command is executed.
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and result.stdout.strip():
            values = [v.strip() for v in result.stdout.strip().split(",")]
            if len(values) >= 5:
                parts.append(f"GPU: {values[0]}, {values[1]}% load, {values[2]}/{values[3]} MB VRAM, {values[4]} C")
    except (OSError, subprocess.SubprocessError):
        parts.append("GPU telemetry: unavailable (NVIDIA nvidia-smi not found).")
    return "\n".join(parts)


def running_apps():
    names = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
            if name:
                names.add(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return "Running processes (first 45): " + ", ".join(sorted(names, key=str.casefold)[:45])


APP_ALLOWLIST = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["taskmgr.exe"],
    "paint": ["mspaint.exe"],
    "settings": ["cmd.exe", "/c", "start", "", "ms-settings:"],
    "terminal": ["wt.exe"],
}


def open_app(app_name: str):
    key = " ".join(str(app_name).casefold().split())
    command = APP_ALLOWLIST.get(key)
    if not command:
        return launch_discovered_app(app_name)
    try:
        if key == "settings":
            os.startfile("ms-settings:")
        else:
            subprocess.Popen(command, close_fds=True,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return f"Opened {key}."
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Could not open {key}: {exc}"


class _SearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._active = None
        self._capture = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._active = {"title": "", "url": attrs.get("href", "")}
            self._capture = True
        elif tag == "a" and "result__snippet" in classes and self.results:
            self._capture = True
            self._active = self.results[-1]

    def handle_data(self, data):
        if self._capture and self._active is not None:
            self._active["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._capture and self._active is not None:
            if self._active not in self.results and self._active.get("title"):
                self.results.append(self._active)
            self._capture = False
            self._active = None


def open_website(address: str):
    """Open a validated HTTP(S) website in the user's default browser."""
    raw = str(address or "").strip().strip('"').strip("'").rstrip(".,!?")
    if not raw or len(raw) > 2048 or any(ch.isspace() for ch in raw):
        return "Please provide a valid website address, such as gmail.com."

    candidate = raw if "://" in raw else "https://" + raw
    try:
        parsed = urllib.parse.urlsplit(candidate)
        host = parsed.hostname or ""
        if (
            parsed.scheme not in ("http", "https")
            or not host
            or "." not in host
            or parsed.username is not None
            or parsed.password is not None
            or any(ch in host for ch in ("\\", "%", "<", ">", '"', "'"))
        ):
            return "That doesn't look like a valid website address. Try a domain such as gmail.com."
        # Accessing .port validates malformed port values.
        _ = parsed.port
        if not webbrowser.open(candidate, new=2):
            return f"Windows could not open {candidate} in the default browser."
        return f"Opened {host} in your default browser."
    except (ValueError, OSError) as exc:
        return f"Could not open that website: {exc}"


def web_search(query: str):
    query = " ".join(str(query).split())[:240]
    if not query:
        return "Search query was empty."
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 JARVIS/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            page = response.read(700_000).decode("utf-8", "replace")
    except Exception as exc:
        return f"Web search failed: {exc}"
    parser = _SearchParser()
    parser.feed(page)
    if not parser.results:
        # Fallback extraction keeps output bounded if DDG changes its markup.
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', page, re.S)
        return "Search page returned no parsable results. " + " ".join(
            re.sub(r"<[^>]+>", "", html.unescape(t)) for t in titles[:5]
        )
    return "\n".join(
        f"{i+1}. {html.unescape(item['title']).strip()} — {item['url']}"
        for i, item in enumerate(parser.results[:5])
    )


def capture_screen_data_url(window_only: bool = False):
    """Capture the primary desktop or foreground window after an explicit request."""
    with mss.mss() as capture:
        monitor = capture.monitors[1]
        if window_only and os.name == "nt":
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                rect = wintypes.RECT()
                if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                    if right > left and bottom > top:
                        monitor = {"left": left, "top": top, "width": right-left, "height": bottom-top}
            except Exception:
                pass
        shot = capture.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.thumbnail((1600, 1000))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=75, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + encoded



def _project_root():
    configured = os.environ.get("JARVIS_PROJECT_DIR", "").strip()
    if not configured:
        env_path = ROOT / ".env"
        try:
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("JARVIS_PROJECT_DIR="):
                    configured = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except OSError:
            pass
    root = Path(configured).expanduser() if configured else ROOT
    return root.resolve()


def _safe_project_path(relative_path: str):
    root = _project_root()
    candidate = (root / str(relative_path)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("That path is outside the configured project directory.")
    return root, candidate


def list_project_files(subdirectory: str = ""):
    try:
        root, folder = _safe_project_path(subdirectory or ".")
        if not folder.is_dir():
            return "That project directory does not exist."
        ignored = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
        results = []
        for path in folder.rglob("*"):
            if any(part in ignored for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                results.append(str(path.relative_to(root)))
            if len(results) >= 150:
                break
        return "Project files (limited to 150):\n" + ("\n".join(results) or "(no files found)")
    except Exception as exc:
        return f"Could not list project files: {exc}"


def read_project_file(relative_path: str):
    try:
        root, path = _safe_project_path(relative_path)
        if not path.is_file():
            return "That project file does not exist."
        if path.stat().st_size > 150_000:
            return "That file is larger than the 150 KB read limit."
        return path.read_text(encoding="utf-8", errors="replace")[:150_000]
    except Exception as exc:
        return f"Could not read project file: {exc}"


def write_project_file(relative_path: str, content: str):
    """Write only inside the configured project, preserving a .bak copy."""
    try:
        root, path = _safe_project_path(relative_path)
        if path == root or not path.parent.is_dir():
            return "The target must be a file inside an existing project folder."
        if path.name.casefold().startswith(".env") or path.suffix.casefold() in {".pem", ".key", ".pfx", ".p12"} or path.name.casefold() in {
            "id_rsa", "id_ed25519", "credentials.json", "secrets.json"
        }:
            return "JARVIS will not edit credential or private-key files."
        text = str(content)
        if len(text.encode("utf-8")) > 150_000:
            return "The proposed file exceeds the 150 KB write limit."
        if path.exists():
            if not path.is_file():
                return "The target is not a regular file."
            if path.stat().st_size > 150_000:
                return "The existing file is larger than the 150 KB edit limit."
            backup = path.with_suffix(path.suffix + ".jarvis.bak")
            backup.write_bytes(path.read_bytes())
        temp = path.with_suffix(path.suffix + ".jarvis.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
        return f"Updated {path.relative_to(root)}. A .jarvis.bak backup was created if the file already existed."
    except Exception as exc:
        return f"Could not update project file: {exc}"


def windows_action(action: str):
    """Small allowlist of reversible or standard Windows shortcuts/actions."""
    actions = {
        "open_file_explorer": "Open File Explorer",
        "open_task_manager": "Open Task Manager",
        "open_settings": "Open Windows Settings",
        "show_desktop": "Show desktop",
        "volume_up": "Increase system volume",
        "volume_down": "Decrease system volume",
        "volume_mute": "Toggle system mute",
        "lock_workstation": "Lock Windows",
    }
    if action not in actions:
        return "Action not allowed. Available actions: " + ", ".join(actions)
    try:
        if action == "open_file_explorer":
            subprocess.Popen(["explorer.exe"])
        elif action == "open_task_manager":
            subprocess.Popen(["taskmgr.exe"])
        elif action == "open_settings":
            os.startfile("ms-settings:")
        elif action == "lock_workstation":
            ctypes.windll.user32.LockWorkStation()
        else:
            user32 = ctypes.windll.user32
            if action == "show_desktop":
                # Win+D
                user32.keybd_event(0x5B, 0, 0, 0)
                user32.keybd_event(0x44, 0, 0, 0)
                user32.keybd_event(0x44, 0, 2, 0)
                user32.keybd_event(0x5B, 0, 2, 0)
            else:
                key = {"volume_up": 0xAF, "volume_down": 0xAE, "volume_mute": 0xAD}[action]
                user32.keybd_event(key, 0, 0, 0)
                user32.keybd_event(key, 0, 2, 0)
        success_messages = {
            "open_file_explorer": "File Explorer opened.",
            "open_task_manager": "Task Manager opened.",
            "open_settings": "Windows Settings opened.",
            "show_desktop": "Desktop shown.",
            "volume_up": "System volume increased.",
            "volume_down": "System volume decreased.",
            "volume_mute": "System mute toggled.",
            "lock_workstation": "Windows lock request sent.",
        }
        return success_messages[action]
    except Exception as exc:
        return f"Windows action failed: {exc}"


# Restricted Windows automation helpers.
CLOSE_APP_ALLOWLIST = {
    "notepad": "notepad.exe", "calculator": "CalculatorApp.exe",
    "task manager": "Taskmgr.exe",
    "paint": "mspaint.exe", "terminal": "WindowsTerminal.exe",
}
SAFE_COMMANDS = {
    "whoami": ["whoami"], "hostname": ["hostname"], "ipconfig": ["ipconfig"],
    "tasklist": ["tasklist"], "systeminfo": ["systeminfo"],
    "python_version": ["py", "--version"], "git_version": ["git", "--version"],
}

def close_app(app_name: str):
    # Prefer graceful window closure for every application; never force-kill by image name.
    return close_discovered_app(app_name)


def create_project_item(relative_path: str, item_type: str = "file", content: str = ""):
    try:
        root, path = _safe_project_path(relative_path)
        kind = str(item_type).casefold()
        if path == root or kind not in ("file", "folder") or not path.parent.is_dir():
            return "Choose a file or folder path inside an existing configured project folder."
        if path.exists():
            return "That path already exists; nothing was overwritten."
        if path.name.casefold().startswith(".env") or path.suffix.casefold() in {".pem", ".key", ".pfx", ".p12"}:
            return "JARVIS will not create credential or private-key files."
        if kind == "folder":
            path.mkdir()
            return f"Created folder {path.relative_to(root)}."
        text = str(content)
        if len(text.encode("utf-8")) > 100_000:
            return "The new file exceeds the 100 KB creation limit."
        with path.open("x", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return f"Created file {path.relative_to(root)}."
    except Exception as exc:
        return f"Could not create the project item: {exc}"

def delete_project_item(relative_path: str):
    """Move a project item to the Windows Recycle Bin; never permanently unlink it."""
    try:
        root, path = _safe_project_path(relative_path)
        if path == root or not path.exists():
            return "That project item does not exist or is not deletable."
        if path.name.casefold().startswith(".env") or path.suffix.casefold() in {".pem", ".key", ".pfx", ".p12"}:
            return "JARVIS will not delete credential or private-key files."
        if os.name != "nt":
            return "Recycle Bin deletion is available only on Windows."
        from ctypes import wintypes
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                        ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
        operation = SHFILEOPSTRUCTW()
        operation.wFunc = 3
        operation.pFrom = str(path) + "\0\0"
        operation.fFlags = 0x40 | 0x10 | 0x4
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result != 0 or operation.fAnyOperationsAborted:
            return f"Windows did not complete the Recycle Bin operation (code {result})."
        return f"Moved {path.relative_to(root)} to the Windows Recycle Bin."
    except Exception as exc:
        return f"Could not move the project item to the Recycle Bin: {exc}"

def run_safe_command(command_id: str):
    key = str(command_id).strip().casefold()
    command = SAFE_COMMANDS.get(key)
    if not command:
        return "That command is not approved. Available read-only commands: " + ", ".join(SAFE_COMMANDS)
    try:
        result = subprocess.run(command, cwd=str(_project_root()), capture_output=True, text=True,
                                timeout=20, check=False, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = (result.stdout or "").strip()
        if result.stderr:
            output = (output + "\n" + result.stderr.strip()).strip()
        return f"Command {key} exited with code {result.returncode}.\n{output[:4500] or '(no output)'}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Command {key} failed: {exc}"

def detect_spoken_script_command(user_text: str):
    """Turn spoken script requests into a safe exact-path confirmation flow."""
    text = " ".join(str(user_text).casefold().split()).strip(" .!?")
    confirm = re.match(r"^(?:please )?confirm run script (.+)$", text)
    if confirm:
        resolved = resolve_spoken_python_path(confirm.group(1))
        if not resolved:
            return ("__reply__", {"message": "I couldn't match that spoken filename to one unique existing Python script in the configured project folder. Please type the exact relative filename; I did not run anything."})
        return ("run_project_python", {"relative_path": resolved, "arguments": ""})
    request = re.match(r"^(?:please )?run (?:the )?script (.+)$", text)
    if request:
        resolved = resolve_spoken_python_path(request.group(1))
        if not resolved:
            return ("__reply__", {"message": "I couldn't match that spoken filename to one unique existing Python script in the configured project folder. Please say or type its exact relative filename. Nothing was run."})
        return ("__reply__", {"message": f"I found the existing script '{resolved}'. To run it, say: confirm run script {resolved}. This confirmation is required even when No Confirms is enabled."})
    return None


def _looks_like_website_address(value: str) -> bool:
    """Recognize domain-shaped addresses without maintaining a website-name list."""
    candidate = str(value or "").strip().strip('"').strip("'").rstrip(".,!?")
    # Speech recognition sometimes spells out the separator.
    candidate = re.sub(r"\\s+dot\\s+", ".", candidate, flags=re.I)
    if candidate.casefold().startswith(("https://", "http://")):
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0].split(":", 1)[0]
    if not candidate or " " in candidate or "." not in candidate:
        return False
    labels = candidate.rstrip(".").split(".")
    if len(labels) < 2:
        return False
    # Avoid treating common executable/document extensions as websites.
    non_web_extensions = {
        "exe", "msi", "bat", "cmd", "ps1", "py", "pyw", "js", "ts", "json",
        "txt", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip",
        "rar", "7z", "png", "jpg", "jpeg", "gif", "mp3", "mp4", "mov",
    }
    if labels[-1].casefold() in non_web_extensions:
        return False
    if not re.fullmatch(r"[a-z]{2,63}", labels[-1], re.I):
        return False
    return all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label, re.I)
        for label in labels
    )


def _website_request_target(user_text: str):
    """Return a domain/URL only when the user's wording clearly refers to a site."""
    text = " ".join(str(user_text).strip().split()).strip(" .!?")
    # A domain by itself is an unambiguous website request.
    if _looks_like_website_address(text):
        return re.sub(r"\\s+dot\\s+", ".", text, flags=re.I).rstrip(".,!?")
    # For commands, classify by the target's address shape, not a list of site names.
    match = re.match(
        r"^(?:please )?(?:open|go to|visit|browse to|navigate to) "
        r"(?:the )?(?:website )?(.+)$",
        text,
        re.I,
    )
    if not match:
        return None
    target = match.group(1).strip().strip('"').strip("'").rstrip(".,!?")
    target = re.sub(r"\\s+dot\\s+", ".", target, flags=re.I)
    if _looks_like_website_address(target):
        return target
    return None


def detect_common_windows_command(user_text: str):
    """Handle clear desktop and website intents before model inference."""
    text = " ".join(str(user_text).casefold().split()).strip(" .!?")
    aliases = {"explorer": "file explorer", "calc": "calculator"}
    match = re.match(r"^(?:please )?(?:open|launch|start|run) (?:the )?(task manager|file explorer|explorer|notepad|calculator|calc|paint|settings|terminal)$", text)
    if match:
        app = aliases.get(match.group(1), match.group(1))
        return ("windows_action", {"action": "open_task_manager"}) if app == "task manager" else (("windows_action", {"action": "open_file_explorer"}) if app == "file explorer" else (("windows_action", {"action": "open_settings"}) if app == "settings" else ("open_app", {"app_name": app})))
    if re.match(r"^(?:please )?(?:close|quit|exit) (?:it|that|the last app(?: you opened)?|the app you just opened|the last opened app|the last opened you did)$", text):
        return ("close_last_opened_app", {})
    match = re.match(r"^(?:please )?(?:close|quit|exit) (?:the )?(task manager|file explorer|explorer|notepad|calculator|calc|paint|terminal)$", text)
    if match:
        return ("close_app", {"app_name": aliases.get(match.group(1), match.group(1))})
    actions = {
        "show_desktop": r"^(?:please )?(?:show|go to) (?:the )?desktop$",
        "volume_mute": r"^(?:please )?(?:mute|unmute) (?:the )?(?:system )?volume$",
        "volume_up": r"^(?:please )?(?:turn|volume) (?:the )?volume up$",
        "volume_down": r"^(?:please )?(?:turn|volume) (?:the )?volume down$",
    }
    for action, pattern in actions.items():
        if re.match(pattern, text):
            return ("windows_action", {"action": action})
    # Local file searches must be routed before the generic installed-app finder.
    file_search = re.match(r"^(?:please )?(?:find|search for|look for|locate) (.+)$", text)
    if file_search:
        target = file_search.group(1).strip()
        file_terms = ("file", "folder", "document", "readme", "config", "configuration",
                      "python", "script", "project", "in the project", "in my files")
        if any(term in target for term in file_terms):
            query = re.sub(r"\\b(?:my|the|a|an|file|folder|document|in the project folder|in project folder|in my project folder)\\b", " ", target)
            query = " ".join(query.split()).strip() or target
            return ("search_local_files", {"query": query})
    # File/folder creation and diagnostics are also recognized deterministically.
    match = re.match(r"^(?:please )?(?:create|make) (?:a )?(file|folder) (?:named )?(.+)$", text)
    if match:
        return ("create_project_item", {
            "item_type": match.group(1),
            "relative_path": match.group(2).strip().strip('"'),
            "content": "",
        })
    match = re.match(r"^(?:please )?(?:find|search for|look for|locate) (?:the )?(?:installed )?(?:app )?(.+)$", text)
    if match:
        query = match.group(1).strip()
        if query and query not in {"a file", "a folder"}:
            return ("discover_apps", {"query": query})
    # Domain-shaped targets are websites, not installed applications.
    website_target = _website_request_target(user_text)
    if website_target:
        return ("open_website", {"address": website_target})
    match = re.match(r"^(?:please )?(?:open|launch|start) (.+)$", text)
    if match and match.group(1) not in {"file explorer", "explorer", "task manager", "settings", "notepad", "calculator", "calc", "paint", "terminal"}:
        return ("launch_discovered_app", {"app_name": match.group(1)})
    match = re.match(r"^(?:please )?(?:close|quit|exit) (.+)$", text)
    if match and match.group(1) not in {"file explorer", "explorer", "task manager", "settings", "notepad", "calculator", "calc", "paint", "terminal"}:
        return ("close_discovered_app", {"app_name": match.group(1)})
    match = re.match(r"^confirm delete (.+)$", text)
    if match:
        return ("delete_project_item", {"relative_path": match.group(1).strip().strip('"')})
    command_aliases = {
        "python --version": "python_version",
        "git --version": "git_version",
    }
    match = re.match(r"^(?:please )?(?:run|execute) (whoami|hostname|ipconfig|tasklist|systeminfo|python --version|git --version)$", text)
    if match:
        return ("run_safe_command", {"command_id": command_aliases.get(match.group(1), match.group(1))})
    return None


TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "describe_screen", "description": "Capture and inspect the primary screen or active foreground window. Use only when the user explicitly asks about visible content. Set window_only true for the active window.", "parameters": {"type": "object", "properties": {"window_only": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {"name": "get_system_status", "description": "Read current CPU, memory, disk, battery, network totals and available NVIDIA GPU telemetry.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "list_running_apps", "description": "List running process names on this Windows computer.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "open_app", "description": "Open an application from the safe built-in allowlist only.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "enum": list(APP_ALLOWLIST)}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "remember_fact", "description": "Save a non-sensitive preference or fact only when the user explicitly asks you to remember it.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "recall_memory", "description": "Read the user's saved JARVIS memory when relevant or requested.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "forget_memory", "description": "Remove saved memory entries matching the user's explicit request.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the web for current information and return a few result titles and links.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "open_website", "description": "Open a user-requested website in the computer's default browser. Accepts a domain or HTTP(S) URL.", "parameters": {"type": "object", "properties": {"address": {"type": "string"}}, "required": ["address"]}}},
    {"type": "function", "function": {"name": "windows_action", "description": "Perform one standard Windows desktop action from a fixed safe allowlist.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["open_file_explorer", "open_task_manager", "open_settings", "show_desktop", "volume_up", "volume_down", "volume_mute", "lock_workstation"]}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "close_app", "description": "Close a running app from the approved application list only.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "enum": list(CLOSE_APP_ALLOWLIST)}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "create_project_item", "description": "Create a new file or folder inside the configured project directory without overwriting existing files.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}, "item_type": {"type": "string", "enum": ["file", "folder"]}, "content": {"type": "string"}}, "required": ["relative_path", "item_type"]}}},
    {"type": "function", "function": {"name": "delete_project_item", "description": "Move a project item to the Recycle Bin only after the user's latest message explicitly confirms with 'confirm delete' and the exact relative path.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}}, "required": ["relative_path"]}}},
    {"type": "function", "function": {"name": "run_safe_command", "description": "Run a predefined read-only diagnostic command only. Never accept arbitrary command text.", "parameters": {"type": "object", "properties": {"command_id": {"type": "string", "enum": list(SAFE_COMMANDS)}}, "required": ["command_id"]}}},
    {"type": "function", "function": {"name": "discover_apps", "description": "Search installed Windows applications and Start Menu shortcuts without launching them.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "launch_discovered_app", "description": "Find and launch an installed Windows app by its displayed name.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "close_discovered_app", "description": "Find matching app windows and send a normal WM_CLOSE request; never force-kill arbitrary processes.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "run_project_python", "description": "Run an existing Python script from the configured project directory in a hidden window, with a timeout and captured output. Only use when the user explicitly asks to run that script.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}, "arguments": {"type": "string"}}, "required": ["relative_path"]}}},
    {"type": "function", "function": {"name": "save_skill", "description": "Save a user-approved reusable natural-language skill after a task succeeds. Never save code or secrets.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "trigger": {"type": "string"}, "procedure": {"type": "string"}}, "required": ["name", "trigger", "procedure"]}}},
    {"type": "function", "function": {"name": "forget_skill", "description": "Remove a saved learned skill by exact name when the user asks.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "list_skills", "description": "List the user's saved reusable skills.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "list_project_files", "description": "List files in the configured coding project directory, excluding dependency and version-control folders.", "parameters": {"type": "object", "properties": {"subdirectory": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "read_project_file", "description": "Read a text file from the configured coding project directory for code analysis.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}}, "required": ["relative_path"]}}},
    {"type": "function", "function": {"name": "write_project_file", "description": "Edit a project text file only when the user explicitly requested a code edit. Always preserve a backup. Never use for secrets.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["relative_path", "content"]}}},
    {"type": "function", "function": {"name": "search_local_files", "description": "Search filenames and readable document contents in the configured JARVIS project folder when the user asks to find a local file or document.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "clipboard_assist", "description": "Read plain text currently on the Windows clipboard so you can summarize, explain, rewrite, or transform it. Use only when the user explicitly asks you to work with their clipboard. Do not change the clipboard.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "create_reminder", "description": "Create a local reminder. Convert the requested time to ISO 8601 including the user's local timezone offset. Repeat must be none, daily, or weekly.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "due_at": {"type": "string"}, "repeat": {"type": "string", "enum": ["none", "daily", "weekly"]}}, "required": ["title", "due_at"]}}},
    {"type": "function", "function": {"name": "list_reminders", "description": "List pending local reminders when the user asks what reminders they have.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "cancel_reminder", "description": "Cancel a pending local reminder by its ID after the user asks to cancel it.", "parameters": {"type": "object", "properties": {"reminder_id": {"type": "string"}}, "required": ["reminder_id"]}}},
    *plugin_tools(),
]


def execute_tool(name: str, arguments: dict):
    if name == "describe_screen":
        return "Screen capture requested. The screenshot will be attached for visual analysis."
    if name == "get_system_status":
        return system_status()
    if name == "list_running_apps":
        return running_apps()
    if name == "open_app":
        return open_app(arguments.get("app_name", ""))
    if name == "remember_fact":
        return remember_fact(arguments.get("fact", ""))
    if name == "recall_memory":
        return recall_memory()
    if name == "forget_memory":
        return forget_memory(arguments.get("fact", ""))
    if name == "web_search":
        return web_search(arguments.get("query", ""))
    if name == "open_website":
        return open_website(arguments.get("address", ""))
    if name == "windows_action":
        return windows_action(arguments.get("action", ""))
    if name == "close_app":
        return close_app(arguments.get("app_name", ""))
    if name == "create_project_item":
        return create_project_item(arguments.get("relative_path", ""), arguments.get("item_type", "file"), arguments.get("content", ""))
    if name == "delete_project_item":
        return delete_project_item(arguments.get("relative_path", ""))
    if name == "run_safe_command":
        return run_safe_command(arguments.get("command_id", ""))
    if name == "discover_apps":
        return discover_apps(arguments.get("query", ""))
    if name == "launch_discovered_app":
        return launch_discovered_app(arguments.get("app_name", ""))
    if name == "close_discovered_app":
        return close_discovered_app(arguments.get("app_name", ""))
    if name == "close_last_opened_app":
        return close_last_opened_app()
    if name == "run_project_python":
        return run_project_python(arguments.get("relative_path", ""), arguments.get("arguments", ""))
    if name == "save_skill":
        return save_skill(arguments.get("name", ""), arguments.get("trigger", ""), arguments.get("procedure", ""))
    if name == "forget_skill":
        return forget_skill(arguments.get("name", ""))
    if name == "list_skills":
        skills = load_skills()
        return "\n".join(f"{item['name']} — trigger: {item['trigger']} — enabled: {item.get('enabled', True)}" for item in skills) or "No learned skills saved yet."
    if name == "list_project_files":
        return list_project_files(arguments.get("subdirectory", ""))
    if name == "read_project_file":
        return read_project_file(arguments.get("relative_path", ""))
    if name == "write_project_file":
        return write_project_file(arguments.get("relative_path", ""), arguments.get("content", ""))
    if name == "search_local_files":
        return search_local_files(arguments.get("query", ""))
    if name == "clipboard_assist":
        return read_clipboard_text()
    if name == "create_reminder":
        return create_reminder(arguments.get("title", ""), arguments.get("due_at", ""), arguments.get("repeat", "none"))
    if name == "list_reminders":
        return list_reminders()
    if name == "cancel_reminder":
        return cancel_reminder(arguments.get("reminder_id", ""))
    return execute_plugin(name, arguments) or "Tool not available."
