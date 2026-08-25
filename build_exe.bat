@echo off
REM ============================================================
REM  Build a standalone FinCompass.exe (Windows, PyInstaller)
REM  Output: dist\FinCompass.exe
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r requirements.txt || goto :error
pip install -r requirements-build.txt || goto :error

echo Building FinCompass.exe (this can take a few minutes)...
pyinstaller --noconfirm --clean --onefile --windowed --name FinCompass --version-file version_info.txt ^
  --add-data "static;static" ^
  --add-data "config;config" ^
  --add-data "datasets\market-seed;datasets\market-seed" ^
  --add-data "models;models" ^
  --add-data "adaptive_models;adaptive_models" ^
  --add-data "legal;legal" ^
  --add-data "docs;docs" ^
  --add-data "PRIVACY.md;." ^
  --collect-submodules uvicorn ^
  --collect-submodules sklearn ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan.on ^
  run_fincompass.py || goto :error

echo.
echo Done. Executable: dist\FinCompass.exe
echo Double-click it to run FinCompass.
pause
goto :eof

:error
echo.
echo Build failed - see the message above.
pause
exit /b 1
