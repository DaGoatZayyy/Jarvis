"""Local desktop intelligence and persistent context for J.A.R.V.I.S."""
from __future__ import annotations

import html
import ctypes
import base64
import io
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import psutil
import mss
from PIL import Image
from jarvis_plugins import execute_plugin, plugin_tools

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
        return "That app is not in the approved launch list. Available apps: " + ", ".join(APP_ALLOWLIST)
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


def capture_screen_data_url():
    """Capture the primary desktop only when the user explicitly asks about the screen."""
    with mss.mss() as capture:
        monitor = capture.monitors[1]
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
        return "Project files (limited to 150):\\n" + ("\\n".join(results) or "(no files found)")
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
        return actions[action] + "."
    except Exception as exc:
        return f"Windows action failed: {exc}"

TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "describe_screen", "description": "Capture and inspect the current primary screen. Use only when the user explicitly asks what is on their screen or asks for help with something visible.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_system_status", "description": "Read current CPU, memory, disk, battery, network totals and available NVIDIA GPU telemetry.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "list_running_apps", "description": "List running process names on this Windows computer.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "open_app", "description": "Open an application from the safe built-in allowlist only.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "enum": list(APP_ALLOWLIST)}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "remember_fact", "description": "Save a non-sensitive preference or fact only when the user explicitly asks you to remember it.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "recall_memory", "description": "Read the user's saved JARVIS memory when relevant or requested.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "forget_memory", "description": "Remove saved memory entries matching the user's explicit request.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the web for current information and return a few result titles and links.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "windows_action", "description": "Perform one standard Windows desktop action from a fixed safe allowlist.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["open_file_explorer", "open_task_manager", "open_settings", "show_desktop", "volume_up", "volume_down", "volume_mute", "lock_workstation"]}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "list_project_files", "description": "List files in the configured coding project directory, excluding dependency and version-control folders.", "parameters": {"type": "object", "properties": {"subdirectory": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "read_project_file", "description": "Read a text file from the configured coding project directory for code analysis.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}}, "required": ["relative_path"]}}},
    {"type": "function", "function": {"name": "write_project_file", "description": "Edit a project text file only when the user explicitly requested a code edit. Always preserve a backup. Never use for secrets.", "parameters": {"type": "object", "properties": {"relative_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["relative_path", "content"]}}},
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
    if name == "windows_action":
        return windows_action(arguments.get("action", ""))
    if name == "list_project_files":
        return list_project_files(arguments.get("subdirectory", ""))
    if name == "read_project_file":
        return read_project_file(arguments.get("relative_path", ""))
    if name == "write_project_file":
        return write_project_file(arguments.get("relative_path", ""), arguments.get("content", ""))
    return execute_plugin(name, arguments) or "Tool not available."
