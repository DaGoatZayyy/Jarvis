# Contributing to JARVIS

Thank you for considering a contribution. JARVIS is an open-source Windows assistant. Contributions can include bug fixes, documentation, reliability improvements, accessibility improvements, and new features.

## Before you start

1. Check existing issues and pull requests to see whether the work is already being discussed.
2. For a substantial feature or architectural change, open an issue first so the direction can be discussed.
3. For small documentation fixes or clearly scoped bug fixes, you can usually proceed directly.

## Development setup

JARVIS currently targets Windows 10 and Windows 11.

1. Fork this repository on GitHub and clone your fork.
2. Create and activate a virtual environment:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```powershell
   py -m pip install --upgrade pip
   py -m pip install -r requirements.txt
   ```
4. Create your local configuration from the example:
   ```powershell
   Copy-Item .env.example .env
   ```
5. Add your own credentials locally if needed. Never commit your .env file or real credentials.
6. Run the app with py jarvis.py while developing. You can also use run.bat for the tray launcher.

## Branches and commits

- Create a focused branch for each change, for example fix/clipboard-routing or feature/reminder-snooze.
- Keep changes small enough to review.
- Use clear commit messages that describe the change.
- Avoid unrelated formatting or refactoring in a feature or bug-fix pull request.

## Code expectations

- Preserve the existing Windows tray-app behavior and user settings.
- Keep provider-specific behavior explicit. Do not silently send local Ollama conversations to a cloud provider.
- Do not log API keys, clipboard contents, private conversation content, or other secrets.
- Treat user-provided file paths and external input carefully.
- Keep confirmation safeguards for actions that can modify files or run scripts.
- Add or update documentation when behavior, settings, dependencies, or setup steps change.
- Do not add dependencies unless needed; explain new dependencies in the pull request.

## Testing

Test the behavior you changed on Windows when possible. In your pull request, list:
- The exact commands or steps you ran.
- The expected result and actual result.
- Windows version and relevant provider/model details when they affect the change.
- Any tests you could not run.

Do not claim a feature is tested if it was only reviewed statically. If a change depends on an API key, model, microphone, audio device, or Windows configuration, explain that dependency.

## Pull request process

1. Push your branch to your fork.
2. Open a pull request targeting the official repository's main branch.
3. Complete the pull request template.
4. Link related issues and include screenshots or sanitized logs when useful.
5. Respond to review feedback and update your branch as needed.

The maintainer reviews all contributions and makes the final decision about merging. A pull request may be declined, revised, or held for testing. Not every proposed feature is guaranteed to be accepted.

## Using JARVIS as a base

You may use, modify, and build on JARVIS subject to the MIT License. Keep the copyright and license notice with copies or substantial portions of the software. Acknowledging the original project and linking to https://github.com/DaGoatZayyy/Jarvis is appreciated and helps others find the upstream project.

## Questions

For project questions and feature discussions, open a GitHub issue. Do not post secrets, private configuration files, or sensitive personal data.
