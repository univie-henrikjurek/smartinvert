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
rem
rem Advanced (ADR 0010): run the tool with YOUR OWN Python environment
rem (the environment must already contain the dependencies):
rem   start.bat --use-env C:\path\to\venv               (venv or conda folder)
rem   start.bat --use-env C:\path\to\venv\Scripts\python.exe
rem The choice is stored in .smartinvert_env (git-ignored) and silently reused
rem on later starts.  start.bat --use-standard switches back to the standard
rem isolated environment.  In BYO-env mode the starter never installs anything
rem into your environment.
setlocal EnableExtensions
cd /d "%~dp0"

echo Smartboard PDF Inverter
echo.

rem ------------------------------------------------ [0] BYO-env mode ------
rem Parse the starter-level flags --use-env / --use-standard out of the
rem arguments; everything else is passed to the tool unchanged (kept in
rem ARGS, so consumed flags never leak into the CLI call).
set "ENV_FILE=.smartinvert_env"
set "CUSTOM_PY="
set "ARGS="
set "HAD_ARGS=0"

rem Empty command line -> GUI, nothing to parse.
if "%~1"=="" goto parse_done

rem cmd only exposes %1..%9 to a script, so a starter flag given beyond
rem the 9th token would be invisible to the shift-based parser below.
rem Acceptable: the flags are given up front in practice, and once the
rem choice is stored in .smartinvert_env no flag is needed at all
rem (known limitation, see ADR 0010).
set "WANT_BYO=0"
for %%t in (%*) do (
    if /i "%%t"=="--use-env" set "WANT_BYO=1"
    if /i "%%t"=="--use-standard" set "WANT_BYO=1"
)

if "%WANT_BYO%"=="1" goto parse_loop

rem No starter flags: classic passthrough - keep the command line verbatim
rem (same tokens and quotes as "%*"), so ANY number of arguments works.
set "HAD_ARGS=1"
set "ARGS=%*"
goto parse_done

:parse_loop
if "%~1"=="" goto parse_done

if /i "%~1"=="--use-env" goto byo_use_env
if /i "%~1"=="--use-standard" goto byo_use_standard

set "HAD_ARGS=1"
set "A=%~1"
if "%A: =%"=="%A%" (
    set "ARGS=%ARGS% %A"
) else (
    set "ARGS=%ARGS% "%A""
)
shift
goto parse_loop

:byo_use_env
shift
if "%~1"=="" (
    echo error: --use-env needs a path ^(venv folder or python executable^)
    pause
    exit /b 1
)
call :resolve_python_path "%~1"
if errorlevel 1 (
    echo error: no usable Python found at: %~1
    pause
    exit /b 1
)
set "CUSTOM_PY=%RESOLVED_PY%"
call :validate_python_env "%CUSTOM_PY%"
if errorlevel 1 (
    pause
    exit /b 1
)
rem escape cmd metacharacters so the choice line is written verbatim
rem ("^" first, so the escaping itself is not re-escaped)
set "SAFE=%CUSTOM_PY:^=^^%"
set "SAFE=%SAFE:&=^&%"
set "SAFE=%SAFE:|=^|%"
set "SAFE=%SAFE:<=^<%"
set "SAFE=%SAFE:>=^>%"
echo PYTHON=%SAFE%> "%ENV_FILE%"
echo [env] using your Python environment: %CUSTOM_PY%
echo [env] remembered in %ENV_FILE% ^(start.bat --use-standard to revert^)
shift
goto parse_loop

:byo_use_standard
if exist "%ENV_FILE%" (
    del "%ENV_FILE%"
    echo [env] switched back to the standard isolated environment
)
shift
goto parse_loop

:parse_done

rem No --use-env on the command line: silently reuse a stored choice - but
rem re-validate it (the environment may have been moved/deleted since).
if defined CUSTOM_PY goto env_loaded
if not exist "%ENV_FILE%" goto env_loaded
set "STORED="
for /f "usebackq tokens=1 delims=" %%a in ("%ENV_FILE%") do set "STORED=%%a"
if not defined STORED goto env_loaded
set "STORED=%STORED:PYTHON==%"
if not defined STORED goto env_loaded
if exist "%STORED%" goto stored_present
echo error: stored Python environment no longer exists: %STORED%
echo hint : run "start.bat --use-standard" to go back to the default.
pause
exit /b 1

:stored_present
call :validate_python_env "%STORED%"
if errorlevel 1 (
    echo error: stored Python environment is broken: %STORED%
    echo hint : reinstall the dependencies or run "start.bat --use-standard".
    pause
    exit /b 1
)
set "CUSTOM_PY=%STORED%"
echo [env] using your stored Python environment: %CUSTOM_PY%

:env_loaded

rem BYO-env mode: skip the uv/.venv machinery entirely - the tool code is
rem loaded from this checkout (CWD is the repo root), your environment is
rem never modified.
if defined CUSTOM_PY goto byo_run

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

rem ------------------------------------------------------------- [3/3] run -
if "%HAD_ARGS%"=="1" goto std_cli

echo [3/3] starting GUI ...
.venv\Scripts\python.exe -m smartboard_invert.gui
if errorlevel 1 pause
exit /b 0

:std_cli
echo [3/3] running ...
.venv\Scripts\smartinvert.exe %ARGS%
exit /b %errorlevel%

:byo_run
if "%HAD_ARGS%"=="1" goto byo_cli

echo [3/3] starting GUI ...
"%CUSTOM_PY%" -m smartboard_invert.gui
if errorlevel 1 pause
exit /b 0

:byo_cli
echo [3/3] running ...
"%CUSTOM_PY%" -m smartboard_invert %ARGS%
exit /b %errorlevel%

rem ------------------------------------------------------------- helpers ---
rem Accepts a venv/conda root folder or a direct python.exe path.
rem Sets RESOLVED_PY on success (exit /b 0), returns exit /b 1 otherwise.
:resolve_python_path
set "RESOLVED_PY="
set "P=%~1"
if "%P:~-1%"=="\" set "P=%P:~0,-1%"
if exist "%P%\" (
    rem a folder: venv layout (Scripts\python.exe) or conda layout (python.exe)
    if exist "%P%\Scripts\python.exe" (
        set "RESOLVED_PY=%P%\Scripts\python.exe"
        exit /b 0
    )
    if exist "%P%\python.exe" (
        set "RESOLVED_PY=%P%\python.exe"
        exit /b 0
    )
    exit /b 1
)
if exist "%P%" (
    rem a direct executable
    set "RESOLVED_PY=%P%"
    exit /b 0
)
exit /b 1

rem Prints an error and returns errorlevel 1 if the interpreter is too old
rem or the required dependencies are missing.  Never installs anything.
:validate_python_env
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>nul
if errorlevel 1 (
    echo error: "%~1" is not a usable Python 3.9+ interpreter.
    exit /b 1
)
"%~1" -c "import fitz, cv2, numpy, PIL" 2>nul
if errorlevel 1 (
    echo error: the environment of "%~1" is missing the required
    echo         dependencies ^(PyMuPDF, opencv-python-headless, numpy,
    echo         Pillow^).  Install them yourself with:
    echo.
    echo         "%~1" -m pip install PyMuPDF opencv-python-headless numpy Pillow
    echo.
    echo         This tool never installs anything into your environment.
    exit /b 1
)
exit /b 0
