@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Preflight.ps1"
if errorlevel 1 goto finish
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\TCW.ps1" -Action Validate -ExerciseLifecycle
:finish
echo.
echo Review evidence\workstation and evidence\live_validation.
echo Generated answers and citations still require human review.
pause
