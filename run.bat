@echo off
REM ============================================================
REM  FinCompass - one-click local run (Windows)
REM  Double-click this file. It switches to its own folder,
REM  sets up a virtual environment, installs dependencies,
REM  and starts the local server, then opens your browser.
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not on PATH. Install Python 3.11 or 3.12 from python.org, then retry.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
)

echo Installing / updating dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || goto :error

if not exist ".env" (
  echo Creating .env from .env.example ...
  copy /y ".env.example" ".env" >nul
)

echo.
echo Starting FinCompass at http://127.0.0.1:8000  (press Ctrl+C to stop)
echo.
start "" "http://127.0.0.1:8000"
python -m uvicorn api:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo FinCompass failed to start - see the message above.
pause
exit /b 1
