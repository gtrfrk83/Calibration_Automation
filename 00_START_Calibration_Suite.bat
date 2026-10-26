@echo off
rem Starts the Calibration Suite in the Qt look. Double-click this file.
rem The procedure windows follow CALSUITE_UI; set it to tk (or delete the next line) to get the Tk windows back.
set CALSUITE_UI=qt
cd /d "%~dp0"

rem Pick ONE Python and use it for everything (the check, the install and the program), so a PySide6 installed
rem with "pip" for one Python is never looked for in another (the usual cause of "No module named PySide6").
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python 3 was not found. Install Python 3 from python.org ^(tick "Add python.exe to PATH"^), then run this again.
  pause
  exit /b 1
)

%PY% -c "import PySide6" >nul 2>&1
if errorlevel 1 (
  echo.
  echo PySide6 is not installed for the Python this file uses:
  %PY% -c "import sys; print('  ' + sys.executable + '  (Python ' + sys.version.split()[0] + ')')"
  echo Installing it now into that same Python ...
  %PY% -m pip install PySide6
  %PY% -c "import PySide6" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo PySide6 still could not be loaded. Send the lines above to the person who maintains the suite.
    echo ^(PySide6 supports Python 3.9 to 3.13; a newer Python than that needs an older one installed next to it.^)
    pause
    exit /b 1
  )
)

%PY% Calibration_Procedure_Manager_qt.py
if errorlevel 1 (
  echo.
  echo The Manager stopped with an error. See the message above.
  pause
)
