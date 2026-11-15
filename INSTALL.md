# Installation Guide

This guide takes you from a fresh machine to a first successful run. The only
prerequisite is **Python 3.10 or newer** — the starter script (`start.bat` on
Windows, `start.sh` on Linux/macOS) handles everything else: it creates an
isolated virtual environment, installs the dependencies, and launches the CLI
or GUI.

---

## 1. Install Python (skip if you already have it)

Quick check in a terminal: `python --version` (Windows) or
`python3 --version` (Linux/macOS). You need **3.10 or newer**.

### Windows

1. Download the installer from
   <https://www.python.org/downloads/> (3.10 or newer, “Windows installer
   64-bit”).
2. **Important:** on the first screen, tick **☑ Add python.exe to PATH**, then
   click *Install Now*.
3. Open a **new** terminal window (existing windows don't see the updated
   PATH) and verify with `python --version`.

> The Tkinter GUI is included in the python.org Windows installer — there is
> nothing extra to install.

### macOS

`python3 --version` — if Python is present, you're done. Otherwise install
Python from <https://www.python.org/downloads/> (graphical installer) or via
Homebrew: `brew install python`.

### Linux (Ubuntu/Debian)

`python3 --version` — usually preinstalled. If creating virtual environments
fails, install the venv module: `sudo apt install python3-venv`.
For the **GUI**, additionally: `sudo apt install python3-tk`.

---

## 2. Get the project (pick one)

### Option A: without Git (ZIP download)

1. Open the repository: <https://github.com/univie-henrikjurek/smartinvert>
2. Click the green **Code** button → **Download ZIP**.
3. Extract the archive (right-click → *Extract All* on Windows).

### Option B: with Git

Install [Git for Windows](https://git-scm.com/download/win) if you don't have
it, then:

```powershell
git clone https://github.com/univie-henrikjurek/smartinvert.git
cd smartinvert
```

From here on, run all commands **inside the project folder** (the one that
contains `start.bat`, `start.sh`, and `inputs/`).

---

## 3. Run it — one command

### Windows

Open PowerShell in the project folder (tip: in File Explorer, click the address
bar, type `powershell`, press Enter).

```powershell
# Process the bundled sample file (good first test)
.\start.bat -i inputs\test.pdf -o outputs\test.pdf

# Process your own file
.\start.bat -i test_input.pdf -o test_output.pdf

# Batch: every PDF in a directory (output files keep their names)
.\start.bat -i inputs\ -o outputs\

# Open the GUI (or simply double-click start.bat)
.\start.bat
```

### Linux / macOS

```bash
./start.sh -i test_input.pdf -o test_output.pdf
./start.sh -i inputs/ -o outputs/
./start.sh                    # open the GUI
```

**First run:** the script creates `.venv/` and installs the dependencies
(PyMuPDF, OpenCV, NumPy, Pillow). Expect **1–3 minutes** depending on your
internet connection. Leave `.venv/` in place — every later start is instant.

---

## 4. Using the GUI

Run the starter **without arguments** (or double-click `start.bat`) to open
the window:

- **PDF…** — select a single file, or **Folder…** — process a whole directory
  (batch; output files keep their names)
- **Output (optional)** — destination file or folder. Leave empty for the
  default `<name>_inverted.pdf` next to the input; folder input requires an
  output folder
- **DPI** slider (default 150 — raise to ~300 for sharper output, at the cost
  of processing time)
- **Preview first page** — original and processed page side by side
- **Run** — processes all pages with a progress bar; a dialog reports the
  output location when finished

---

## 5. What you get

- One output PDF at the destination you specified (or the default location).
  Only the detected board region on each page is inverted; the white page
  around it, the page size, and the board position are unchanged.
- With `--debug` (CLI) or via the debug output, per-page composites are
  written to `<output folder>/debug/<name>_pNN_debug.png`:
  *original | original + detected rectangle | result* — useful to verify what
  was detected.
- The input file is **never** modified or overwritten (the tool refuses to
  write to the input path).

### Most useful CLI options

| Flag | Meaning |
| --- | --- |
| `-i`, `--input` | Input PDF file or directory |
| `-o`, `--output` | Output file or directory |
| `--dpi N` | Detection + output resolution (20–600, default 150) |
| `--no-invert` | Detect only, without inverting (analysis/debug) |
| `--debug` | Write per-page debug composites |
| `-v` / `-vv` | Verbose / very verbose logging |
| `--version` | Show the version |

Full reference: `.\start.bat --help` (Windows) or `./start.sh --help`
(Linux/macOS).

---

## 6. Optional: use `smartinvert` directly on your PATH

If you prefer calling the command directly (without the starter script),
activate the virtual environment per terminal session:

```powershell
# Windows
.venv\Scripts\activate
smartinvert -i test_input.pdf -o test_output.pdf
```

```bash
# Linux / macOS
source .venv/bin/activate
smartinvert -i test_input.pdf -o test_output.pdf
```

Leave the session again with `deactivate`.

---

## 7. Troubleshooting

| Problem | Solution |
| --- | --- |
| `'python' is not recognized as an internal or external command` | Reinstall Python with the **Add python.exe to PATH** option ticked, then open a **new** terminal |
| `error: Python 3.10+ not found` (from the starter) | Python is missing or too old — install Python 3.10+ (step 1) |
| Double-clicking `start.bat` opens a window that closes immediately | Run `start.bat` from PowerShell so the error message is visible (usually missing or too-old Python) |
| First run is slow | Normal — a one-time download of ~60–90 MB of dependencies; subsequent runs are instant |
| `ModuleNotFoundError: No module named 'tkinter'` (GUI only) | Linux (Ubuntu/Debian): `sudo apt install python3-tk`. Windows/macOS: use the Python from python.org (includes Tkinter) |
| Windows Smart Screen: “Your PC was protected” | Click **More info → Run anyway** — the scripts are local and unsigned, this is expected |
| GUI won't open in a remote/SSH session without a display | The GUI needs a desktop; use the CLI there instead (`start.bat -i … -o …`) |
| Detection fails on a page (“no unambiguous region”) | The page was copied unchanged (fail-safe). Try a higher `--dpi`, check the debug composite, or inspect the page manually |

---

## 8. Uninstalling

Delete the project folder (including `.venv`). Nothing else is installed on
the system.
