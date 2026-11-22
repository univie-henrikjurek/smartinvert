# Installation Guide

This guide takes you from a fresh machine to a first successful run.

**There is nothing to install beforehand.** The starter script
(`start.bat` on Windows, `start.sh` on Linux/macOS) sets up everything by
itself — including a private Python interpreter. All you need is an internet
connection for the first run.

> *How it works under the hood: the starter uses
> [uv](https://docs.astral.sh/uv/) (a fast Python package/interpreter
> manager, ~15 MB) to create a virtual environment `.venv/` with a private
> CPython 3.12 that uv downloads on first use. If uv cannot be installed
> (e.g. a restricted network), the starter transparently falls back to your
> system Python (3.9 or newer).*

---

## 1. Get the project (pick one)

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

From here on, everything happens **inside the project folder** (the one that
contains `start.bat`, `start.sh`, and `inputs/`).

---

## 2. Run it — one command

### Windows

**Double-click `start.bat`** to open the GUI, or open PowerShell in the
project folder (tip: click the address bar, type `powershell`, press Enter):

```powershell
# Process the bundled sample file (good first test)
.\start.bat -i inputs\test.pdf -o outputs\test.pdf

# Process your own file
.\start.bat -i test_input.pdf -o test_output.pdf

# Batch: every PDF in a directory (output files keep their names)
.\start.bat -i inputs\ -o outputs\

# Open the GUI
.\start.bat
```

### Linux / macOS

```bash
# Process the bundled sample file (good first test)
./start.sh -i inputs/test.pdf -o outputs/test.pdf

# Process your own file
./start.sh -i test_input.pdf -o test_output.pdf

# Batch
./start.sh -i inputs/ -o outputs/

# Open the GUI
./start.sh
```

**First run:** you will see three steps —

```
[1/3] uv not found - installing (one-time, ~15 MB) ...
[2/3] creating .venv with Python 3.12 + dependencies (first run downloads ~80 MB; later starts are instant) ...
[3/3] starting ...
```

This takes **1–3 minutes** depending on your internet connection (it
downloads ~80 MB of dependencies once). Leave `.venv/` in place — every
later start is instant and skips straight to `[3/3]`.

---

## 3. Using the GUI

Run the starter **without arguments** (or double-click `start.bat`) to open
the window:

- **PDF…** — select a single file, or **Folder…** — process a whole directory
  (batch; output files keep their names)
- **Output (optional)** — destination file or folder. Leave empty for the
  default `<name>_inverted.pdf` next to the input; folder input requires an
  output folder
- **Auf Board zuschneiden (Rand entfernen)** — removes the page margin
  around the board (default: on)
- **Zielhintergrund** — *Complement (255 − v)* (default) or *Reinweiß*
- **▸ Erweiterte Optionen** — expand for the advanced settings:
  *Invert colours*, which marker colours to keep un-inverted
  (Rot/Grün/Blau/Gelb — default: Rot + Grün), and *Zusätzliche
  Hex-Farben* (explicit hex colours/ranges to keep, e.g. `FF0000,
  00FF00, 000001-0000FF`; empty = off)
- **Preview first page** — original and processed page side by side
- **Run** — processes all pages with a progress bar; when finished, the
  Done dialog reports the output location and offers
  **Speicherordner öffnen**, which opens the file manager right at your
  result — no need to navigate there yourself
- Problematic files (password-protected, damaged, or empty PDFs) get a
  clear explanation instead of an error dump — e.g. a password-protected
  PDF tells you to remove the password first

---

## 4. What you get

- One output PDF at the destination you specified (or the default location).
  Only the detected board region on each page is inverted; the white page
  around it, the page size, and the board position are unchanged.
- With `--debug` (CLI), per-page composites are written to
  `<output folder>/debug/<name>_pNN_debug.png`:
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

## 5. Optional: use `smartinvert` directly on your PATH

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

## 6. Advanced: use your own Python environment (BYO-env)

> For experienced users only. If you already maintain a Python environment
> (your own venv, a conda environment, …), you can run the tool **with it**
> instead of the private `.venv/` that the starter normally creates. The
> starter **validates but never installs anything into your environment** and
> never modifies it — the tool code is simply loaded from this project folder
> at start time.

### What your environment needs

- Python **3.9 or newer**, and
- the four runtime dependencies installed in it:

  ```
  PyMuPDF   opencv-python-headless   numpy   Pillow
  ```

  Install them with your environment's package manager, e.g.:

  ```
  <your python> -m pip install PyMuPDF opencv-python-headless numpy Pillow
  ```

  (for uv-managed environments: `uv pip install --python <your python> PyMuPDF opencv-python-headless numpy Pillow`)

