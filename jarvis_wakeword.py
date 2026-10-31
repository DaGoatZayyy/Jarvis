"""Local Hey Jarvis wake-word detection for the J.A.R.V.I.S. tray app.

Audio is processed on-device. The wake-word listener does not upload or save
microphone audio; normal command transcription follows the existing app flow.
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np
import sounddevice as sd


class WakeWordListener:
    SAMPLE_RATE = 16000
    FRAME_SAMPLES = 1280  # 80 ms frames required by openWakeWord.

    def __init__(self, on_detected, on_error, threshold: float = 0.55):
        self.on_detected = on_detected
        self.on_error = on_error
        self.threshold = threshold
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="JarvisWakeWord",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        self._thread = None

    def _run(self):
        try:
            import openwakeword
            from openwakeword.model import Model

            # Download only the built-in Hey Jarvis model; it is cached locally.
            openwakeword.utils.download_models(model_names=["hey_jarvis_v0.1"])
            model = Model(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx",
            )
            frames = queue.Queue(maxsize=12)

            def audio_callback(indata, frame_count, timing, status):
                if status:
                    # Audio overflows are recoverable; keep the newest frames.
                    pass
                frame = np.asarray(indata[:, 0], dtype=np.int16).copy()
                try:
                    frames.put_nowait(frame)
                except queue.Full:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        frames.put_nowait(frame)
                    except queue.Full:
                        pass

            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=self.FRAME_SAMPLES,
                callback=audio_callback,
            ):
                last_activation = 0.0
                while not self._stop_event.is_set():
                    try:
                        frame = frames.get(timeout=0.15)
                    except queue.Empty:
                        continue

                    scores = model.predict(frame)
                    score = max((float(value) for value in scores.values()), default=0.0)
                    now = time.monotonic()
                    if score >= self.threshold and now - last_activation >= 2.0:
                        last_activation = now
                        self.on_detected()
                        return

        except Exception as exc:
            if not self._stop_event.is_set():
                self.on_error(
                    "Hey Jarvis listener could not start: "
                    f"{exc}. Check microphone permissions and install requirements."
                )
