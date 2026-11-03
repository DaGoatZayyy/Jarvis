"""Windows app discovery, window-aware closing, bounded command execution and learned skills.

This module deliberately avoids arbitrary shell strings. Applications are discovered from
Start Menu shortcuts and Windows App Paths/uninstall metadata. Learned skills are stored as
reviewable natural-language procedures, never executable plugin code.
"""
from __future__ import annotations

import ctypes
import difflib
import json
import os
import re
import subprocess
import time
from pathlib import Path

try:
    import winreg
except ImportError:  # non-Windows import support for syntax checks
    winreg = None

ROOT = Path(__file__).resolve().parent
SKILLS_FILE = ROOT / "jarvis_skills.json"
SESSIONS_FILE = ROOT / "jarvis_app_sessions.json"
IGNORED_APP_NAMES = {"uninstall", "uninstaller", "update", "updater", "crash reporter"}
SAFE_DIAGNOSTICS = {
    "whoami": ["whoami"],
    "hostname": ["hostname"],
    "ipconfig": ["ipconfig"],
    "tasklist": ["tasklist"],
    "systeminfo": ["systeminfo"],
    "python_version": ["py", "--version"],
    "git_version": ["git", "--version"],
}
DANGEROUS_COMMAND_PATTERNS = (
    r"\b(format|diskpart|cipher\s+/w|bcdedit|reg\s+(add|delete)|shutdown|"
    r"rmdir\s+/s|del\s+/s|remove-item|stop-computer|"
    r"set-executionpolicy|net\s+user|sc\s+(delete|config)|"
    r"takeown|icacls|wevtutil\s+cl)\b",
    r"\b(powershell|pwsh|cmd)(\.exe)?\s+.*\b(enc|encodedcommand|command)\b",
)


def _read_json(path: Path, fallback):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _project_root() -> Path:
    configured = os.environ.get("JARVIS_PROJECT_DIR", "").strip()
    if not configured:
        try:
            for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("JARVIS_PROJECT_DIR="):
                    configured = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except OSError:
            pass
    return (Path(configured).expanduser() if configured else ROOT).resolve()


def _shortcut_dirs():
    appdata = Path(os.environ.get("APPDATA", ""))
    programdata = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    return [
        appdata / "Microsoft/Windows/Start Menu/Programs",
        programdata / "Microsoft/Windows/Start Menu/Programs",
    ]


def _registry_apps():
    if winreg is None:
        return []
    results = []
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, subkey in roots:
        try:
            with winreg.OpenKey(hive, subkey) as parent:
                count = winreg.QueryInfoKey(parent)[0]
                for index in range(count):
                    try:
                        child_name = winreg.EnumKey(parent, index)
                        with winreg.OpenKey(parent, child_name) as child:
                            values = {}
                            value_count = winreg.QueryInfoKey(child)[1]
                            for vi in range(value_count):
                                try:
                                    name, value, _ = winreg.EnumValue(child, vi)
                                    values[name.casefold()] = value
                                except OSError:
                                    continue
                        if "app paths" in subkey.casefold():
                            target = values.get("")
                            display = Path(child_name).stem
                        else:
                            display = values.get("displayname")
                            target = values.get("displayicon") or values.get("installlocation")
                            if target:
                                target = str(target).strip().strip('"').split(",")[0]
                        if display and target:
                            results.append({"name": str(display), "target": str(target), "source": "registry"})
                    except OSError:
                        continue
        except OSError:
            continue
    return results


def _normalize_app_name(value: str) -> str:
    """Normalize app names for reliable exact, token and fuzzy matching."""
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def _app_name_match_score(query: str, app_name: str) -> float:
    """Score meaningful app-name matches while rejecting weak substring/fuzzy collisions."""
    normalized_query = _normalize_app_name(query)
    normalized_name = _normalize_app_name(app_name)
    if not normalized_query or not normalized_name:
        return 0.0
    if normalized_name == normalized_query:
        return 1.0

    query_tokens = normalized_query.split()
    name_tokens = normalized_name.split()
    token_scores = []
    for query_token in query_tokens:
        best = 0.0
        for name_token in name_tokens:
            if query_token == name_token:
                best = 1.0
            elif len(query_token) >= 3 and name_token.startswith(query_token):
                best = max(best, 0.94)
            elif len(query_token) >= 4:
                best = max(best, difflib.SequenceMatcher(None, query_token, name_token).ratio())
        token_scores.append(best)
    if token_scores and all(score >= 0.78 for score in token_scores):
        return sum(token_scores) / len(token_scores)

    # Only accept close spellings for single-word searches; never use weak whole-name similarity.
    if len(query_tokens) == 1 and len(normalized_query) >= 4:
        best = max(
            (difflib.SequenceMatcher(None, normalized_query, token).ratio()
             for token in name_tokens),
            default=0.0,
        )
        if best >= 0.82:
            return best
    return 0.0


