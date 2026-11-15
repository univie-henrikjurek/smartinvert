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
set -euo pipefail
cd "$(dirname "$0")"

echo "Smartboard PDF Inverter"

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
if [ "$#" -gt 0 ]; then
    exec .venv/bin/smartinvert "$@"
else
    exec .venv/bin/python -m smartboard_invert.gui
fi
