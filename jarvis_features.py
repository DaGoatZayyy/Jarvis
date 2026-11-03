"""Local clipboard, file-search and reminder helpers for J.A.R.V.I.S."""
from __future__ import annotations

import ctypes
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REMINDERS_FILE = ROOT / "jarvis_reminders.json"
IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".next", "dist", "build"}
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".ini", ".log", ".csv", ".xml"}


def read_clipboard_text() -> str:
    """Read plain text from the Windows clipboard without changing it."""
    if os.name != "nt":
        return "Clipboard reading is supported on Windows only."
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return "The clipboard is currently busy. Try again in a moment."
    handle = None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return "The clipboard does not currently contain plain text."
        kernel32.GlobalLock.restype = ctypes.c_void_p
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return "Could not access clipboard text."
        try:
            value = ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
        return value[:20000] or "The clipboard is empty."
    finally:
        user32.CloseClipboard()


def search_local_files(query: str, root: str = "") -> str:
    """Search filenames and readable text within the configured project folder."""
    query = " ".join(str(query).casefold().split())
    if not query:
        return "Tell me what file or document you are looking for."
    configured = str(root or os.environ.get("JARVIS_PROJECT_DIR", "")).strip()
    folder = Path(configured).expanduser() if configured else ROOT
    folder = folder.resolve()
    if not folder.is_dir():
        return f"The search folder does not exist: {folder}"
    terms = [term for term in re.findall(r"[a-z0-9_.-]{2,}", query) if term not in {"find", "file", "document", "the", "about", "that", "with"}]
    if not terms:
        terms = [query]
    results = []
    scanned = 0
    for current, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.casefold() not in IGNORED_DIRS]
        for name in files:
            path = Path(current) / name
            scanned += 1
            if scanned > 5000:
                break
            relative = path.relative_to(folder).as_posix()
            haystack = name.casefold()
            score = sum(3 for term in terms if term in haystack)
            if path.suffix.casefold() in TEXT_EXTENSIONS:
                try:
                    if path.stat().st_size <= 500_000:
                        content = path.read_text(encoding="utf-8", errors="ignore").casefold()
                        score += sum(min(content.count(term), 5) for term in terms)
                    else:
                        content = ""
                except OSError:
                    content = ""
            else:
                content = ""
            if score:
                snippet = ""
                if content:
                    pos = min((content.find(term) for term in terms if term in content), default=-1)
                    if pos >= 0:
                        snippet = " — " + " ".join(content[max(0, pos-70):pos+180].split())
                results.append((score, relative, snippet))
        if scanned > 5000:
            break
    results.sort(key=lambda item: (-item[0], item[1].casefold()))
    if not results:
        return f"No matching files found in {folder}. Scanned up to {scanned} files."
    return "Search results in " + str(folder) + ":\n" + "\n".join(f"- {name}{snippet}" for _, name, snippet in results[:10])


def _load_reminders():
    try:
        data = json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict) and item.get("id") and item.get("title") and item.get("due_at")]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def _save_reminders(items):
    temp = REMINDERS_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(REMINDERS_FILE)


def create_reminder(title: str, due_at: str, repeat: str = "none") -> str:
    title = " ".join(str(title).split())[:180]
    if not title:
        return "A reminder needs a title."
    try:
        due = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
        if due.tzinfo is None:
            return "Reminder time must include a timezone offset."
        due = due.astimezone(timezone.utc)
    except ValueError:
        return "Use an ISO 8601 reminder time with a timezone offset."
    if due.timestamp() <= time.time():
        return "That reminder time is in the past. Choose a future time."
    repeat = str(repeat).casefold().strip()
    if repeat not in {"none", "daily", "weekly"}:
        return "Repeat must be none, daily, or weekly."
    items = _load_reminders()
    item = {"id": str(int(time.time() * 1000)), "title": title, "due_at": due.isoformat(), "repeat": repeat, "created_at": datetime.now(timezone.utc).isoformat()}
    items.append(item)
    _save_reminders(items)
    return f"Reminder saved: {title} at {due.astimezone().strftime('%Y-%m-%d %I:%M %p %Z')} ({repeat})."


def list_reminders() -> str:
    items = sorted(_load_reminders(), key=lambda item: item["due_at"])
    if not items:
        return "You have no pending reminders."
    return "\n".join(f"- {item['id']}: {item['title']} — {datetime.fromisoformat(item['due_at']).astimezone().strftime('%Y-%m-%d %I:%M %p %Z')} ({item.get('repeat', 'none')})" for item in items[:30])


def cancel_reminder(reminder_id: str) -> str:
    items = _load_reminders()
    kept = [item for item in items if str(item["id"]) != str(reminder_id)]
    if len(kept) == len(items):
        return "No reminder matched that ID."
    _save_reminders(kept)
    return "Reminder cancelled."


def due_reminders():
    now = datetime.now(timezone.utc)
    items = _load_reminders()
    due_items = []
    remaining = []
    changed = False
    for item in items:
        try:
            due = datetime.fromisoformat(item["due_at"])
        except (ValueError, TypeError):
            changed = True
            continue
        if due <= now:
            due_items.append(item)
            repeat = item.get("repeat", "none")
            if repeat in {"daily", "weekly"}:
                from datetime import timedelta
                step = timedelta(days=1 if repeat == "daily" else 7)
                while due <= now:
                    due += step
                item["due_at"] = due.isoformat()
                remaining.append(item)
            else:
                changed = True
        else:
            remaining.append(item)
    if changed or len(remaining) != len(items):
        _save_reminders(remaining)
    return due_items