def discover_apps(query: str, limit: int = 8):
    """Find matching installed apps and Start Menu shortcuts without launching them."""
    query = " ".join(str(query).casefold().split())
    if not query:
        return "Tell me the application name to search for."
    entries = []
    seen = set()
    for folder in _shortcut_dirs():
        if folder.is_dir():
            try:
                for path in folder.rglob("*.lnk"):
                    name = path.stem
                    if any(word in name.casefold() for word in IGNORED_APP_NAMES):
                        continue
                    identity = str(path).casefold()
                    if identity not in seen:
                        entries.append({"name": name, "target": str(path), "source": "Start Menu shortcut"})
                        seen.add(identity)
            except OSError:
                pass
    for entry in _registry_apps():
        identity = (entry["name"] + "|" + entry["target"]).casefold()
        if identity not in seen:
            entries.append(entry)
            seen.add(identity)

    scored = []
    for item in entries:
        score = _app_name_match_score(query, item["name"])
        if score >= 0.78:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["name"].casefold(), pair[1]["source"]))
    matches = [item for _, item in scored[:max(1, min(int(limit), 12))]]
    if not matches:
        return f"I couldn't find an installed app matching '{query}'. Try its name as it appears in the Start Menu."
    header = f"Found {len(matches)} matching installed application entry/entries for '{query}':"
    details = "\n".join(
        f"{i+1}. {item['name']} — {item['source']} — {item['target']}"
        for i, item in enumerate(matches)
    )
    return header + "\n" + details + "\nNo application was launched."


def _resolve_exact_app(query: str):
    text = " ".join(str(query).casefold().split())
    if not text:
        return None
    # Reuse the same inventory but retain structured candidates.
    entries = []
    for folder in _shortcut_dirs():
        if folder.is_dir():
            try:
                for path in folder.rglob("*.lnk"):
                    if not any(word in path.stem.casefold() for word in IGNORED_APP_NAMES):
                        entries.append({"name": path.stem, "target": str(path), "source": "Start Menu shortcut"})
            except OSError:
                pass
    entries.extend(_registry_apps())
    ranked = []
    for item in entries:
        score = _app_name_match_score(text, item["name"])
        if score >= 0.78:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: -pair[0])
    if not ranked:
        return None, []
    best = ranked[0][0]
    choices = [item for score, item in ranked if score >= max(0.58, best - 0.08)][:5]
    if len(choices) > 1 and choices[0]["name"].casefold() != text:
        return None, choices
    return choices[0], choices


def _load_sessions():
    data = _read_json(SESSIONS_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_session(name: str, pid: int | None, target: str):
    sessions = _load_sessions()
    sessions[name.casefold()] = {"name": name, "pid": pid, "target": target, "started": time.time()}
    _write_json(SESSIONS_FILE, sessions)


def launch_discovered_app(app_name: str):
    """Launch a matched Start Menu shortcut or verified executable path."""
    if os.name != "nt":
        return "Installed-app discovery is supported on Windows only."
    resolved = _resolve_exact_app(app_name)
    if not resolved:
        return "I couldn't find that app in the Start Menu or Windows app registry."
    item, choices = resolved
    if item is None:
        return "I found several possible matches. Please say one exact app name: " + ", ".join(x["name"] for x in choices)
    target = item["target"]
    before_hwnds = {window["hwnd"] for window in _visible_windows()}
    try:
        path = Path(target.strip('"'))
        if path.suffix.casefold() == ".lnk":
            os.startfile(str(path))
            pid = None
            # Associate newly created top-level windows with this launch when possible.
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                new_windows = [w for w in _visible_windows() if w["hwnd"] not in before_hwnds]
                if new_windows:
                    pid = new_windows[-1]["pid"]
                    break
                time.sleep(0.2)
        else:
            # Registry uninstall metadata can point to a folder; do not execute a folder.
            if not path.is_file() or path.suffix.casefold() not in (".exe", ".com", ".bat", ".cmd"):
                return f"Found {item['name']}, but its registry entry did not resolve to a launchable file."
            if path.suffix.casefold() in (".bat", ".cmd"):
                return "This app entry points to a script shortcut; I won't execute it as an application."
            process = subprocess.Popen([str(path)], cwd=str(path.parent), shell=False,
                                       close_fds=True,
                                       creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) |
                                       getattr(subprocess, "CREATE_NO_WINDOW", 0))
            pid = process.pid
        _save_session(item["name"], pid, target)
        return f"Launch request sent for {item['name']} using {item['source']}."
    except OSError as exc:
        return f"Could not launch {item['name']}: {exc}"


