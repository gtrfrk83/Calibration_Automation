@echo off
rem Starts the Calibration Suite in the Qt look. Double-click this file.
rem The procedure windows follow CALSUITE_UI; set it to tk (or delete the next line) to get the Tk windows back.
set CALSUITE_UI=qt
cd /d "%~dp0"
python Calibration_Procedure_Manager_qt.py
if errorlevel 1 (
  echo.
  echo The Manager stopped with an error. If it says No module named PySide6, run: pip install PySide6
  pause
)
