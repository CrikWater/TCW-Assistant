@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\gis_owner.py" status
pause