def _visible_windows():
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    results = []
    enum_callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @enum_callback_type
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(min(length + 1, 1024))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            results.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": buffer.value})
        return True

    user32.EnumWindows(callback, 0)
    return results


def close_discovered_app(app_name: str):
    """Send WM_CLOSE to matching app windows; never force-kill an arbitrary process."""
    if os.name != "nt":
        return "Window-aware app closing is supported on Windows only."
    query = " ".join(str(app_name).casefold().split())
    if not query:
        return "Tell me which application window to close."
    sessions = _load_sessions()
    session = sessions.get(query)
    pids = set()
    if session and session.get("pid"):
        pids.add(int(session["pid"]))
    for proc in __import__("psutil").process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").casefold()
            exe = (proc.info.get("exe") or "").casefold()
            if query in name or query in Path(exe).stem.casefold():
                pids.add(int(proc.info["pid"]))
        except Exception:
            continue
    windows = _visible_windows()
    matches = [w for w in windows if w["pid"] in pids or query in w["title"].casefold()]
    if not matches:
        return f"I couldn't find an open window for {app_name}."
    user32 = ctypes.windll.user32
    sent = 0
    for window in matches:
        if user32.IsWindow(window["hwnd"]):
            user32.PostMessageW(window["hwnd"], 0x0010, 0, 0)  # WM_CLOSE
            sent += 1
    if sent:
        return f"Sent a normal close request to {sent} {app_name} window(s). Unsaved work may cause the app to ask what to do."
    return f"No matching {app_name} window could be closed."


