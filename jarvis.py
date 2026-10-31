
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
    "JARVIS_CALLS_YOU": "sir",
    "JARVIS_HOTKEY": "ctrl+shift+space",
    "JARVIS_SPEECH_LANGUAGE": "en-US",
}

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.25
MAX_RECORD_SECONDS = 25
SILENCE_SECONDS = 1.25
START_TIMEOUT_SECONDS = 8


def log(message: str):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
    try:
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


_history = []
_history_lock = threading.Lock()


def system_prompt(cfg: dict) -> str:
    title = cfg.get("JARVIS_CALLS_YOU", "sir").strip() or "sir"

    return (
        "You are J.A.R.V.I.S., a concise desktop AI assistant. "
        f'Address the user as "{title}". '
        "Be calm, precise and helpful. "
        "Your response will be spoken aloud, so use natural spoken language. "
        "Avoid markdown, lists, emojis, URLs and code unless requested. "
        f"The local date and time is "
        f"{time.strftime('%A, %B %d, %Y, %I:%M %p')}."
    )


def openrouter_post(cfg: dict, payload: dict) -> dict:
    key = cfg.get("OPENROUTER_API_KEY", "").strip()

    if not key:
        raise AssistantError(
            "OpenRouter API key is missing. Open Settings to add it."
        )

    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
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

    except urllib.error.HTTPError as err:
        detail = err.read()[:500].decode("utf-8", "replace")
        raise AssistantError(
            f"OpenRouter error {err.code}: {detail}"
        ) from err

    except (urllib.error.URLError, TimeoutError) as err:
        raise AssistantError(
            f"Could not reach OpenRouter: {err}"
        ) from err

    except json.JSONDecodeError as err:
        raise AssistantError(
            "OpenRouter returned invalid JSON."
        ) from err

    choices = data.get("choices") or [{}]
    problem = data.get("error") or choices[0].get("error")

    if isinstance(problem, dict):
        raise AssistantError(
            str(problem.get("message") or problem)
        )

    content = (
        choices[0].get("message") or {}
    ).get("content")

    if not isinstance(content, str) or not content.strip():
        raise AssistantError(
            "The AI model returned an empty response."
        )

    return {"reply": " ".join(content.split())}


def think(cfg: dict, user_text: str) -> str:
    with _history_lock:
        messages = list(_history) + [
            {"role": "user", "content": user_text}
        ]

    payload = {
        "model": cfg.get(
            "OPENROUTER_MODEL",
            DEFAULTS["OPENROUTER_MODEL"]
        ),
        "messages": [
            {"role": "system", "content": system_prompt(cfg)},
            *messages
        ],
        "max_tokens": 1000,
    }

    reply = openrouter_post(cfg, payload)["reply"]

    with _history_lock:
        _history.extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ])
        del _history[:-16]

    return reply


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


def record_until_silence() -> np.ndarray:
    """Record microphone audio without requiring PyAudio."""

    blocks = queue.Queue()

    def callback(indata, frames, timing, status):
        blocks.put(indata.copy())

    captured = []
    started = False
    start_time = time.monotonic()
    last_voice_time = start_time
    ambient_levels = []

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=int(SAMPLE_RATE * BLOCK_SECONDS),
            callback=callback,
        ):
            while True:
                elapsed = time.monotonic() - start_time

                if elapsed > MAX_RECORD_SECONDS + START_TIMEOUT_SECONDS:
                    break

                try:
                    block = blocks.get(timeout=1.0)
                except queue.Empty:
                    if (
                        not started
                        and elapsed > START_TIMEOUT_SECONDS
                    ):
                        raise AssistantError(
                            "No speech detected. Check your microphone."
                        )
                    continue

                captured.append(block)

                level = float(
                    np.sqrt(
                        np.mean(block.astype(np.float32) ** 2)
                    )
                )

                if not started:
                    if elapsed < 0.7:
                        ambient_levels.append(level)

                    ambient = (
                        float(np.median(ambient_levels))
                        if ambient_levels else 0.0
                    )

                    threshold = max(280.0, ambient * 2.8)

                    if level >= threshold:
                        started = True
                        last_voice_time = time.monotonic()

                else:
                    ambient = (
                        float(np.median(ambient_levels))
                        if ambient_levels else 0.0
                    )

                    threshold = max(280.0, ambient * 2.8)

                    if level >= threshold:
                        last_voice_time = time.monotonic()

                    elif (
                        time.monotonic() - last_voice_time
                        >= SILENCE_SECONDS
                    ):
                        break

                if started and elapsed >= MAX_RECORD_SECONDS:
                    break

    except AssistantError:
        raise

    except Exception as err:
        raise AssistantError(
            f"Microphone error: {err}. "
            "Check Windows microphone permissions and input device."
        ) from err

    if not started or not captured:
        raise AssistantError(
            "No speech detected. Press the keybind and speak clearly."
        )

    return np.concatenate(captured, axis=0)


class Bridge(QObject):
    status = Signal(str)
    transcript = Signal(str)
    response = Signal(str)
    error = Signal(str)
    audio_ready = Signal(bytes)
    hotkey_pressed = Signal()


