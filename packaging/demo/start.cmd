@echo off
if not exist "%~dp0start.ps1" (
  echo Please extract the zip first ^(right-click ^> Extract All^), then run this file from the extracted folder.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
