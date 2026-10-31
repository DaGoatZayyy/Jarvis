# J.A.R.V.I.S. Desktop

A Windows system-tray voice assistant that records your voice while a global key combination is held, transcribes it, sends the text to an OpenRouter model, and speaks the reply with Fish Audio.

## Features

- Runs in the Windows system tray without keeping a console window open.
- Global push-to-talk keybind.
- Hold the keybind and speak; release it to submit your recording.
- Google Speech Recognition transcription through the SpeechRecognition library.
- OpenRouter chat completions with a short rolling conversation history.
- Fish Audio text-to-speech playback.
- Tray notifications, settings dialog, voice test, and activity log.
- Activity log rotation to keep the current log file bounded.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer.
- A microphone and a working Windows audio output device.
- An OpenRouter API key.
- A Fish Audio API key.
- Internet access for speech recognition and both AI services.

## Installation

1. Download or clone this repository.
2. Open a terminal in the project folder.
3. Install the Python dependencies:

   ```powershell
   py -m pip install --upgrade pip
   py -m pip install -r requirements.txt
   ```

4. Copy the example configuration to your private local configuration:

   ```powershell
   Copy-Item .env.example .env
   ```

5. Open `.env` in a text editor and add your own API keys:

   - `OPENROUTER_API_KEY`: your OpenRouter API key.
   - `FISH_API_KEY`: your Fish Audio API key.

   The remaining settings already have example/default values. Do not upload your real `.env` file to GitHub or share it in screenshots.

6. Start JARVIS:

   ```powershell
   .\run.bat
   ```

   The batch file starts Python with `pythonw`, so the app runs without a persistent command window. You can also run `py jarvis.py` while troubleshooting to see startup errors in a terminal.

## Push-to-talk

The default keybind is:

```text
ctrl+shift+space
```

1. Press and hold the complete key combination.
2. Speak while continuing to hold it.
3. Release the combination when you have finished speaking.
4. JARVIS records until release, transcribes the recording, asks the configured OpenRouter model for a response, generates speech with Fish Audio, and plays the response.

The maximum recording duration is 25 seconds. If no speech is detected, JARVIS reports an error instead of sending an empty recording.

You can change the keybind from the tray icon's **Settings** menu. Use the syntax accepted by the Python `keyboard` package, such as `ctrl+shift+space` or `alt+space`. Some global keyboard hooks may require running the app with appropriate Windows permissions. Avoid choosing a key combination already used by another application.

You can also start a one-off listen from the tray menu. The push-to-talk keybind is the recommended way to control exactly when recording stops.

## Configuration reference

| Setting | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter credential |
| `OPENROUTER_MODEL` | OpenRouter model identifier |
| `FISH_API_KEY` | Fish Audio credential |
| `FISH_VOICE_ID` | Fish Audio voice/reference ID |
| `FISH_MODEL` | Fish Audio model |
| `JARVIS_HOTKEY` | Global push-to-talk combination |
| `JARVIS_CALLS_YOU` | Name/title used when addressing you |
| `JARVIS_SPEECH_LANGUAGE` | Speech recognition language, e.g. `en-US` |

You can edit `.env` directly or use **Settings** from the tray menu. In the settings window, API key fields are intentionally blank; leaving a key field blank preserves the currently saved key.

## Activity log

JARVIS writes activity to `jarvis.log` beside `jarvis.py`. The activity window loads the existing log when opened. Clearing activity clears the current log file too. When the log reaches approximately 1 MB, the previous log is rotated to `jarvis.log.1`.

The log can contain recognized speech and AI responses. Review it before sharing diagnostic files.

## Privacy and data handling

This project uses online services:

- Microphone audio is sent to Google's speech recognition service through `recognize_google()` for transcription.
- Recognized text and conversation context are sent to OpenRouter.
- The AI response text is sent to Fish Audio to generate speech.

Do not speak passwords, API keys, financial details, or other sensitive information to the assistant. Review the privacy terms of the services you choose to use.

## Troubleshooting

- **No microphone detected:** Check Windows microphone permissions and the default input device under Windows Sound settings.
- **No speech detected:** Hold the keybind while speaking; check microphone input level and try a different input device.
- **Keybind does not work:** Try another combination, check for conflicts with other apps, and check whether Windows permissions are blocking the global keyboard hook.
- **OpenRouter errors:** Verify the API key, model ID, account limits, and internet connection.
- **Fish Audio errors:** Verify the Fish Audio key, voice ID, model, and account limits.
- **No sound:** Check the Windows output device and volume. Use **Test Fish Audio voice** in the tray menu.
- **Need diagnostic output:** Run `py jarvis.py` from PowerShell instead of using `run.bat`.

## Project files

- `jarvis.py` — tray application, recording, transcription, AI requests, and playback.
- `requirements.txt` — Python dependencies.
- `run.bat` — launches JARVIS without a persistent console.
- `.env.example` — safe configuration template with no credentials.
- `.env` — your private local settings; intentionally ignored by Git.
