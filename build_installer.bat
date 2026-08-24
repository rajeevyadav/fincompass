@echo off
REM Build the windowed exe, then compile the Windows installer with Inno Setup.
REM Requires Inno Setup (free): https://jrsoftware.org/isdl.php  (provides iscc)
setlocal
cd /d "%~dp0"
call build_exe.bat
if not exist "dist\FinCompass.exe" ( echo exe build failed & pause & exit /b 1 )
where iscc >nul 2>&1
if errorlevel 1 (
  echo.
  echo Inno Setup ^(iscc^) not found on PATH. Install it from https://jrsoftware.org/isdl.php
  echo then re-run this script, or open installer\FinCompass.iss in the Inno Setup IDE and Compile.
  pause
  exit /b 1
)
iscc "installer\FinCompass.iss" || ( echo installer build failed & pause & exit /b 1 )
echo.
echo Done. Installer: dist\FinCompass-1.0.0-Setup.exe
pause
