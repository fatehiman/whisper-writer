@echo off
REM Launch WhisperWriter (speech-to-text, English + Persian auto-detect, GPU).
cd /d "%~dp0"
"%~dp0venv\Scripts\pythonw.exe" run.py
