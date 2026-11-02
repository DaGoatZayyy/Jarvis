# J.A.R.V.I.S. Desktop

A Windows system-tray voice assistant with push-to-talk, switchable OpenRouter or local Ollama AI, Fish Audio speech, local desktop intelligence, persistent conversation history and optional on-demand screen analysis.

## Features

- Runs in the Windows system tray without a persistent console window.
- Hold-to-talk global keybind; releasing it submits the recording.
- Optional always-on local "Hey Jarvis" wake-word listener; after activation, it records a command and stops automatically after a short silence. Wake-word detection runs locally on-device.
- Speech transcription through Google Speech Recognition (unchanged in both AI modes).
- A task-based OpenRouter model pool with automatic failover when OpenRouter is selected.
- A tray-menu **Enable Local AI** toggle to switch to Ollama, plus **Local AI Settings** to configure the server URL and choose from installed models. Provider selection is saved in `.env`.
- Local Ollama chat uses the same system prompt, conversation history, memory and desktop tools where the selected model supports tool calling. Provider selection is fixed for each request: Local AI never silently falls back to OpenRouter.
- General questions and everyday conversation default to Xing4.0; coding requests prefer Recursive Flint; screen/image tasks prefer NVIDIA Nemotron 3.5 Super VL; explicit quick extraction requests prefer Liquid LFM.
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
- **No Confirms** setting in Settings: skips routine confirmation prompts for explicitly requested actions. Exact deletion confirmation and protected/dangerous-operation safeguards are never bypassed.
- Editable long-term memory manager in the tray menu; review, edit, remove or clear saved facts.
- Hands-free conversation mode: after each spoken response, JARVIS listens for a follow-up and returns to idle after a quiet timeout.
- Windows voice actions for File Explorer, Task Manager, Settings, show desktop, volume and locking Windows. Exact common open/close requests are detected locally before the AI call.
- Expanded automation for allowlisted app closing, creating project files/folders, Recycle Bin deletion with exact spoken confirmation, and predefined read-only diagnostic commands.
- Windows app discovery searches Start Menu shortcuts and Windows app registry entries, then launches matched installed apps by their resolved target.
- Window-aware app closing sends a normal close message to matching windows instead of force-killing processes; unsaved-work prompts are left to the app.
- Hidden Python runner can execute an explicitly confirmed existing .py script inside the configured project folder and captures its real exit code/stdout/stderr with a timeout.
- Learned skills: save user-approved reusable written procedures, match them to later requests, and manage/edit/disable them from the tray menu. Skills are guidance text, not executable code.
- Project-aware coding tools to list and read files and apply explicitly requested edits with local backups. Choose the project folder from the tray menu.
- Local Python plugin system: add reviewed plugins to the plugins folder without changing the core application.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer.
- A microphone and working Windows audio output.
- An OpenRouter API key when using OpenRouter, a running Ollama installation and downloaded model when using Local AI, and a Fish Audio API key for voice playback.
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

5. Edit `.env` and enter your own `OPENROUTER_API_KEY` (if using OpenRouter) and `FISH_API_KEY`. The default `OPENROUTER_MODELS` list already contains the model pool; you can keep it as-is.
6. For Local AI, install Ollama from https://ollama.com, start it, then pull a model such as `qwen2.5:7b` with `ollama pull qwen2.5:7b`. In the J.A.R.V.I.S. tray menu, open **Local AI Settings**, refresh installed models, select one, and enable **Local AI**.
7. Start JARVIS:

   ```powershell
   .\run.bat
   ```

The batch file uses `pythonw` so JARVIS runs without a persistent command window. On first startup, openWakeWord may download/cache its wake-word model. For troubleshooting, run `py jarvis.py` from PowerShell to see errors.

**Never commit or share your real `.env` file.** The `.env.example` file contains placeholders only.

## Push-to-talk

Default keybind: `ctrl+shift+space`.

1. Press and hold the complete key combination.
2. Speak while holding it.
3. Release the combination to submit the recording.
4. JARVIS transcribes your speech, asks the AI, generates Fish Audio speech and plays the reply.

## Hey Jarvis wake word

- The wake-word listener starts automatically when JARVIS starts (unless disabled in Settings).
- Say **"Hey Jarvis"**, pause briefly, then speak your request. JARVIS records until it detects about 1.25 seconds of silence, or reaches the 25-second limit.
- Wake-word detection uses openWakeWord locally on your PC. The wake-word audio is not sent to a cloud service. After activation, the captured command still follows Google Speech Recognition, the currently selected AI provider and Fish Audio.
- The microphone remains active for local wake-word detection while JARVIS is idle. Stop JARVIS or set `JARVIS_WAKE_WORD_ENABLED=0` in `.env` to disable it.
- If the wake-word model or microphone cannot initialize, the tray log reports the error; push-to-talk remains available.

Maximum recording duration is 25 seconds. The global keybind can be changed in the tray menu's Settings dialog. The Python `keyboard` package may require appropriate Windows permissions.

