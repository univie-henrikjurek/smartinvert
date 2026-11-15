# Smartboard PDF Inverter

Selectively invert the smartboard area of PDF documents — nothing else.

Smartboard PDF Inverter automatically detects the rectangular smartboard
(whiteboard) region on every page of a PDF and inverts **only that area**
(strict `255 − v` per pixel channel). The white page around the board, the page
size, the board's position, and the page order are preserved exactly:
everything outside the detected rectangle is left pixel-identical.

<p align="center">
  <img src="docs/demo-smartboard.png" alt="Before / detected / after" width="900">
</p>

*Detection and selective inversion on the bundled sample file: the board region
is found automatically (green outline) and inverted; the surrounding page is
untouched.*

## Highlights

- **Automatic detection** — background-relative thresholding combined with
  plausibility gates (area, rectangularity, contrast, page margin, ambiguity)
  and a confidence score. If no unambiguous region is found, the page is left
  unchanged and a warning is emitted — the whole page can never be inverted by
  accident.
- **Strictly selective inversion** — the strict pixel transformation
  `255 − v` is applied inside the detected rectangle only.
- **Page-faithful output** — original page size (MediaBox), board position, and
  page order are preserved. Three output strategies, chosen per page:
  lossless page copy, in-place board-image replacement (lossless PNG), or
  re-embedding of a rendered page at the original size (for vector content).
- **Built-in verification** — every processed page is re-rendered and compared
  against the original; pixels outside the region must be unchanged (the
  numbers are logged and available in the API).
- **Batch processing** — process a single file or an entire directory in one
  command.
- **CLI and GUI** — a command-line interface (`smartinvert`) and a small
  Tkinter GUI with live preview and progress reporting.
- **Safe by design** — the input file is never modified; rotated pages and
  ambiguous content fail safe (copied unchanged, never wrongly inverted).

## How it works

1. **Detection** — each page is rendered at the configured DPI. A deterministic
   background-relative threshold (`T = B − max(30, 0.25·(B − p25))`,
   `B = p95`) plus morphological closing and connected-component analysis
   yields candidate regions; hard gates on area, dimensions, rectangularity,
   margin, contrast, and a second-largest-candidate ratio select the board.
   Details: [ADR 0001](docs/adr/0001-robuste-erkennung-und-seitentreue-ausgabe.md).
2. **Transformation** — inside the rectangle only: strict inversion
   (`255 − v`), plus optional (legacy) CLAHE contrast enhancement and
   morphological cleaning.
3. **Page-faithful output** — the page is reproduced with its original size and
   one of the three strategies above.
4. **Verification & debug** — the output page is re-rendered at the same DPI
   and compared with the input (max/mean diff outside and inside the region);
   `--debug` writes per-page composites
   (`original | original + rectangle | result`) to `<output>/debug/`.

## Quick start

> Step-by-step installation guide (Windows, macOS, Linux), including
> troubleshooting: see **[INSTALL.md](INSTALL.md)**.

Requires **Python 3.10+**.

```bash
git clone https://github.com/univie-henrikjurek/smartinvert.git
cd smartinvert

./start.sh -i test_input.pdf -o test_output.pdf   # Linux / macOS
.\start.bat -i test_input.pdf -o test_output.pdf  # Windows (PowerShell)
```

The first run creates a virtual environment in `.venv/` and installs the
dependencies (PyMuPDF, OpenCV, NumPy, Pillow) — one-time cost of roughly
1–3 minutes; every later start is instant. **Running the starter without
arguments opens the GUI.**

```bash
# Batch: all PDFs in a directory (output files keep their names)
./start.sh -i inputs/ -o outputs/ --debug

# Higher output quality (detection + embedding resolution)
./start.sh -i inputs/test.pdf -o out.pdf --dpi 300
```

Without `-o`, a single input file produces `<name>_inverted.pdf` next to the
input (legacy behaviour).

## Command line

After the first run the tool is also available directly as the
`smartinvert` command (inside `.venv/`, or on your PATH after activation).

```
Usage: smartinvert -i INPUT [-o OUTPUT] [options]

  -i, --input PATH       Input PDF file or directory (default: inputs/)
  -o, --output PATH      Output file (file input) or directory
                         (default: outputs/, same file names)
      --dpi N            Rendering DPI for detection and output
                         (default: 150, range 20–600)
      --invert / --no-invert
                         Invert the detected region (default: enabled)
      --clahe / --no-clahe
                         CLAHE contrast enhancement inside the region
                         (legacy, default: off)
      --clean / --no-clean
                         Morphological cleaning inside the region
                         (legacy, default: off)
      --debug            Write per-page debug composites to <output>/debug/
      --config PATH      Optional JSON config file; CLI flags take precedence
  -v / -vv               Log level INFO / DEBUG
      --version          Show version and exit
```

Exit code: `0` on success, `1` if at least one file failed (a batch continues
past failing files). Run `smartinvert --help` for the full reference.

## GUI

Open the GUI by running the starter without arguments (or double-click
`start.bat` on Windows):

```bash
./start.sh        # Linux / macOS
start.bat         # Windows
```

- **PDF…** — select one file, or **Folder…** — process a whole directory
  (batch)
- **Output (optional)** — destination file/folder; leave empty for the default
  `<name>_inverted.pdf` next to the input (folder input requires an output
  folder)
- **DPI** slider (default 150; raise to 300 for sharper results)
- **Preview first page** — original and processed page side by side
- **Run** — processes with a progress bar and reports the output location

## Project layout

```
smartboard_invert/
  detection.py    # Rectangle detection (threshold, gates, confidence, refinement)
  processing.py   # Image transformations (255 − v, CLAHE, cleaning), PDF ⇄ images
  pdfpipeline.py  # process_pdf(): three output strategies, verification, debug
  cli.py          # Batch CLI with JSON config support
  gui.py          # Tkinter GUI
  __main__.py     # python -m smartboard_invert entry point
docs/adr/         # Architecture decision records
tests/            # pytest suite with synthetic PDF fixtures (ground truth)
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e .            # editable install
.venv/bin/pip install pytest pytest-cov
.venv/bin/pytest --cov=smartboard_invert --cov-report=term-missing
```

The test suite covers detection, processing, the end-to-end pipeline
(including the mandatory scenario set), and the CLI, with an 80 % coverage
gate. CI (GitHub Actions) runs the suite on Python 3.10 and 3.13, installs the
package the same way end users do, and executes a smoke test on the bundled
sample. See [STATUS.md](STATUS.md) for the current project state.

## License

[MIT](LICENSE) — free to use, modify, and distribute, including commercially;
the only obligation is to keep the copyright and license notice.