class SettingsDialog(QDialog):

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)

        self.setWindowTitle("J.A.R.V.I.S. Settings")
        self.setMinimumWidth(500)

        self.fields = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        fields = [
            ("OPENROUTER_API_KEY", "OpenRouter API key", True),
            ("OPENROUTER_MODEL", "OpenRouter model", False),
            ("FISH_API_KEY", "Fish Audio API key", True),
            ("FISH_VOICE_ID", "Fish Audio voice ID", False),
            ("FISH_MODEL", "Fish Audio model", False),
            ("JARVIS_HOTKEY", "Global keybind", False),
            ("JARVIS_CALLS_YOU", "How JARVIS addresses you", False),
            ("JARVIS_SPEECH_LANGUAGE", "Speech language", False),
        ]

        for key, label, secret in fields:
            edit = QLineEdit(settings.get(key, ""))

            if secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.setPlaceholderText("Paste API key here")

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
            "API keys are hidden in this window."
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
        return {
            key: field.text().strip()
            for key, field in self.fields.items()
        }


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

        # The keyboard hook emits this signal. It does not directly
        # manipulate Qt widgets from the keyboard thread.
        self.bridge.hotkey_pressed.connect(self.start_listening)

        self.listening = False
        self.state_lock = threading.Lock()
        self.hotkey_handle = None

        self.activity_window = None

        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)

        self.audio_temp_path = None
        self.player.mediaStatusChanged.connect(
            self.on_media_status
        )

        self.tray = QSystemTrayIcon(self._make_icon(), app)
        self.tray.setToolTip("J.A.R.V.I.S. - Starting")

        menu = QMenu()

        self.listen_action = QAction("Start listening", menu)
        self.listen_action.triggered.connect(
            self.start_listening
        )
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
            self.listen_action.setText("Start listening")
            return

        self.tray.setToolTip(f"J.A.R.V.I.S. - {message}")
        log(message)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.start_listening()

    def register_hotkey(self):
        if self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
            except Exception:
                pass

            self.hotkey_handle = None

        hotkey = self.settings.get(
            "JARVIS_HOTKEY",
            DEFAULTS["JARVIS_HOTKEY"]
        ).strip()

        try:
            self.hotkey_handle = keyboard.add_hotkey(
                hotkey,
                lambda: self.bridge.hotkey_pressed.emit(),
                suppress=False,
                trigger_on_release=False,
            )

            self.set_status(f"Ready - hotkey {hotkey}")

        except Exception as err:
            self.bridge.error.emit(
                f"Could not register keybind '{hotkey}': {err}. "
                "Try ctrl+shift+space."
            )

    @Slot()
    def start_listening(self):
        with self.state_lock:
            if self.listening:
                return

            self.listening = True

        self.listen_action.setText("Listening...")
        self.bridge.status.emit("Listening - speak now")

        threading.Thread(
            target=self._listen_worker,
            daemon=True
        ).start()

    def _listen_worker(self):
        try:
            self.bridge.status.emit("Listening - speak now")

            raw_audio = record_until_silence()

            audio = sr.AudioData(
                raw_audio.tobytes(),
                SAMPLE_RATE,
                2
            )

            self.bridge.status.emit("Transcribing speech...")

            recognizer = sr.Recognizer()

            try:
                spoken_text = recognizer.recognize_google(
                    audio,
                    language=load_settings().get(
                        "JARVIS_SPEECH_LANGUAGE",
                        "en-US"
                    )
                )

            except sr.UnknownValueError as err:
                raise AssistantError(
                    "I couldn't understand that. Please try again."
                ) from err

            except sr.RequestError as err:
                raise AssistantError(
                    f"Speech recognition service error: {err}"
                ) from err

            if not spoken_text.strip():
                raise AssistantError("No speech was detected.")

            self.bridge.transcript.emit(spoken_text)

            self.bridge.status.emit("Thinking...")

            reply = think(load_settings(), spoken_text)

            self.bridge.response.emit(reply)

            self.bridge.status.emit(
                "Generating Fish Audio voice..."
            )

            audio_data = fish_tts(load_settings(), reply)

            self.bridge.audio_ready.emit(audio_data)

        except Exception as err:
            self.bridge.error.emit(str(err))

        finally:
            with self.state_lock:
                self.listening = False

            self.bridge.status.emit("__reset_listen_action__")
            self.bridge.status.emit("Ready")

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

    @Slot(bytes)
    def play_audio(self, audio_data: bytes):
        try:
            self._delete_audio_temp()

            handle = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".mp3"
            )

            handle.write(audio_data)
            handle.close()

            self.audio_temp_path = handle.name

            self.player.setSource(
                QUrl.fromLocalFile(self.audio_temp_path)
            )

            self.player.play()
            self.set_status("Speaking")

        except Exception as err:
            self.show_error(
                f"Could not play Fish Audio output: {err}"
            )

    @Slot()
    def on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.set_status("Ready")
            self._delete_audio_temp()

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
            self.register_hotkey()

            self.tray.showMessage(
                "Settings saved",
                "Your J.A.R.V.I.S. settings have been updated.",
                QSystemTrayIcon.MessageIcon.Information,
                3000
            )

    @Slot()
    def test_voice(self):
        threading.Thread(
            target=self._test_voice_worker,
            daemon=True
        ).start()

    def _test_voice_worker(self):
        try:
            self.bridge.status.emit("Testing Fish Audio...")

            data = fish_tts(
                load_settings(),
                "Hello. J.A.R.V.I.S. voice test complete."
            )

            self.bridge.audio_ready.emit(data)

        except Exception as err:
            self.bridge.error.emit(str(err))

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

            layout.addWidget(self.activity_text)

            clear_button = QPushButton("Clear activity")
            clear_button.clicked.connect(
                self.activity_text.clear
            )

            layout.addWidget(clear_button)

        self.activity_window.show()
        self.activity_window.raise_()
        self.activity_window.activateWindow()

    def _append_activity(self, text: str):
        if self.activity_window is not None:
            self.activity_text.append(text)

    @Slot()
    def exit_app(self):
        try:
            if self.hotkey_handle is not None:
                keyboard.remove_hotkey(self.hotkey_handle)
        except Exception:
            pass

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

    JarvisApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