## AI provider selection

Right-click the J.A.R.V.I.S. tray icon and use **Enable Local AI** to switch between OpenRouter and Ollama. The checkmark indicates the selected provider. Use **Local AI Settings** to edit the Ollama URL, refresh installed models and choose the model tag. These settings are saved in `.env` and persist across restarts.

When Local AI is enabled, J.A.R.V.I.S. sends AI requests only to the configured Ollama server. If Ollama is unavailable or the model is missing, J.A.R.V.I.S. reports an error; it does not send that request to OpenRouter. Switching providers affects the next request, not a request already in progress. Speech recognition remains Google Speech Recognition and voice generation remains Fish Audio.

Ollama's `/api/tags` endpoint is used to discover installed models and `/api/chat` is used for local conversations. Tool calling and image understanding depend on the selected Ollama model.

## Multi-model routing

JARVIS classifies each request using lightweight keyword rules and puts a suitable model first, followed by the remaining configured models as fallbacks:

| Request type | Preferred model | Why |
| --- | --- | --- |
| Coding, debugging, repository work | `recursive/flint-v1.0:free` | Designed for coding-agent tasks |
| Complex reasoning, planning, analysis | `xingchen-agi/xing4.0-29b-a4b:free` | Reasoning, multi-step planning and tool use |
| Screen, image or document understanding | `nvidia/nemotron-3.5-super-vl:free` | Supports image/video input and tool calling |
| Explicit quick extraction/classification requests | `liquid/lfm-2.5-2.6b:free` | Compact model for lightweight extraction tasks |
| General questions, everyday conversation and default requests | `xingchen-agi/xing4.0-29b-a4b:free` | OpenAI-compatible chat endpoint with reasoning and tool calling |

Inkling Small and full Inkling are excluded because OpenRouter currently restricts their free endpoints to agentic harnesses; they reject JARVIS normal chat-completions requests with HTTP 403. If another configured model returns this model-specific restriction, JARVIS disables it for the current run and continues with the next model. If a model returns a rate limit, provider error, timeout, unavailable-model response or empty answer, JARVIS tries the next configured model. Models that fail are temporarily cooled down so the next request can start with a healthier option. Authentication and account-credit errors stop failover because changing models cannot fix the API key or account.

Edit `OPENROUTER_MODELS` in your .env file or in Settings to change the pool/order. Both Thinking Machines free endpoints are excluded from the normal JARVIS chat pool because OpenRouter restricts them to agentic harnesses. The provider also states that prompts and outputs on those free endpoints may be logged and used to improve its models, so do not route private information through them.

OpenRouter currently documents a free-model account limit of 20 requests per minute and 50 requests per day; the daily allowance can change. Failed requests may also count toward the daily cap. If OpenRouter reports an account-wide daily limit, JARVIS stops retrying because switching models will not bypass it. Check OpenRouter's current rate-limit documentation for the latest rules.

## Windows automation

J.A.R.V.I.S. can search Start Menu shortcuts and Windows app registry entries when an application is not in the basic launch list. Ask it to "find [app]" or "open [app]". If several apps match, it asks you to choose a specific name. For apps it launched, it records the process where possible. Closing uses a normal Windows window-close request (WM_CLOSE), giving apps a chance to ask about unsaved work; it does not force-kill unknown processes.

The hidden runner supports the predefined read-only diagnostics listed below. It can also run an existing Python script inside the configured project folder, but only after you say the exact phrase `confirm run script relative/path.py`. This confirmation is always required, even with No Confirms enabled, because Python scripts can make changes. Script output, errors and exit status are captured; execution has a 45-second limit. Arbitrary CMD/PowerShell text, encoded commands, installers, destructive commands and system/security configuration changes are not enabled.

Learned skills are saved as written procedures in `jarvis_skills.json`. Ask J.A.R.V.I.S. to "save this as a skill" after a workflow succeeds. It will not save a skill unless explicitly requested. Matching skills are added as guidance to later requests. Use **Manage learned skills** in the tray menu to review, edit, disable or remove them. Skills are not Python plugins and cannot execute code.


Ask JARVIS to open or close supported apps, open File Explorer, Task Manager or Settings, show the desktop, adjust or mute volume, or lock Windows. Exact common open/close requests are detected locally before the AI call, so these actions do not rely on the model choosing a tool. App closing is allowlisted. Set a coding project folder to let JARVIS create files and folders there; creation never overwrites existing files. Deletion is restricted to that project folder and moves items to the Windows Recycle Bin. JARVIS requires the exact follow-up phrase confirm delete followed by the relative path. Terminal support is limited to predefined read-only diagnostics such as whoami, hostname, ipconfig, tasklist, systeminfo, and version checks. Arbitrary PowerShell, CMD, scripts, installers, and destructive commands are not supported. Hands-free conversation mode can be enabled from the tray menu. It listens for a follow-up after each spoken reply and ends the session after a quiet/no-speech timeout; turn it off in the tray menu at any time.

