# J.A.R.V.I.S. Desktop

A Windows system-tray voice assistant with push-to-talk, OpenRouter AI, Fish Audio speech, local desktop intelligence, persistent conversation history and optional on-demand screen analysis.

## Features

- Runs in the Windows system tray without a persistent console window.
- Hold-to-talk global keybind; releasing it submits the recording.
- Speech transcription through Google Speech Recognition.
- Task-based OpenRouter model routing across five free models, with automatic failover for rate limits, unavailable providers, timeouts and empty responses.
- Coding requests prefer Recursive Flint; complex reasoning prefers Xing4.0; screen/image tasks prefer NVIDIA Nemotron 3.5 Super VL; short quick requests prefer Liquid LFM; general requests prefer Inkling Small.
- The model actually used and the fallback route are recorded in `jarvis.log`.
- Persistent conversation history in `jarvis_history.json`.
- Explicitly requested long-term facts/preferences in `jarvis_memory.json`.
- Desktop tools for CPU, RAM, disk, battery, network totals and optional NVIDIA GPU telemetry.
- Running-process awareness and a restricted app-launch allowlist (Notepad, Calculator, File Explorer, Task Manager, Paint, Settings and Terminal).
- Web search through DuckDuckGo HTML results.
- On-demand screen analysis. A screenshot is captured only when you explicitly ask JARVIS about something visible on your screen.
- Fish Audio voice ID selection plus configurable playback volume and speed.
- Press the push-to-talk hotkey during JARVIS playback to interrupt the spoken response.
- Tray notifications, settings dialog, voice test and activity log.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer.
- A microphone and working Windows audio output.
- An OpenRouter API key and Fish Audio API key.
- Internet access for speech recognition and AI services.

## Installation

1. Download or clone this repository.
2. Open PowerShell in the project folder.
3. Install dependencies:

   ```powershell
   py -m pip install --upgrade pip
   py -m pip install -r requirements.txt
   ```

4. Create your private settings file:

   ```powershell
   Copy-Item .env.example .env
   ```

5. Edit `.env` and enter your own `OPENROUTER_API_KEY` and `FISH_API_KEY`. The default `OPENROUTER_MODELS` list already contains the model pool; you can keep it as-is.
6. Start JARVIS:

   ```powershell
   .\run.bat
   ```

The batch file uses `pythonw` so JARVIS runs without a persistent command window. For troubleshooting, run `py jarvis.py` from PowerShell to see errors.

**Never commit or share your real `.env` file.** The `.env.example` file contains placeholders only.

## Push-to-talk

Default keybind: `ctrl+shift+space`.

1. Press and hold the complete key combination.
2. Speak while holding it.
3. Release the combination to submit the recording.
4. JARVIS transcribes your speech, asks the AI, generates Fish Audio speech and plays the reply.

Maximum recording duration is 25 seconds. The global keybind can be changed in the tray menu's Settings dialog. The Python `keyboard` package may require appropriate Windows permissions.

## Multi-model routing

JARVIS classifies each request using lightweight keyword rules and puts a suitable model first, followed by the remaining configured models as fallbacks:

| Request type | Preferred model | Why |
| --- | --- | --- |
| Coding, debugging, repository work | `recursive/flint-v1.0:free` | Designed for coding-agent tasks |
| Complex reasoning, planning, analysis | `xingchen-agi/xing4.0-29b-a4b:free` | Reasoning, multi-step planning and tool use |
| Screen, image or document understanding | `nvidia/nemotron-3.5-super-vl:free` | Supports image/video input and tool calling |
| Short, simple requests | `liquid/lfm-2.5-2.6b:free` | Compact reasoning model; not selected for coding-heavy tasks |
| General assistant requests | `thinkingmachines/inkling-small:free` | General reasoning, coding and multimodal tasks |

If a model returns a rate limit, provider error, timeout, unavailable-model response or empty answer, JARVIS tries the next configured model. Models that fail are temporarily cooled down so the next request can start with a healthier option. Authentication and account-credit errors stop failover because changing models cannot fix the API key or account.

Edit `OPENROUTER_MODELS` in your .env file or in Settings to change the pool/order. The full `thinkingmachines/inkling:free` endpoint is deliberately excluded: its OpenRouter listing says prompts and outputs are logged and used to improve models, and warns against sending personal or confidential information. JARVIS includes conversation history and may include saved memory, so that endpoint is not a safe automatic fallback for this setup.

Free model availability and rate limits can change. Fallback does not bypass OpenRouter account-wide free-tier limits.

## Desktop intelligence examples

You can ask JARVIS questions such as:

