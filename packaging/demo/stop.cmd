@echo off
if not exist "%~dp0stop.ps1" (
  echo Please extract the zip first ^(right-click ^> Extract All^), then run this file from the extracted folder.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
pause
