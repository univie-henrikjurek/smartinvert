#!/usr/bin/env bash
# Smartboard PDF Inverter – one-command starter (Linux / macOS).
#
# Usage:
#   ./start.sh -i input.pdf -o output.pdf   run the CLI with your arguments
#   ./start.sh -i inputs/ -o outputs/       batch: whole directory
#   ./start.sh                              open the GUI (file or folder)
#
# No Python installation is required: the starter uses uv, which downloads a
# managed CPython 3.12 on first use.  If uv cannot be installed (e.g. no
# network), it falls back to the system Python (>= 3.9).
#
# Advanced (ADR 0010): run the tool with YOUR OWN Python environment
# (the environment must already contain the dependencies):
#   ./start.sh --use-env /path/to/venv          (venv folder)
#   ./start.sh --use-env /path/to/venv/bin/python
# The choice is stored in .smartinvert_env (git-ignored) and silently reused
# on later starts.  ./start.sh --use-standard switches back to the standard
# isolated environment.  In BYO-env mode the starter never installs anything
# into your environment.
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".smartinvert_env"

echo "Smartboard PDF Inverter"

# ------------------------------------------------- helpers (BYO-env mode) ---

resolve_python_path() {
  # Accepts a venv/conda root folder or a direct python executable path.
  local p="$1"
  if [ -f "$p" ] && [ -x "$p" ]; then
    printf '%s' "$p"
    return 0
  fi
  if [ -x "$p/bin/python" ]; then
    printf '%s' "$p/bin/python"
    return 0
  fi
  # conda environments (and some layouts) keep python at the folder root
  if [ -x "$p/python" ]; then
    printf '%s' "$p/python"
    return 0
  fi
  return 1
}

validate_python_env() {
  local py="$1"
  if ! "$py" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    echo "error: '$py' is not a usable Python 3.9+ interpreter." >&2
    return 1
  fi
  if ! "$py" -c 'import fitz, cv2, numpy, PIL' 2>/dev/null; then
    {
      echo "error: the environment of '$py' is missing the required"
      echo "       dependencies (PyMuPDF, opencv-python-headless, numpy,"
      echo "       Pillow).  Install them yourself with:"
      echo ""
      echo "         \"$py\" -m pip install PyMuPDF opencv-python-headless numpy Pillow"
      echo ""
      echo "       This tool never installs anything into your environment."
    } >&2
    return 1
  fi
  return 0
}

# ------------------------------------------------- [0] BYO-env mode ---------
# Parse the starter-level flags --use-env / --use-standard out of the
# arguments; everything else is passed to the tool unchanged.
CUSTOM_PY=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --use-env)
      if [ $# -lt 2 ] || [ -z "${2:-}" ]; then
        echo "error: --use-env needs a path (venv folder or python executable)" >&2
        exit 1
      fi
      if ! CUSTOM_PY="$(resolve_python_path "$2")"; then
        echo "error: no usable Python found at: $2" >&2
        exit 1
      fi
      validate_python_env "$CUSTOM_PY" || exit 1
      # remember an absolute path so the stored choice keeps working
      # regardless of the directory the starter is invoked from
      case "$CUSTOM_PY" in
        /*) ;;
        *) CUSTOM_PY="$PWD/$CUSTOM_PY" ;;
      esac
      # validated → remember the choice (git-ignored, checkout-local)
      printf 'PYTHON=%s\n' "$CUSTOM_PY" > "$ENV_FILE"
      echo "[env] using your Python environment: $CUSTOM_PY"
      echo "[env] remembered in $ENV_FILE (./start.sh --use-standard to revert)"
      shift 2
      ;;
    --use-standard)
      if [ -f "$ENV_FILE" ]; then
        rm -f "$ENV_FILE"
        echo "[env] switched back to the standard isolated environment"
      fi
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done
# restore the (possibly empty) remaining arguments — the ${ARGS[@]+...} form
# is safe under `set -u` on old bash (macOS ships bash 3.2)
set -- ${ARGS[@]+"${ARGS[@]}"}

# No --use-env on the command line: silently reuse a stored choice — but
# re-validate it (the environment may have been moved/deleted since).
if [ -z "$CUSTOM_PY" ] && [ -f "$ENV_FILE" ]; then
  CUSTOM_PY="$(sed -n 's/^PYTHON=//p' "$ENV_FILE" | head -n 1)"
  if [ -z "$CUSTOM_PY" ] || [ ! -x "$CUSTOM_PY" ]; then
    echo "error: stored Python environment no longer exists: ${CUSTOM_PY:-<empty>}" >&2
    echo "hint : run './start.sh --use-standard' to go back to the default." >&2
    exit 1
  fi
  if ! "$CUSTOM_PY" -c 'import fitz, cv2, numpy, PIL' 2>/dev/null; then
    echo "error: stored Python environment is broken: $CUSTOM_PY" >&2
    echo "hint : reinstall the dependencies or run './start.sh --use-standard'." >&2
    exit 1
  fi
  echo "[env] using your stored Python environment: $CUSTOM_PY"
fi

# BYO-env mode: skip the uv/.venv machinery entirely — the tool code is
# loaded from this checkout (CWD is the repo root), your environment is
# never modified.
if [ -n "$CUSTOM_PY" ]; then
  echo "[3/3] starting ..."
  if [ $# -gt 0 ]; then
    exec "$CUSTOM_PY" -m smartboard_invert "$@"
  else
    exec "$CUSTOM_PY" -m smartboard_invert.gui
  fi
fi

# ------------------------------------------------------------ [1/3] uv ----
find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return 0
    fi
    local d
    for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        if [ -x "$d/uv" ]; then
            printf '%s\n' "$d/uv"
            return 0
        fi
    done
    return 1
}

UV_BIN="$(find_uv || true)"
CLASSIC=0
PY="${PYTHON:-python3}"

if [ -z "$UV_BIN" ]; then
    echo "[1/3] uv not found - installing (one-time, ~15 MB) ..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh || true
        export PATH="$HOME/.local/bin:$PATH"
    fi
    UV_BIN="$(find_uv || true)"
fi

if [ -z "$UV_BIN" ]; then
    echo "[1/3] uv unavailable - falling back to system Python (>= 3.9) ..."
    if command -v "$PY" >/dev/null 2>&1 \
        && "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
        CLASSIC=1
    else
        echo "error: could not set up uv and no suitable system Python (3.9+) was found." >&2
        echo "hint : install curl or Python 3.9+ (https://www.python.org/downloads/)." >&2
        exit 1
    fi
fi

# -------------------------------------------- [2/3] venv + dependencies ---
if [ ! -x .venv/bin/python ]; then
    if [ "$CLASSIC" -eq 1 ]; then
        echo "[2/3] creating .venv with system Python ($("$PY" --version 2>&1 | awk '{print $2}')) + dependencies (first run downloads ~80 MB) ..."
        "$PY" -m venv .venv
    else
        echo "[2/3] creating .venv with Python 3.12 + dependencies (first run downloads ~80 MB; later starts are instant) ..."
        "$UV_BIN" venv --python 3.12 .venv
    fi
fi

if [ "$CLASSIC" -eq 1 ]; then
    .venv/bin/pip install --quiet .
else
    "$UV_BIN" pip install --python .venv/bin/python --quiet .
fi

# ------------------------------------------------------------ [3/3] run ---
echo "[3/3] starting ..."
if [ $# -gt 0 ]; then
    exec .venv/bin/smartinvert "$@"
else
    exec .venv/bin/python -m smartboard_invert.gui
fi