- "What's my CPU and RAM usage?"
- "How much free space is on my system drive?"
- "Is my NVIDIA GPU being used?"
- "What applications are running?"
- "Open Calculator."
- "Search the web for the latest Windows 11 update."
- "What's on my screen?" or "Help me understand this error on my screen."

App launching is restricted to a built-in allowlist. JARVIS does not execute arbitrary terminal commands or launch arbitrary paths.

### Screen privacy

Screen analysis is on-demand, not continuous. The screenshot is captured only after you explicitly ask about visible screen content, and it is sent to your configured OpenRouter model for analysis. Do not ask JARVIS to capture screens containing passwords, private messages, financial details or other sensitive information.

### Web search

Search queries are sent to DuckDuckGo. JARVIS receives a small set of result titles and links; it does not automatically open every result.

## Memory and conversation history

- Conversation history is stored locally in `jarvis_history.json` and reused for context.
- Long-term memory is stored locally in `jarvis_memory.json`.
- Ask JARVIS to remember a non-sensitive preference or fact to save it.
- Ask what it remembers to review saved memory.
- Ask it to forget a saved fact to remove matching entries.

Memory is not intended for passwords, API keys, financial information or other secrets. You can stop JARVIS and delete either JSON file to clear its local data.

## Voice settings

Open Settings from the tray icon:

| Setting | Purpose |
| --- | --- |
| `FISH_VOICE_ID` | Fish Audio voice/reference ID |
| `FISH_MODEL` | Fish Audio model |
| `JARVIS_VOICE_VOLUME` | Playback volume from 0.0 to 1.0 |
| `JARVIS_VOICE_SPEED` | Playback speed from 0.5 to 2.0 |
| `JARVIS_SPEECH_LANGUAGE` | Recognition locale, e.g. `en-US` |

During voice playback, press the push-to-talk hotkey to stop the current reply and begin a new recording.

## Configuration reference

| Setting | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | OpenRouter credential |
| `OPENROUTER_MODELS` | Comma-separated model pool and fallback order |
| `FISH_API_KEY` | Fish Audio credential |
| `FISH_VOICE_ID` | Fish Audio voice/reference ID |
| `FISH_MODEL` | Fish Audio model |
| `JARVIS_HOTKEY` | Global push-to-talk combination |
| `JARVIS_CALLS_YOU` | How JARVIS addresses you |
| `JARVIS_SPEECH_LANGUAGE` | Speech recognition locale |
| `JARVIS_VOICE_VOLUME` | Playback volume, 0.0-1.0 |
| `JARVIS_VOICE_SPEED` | Playback speed, 0.5-2.0 |

You can edit `.env` directly or use the tray Settings dialog. The model-pool field accepts comma-separated IDs. Secret fields are blank in the dialog; leaving them blank preserves the saved credentials.

## Activity log

Activity is written to `jarvis.log` beside `jarvis.py`. The log window loads existing entries. Clearing activity clears the current log file. At approximately 1 MB, the log rotates to `jarvis.log.1`.

The log may contain recognized speech and AI responses. Review it before sharing diagnostics.

## Privacy and data handling

- Microphone audio is sent to Google's speech recognition service for transcription.
- Recognized text and conversation context are sent to OpenRouter.
- AI response text is sent to Fish Audio for speech generation.
- Explicitly requested screen captures are sent to OpenRouter.
- Search queries are sent to DuckDuckGo.
- Conversation history and saved memory are stored locally in JSON files.

Do not speak passwords, API keys, financial details or other sensitive information to JARVIS. Review the privacy terms of the services you use.

## Troubleshooting

- **Microphone unavailable:** Check Windows microphone permissions and the default input device.
- **No speech detected:** Hold the keybind while speaking; check microphone input levels.
- **Keybind not working:** Try another combination and check conflicts or Windows permissions.
- **AI tool calls unavailable:** Some OpenRouter model/provider combinations may not support function calling. JARVIS retries as ordinary chat if the provider rejects tools; desktop actions will be unavailable on that request.
- **GPU telemetry unavailable:** NVIDIA metrics require the NVIDIA driver utility `nvidia-smi` to be available.
- **No audio:** Check Windows output device and volume. Use **Test Fish Audio voice** in the tray menu.
- **Need diagnostic output:** Run `py jarvis.py` from PowerShell.

## Project files

- `jarvis.py` — tray app, recording, AI requests and playback.
- `jarvis_intelligence.py` — desktop tools, screen capture, web search, memory and history.
- `requirements.txt` — Python dependencies.
- `run.bat` — background launch.
- `.env.example` — safe configuration template.
- `.env` — private local credentials and settings; ignored by Git.
- `jarvis_history.json` / `jarvis_memory.json` — local conversation history and saved memory.
