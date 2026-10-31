
"""J.A.R.V.I.S. Desktop - Windows system tray voice assistant.

Hotkey -> microphone -> speech recognition -> OpenRouter -> Fish Audio TTS.
Uses sounddevice instead of PyAudio for microphone recording.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import keyboard
import numpy as np
import sounddevice as sd
import speech_recognition as sr

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QStyle,
    QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from jarvis_intelligence import (TOOL_DEFINITIONS, execute_tool, load_history, save_history, recall_memory, capture_screen_data_url)


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
LOG_FILE = ROOT / "jarvis.log"

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULTS = {
    "FISH_API_KEY": "",
    "OPENROUTER_API_KEY": "",
    "FISH_VOICE_ID": "41f0953d7a6b4c078445c7e65d620eeb",
    "FISH_MODEL": "s2.1-pro-free",
    "OPENROUTER_MODEL": "apodex/apodex-1.1-mini:free",
    "OPENROUTER_MODELS": "recursive/flint-v1.0:free,xingchen-agi/xing4.0-29b-a4b:free,nvidia/nemotron-3.5-super-vl:free,liquid/lfm-2.5-2.6b:free,thinkingmachines/inkling-small:free",
    "JARVIS_CALLS_YOU": "sir",
    "JARVIS_HOTKEY": "ctrl+shift+space",
    "JARVIS_SPEECH_LANGUAGE": "en-US",
    "JARVIS_VOICE_VOLUME": "0.85",
    "JARVIS_VOICE_SPEED": "1.0",
}

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.25
MAX_RECORD_SECONDS = 25
SILENCE_SECONDS = 1.25
START_TIMEOUT_SECONDS = 8


def log(message: str):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
    try:
        # Keep the current log bounded; retain one previous log as a backup.
        if LOG_FILE.exists() and LOG_FILE.stat().st_size >= 1_000_000:
            backup = ROOT / "jarvis.log.1"
            try:
                backup.unlink(missing_ok=True)
                LOG_FILE.replace(backup)
            except OSError:
                pass
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_env() -> dict:
    values = {}

    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(
            encoding="utf-8-sig"
        ).splitlines():

            line = raw.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def load_settings() -> dict:
    settings = dict(DEFAULTS)
    settings.update(read_env())
    return settings


def save_settings(updates: dict):
    settings = read_env()
    settings.update(updates)

    lines = ["# JARVIS desktop settings"]

    for key, value in settings.items():
        # Prevent accidental multi-line .env entries.
        value = str(value).replace("\r", "").replace("\n", "")
        lines.append(f"{key}={value}")

    ENV_FILE.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8"
    )


class AssistantError(Exception):
    pass


_history = load_history()
_history_lock = threading.Lock()


def system_prompt(cfg: dict) -> str:
    title = cfg.get("JARVIS_CALLS_YOU", "sir").strip() or "sir"

    return (
        "You are J.A.R.V.I.S., a concise desktop AI assistant. "
        f'Address the user as "{title}". '
        "Be calm, precise and helpful. "
        "Your response will be spoken aloud, so use natural spoken language. "
        "Use desktop tools when they help. Only capture the screen when the user explicitly asks about visible screen content. Never launch an app unless asked. Only save a memory when the user clearly asks you to remember it. "
        "Avoid markdown, lists, emojis, URLs and code unless requested. "
        f"The local date and time is "
        f"{time.strftime('%A, %B %d, %Y, %I:%M %p')}."
    )


MODEL_CATALOG = {
    "recursive/flint-v1.0:free": "coding and software engineering",
    "xingchen-agi/xing4.0-29b-a4b:free": "reasoning, planning and desktop tool use",
    "nvidia/nemotron-3.5-super-vl:free": "screen, image and document understanding",
    "liquid/lfm-2.5-2.6b:free": "quick, lightweight questions and extraction",
    "thinkingmachines/inkling-small:free": "general assistant, reasoning and multimodal tasks",
    "thinkingmachines/inkling:free": "general agentic tasks (not enabled by default)",
}

MODEL_COOLDOWNS = {}
MODEL_COOLDOWN_LOCK = threading.Lock()


def configured_models(cfg: dict) -> list[str]:
    raw = cfg.get("OPENROUTER_MODELS", DEFAULTS["OPENROUTER_MODELS"])
    models = [item.strip() for item in str(raw).split(",") if item.strip()]
    # Preserve user order while removing duplicates and unknown model IDs.
    valid = []
    for model in models:
        if model in MODEL_CATALOG and model not in valid and model != "thinkingmachines/inkling:free":
            valid.append(model)
    if not valid:
        valid = [
            "recursive/flint-v1.0:free",
            "xingchen-agi/xing4.0-29b-a4b:free",
            "nvidia/nemotron-3.5-super-vl:free",
            "liquid/lfm-2.5-2.6b:free",
            "thinkingmachines/inkling-small:free",
        ]
    return valid


def route_models(cfg: dict, user_text: str) -> list[str]:
    """Pick a task-appropriate first model, then retain all others as fallbacks."""
    text = user_text.casefold()
    models = configured_models(cfg)

    vision_terms = (
        "screen", "screenshot", "monitor", "on my display", "what's on",
        "what is on", "image", "picture", "photo", "diagram", "document",
        "read this image", "look at this",
    )
    coding_terms = (
        "code", "coding", "program", "script", "python", "javascript",
        "typescript", "html", "css", "debug", "bug", "stack trace",
        "traceback", "github", "repository", "repo", "function", "api",
        "compile", "build error", "refactor", "sql", "powershell",
    )
    reasoning_terms = (
        "reason", "reasoning", "think through", "analyze", "analyse",
        "compare", "evaluate", "plan", "strategy", "complex", "math",
        "prove", "why does", "tradeoff", "trade-off",
    )
    desktop_terms = (
        "cpu", "ram", "memory usage", "gpu", "disk space", "battery",
        "running processes", "running apps", "open ", "launch ",
        "computer", "desktop", "task manager",
    )

    if any(term in text for term in vision_terms):
        preferred = [
            "nvidia/nemotron-3.5-super-vl:free",
            "thinkingmachines/inkling-small:free",
            "xingchen-agi/xing4.0-29b-a4b:free",
        ]
    elif any(term in text for term in coding_terms):
        preferred = [
            "recursive/flint-v1.0:free",
            "xingchen-agi/xing4.0-29b-a4b:free",
            "thinkingmachines/inkling-small:free",
            "nvidia/nemotron-3.5-super-vl:free",
        ]
    elif any(term in text for term in reasoning_terms):
        preferred = [
            "xingchen-agi/xing4.0-29b-a4b:free",
            "nvidia/nemotron-3.5-super-vl:free",
            "thinkingmachines/inkling-small:free",
            "recursive/flint-v1.0:free",
        ]
    elif any(term in text for term in desktop_terms):
        preferred = [
            "xingchen-agi/xing4.0-29b-a4b:free",
            "thinkingmachines/inkling-small:free",
            "nvidia/nemotron-3.5-super-vl:free",
            "recursive/flint-v1.0:free",
        ]
    elif len(text.split()) <= 12:
        preferred = [
            "liquid/lfm-2.5-2.6b:free",
            "thinkingmachines/inkling-small:free",
            "xingchen-agi/xing4.0-29b-a4b:free",
        ]
    else:
        preferred = [
            "thinkingmachines/inkling-small:free",
            "xingchen-agi/xing4.0-29b-a4b:free",
            "liquid/lfm-2.5-2.6b:free",
            "recursive/flint-v1.0:free",
        ]

    ordered = [model for model in preferred if model in models]
    ordered.extend(model for model in models if model not in ordered)

    with MODEL_COOLDOWN_LOCK:
        ready = [model for model in ordered if MODEL_COOLDOWNS.get(model, 0) <= time.monotonic()]
    # If every model is cooling down, try the preferred order rather than stopping.
    return ready or ordered


def openrouter_post(cfg: dict, payload: dict, candidates: list[str] | None = None) -> dict:
    key = cfg.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise AssistantError("OpenRouter API key is missing. Open Settings to add it.")

    candidates = candidates or configured_models(cfg)
    failures = []

    for model in candidates:
        request_payload = dict(payload)
        request_payload["model"] = model
        request = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(request_payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost",
                "X-Title": "JARVIS Desktop",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read())

            problem = data.get("error")
            if isinstance(problem, dict):
                raise AssistantError(str(problem.get("message") or problem))

            choices = data.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            if not message or not (message.get("content") or message.get("tool_calls")):
                raise AssistantError("Provider returned an empty response.")

            log(f"AI model selected: {model}")
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS.pop(model, None)
            return {"message": message, "model": model}

        except urllib.error.HTTPError as err:
            detail = err.read()[:700].decode("utf-8", "replace")
            failures.append(f"{model}: HTTP {err.code} {detail[:220]}")
            # Authentication, billing, and malformed-request errors affect the
            # whole account/request; model switching will not fix them.
            if err.code in (401, 402, 403):
                break
            cooldown = 900 if err.code == 429 else 90 if err.code >= 500 else 30
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS[model] = time.monotonic() + cooldown
            continue

        except (urllib.error.URLError, TimeoutError) as err:
            failures.append(f"{model}: connection/timeout: {err}")
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS[model] = time.monotonic() + 45
            continue

        except (json.JSONDecodeError, AssistantError) as err:
            failures.append(f"{model}: {err}")
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS[model] = time.monotonic() + 60
            continue

    summary = " | ".join(failures[-5:])
    raise AssistantError("Every available JARVIS model failed. " + summary)


def think(cfg: dict, user_text: str) -> str:
    with _history_lock:
        history = list(_history)
    messages = [{"role": "user", "content": user_text}]
    memory_context = recall_memory()
    system = system_prompt(cfg)
    if memory_context != "No saved memories yet.":
        system += "\n\nSaved user memory (use only when relevant):\n" + memory_context
    request_messages = [{"role": "system", "content": system}, *history, *messages]
    candidates = route_models(cfg, user_text)
    log("Model route: " + " -> ".join(candidates))

    for _ in range(4):
        payload = {
            "model": candidates[0],
            "messages": request_messages,
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "max_tokens": 1200,
        }
        try:
            result = openrouter_post(cfg, payload, candidates)
        except AssistantError as err:
            # Some free model/provider routes reject function calling. Retry as plain chat.
            detail = str(err).casefold()
            unsupported_tools = any(term in detail for term in (
                "tool", "function", "unsupported", "not support", "unknown parameter"
            ))
            if not unsupported_tools:
                raise
            fallback_payload = {
                "model": candidates[0],
                "messages": request_messages,
                "max_tokens": 1200,
            }
            result = openrouter_post(cfg, fallback_payload, candidates)
        message = result.get("message") or {}
        log("Response generated by: " + str(result.get("model", "unknown")))
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            request_messages.append(message)
            for call in tool_calls:
                function = call.get("function") or {}
                name = function.get("name", "")
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        arguments = {}
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                if name == "describe_screen":
                    explicit_screen_request = any(term in user_text.casefold() for term in (
                        "screen", "screenshot", "display", "what's on my monitor",
                        "what is on my monitor", "visible window",
                    ))
                    tool_result = (
                        execute_tool(name, arguments) if explicit_screen_request
                        else "Screen capture is blocked because the latest user request did not explicitly ask about screen content."
                    )
                else:
                    tool_result = execute_tool(name, arguments)
                request_messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": str(tool_result)[:5000],
                })
                if name == "describe_screen" and explicit_screen_request:
                    # Screen contents are only captured after an explicit user request.
                    screen_data = capture_screen_data_url()
                    request_messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this screenshot and answer the user's screen-related question. Do not infer private details that are not visible."},
                            {"type": "image_url", "image_url": {"url": screen_data}},
                        ],
                    })
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AssistantError("The AI model returned an empty response.")
        reply = " ".join(content.split())
        with _history_lock:
            _history.extend([{"role": "user", "content": user_text},
                             {"role": "assistant", "content": reply}])
            del _history[:-80]
            save_history(_history)
        return reply
    raise AssistantError("JARVIS reached its tool-call limit. Try a more specific request.")


def fish_tts(cfg: dict, text: str) -> bytes:
    key = cfg.get("FISH_API_KEY", "").strip()

    if not key:
        raise AssistantError(
            "Fish Audio API key is missing. Add it in Settings."
        )

    body = json.dumps({
        "text": text,
        "reference_id": cfg.get(
            "FISH_VOICE_ID",
            DEFAULTS["FISH_VOICE_ID"]
        ),
        "format": "mp3",
        "mp3_bitrate": 128,
        "normalize": True,
        "latency": "balanced",
    }).encode("utf-8")

    request = urllib.request.Request(
        FISH_TTS_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "model": cfg.get(
                "FISH_MODEL",
                DEFAULTS["FISH_MODEL"]
            ),
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            audio = response.read()

    except urllib.error.HTTPError as err:
        detail = err.read()[:500].decode("utf-8", "replace")
        raise AssistantError(
            f"Fish Audio error {err.code}: {detail}"
        ) from err

    except (urllib.error.URLError, TimeoutError) as err:
        raise AssistantError(
            f"Could not reach Fish Audio: {err}"
        ) from err

    if not audio:
        raise AssistantError("Fish Audio returned empty audio.")

    return audio


def record_until_release(stop_event: threading.Event) -> np.ndarray:
    """Record while the configured push-to-talk hotkey remains held."""
    blocks = queue.Queue()

    def callback(indata, frames, timing, status):
        blocks.put(indata.copy())

    captured = []
    started = False
    start_time = time.monotonic()
    ambient_levels = []

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=int(SAMPLE_RATE * BLOCK_SECONDS),
            callback=callback,
        ):
            while not stop_event.is_set():
                elapsed = time.monotonic() - start_time

                if elapsed >= MAX_RECORD_SECONDS:
                    break

                try:
                    block = blocks.get(timeout=0.1)
                except queue.Empty:
                    if not started and elapsed >= START_TIMEOUT_SECONDS:
                        raise AssistantError(
                            "No speech detected. Check your microphone and try again."
                        )
                    continue

                captured.append(block)
                level = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))

                if not started:
                    if elapsed < 0.7:
                        ambient_levels.append(level)
                    ambient = float(np.median(ambient_levels)) if ambient_levels else 0.0
                    threshold = max(280.0, ambient * 2.8)
                    if level >= threshold:
                        started = True

        if not started or not captured:
            raise AssistantError(
                "No speech detected. Hold the keybind while speaking, then release it."
            )

        return np.concatenate(captured, axis=0)

    except AssistantError:
        raise
    except Exception as err:
        raise AssistantError(
            f"Microphone error: {err}. Check Windows microphone permissions and input device."
        ) from err


class Bridge(QObject):
    status = Signal(str)
    transcript = Signal(str)
    response = Signal(str)
    error = Signal(str)
    audio_ready = Signal(bytes)
    hotkey_pressed = Signal()
    hotkey_released = Signal()
    processing_finished = Signal()


class SettingsDialog(QDialog):

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)

        self.setWindowTitle("J.A.R.V.I.S. Settings")
        self.setMinimumWidth(500)

        self.fields = {}
        self.existing_secrets = {
            "OPENROUTER_API_KEY": settings.get("OPENROUTER_API_KEY", ""),
            "FISH_API_KEY": settings.get("FISH_API_KEY", ""),
        }

        layout = QVBoxLayout(self)
        form = QFormLayout()

        fields = [
            ("OPENROUTER_API_KEY", "OpenRouter API key", True),
            ("OPENROUTER_MODELS", "OpenRouter model pool (comma-separated)", False),
            ("FISH_API_KEY", "Fish Audio API key", True),
            ("FISH_VOICE_ID", "Fish Audio voice ID", False),
            ("FISH_MODEL", "Fish Audio model", False),
            ("JARVIS_HOTKEY", "Global keybind", False),
            ("JARVIS_CALLS_YOU", "How JARVIS addresses you", False),
            ("JARVIS_SPEECH_LANGUAGE", "Speech language", False),
            ("JARVIS_VOICE_VOLUME", "Voice volume (0.0-1.0)", False),
            ("JARVIS_VOICE_SPEED", "Voice speed (0.5-2.0)", False),
        ]

        for key, label, secret in fields:
            edit = QLineEdit("" if secret else settings.get(key, ""))

            if secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.setPlaceholderText("Leave blank to keep the saved key")

            if key == "JARVIS_HOTKEY":
                edit.setPlaceholderText(
                    "Example: ctrl+shift+space"
                )

            if key == "JARVIS_SPEECH_LANGUAGE":
                edit.setPlaceholderText("Example: en-US")

            self.fields[key] = edit
            form.addRow(label, edit)

        layout.addLayout(form)

        note = QLabel(
            "Settings are saved in a .env file beside jarvis.py. "
            "API keys are hidden. Leave a key field blank to keep its current value."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        save = QPushButton("Save settings")

        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)

        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout.addLayout(buttons)

    def values(self) -> dict:
        values = {
            key: field.text().strip()
            for key, field in self.fields.items()
        }
        for key, old_value in self.existing_secrets.items():
            if not values.get(key):
                values[key] = old_value
        return values


class JarvisApp(QObject):

    def __init__(self, app: QApplication):
        super().__init__()

        self.app = app
        self.settings = load_settings()

        self.bridge = Bridge()

        self.bridge.status.connect(self.set_status)
        self.bridge.transcript.connect(self.show_transcript)
        self.bridge.response.connect(self.show_response)
        self.bridge.error.connect(self.show_error)
        self.bridge.audio_ready.connect(self.play_audio)
        self.bridge.hotkey_pressed.connect(self.start_listening)
        self.bridge.hotkey_released.connect(self.stop_listening)
        self.bridge.processing_finished.connect(self.finish_processing)

        # busy remains true through TTS playback, preventing overlapping sessions.
        self.busy = False
        self.listening = False
        self.stop_event = None
        self.hotkey_handles = []

        self.activity_window = None

        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)
        self._apply_voice_settings()

        self.audio_temp_path = None
        self.player.mediaStatusChanged.connect(self.on_media_status)
        self.player.errorOccurred.connect(self.on_player_error)

        self.tray = QSystemTrayIcon(self._make_icon(), app)
        self.tray.setToolTip("J.A.R.V.I.S. - Starting")

        menu = QMenu()

        self.listen_action = QAction("Start / stop listening", menu)
        self.listen_action.triggered.connect(self.toggle_listening)
        menu.addAction(self.listen_action)

        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        test_action = QAction("Test Fish Audio voice", menu)
        test_action.triggered.connect(self.test_voice)
        menu.addAction(test_action)

        activity_action = QAction("View activity", menu)
        activity_action.triggered.connect(self.show_activity)
        menu.addAction(activity_action)

        menu.addSeparator()

        exit_action = QAction("Exit J.A.R.V.I.S.", menu)
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(exit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

        self.register_hotkey()
        self.set_status("Ready")

        if (
            not self.settings.get("OPENROUTER_API_KEY")
            or not self.settings.get("FISH_API_KEY")
        ):
            self.tray.showMessage(
                "J.A.R.V.I.S. setup",
                "Right-click the tray icon and open Settings "
                "to add your API keys.",
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )

    def _make_icon(self) -> QIcon:
        return self.app.style().standardIcon(
            QStyle.StandardPixmap.SP_ComputerIcon
        )

    @Slot(str)
    def set_status(self, message: str):
        if message == "__reset_listen_action__":
            self.listen_action.setText("Start / stop listening")
            return

        self.tray.setToolTip(f"J.A.R.V.I.S. - {message}")
        log(message)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_listening()

    @Slot()
    def toggle_listening(self):
        if self.listening:
            self.stop_listening()
        else:
            self.start_listening()

    def register_hotkey(self):
        for handle in self.hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self.hotkey_handles.clear()

        hotkey = self.settings.get(
            "JARVIS_HOTKEY",
            DEFAULTS["JARVIS_HOTKEY"]
        ).strip()

        try:
            # One callback starts capture on key-down; the other ends it
            # when the complete combination is released.
            press_handle = keyboard.add_hotkey(
                hotkey,
                lambda: self.bridge.hotkey_pressed.emit(),
                suppress=False,
                trigger_on_release=False,
            )
            release_handle = keyboard.add_hotkey(
                hotkey,
                lambda: self.bridge.hotkey_released.emit(),
                suppress=False,
                trigger_on_release=True,
            )
            self.hotkey_handles.extend([press_handle, release_handle])
            self.set_status(f"Ready - hold {hotkey} to talk")

        except Exception as err:
            self.bridge.error.emit(
                f"Could not register keybind '{hotkey}': {err}. Try ctrl+shift+space."
            )

    @Slot()
    def start_listening(self):
        # Pressing push-to-talk during playback interrupts the current reply.
        if self.busy:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.stop()
                self._delete_audio_temp()
                self.busy = False
                self.listening = False
            else:
                return

        self.busy = True
        self.listening = True
        self.stop_event = threading.Event()
        self.listen_action.setText("Stop listening")
        self.bridge.status.emit("Listening - hold the keybind and speak")

        threading.Thread(
            target=self._listen_worker,
            args=(self.stop_event,),
            daemon=True
        ).start()

    @Slot()
    def stop_listening(self):
        if self.listening and self.stop_event is not None:
            self.stop_event.set()
            self.bridge.status.emit("Processing your speech...")

    @Slot()
    def finish_processing(self):
        self.busy = False
        self.listening = False
        self.stop_event = None
        self.listen_action.setText("Start listening")
        self.bridge.status.emit("Ready")

    def _listen_worker(self, stop_event: threading.Event):
        audio_queued = False
        try:
            self.bridge.status.emit("Listening - hold the keybind and speak")
            raw_audio = record_until_release(stop_event)

            audio = sr.AudioData(raw_audio.tobytes(), SAMPLE_RATE, 2)
            self.bridge.status.emit("Transcribing speech...")
            recognizer = sr.Recognizer()

            try:
                spoken_text = recognizer.recognize_google(
                    audio,
                    language=load_settings().get("JARVIS_SPEECH_LANGUAGE", "en-US")
                )
            except sr.UnknownValueError as err:
                raise AssistantError("I couldn't understand that. Please try again.") from err
            except sr.RequestError as err:
                raise AssistantError(f"Speech recognition service error: {err}") from err

            if not spoken_text.strip():
                raise AssistantError("No speech was detected.")

            self.bridge.transcript.emit(spoken_text)
            self.bridge.status.emit("Thinking...")
            reply = think(load_settings(), spoken_text)
            self.bridge.response.emit(reply)

            self.bridge.status.emit("Generating Fish Audio voice...")
            audio_data = fish_tts(load_settings(), reply)
            audio_queued = True
            self.bridge.audio_ready.emit(audio_data)

        except Exception as err:
            self.bridge.error.emit(str(err))
        finally:
            # Successful audio is still busy until playback ends.
            if not audio_queued:
                self.bridge.processing_finished.emit()

    @Slot(str)
    def show_transcript(self, text: str):
        log(f"You: {text}")

        self.tray.showMessage(
            "You said",
            text[:240],
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )

        self._append_activity(f"You: {text}")

    @Slot(str)
    def show_response(self, text: str):
        log(f"J.A.R.V.I.S.: {text}")

        self.tray.showMessage(
            "J.A.R.V.I.S.",
            text[:240],
            QSystemTrayIcon.MessageIcon.Information,
            5000
        )

        self._append_activity(f"J.A.R.V.I.S.: {text}")

    @Slot(str)
    def show_error(self, message: str):
        log(f"ERROR: {message}")

        self.tray.showMessage(
            "J.A.R.V.I.S. error",
            message[:300],
            QSystemTrayIcon.MessageIcon.Warning,
            6000
        )

        self._append_activity(f"ERROR: {message}")

    def _apply_voice_settings(self):
        try:
            volume = max(0.0, min(1.0, float(self.settings.get("JARVIS_VOICE_VOLUME", "0.85"))))
            speed = max(0.5, min(2.0, float(self.settings.get("JARVIS_VOICE_SPEED", "1.0"))))
        except (TypeError, ValueError):
            volume, speed = 0.85, 1.0
        self.audio_output.setVolume(volume)
        self.player.setPlaybackRate(speed)

    @Slot(bytes)
    def play_audio(self, audio_data: bytes):
        try:
            self.player.stop()
            self._delete_audio_temp()

            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            handle.write(audio_data)
            handle.close()
            self.audio_temp_path = handle.name

            self.player.setSource(QUrl.fromLocalFile(self.audio_temp_path))
            self._apply_voice_settings()
            self.player.play()
            self.set_status("Speaking")

        except Exception as err:
            self.show_error(f"Could not play Fish Audio output: {err}")
            self._delete_audio_temp()
            self.finish_processing()

    @Slot()
    def on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._delete_audio_temp()
            self.finish_processing()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.show_error("The generated audio could not be played.")
            self._delete_audio_temp()
            self.finish_processing()

    @Slot(object, str)
    def on_player_error(self, error, error_string):
        self.show_error(f"Audio playback error: {error_string}")
        self._delete_audio_temp()
        self.finish_processing()

    def _delete_audio_temp(self):
        if (
            self.audio_temp_path
            and os.path.exists(self.audio_temp_path)
        ):
            try:
                os.unlink(self.audio_temp_path)
            except OSError:
                pass

        self.audio_temp_path = None

    @Slot()
    def open_settings(self):
        dialog = SettingsDialog(load_settings())

        if dialog.exec() == QDialog.DialogCode.Accepted:
            updates = dialog.values()

            save_settings(updates)

            self.settings = load_settings()
            self._apply_voice_settings()
            self.register_hotkey()

            self.tray.showMessage(
                "Settings saved",
                "Your J.A.R.V.I.S. settings have been updated.",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )

    @Slot()
    def test_voice(self):
        if self.busy:
            self.tray.showMessage(
                "J.A.R.V.I.S.",
                "Wait until the current listen or voice playback finishes.",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )
            return

        self.busy = True
        threading.Thread(target=self._test_voice_worker, daemon=True).start()

    def _test_voice_worker(self):
        audio_queued = False
        try:
            self.bridge.status.emit("Testing Fish Audio...")
            data = fish_tts(
                load_settings(),
                "Hello. J.A.R.V.I.S. voice test complete."
            )
            audio_queued = True
            self.bridge.audio_ready.emit(data)
        except Exception as err:
            self.bridge.error.emit(str(err))
        finally:
            if not audio_queued:
                self.bridge.processing_finished.emit()

    @Slot()
    def show_activity(self):
        if self.activity_window is None:
            self.activity_window = QWidget()
            self.activity_window.setWindowTitle(
                "J.A.R.V.I.S. Activity"
            )
            self.activity_window.resize(650, 420)

            layout = QVBoxLayout(self.activity_window)

            self.activity_text = QTextEdit()
            self.activity_text.setReadOnly(True)
            if LOG_FILE.exists():
                try:
                    self.activity_text.setPlainText(
                        LOG_FILE.read_text(encoding="utf-8", errors="replace")
                    )
                except OSError:
                    pass

            layout.addWidget(self.activity_text)

            clear_button = QPushButton("Clear activity")
            clear_button.clicked.connect(self.clear_activity)

            layout.addWidget(clear_button)

        self.activity_window.show()
        self.activity_window.raise_()
        self.activity_window.activateWindow()

    def _append_activity(self, text: str):
        if self.activity_window is not None:
            self.activity_text.append(text)

    @Slot()
    def clear_activity(self):
        if self.activity_window is not None:
            self.activity_text.clear()
        try:
            LOG_FILE.write_text("", encoding="utf-8")
        except OSError as err:
            self.show_error(f"Could not clear the activity log: {err}")

    @Slot()
    def exit_app(self):
        if self.stop_event is not None:
            self.stop_event.set()
        for handle in self.hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self.hotkey_handles.clear()

        self.player.stop()
        self._delete_audio_temp()
        self.tray.hide()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("J.A.R.V.I.S.")
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "J.A.R.V.I.S.",
            "Windows system tray is not available."
        )
        return

    jarvis = JarvisApp(app)  # Keep the QObject alive for the entire event loop.
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
