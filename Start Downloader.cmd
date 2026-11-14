@echo off
setlocal
pushd "%~dp0"
where pyw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pyw.exe -3 "%~dp0app.pyw"
    popd
    exit /b
)
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0app.pyw"
    popd
    exit /b
)
where python.exe >nul 2>&1
if not errorlevel 1 (
    python.exe "%~dp0app.pyw"
    if errorlevel 1 pause
    popd
    exit /b
)
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/.
echo During installation, keep Tcl/Tk enabled and add Python to PATH.
pause
popd
