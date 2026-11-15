#!/usr/bin/env bash
# Smartboard PDF Inverter – one-command starter (Linux/macOS).
#
# Usage:
#   ./start.sh -i input.pdf -o output.pdf   # run the CLI with your arguments
#   ./start.sh -i inputs/ -o outputs/       # batch: whole directory
#   ./start.sh                              # open the GUI (file or folder)
#
# First run creates .venv/ and installs dependencies (~1-2 min); later runs
# are instant.  Override the interpreter with PYTHON=/path/to/python3.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "error: '$PY' not found. Install Python 3.9+ or set PYTHON=/path/to/python3" >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "First run: creating virtual environment in .venv/ ..."
    "$PY" -m venv .venv
fi

# Quiet, fast no-op when everything is already installed.
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet .

if [ "$#" -gt 0 ]; then
    exec .venv/bin/smartinvert "$@"
else
    exec .venv/bin/python -m smartboard_invert.gui
fi
