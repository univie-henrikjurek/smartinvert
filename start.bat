@echo off
rem Smartboard PDF Inverter - one-command starter (Windows).
rem
rem Usage:
rem   start.bat -i input.pdf -o output.pdf   run the CLI with your arguments
rem   start.bat -i inputs\ -o outputs\       batch: whole directory
rem   start.bat                              open the GUI (file or folder)
rem
rem First run creates .venv\ and installs dependencies (~1-2 min); later
rem runs are instant.
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo error: Python 3.10+ not found. Install it from https://www.python.org/downloads/
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment in .venv\ ...
    %PY% -m venv .venv
)

rem Quiet, fast no-op when everything is already installed.
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv\Scripts\python.exe -m pip install --quiet .

if "%~1"=="" (
    .venv\Scripts\python.exe -m smartboard_invert.gui
) else (
    .venv\Scripts\smartinvert.exe %*
)