## Project-aware coding assistant

Choose **Set coding project folder** from the tray menu. JARVIS can then list project files and read text files to explain code, trace bugs and understand project structure. When you explicitly ask it to edit a file, it can write the proposed content inside that configured folder and creates a `.jarvis.bak` backup of an existing file first. It refuses paths outside the project and blocks common secret/key files. Review edits and backups before running code. The default project directory is the JARVIS application folder until you select another one.

## Plugin system

Choose **Open plugins folder** in the tray menu. Place reviewed Python `.py` plugins in that folder and restart JARVIS to load them. A plugin must expose `register()` and return a list of entries containing an OpenAI-style function `definition` and a Python `handler` callable. Plugin code runs locally with the same permissions as JARVIS; install only code you trust. See `plugins/README.md` for a template.

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

Screen analysis is on-demand, not continuous. The screenshot is captured only after you explicitly ask about visible screen content, and it is sent to the currently selected AI provider for analysis. Do not ask JARVIS to capture screens containing passwords, private messages, financial details or other sensitive information.

### Web search

Search queries are sent to DuckDuckGo. JARVIS receives a small set of result titles and links; it does not automatically open every result.

## Memory and conversation history

- Use **Manage memory** in the tray menu to view, edit, remove or clear saved facts. One memory per line; saving updates `jarvis_memory.json`.
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
| `JARVIS_PROVIDER` | Selected AI provider: `openrouter` or `ollama` (also switchable in the tray menu) |
| `OLLAMA_BASE_URL` | Ollama server URL, default `http://localhost:11434` |
| `OLLAMA_MODEL` | Local model tag, default `qwen2.5:7b` |
| `OLLAMA_KEEP_ALIVE` | How long Ollama keeps the model loaded, default `5m` |
| `OPENROUTER_API_KEY` | OpenRouter credential |
| `OPENROUTER_MODELS` | Comma-separated model pool and fallback order |
| `FISH_API_KEY` | Fish Audio credential |
| `FISH_VOICE_ID` | Fish Audio voice/reference ID |
| `FISH_MODEL` | Fish Audio model |
| `JARVIS_HOTKEY` | Global push-to-talk combination |
| `JARVIS_PROJECT_DIR` | Optional coding project root selected from the tray menu |
| `JARVIS_NO_CONFIRMS` | Skip routine action confirmations (`1` enabled, `0` disabled); does not bypass deletion confirmation or dangerous-operation protections |
| `JARVIS_WAKE_WORD_ENABLED` | Enable local "Hey Jarvis" listener (`1` or `0`) |
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
- With OpenRouter selected, recognized text and conversation context are sent to OpenRouter. With Local AI selected, chat text and context are sent to the configured Ollama server instead.
- AI response text is sent to Fish Audio for speech generation in both AI modes.
- Explicitly requested screen captures are sent to the currently selected AI provider (OpenRouter or the local Ollama server).
- Search queries are sent to DuckDuckGo.
- Conversation history and saved memory are stored locally in JSON files.

Do not speak passwords, API keys, financial details or other sensitive information to JARVIS. Review the privacy terms of the services you use.

## Troubleshooting

- **Microphone unavailable:** Check Windows microphone permissions and the default input device.
- **No speech detected:** Hold the keybind while speaking; check microphone input levels.
- **Keybind not working:** Try another combination and check conflicts or Windows permissions.
- **AI tool calls unavailable:** Some selected models do not support function calling. JARVIS retries as ordinary chat if the provider rejects tools; desktop actions will be unavailable on that request.
- **Ollama unavailable:** Start the Ollama app/service, confirm the URL in Local AI Settings, refresh installed models and make sure the selected model has been pulled.
- **GPU telemetry unavailable:** NVIDIA metrics require the NVIDIA driver utility `nvidia-smi` to be available.
- **No audio:** Check Windows output device and volume. Use **Test Fish Audio voice** in the tray menu.
- **Need diagnostic output:** Run `py jarvis.py` from PowerShell.

## Project files

- `jarvis.py` — tray app, recording, AI requests and playback.
- `jarvis_intelligence.py` — desktop tools, screen capture, web search, memory and history.
- `jarvis_desktop.py` — Windows app discovery, graceful window closing, hidden project-script runner and local learned-skill storage.
- `jarvis_ai.py` — provider abstraction and explicit provider selection.
- `jarvis_local.py` — Ollama connectivity, model discovery and local chat requests.
- `jarvis_plugins.py` — local Python plugin discovery and tool dispatch.
- `plugins/` — reviewed user-installed extension modules.
- `requirements.txt` — Python dependencies.
- `run.bat` — background launch.
- `.env.example` — safe configuration template.
- `.env` — private local credentials and settings; ignored by Git.
- `jarvis_history.json` / `jarvis_memory.json` / `jarvis_skills.json` — local conversation history, saved memory and user-approved learned procedures.
