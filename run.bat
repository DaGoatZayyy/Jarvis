@echo off
cd /d "%~dp0"
pythonw jarvis.py
if errorlevel 1 pause
