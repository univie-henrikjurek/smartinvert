@echo off
rem Smartboard PDF Inverter - one-command starter (Windows).
rem
rem Usage:
rem   start.bat -i input.pdf -o output.pdf   run the CLI with your arguments
rem   start.bat -i inputs\ -o outputs\       batch: whole directory
rem   start.bat                              open the GUI (file or folder)
rem
rem No Python installation is required: the starter uses uv, which downloads
rem a managed CPython 3.12 on first use.  If uv cannot be installed (e.g. no
rem network), it falls back to the system Python (>= 3.9).
setlocal EnableExtensions
cd /d "%~dp0"

echo Smartboard PDF Inverter
echo.

rem ------------------------------------------------------------ [1/3] uv --
set "UV="
set "CLASSIC=0"
set "PY="

where uv >nul 2>nul
if not errorlevel 1 (
    set "UV=uv"
    goto setup_done
)
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
    goto setup_done
)

echo [1/3] uv not found - installing (one-time, ~15 MB) ...
powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
where uv >nul 2>nul
if not errorlevel 1 (
    set "UV=uv"
    goto setup_done
)
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
    goto setup_done
)

echo [1/3] uv unavailable - falling back to system Python (3.9+) ...
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY (
    %PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
    if errorlevel 1 goto no_python
    set "CLASSIC=1"
    goto setup_done
)
:no_python
echo error: no uv and no suitable system Python (3.9+) found.
echo hint : install Python 3.9+ from https://www.python.org/downloads/
pause
exit /b 1

:setup_done

rem -------------------------------------------- [2/3] venv + dependencies -
if exist ".venv\Scripts\python.exe" goto install_deps
if "%CLASSIC%"=="1" (
    echo [2/3] creating .venv with system Python + dependencies ^(first run downloads ~80 MB^) ...
    %PY% -m venv .venv
) else (
    echo [2/3] creating .venv with Python 3.12 + dependencies ^(first run downloads ~80 MB; later starts are instant^) ...
    %UV% venv --python 3.12 .venv
)

:install_deps
if "%CLASSIC%"=="1" (
    .venv\Scripts\python.exe -m pip install --quiet .
) else (
    %UV% pip install --python .venv\Scripts\python.exe --quiet .
)
if errorlevel 1 (
    echo.
    echo error: installing the dependencies failed - check your internet connection.
    pause
    exit /b 1
)

rem ------------------------------------------------------------ [3/3] run -
if not "%~1"=="" goto run_cli

echo [3/3] starting GUI ...
.venv\Scripts\python.exe -m smartboard_invert.gui
if errorlevel 1 pause
exit /b 0

:run_cli
echo [3/3] running ...
.venv\Scripts\smartinvert.exe %*
exit /b %errorlevel%