The tool itself does **not** need to be installed in your environment.

### Activate the mode (one-time)

Point the starter at your environment — the environment's **folder** or the
Python **executable** both work (relative paths are resolved relative to the
project folder):

```bash
# Linux / macOS
./start.sh --use-env /path/to/your/venv
./start.sh --use-env /path/to/your/venv/bin/python
```

```powershell
# Windows (venv or conda folder, or the python.exe directly)
.\start.bat --use-env C:\path\to\your\venv
.\start.bat --use-env C:\path\to\your\venv\Scripts\python.exe
```

You can combine this with normal arguments in the same call, e.g.
`.\start.bat --use-env C:\env -i in.pdf -o out.pdf`.

The starter checks your environment (Python version + importable
dependencies) and, if everything is fine, remembers the choice in a local,
git-ignored file (`.smartinvert_env` in the project folder). **Every later
start then automatically uses your environment — without any flag** — and
re-validates it each time (so a moved or cleaned-up environment is reported
instead of causing confusing errors later).

If the check fails, the starter prints exactly what is missing and how to
install it — then nothing has changed anywhere.

### Switch back to the standard setup

```bash
./start.sh --use-standard      # Linux / macOS
.\start.bat --use-standard     # Windows
```

This deletes `.smartinvert_env` and restores the usual isolated `.venv/`
setup (double-clicking `start.bat` works exactly as before). The starter
then continues normally — without further arguments it opens the GUI.

### What is different in BYO-env mode?

- The one-time `[1/3]`/`[2/3]` setup steps are skipped entirely — nothing is
  downloaded into your environment.
- The `smartinvert` command does **not** exist in your environment (unless
  you install the tool there yourself) — the starter always uses
  `python -m smartboard_invert …` from the project folder, which works
  without any installation of the tool.
- If your environment is moved or its dependencies are removed, the starter
  refuses to start and points you to `--use-standard` (fail-safe: there is no
  silent fallback to the standard setup).
- **Windows only:** paths containing command-prompt special characters
  (`&`, `|`, `<`, `>`, `^`) are not supported; and when you combine
  `--use-env` with tool arguments in a single call, keep the total number of
  arguments at 9 or fewer (a command-prompt limitation — normally irrelevant
  because the choice is remembered for later starts).

---

## 7. Troubleshooting

| Problem | Solution |
| --- | --- |
| `[1/3] uv not found - installing ...` on the first run | Normal — the one-time setup; it should reach `[3/3]` within a few minutes |
| The uv installation step fails (corporate proxy, restricted network) | The starter automatically falls back to the system Python. If that also fails, install [uv manually](https://docs.astral.sh/uv/getting-started/installation/) or Python 3.9+ from python.org |
| First run is slow | Normal: one-time download of ~80 MB (uv + Python + dependencies). Later runs are instant |
| Double-clicking `start.bat` opens a window that closes immediately | Run `start.bat` from PowerShell so the message is visible (usually a network problem during the one-time setup) |
| `error: no uv and no suitable system Python (3.9+) found` | Install Python 3.9+ from <https://www.python.org/downloads/> (tick **Add python.exe to PATH**) or fix the network so uv can be downloaded |
| Windows Smart Screen: “Your PC was protected” | Click **More info → Run anyway** — the scripts are local and unsigned, this is expected |
| GUI won't open in a remote/SSH session without a display | The GUI needs a desktop; use the CLI there instead (`start.bat -i … -o …`) |
| Detection fails on a page (“no unambiguous region”) | The page was copied unchanged (fail-safe). Try a higher `--dpi`, check the debug composite, or inspect the page manually |
| “…is password-protected (encrypted). Remove the password first” | The PDF has a user password. Open it in a PDF viewer, save a copy *without* the password, and run the tool on that copy |
| “…is not a valid PDF (it may be damaged or not a PDF at all)” | The file is damaged or not a PDF at all — re-export or re-download it from the smartboard app |
| “…contains no pages” | The PDF is empty. Re-export it from the smartboard app |
| Offline machine (no internet at all) | Copy a prepared `.venv/` from another machine of the same OS/architecture, or pre-install the dependencies; see the development notes in the README |

---

## 8. Uninstalling

Delete the project folder (including `.venv`). Optionally also remove uv if
you don't need it for anything else: `~/.local/bin/uv` (Linux/macOS) or
`%USERPROFILE%\.local\bin\uv.exe` (Windows). Nothing else is installed on
the system.
