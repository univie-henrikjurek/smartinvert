# Smartboard PDF Inverter

A small Python tool that automatically detects the dark rectangular area of a scanned whiteboard inside a PDF, inverts its colours (black ↔ white) and leaves the surrounding white margin untouched.  
The tool works on multi‑page PDFs and offers both a command‑line interface and a simple graphical UI.

## Features
* Automatic detection of the whiteboard rectangle (rasterising the PDF page).  
* Colour inversion (RGB = 255 − value) with optional CLAHE contrast enhancement and noise cleaning.  
* Multi‑page support – each page is processed independently.  
* CLI (`smartboard-invert`) and lightweight Tkinter GUI.  
* Configurable DPI, inversion, CLAHE and cleaning via CLI flags or a JSON config file.  
* Full test suite (pytest) and CI workflow.

## Installation
```bash
# Clone the repo
git clone <repo‑url>
cd Smartboard-Inv

# Set up a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --break-system-packages -e .
```

## Quick start (CLI)
```bash
smartboard-invert -i inputs/test.pdf -v
# output will be created as inputs/test_inverted.pdf (or specify -o)
```

## GUI
```bash
python -m smartboard_invert.gui
```
Select a PDF, adjust DPI/options, preview the first page and click **Run**.

## Running the test suite
```bash
pytest --cov=smartboard_invert
```
A coverage report of at least 80 % is required.

## CI
The repository contains a GitHub Actions workflow (`.github/workflows/ci.yml`) that runs the tests on push/pull‑request.

## License
MIT – see the LICENSE file.