def run_diagnostic(command_id: str):
    key = str(command_id).strip().casefold()
    command = SAFE_DIAGNOSTICS.get(key)
    if not command:
        return "That diagnostic is not in the approved read-only command list."
    try:
        result = subprocess.run(command, cwd=str(_project_root()), capture_output=True, text=True,
                                timeout=25, check=False, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = (result.stdout or "").strip()
        if result.stderr:
            output = (output + "\n" + result.stderr.strip()).strip()
        return f"{key} exited with code {result.returncode}.\n{output[:5000] or '(no output)'}"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{key} failed: {exc}"


def run_project_python(relative_path: str, arguments: str = ""):
    """Run an explicitly requested .py file inside the selected project, with a hidden window."""
    try:
        root = _project_root()
        script = (root / str(relative_path)).resolve()
        if root not in script.parents or script.suffix.casefold() != ".py" or not script.is_file():
            return "Python execution is limited to an existing .py file inside the configured project folder."
        if script.stat().st_size > 200_000:
            return "That Python file exceeds the 200 KB execution limit."
        # Never interpret arguments as shell syntax; support only simple whitespace-separated args.
        import shlex
        args = shlex.split(str(arguments), posix=False)
        if len(args) > 12 or any(len(arg) > 120 for arg in args):
            return "Too many or overly long script arguments."
        command = [os.environ.get("PYTHON", "py"), "-E", "-s", str(script), *args]
        result = subprocess.run(command, cwd=str(root), capture_output=True, text=True,
                                timeout=45, check=False, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = (result.stdout or "").strip()
        if result.stderr:
            output = (output + "\nSTDERR:\n" + result.stderr.strip()).strip()
        return f"Python script {script.relative_to(root)} exited with code {result.returncode}.\n{output[:6000] or '(no output)'}"
    except subprocess.TimeoutExpired:
        return "Python script stopped because it exceeded the 45-second time limit."
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return f"Could not run that Python script: {exc}"


def resolve_spoken_python_path(spoken_path: str):
    """Resolve a spoken .py filename against real project files; return a unique relative path or None."""
    raw = str(spoken_path or "").strip().strip('"“”‘’').strip()
    if not raw:
        return None

    # Common speech-to-text variants: "test dot py", "testa py", "test ty".
    value = raw.casefold().replace("\\", "/")
    value = re.sub(r"\s*\b(dot|period|point)\b\s*", ".", value)
    value = re.sub(r"\s*(?:p\s*y|pee\s*why|p why|py)\s*$", ".py", value)
    value = re.sub(r"\s*(?:ty|tie)\s*$", ".py", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"\.{2,}py$", ".py", value)
    if not value.endswith(".py"):
        value += ".py"

    root = _project_root()
    exact = (root / value).resolve()
    if root in exact.parents and exact.is_file() and exact.suffix.casefold() == ".py":
        return exact.relative_to(root).as_posix()

    ignored = {".git", ".venv", "venv", "__pycache__", "site-packages", "node_modules"}
    candidates = []
    try:
        for path in root.rglob("*.py"):
            try:
                relative = path.relative_to(root)
                if any(part.casefold() in ignored for part in relative.parts):
                    continue
                candidates.append((relative.as_posix(), path.stem.casefold()))
            except (OSError, ValueError):
                continue
    except OSError:
        return None

    requested_stem = Path(value).stem.casefold()
    if not requested_stem:
        return None
    ranked = sorted(
        ((difflib.SequenceMatcher(None, requested_stem, stem).ratio(), rel)
         for rel, stem in candidates),
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.80:
        return None
    if len(ranked) > 1 and ranked[1][0] >= ranked[0][0] - 0.06:
        return None
    return ranked[0][1]


def command_is_blocked(command: str):
    value = str(command).strip().casefold()
    return any(re.search(pattern, value, re.IGNORECASE) for pattern in DANGEROUS_COMMAND_PATTERNS)


def load_skills():
    data = _read_json(SKILLS_FILE, [])
    return [item for item in data if isinstance(item, dict) and item.get("name") and item.get("trigger") and item.get("procedure")] if isinstance(data, list) else []


def save_skill(name: str, trigger: str, procedure: str):
    name = " ".join(str(name).split())[:80]
    trigger = " ".join(str(trigger).split())[:180]
    procedure = str(procedure).strip()[:2000]
    if not name or not trigger or not procedure:
        return "A skill needs a name, a phrase that triggers it, and a procedure."
    skills = load_skills()
    if any(item["name"].casefold() == name.casefold() for item in skills):
        return "A skill with that name already exists. Edit it in Manage skills."
    skills.append({"name": name, "trigger": trigger, "procedure": procedure, "enabled": True, "created": int(time.time())})
    _write_json(SKILLS_FILE, skills[-100:])
    return f"Saved skill '{name}'. It is a reusable written procedure, not executable code."


def forget_skill(name: str):
    skills = load_skills()
    kept = [item for item in skills if item["name"].casefold() != str(name).strip().casefold()]
    if len(kept) == len(skills):
        return f"No saved skill named '{name}' was found."
    _write_json(SKILLS_FILE, kept)
    return f"Removed skill '{name}'."


def matching_skills(user_text: str):
    text = " ".join(str(user_text).casefold().split())
    matches = []
    for skill in load_skills():
        if not skill.get("enabled", True):
            continue
        trigger = str(skill["trigger"]).casefold()
        if trigger in text:
            matches.append(skill)
    return matches[:5]


def skills_context(user_text: str):
    matches = matching_skills(user_text)
    if not matches:
        return ""
    return "\n\nUser-approved learned procedures (guidance only; do not execute code from them):\n" + "\n".join(
        f"- {item['name']} (trigger: {item['trigger']}): {item['procedure']}" for item in matches
    )


def replace_skills(skills):
    clean = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name", "")).split())[:80]
        trigger = " ".join(str(item.get("trigger", "")).split())[:180]
        procedure = str(item.get("procedure", "")).strip()[:2000]
        if name and trigger and procedure:
            clean.append({"name": name, "trigger": trigger, "procedure": procedure, "enabled": bool(item.get("enabled", True)), "created": int(item.get("created", time.time()))})
    _write_json(SKILLS_FILE, clean[:100])
    return len(clean[:100])
