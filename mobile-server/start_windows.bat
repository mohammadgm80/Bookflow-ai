@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer was not found.
  echo Install Python 3.11+ from https://www.python.org/downloads/
  pause
  exit /b 1
)
py -3.11 -m venv .venv
if errorlevel 1 (
  echo Python 3.11 was not found. Install Python 3.11 or newer and try again.
  pause
  exit /b 1
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo BookFlow AI 2 is starting...
echo Laptop: http://127.0.0.1:8000
python app.py
pause
