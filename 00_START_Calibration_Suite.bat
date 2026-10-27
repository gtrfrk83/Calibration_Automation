@echo off
rem Starts the Calibration Suite in the Qt look. Double-click this file.
rem The suite is Qt only (the Tk build was removed).
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
    echo ^(PySide6 may not have a build yet for the very newest Python; install an older Python 3 next to it and run this again.^)
    pause
    exit /b 1
  )
)

rem The other packages the suite uses (instrument I/O, PDF reports, Excel): install any that are missing, into the same Python.
rem A failure here does not stop the program; the suite's own diagnostics list what is still missing.
for %%P in (pyvisa:pyvisa serial:pyserial reportlab:reportlab openpyxl:openpyxl pypdfium2:pypdfium2 PIL:pillow anthropic:anthropic) do for /f "tokens=1,2 delims=:" %%A in ("%%P") do (
  %PY% -c "import %%A" >nul 2>&1
  if errorlevel 1 (
    echo Installing %%B ...
    %PY% -m pip install %%B
  )
)

%PY% Calibration_Procedure_Manager_qt.py
if errorlevel 1 (
  echo.
  echo The Manager stopped with an error. See the message above.
  pause
)
