@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start.ps1" %*
if errorlevel 1 (
  echo.
  echo Matisse could not start. Read the error above and README.md.
  pause
  exit /b 1
)
