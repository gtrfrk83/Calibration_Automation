@echo off
cd /d "%~dp0"
REM Starts the Calibration Suite. Close this window to quit.
py -3 Calibration_Procedure_Manager.py
if errorlevel 1 (
  echo.
  echo The program could not start. If it says Python was not found, install Python 3 from python.org
  echo ^(tick "Add python.exe to PATH"^), then run this again.
  pause
)
