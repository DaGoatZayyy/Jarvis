# JARVIS

JARVIS is a Windows desktop voice assistant that runs in the system tray. It lets you talk to an AI using a microphone, hear spoken responses, and perform selected desktop actions. It supports OpenRouter cloud models or a local Ollama model.

## Installation

### Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Microphone and audio output
- Fish Audio API key for spoken responses
- OpenRouter API key for cloud AI, or Ollama installed with a model downloaded for local AI

### Install

1. Download the repository from GitHub:

   ```powershell
   git clone https://github.com/DaGoatZayyy/Jarvis.git
   cd Jarvis
   ```

   Or use **Code → Download ZIP**, extract it, and open PowerShell in the extracted folder.

2. Install the Python dependencies:

   ```powershell
   py -m pip install --upgrade pip
   py -m pip install -r requirements.txt
   ```

3. Create your private configuration file:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Open `.env` and add your own `FISH_API_KEY`. Add `OPENROUTER_API_KEY` if you plan to use OpenRouter. Do not share or commit this file.

5. For local AI, install Ollama from https://ollama.com, then download a model. Example:

   ```powershell
   ollama pull qwen2.5:7b
   ```

6. Start JARVIS by double-clicking the single launcher:

   ```text
   run.bat
   ```

   JARVIS starts in the Windows system tray without leaving a terminal window open. The launcher uses `pyw` or `pythonw`. A separate `run.vbs` file is not needed. For troubleshooting, run `py jarvis.py` from PowerShell.

## Updating JARVIS

If you installed it with Git:

```powershell
cd path\to\Jarvis
git pull
py -m pip install -r requirements.txt
```

Then restart JARVIS using `run.bat`. Your local `.env`, conversation history, memory, and other local data should remain in place because they are not tracked by Git.

If you installed from a ZIP, download the latest ZIP and replace the application files. Keep your existing `.env` and any local JSON data files; do not overwrite them with repository templates. If dependencies changed, run:

```powershell
py -m pip install -r requirements.txt
```

## Features that are working

The following core features have been exercised in local tests. Individual behavior can still depend on Windows configuration, microphone quality, API availability, and the selected AI model.

- Windows system-tray app that runs without keeping a command window open.
- Push-to-talk using `Ctrl+Shift+Space`.
- Optional local **Hey Jarvis** wake-word detection.
- Speech-to-text and spoken replies using Google Speech Recognition and Fish Audio.
- Switch between OpenRouter and local Ollama for chat.
- Open common Windows apps and perform supported desktop actions.
- Search installed apps and Start Menu shortcuts; launch discovered apps and request a normal window close.
- Create files in the configured project folder.
- Run an existing Python script inside the configured project folder after the exact confirmation phrase. Script output and exit code are reported.
- Run the supported read-only system diagnostics, such as `ipconfig` and `tasklist`.

## Experimental features

These features are implemented in the project but have not been fully tested across different systems and use cases. They may be incomplete or behave inconsistently. This section should be updated as features are tested and become reliable.

- Persistent memory management and long-term saved facts.
- Learned skills that save reusable written workflows.
- Project-aware coding assistance, including reading and editing project files.
- Python plugin loading and third-party plugin tools.
- On-demand screen capture and AI analysis of the primary display or active foreground window.
- Default-browser website opening from commands such as “Open gmail.com” (implemented; awaiting broader Windows testing).
- Hands-free follow-up conversation mode.
- Advanced model routing and automatic OpenRouter fallback behavior.
- Natural-language file search in the configured coding project folder.
- Clipboard text assistance (read-only; only when explicitly requested).
- Local one-time, daily, and weekly reminders with Windows tray notifications.
- Windows sign-in startup toggle in Settings.
- Optional NVIDIA GPU telemetry and less common Windows automation actions.

## Basic usage

- **Push-to-talk:** Hold `Ctrl+Shift+Space`, speak, then release.
- **Wake word:** Say “Hey Jarvis,” pause briefly, and then say your request.
- **App search:** Say “Find Spotify.” Search reports matches and does not launch the app.
- **File search:** Ask JARVIS to find a file by its name or words in its contents in the configured project folder.
- **Clipboard:** Ask JARVIS to summarize or explain the text currently copied. Clipboard content is read only when requested.
- **Reminders:** Ask JARVIS to create a reminder, list reminders, or cancel one. One-time, daily, and weekly reminders are supported while JARVIS is running.
- **Windows startup:** Enable or disable “Start JARVIS when I sign in to Windows” in Settings.
- **Open or close an app:** Say “Open Spotify” or “Close Spotify.”
- **Open a website:** Say “Open gmail.com” or “Go to youtube.com” to open it in your default browser.
- **Run a project script:** Say “Run script test.py,” review the resolved filename, then say the exact confirmation, for example `confirm run script test.py`.

Python scripts can make changes to your computer. The confirmation is always required, even if **No Confirms** is enabled. Script execution is limited to an existing `.py` file inside the configured project folder.

## AI providers

Right-click the JARVIS tray icon to switch between OpenRouter and Ollama. Use **Local AI Settings** to configure the Ollama server and choose an installed model.

When Ollama is selected, chat requests go to the configured local Ollama server; JARVIS does not silently send those requests to OpenRouter. Speech recognition and voice generation remain separate services in either chat mode.

## Safety and privacy notes

- Never commit or share your real `.env` file. It contains private API credentials.
- Microphone audio is sent to Google Speech Recognition for transcription.
- Chat text is sent to the selected AI provider: OpenRouter or your configured Ollama server.
- Spoken response text is sent to Fish Audio for voice generation.
- Screen captures are only taken for an explicit screen-analysis request and are sent to the selected AI provider.
- Conversation history, memory, skills, and activity logs may contain personal information. Review them before sharing diagnostic files.
- The Python runner is restricted to the configured project folder and requires confirmation. Do not run scripts you do not understand.

## Credits and license

Created by **DaGoatZayyy**.

JARVIS is released under the **MIT License**. You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies of the software, provided that the original copyright and license notice are included with copies or substantial portions of the software.

If you use or modify this project, please credit **DaGoatZayyy** and link back to the original repository:

https://github.com/DaGoatZayyy/Jarvis

See [LICENSE](LICENSE) for the full license text.
