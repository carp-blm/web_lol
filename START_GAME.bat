@echo off
cd /d "%~dp0"
echo Open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C to stop the local preview.
python scripts\serve.py
pause
