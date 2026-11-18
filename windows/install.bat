@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Creating Python virtual environment...
py -3.11 -m venv .venv
if errorlevel 1 (
  echo Python 3.11 not found. Trying Python 3.12...
  py -3.12 -m venv .venv
)
if errorlevel 1 (
  echo Python 3.11 or 3.12 was not found.
  echo Install Python 3.11 or 3.12 (64-bit) and enable Add Python to PATH.
  pause
  exit /b 1
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo Installation failed. Check your internet connection and Python version.
  pause
  exit /b 1
)
echo.
echo Installation completed. Run start.bat to launch BookFlow AI.
pause
