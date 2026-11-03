@echo off
setlocal
cd /d "%~dp0"

REM Start JARVIS with the windowless Python launcher.
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" /B pyw -3 "%~dp0jarvis.py"
    exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" /B pythonw "%~dp0jarvis.py"
    exit /b 0
)

echo JARVIS could not find pyw or pythonw.
echo Install Python 3.10 or newer, then try again.
pause
