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
[2/3] creating .venv with Python 3.12 (uv downloads it on first use) ...
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
- **DPI** slider (default 150 — raise to ~300 for sharper output, at the cost
  of processing time)
- **Preview first page** — original and processed page side by side
- **Run** — processes all pages with a progress bar; a dialog reports the
  output location when finished

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

## 6. Troubleshooting

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
| Offline machine (no internet at all) | Copy a prepared `.venv/` from another machine of the same OS/architecture, or pre-install the dependencies; see the development notes in the README |

---

## 7. Uninstalling

Delete the project folder (including `.venv`). Optionally also remove uv if
you don't need it for anything else: `~/.local/bin/uv` (Linux/macOS) or
`%USERPROFILE%\.local\bin\uv.exe` (Windows). Nothing else is installed on
the system.
