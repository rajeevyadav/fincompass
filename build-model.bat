@echo off
REM ============================================================
REM  Build a real forecast model from free public data (Windows)
REM  Fetches market history, engineers features, trains, validates.
REM  NOTE: FinCompass only ACTIVATES a model that passes strict
REM  validation gates. A real model may be REJECTED (that is the
REM  tool being honest). The evidence engine and screener work
REM  without a validated forecast model.
REM ============================================================
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
call ".venv\Scriptsctivate.bat"
pip install -r requirements.txt >nul
echo Building market dataset (needs internet; a few minutes)...
python toolsuild_market_dataset.py --output datasets\market --profile strict || goto :error
echo Training + validating...
python tools	rain_forecast.py datasets\market --profile strict --name default
echo.
echo Done. If a model was ACTIVATED it is reused automatically on every run.
echo If it was REJECTED, the forecast tab will say so - that is by design.
pause
goto :eof
:error
echo Build failed - see above.
pause
exit /b 1
