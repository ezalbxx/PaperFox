@echo off
setlocal
pushd "%~dp0.."
set "PYTHONUTF8=1"
set "PAPERFOX_PYTHON=.venv\Scripts\python.exe"
if not exist "%PAPERFOX_PYTHON%" (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        py -3.11 -m venv .venv
        if errorlevel 1 goto failed
    )
)
if not exist ".venv\paperfox-installed" (
    "%PAPERFOX_PYTHON%" -m pip install --no-cache-dir ".[paperfox]"
    if errorlevel 1 goto failed
    type nul > ".venv\paperfox-installed"
)
set "PYTHONPATH=%CD%\src"
"%PAPERFOX_PYTHON%" scripts\paperfox_windows.py %*
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo PaperFox could not start. Check Python and the messages above.
popd
pause
exit /b 1
