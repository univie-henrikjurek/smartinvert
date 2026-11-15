# Project Status – Smartboard Inversion

## Overview
This repository implements a PDF whiteboard/smartboard inversion tool (CLI + GUI)
using PyMuPDF, OpenCV and NumPy.

**Phase 1** (completed, commit `ef9e5ab`): render page → invert largest dark
region → re-assemble PDF.

**Phase 2** (completed 2026-11-14): robust automatic detection of the
rectangular smartboard area per page + strictly selective inversion inside
that rectangle (`255 − v`), with exact preservation of page size/position/
order and fail-safe behaviour (never invert the whole page, never
move/crop content).

## Status: DONE

All Phase-2 TODOs completed, test suite green (88 tests, 90.16 % coverage,
gate 80 %), real run on `inputs/test.pdf` verified (see "Final Verification").

**Phase 3 – Distribution (2026-11-15, DONE):**
- CLI renamed `smartboard-invert` → **`smartinvert`** (v0.3.0)
- One-command starter: `./start.sh` (Linux/macOS) / `start.bat` (Windows) –
  creates `.venv` on first run, `pip install .`, then runs `smartinvert "$@"`
  (with arguments) or opens the GUI (without arguments)
- `opencv-python` → `opencv-python-headless` (no highgui used; avoids libGL
  on Linux) – full suite re-verified green
- `LICENSE` (MIT) added; `classifiers`/`keywords` in pyproject
- GUI: folder input (batch) + optional output field
- CI: Python 3.10 + 3.13 matrix (3.9 dropped: EOL + not in runner images),
  installs as real (non-editable) package, installs pytest/pytest-cov,
  smoke test on `inputs/test.pdf`; `--break-system-packages` removed.
  First green run: actions/runs/43715427722 (both jobs ✓)
- Minimum supported Python: **3.10** (was 3.9, EOL since 2025-10)
- Repo: https://github.com/univie-henrikjurek/smartinvert (private), tag
  v0.3.0; packaging verified in a scratch venv (`pip install .` →
  `smartinvert` runs the sample)

**Phase 4 – "It just works" distribution (2026-11-15, v0.4.0):**
- **uv-first starter:** `start.sh`/`start.bat` now install `uv`
  automatically (official installer, one-time ~15 MB) and create `.venv`
  with a **uv-managed CPython 3.12** (downloaded by uv on first use,
  includes Tkinter → GUI works without any system Python). System Python is
  no longer a prerequisite at all.
- **Fallback:** if uv cannot be installed (restricted network), the starter
  transparently falls back to the system Python (classic venv + pip).
- **Python 3.9 supported again** (`requires-python >=3.9`): the 3.10 floor
  was a CI artifact. Only incompatibility found: `Rect.get_area()` (PyMuPDF
  2.x API) → replaced by `width * height` (works on PyMuPDF 1.26 and 2.x).
  Verified: full 88-test suite green on 3.9 (PyMuPDF 1.26.5), 3.12, and 3.13
  (all via uv-managed interpreters).
- **CI is uv-based now:** uv downloads standalone CPython builds, so the
  matrix (3.9 + 3.13) no longer depends on runner-image Python versions.
- **Verified end-to-end (fresh-repo simulation):** (1) no uv anywhere →
  official installer runs → venv 3.12 → sample processed; (2) uv installer
  blocked → classic fallback with system Python → identical output.
- Docs: README/INSTALL rewritten for the no-prerequisite flow.
- Repo is **public** now: https://github.com/univie-henrikjurek/smartinvert

**v0.4.1 – Windows GUI fixes (2026-11-15):**
- Run button crashed: `TclError: unknown option "-state"` — the disable/enable
  loop touched direct children of the root window (Frames/Labels, which have
  no `-state`). Fix: recursive `_set_controls_state()` walk (skips widgets
  without the option).
- Second bug caught by the headless GUI E2E test (xvfb, real Tk window):
  worker thread called `master.after(0, cb)` — tkinter registers the callback
  in the *calling* thread → `RuntimeError: main thread is not in main loop`,
  worker died silently, GUI froze. Fix: thread-safe event queue
  (`queue.Queue` + 100 ms poller in the main loop); worker threads only
  enqueue callbacks.
- DPI slider now shows a live value label (150/200/300), updated on both
  drag and click.
- Verified: headless E2E (Xvfb) drives the real GUI — Run → disabled
  controls → worker → "Saved to …" dialog → controls re-enabled, output
  written. 88/88 tests, CI green (3.9 + 3.13).

**Public-repo leak check + history cleanup (2026-11-15):**
- Full scan of every blob in the history (incl. binaries: PDFs, PNG):
  **no private information** (no personal e-mails, tokens, keys, or local
  machine paths). Binaries carry no metadata beyond "Qt 5.9.2".
- `inputs/test.pdf` has no extractable text (vector drawing only); the demo
  PNG shows the same sample board — both are the user's own sample data,
  intentionally shipped.
- Removed from history via `git filter-repo` (repo was fresh, no other
  clones): `outputs/test_inverted.pdf` and 3 `__pycache__/*.pyc` files
  (committed in Phase 1, deleted in Phase 2, but still reachable in a
  public history; the `.pyc` files embedded sandbox build paths
  `/root/opencode-projects/…`).
- History rewritten + force-pushed (master + tags v0.3.0/v0.4.0/v0.4.1),
  verified from an independent fresh clone: exactly the 25 project files,
  pattern scan clean, CI green (run 43725025521).
- Remaining, **not** leaks (left as-is, user's call): 9 Phase-1/2 commits
  are authored "Smartboard Bot <243551298+univie-henrikjurek@users.noreply.github.com>" (placeholder identity,
  accepted earlier); old `pyproject.toml` versions in history carry the same
  placeholder author field. Current authorship: Henrik Jurek with GitHub
  noreply e-mail (public by design).

## Future Ideas (backlog, no priority yet)
- **Standalone binary** (PyInstaller/Nuitka): single executable per OS
  (zero prerequisites, ~150–200 MB) for releases — ultimate comfort for
  non-technical users; per-OS CI builds + release artifacts needed.
- Optional: PyPI publication (`pip install smartboard-invert`) if distribution
  beyond GitHub ZIP/clone is wanted.
- README/CI annotations: update `actions/checkout`/`setup-python` majors when
  the Node-24 versions are stable (currently only deprecation warnings).

## Final Verification (2026-11-14)

- **Test suite:** `pytest --cov=smartboard_invert --cov-fail-under=80` →
  **88 passed**, total coverage **90.16 %** (detection 94 %, processing 93 %,
  cli 93 %, pdfpipeline 86 %).
- **Real run:** `python -m smartboard_invert --input inputs --output outputs
  --debug -v` on `inputs/test.pdf` (vector-based, 1 page A4 595×842 pt):
  - Page 1: detected, confidence **0.93**, method **rerasterize**,
    rect_pt ≈ (147.8, 10.1, 447.2, 831.4) – matches the ground-truth dark
    vector rect (147.7, 10.1)–(447.1, 831.9).
  - Pipeline self-verification: **outside max diff = 0**, inside mean diff 208.
  - Independent verification (re-render at 150 dpi): outside detected rect
    **max diff = 0**; at 200 dpi the white margin (≥ 20 px from the board)
    is pixel-identical; only a ±10 px ring around the board boundary shows
    resampling differences (≤ 123) – inherent to the re-rasterize fallback
    (150 dpi raster re-rendered at 200 dpi), documented in ADR D3.
  - `--dpi 300` run: outside max diff = 0 (self), margin pixel-identical →
    `--dpi` is the documented quality knob for vector inputs.
  - Output `outputs/test.pdf`: 1 page, 595×842 pt, rotation 0 (unchanged);
    board mean gray 24.7 → 230.4 (≈ exact complement 230.3).
  - Input untouched: sha256 `317853a7…20f2f61` identical before/after.
  - Debug composite: `outputs/debug/test_p01_debug.png`.

## Phase 2 – Analysis Results (2026-11-14, kept for reference)

### Existing code (Phase 1)
- `smartboard_invert/processing.py`: `pdf_to_images` (render at DPI),
  `enhance_image` (CLAHE + morphology + inversion inside an Otsu/largest-contour
  mask), `images_to_pdf` (new page sized to image pixels in **pt** → **wrong page
  size**, e.g. A4@150dpi becomes a 1240×1755 pt page).
- `smartboard_invert/cli.py`: single-file CLI only, no directory batch, no
  `--debug`.
- `smartboard_invert/gui.py`: Tkinter GUI around `enhance_image` (its "Run"
  path re-used the page-size bug of `images_to_pdf`).
- Detection (Phase 1): Otsu threshold + largest external contour only – not
  robust for dark-gray backgrounds, no confidence, no ambiguity handling,
  no plausibility checks, triggerable by large dark vector content.
- CLAHE/morphology were ON by default → conflicted with the strict
  `255 − v` requirement of Phase 2.
- Tests: 3 smoke tests only; no synthetic fixtures.
- Repo hygiene: `__pycache__/*.pyc` and `outputs/test_inverted.pdf` were
  tracked; no `.gitignore` → fixed in baseline commit `6bfeac3`.

### `inputs/test.pdf` (technical inspection)
- 1 page, A4 portrait, MediaBox `[0 0 595 842]` (595×842 pt), no rotation.
- **No image XObjects, no text** – content is 1229 vector paths.
- Smartboard background = one large vector-filled rectangle, fill
  RGB ≈ (19, 21, 25), size 299.4×821.8 pt at (147.7, 10.1)–(447.1, 831.9).
- On top: 1179 white paths (text/strokes), 48 salmon shapes, 1 blue shape.
- Rendered @150dpi: 1240×1755 px; grayscale p5 = p25 = 21, p50–p95 = 255;
  dark (<128) = 48.2 % of the page.
- **Consequence:** dual-path design (image-based boards *and* vector-based
  boards) → ADR 0001.

### Environment
- Project venv `.venv` (Python 3.13.5): PyMuPDF 2.1 (`import fitz`
  deprecated → `import pymupdf as fitz`, compat shim in `processing.py`),
  opencv-python 5.0.0.93, numpy 2.5.4, Pillow 13.0.0; pytest 9.2.0 +
  pytest-cov installed into the venv.
- OpenCV ≥ 5 gotcha: `cv2.threshold(…, THRESH_OTSU)` degenerates to 0.0 on
  strictly bimodal histograms → detection uses a deterministic
  percentile-based threshold instead (ADR 0001 D1).
- PyMuPDF gotcha: `page.rect` already returns visual (rotation-adjusted)
  dimensions for `/Rotate ≠ 0` pages; `show_pdf_page` does **not** carry
  `/Rotate` over → rotated pages are copied with `insert_pdf` (preserves
  MediaBox + `/Rotate` + content stream; verified pixel-identical).

## Phase 2 – TODO Tracker (final)
| ID | Description | Owner | Status |
|----|-------------|-------|--------|
| T-20 | Analyse bestehendes Projekt + `inputs/test.pdf`, dokumentieren | Supervisor | completed |
| T-21 | Repo-Hygiene: `.gitignore`, untrack, Baseline-Commit | Supervisor | completed (`6bfeac3`) |
| T-22 | ADR 0001: Erkennungsstrategie + Ausgabepfade | Architect | completed (`docs/adr/0001-*.md`) |
| T-23 | `detection.py` + fitz-compat + `invert_region`/`enhance_image` | Coder | completed (`ba7cb0a`) |
| T-24 | Unit-Tests `detection.py` | Tester | completed (`ba7cb0a`) |
| T-25 | `pdfpipeline.py` (process_pdf, 3 Ausgabemethoden, debug, verifikation) | Coder | completed (`7cbf768`) |
| T-26 | Pipeline-Tests (8 Pflichtszenarien + Extras) | Tester | completed (`7cbf768`) |
| T-27 | CLI rework (Batch, `python -m`, `--debug`) + GUI fix | Coder | completed (`dec9893`) |
| T-28 | CLI-Tests | Tester | completed (`dec9893`) |
| T-29 | Full test suite green | Tester | completed (88 passed, 90.16 %) |
| T-30 | Real run `inputs/test.pdf` + Verifikation | Coder/Supervisor | completed (see Final Verification) |
| T-31 | Reviewer diff review, fixes | Reviewer/Supervisor | completed (`7483ea6`; 0 critical, alle Major behoben) |
| T-32 | README + STATUS final | Supervisor | completed (this commit) |

(Phase 1 tracker T-01 … T-18: completed, see git history / commit `ef9e5ab`.)

Commits: `6bfeac3` baseline → `ba7cb0a` detection+processing → `7cbf768`
pipeline+tests → `dec9893` CLI+GUI → `7483ea6` review fixes → this commit
(README/STATUS).

## Assumptions (Phase 2, documented decisions)
| # | Assumption | Rationale |
|---|------------|-----------|
| A-8 | The sample file is `inputs/test.pdf` (task text says `Test.pdf`; Linux is case-sensitive and only the lowercase file exists). | Observed file system state. |
| A-9 | Default pipeline is pure `255 − v` inversion; CLAHE/morphology are opt-in (`--clahe`, `--clean`, default off). | Phase-2 spec requires strict pixel inversion (P2-FR-3). |
| A-10 | Replaced image XObjects are re-encoded as PNG (lossless). | Preserves anti-aliasing exactly; file size acceptable. |
| A-11 | Pages with `/Rotate ≠ 0` are **copied unchanged** (via `insert_pdf`, which preserves MediaBox + `/Rotate` + content stream, verified pixel-identical) with a warning. | The pixel↔point mapping used for detection/inversion is not valid for rotated pages; a wrong inversion would be worse than none. |
| A-12 | `outputs/` and `__pycache__/` are generated artifacts → untracked, `.gitignore` added. | Repo hygiene; inputs/ (sample) stays tracked. |
| A-13 | Detection DPI = output render DPI = `--dpi` (default 150). | One knob; 150 dpi is sufficient for robust rectangle detection; raise `--dpi` for sharper vector output. |
| A-14 | "Pixelgenau unverändert außerhalb des Rechtecks" is verified against re-renderings of input and output at the same DPI. | Practical, reproducible verification method (PDFs mix vector/raster; lossless page copy guarantees byte-equality of untouched pages). |

## Blockers
- None.

## Known Debt (minor, documented)
- `pdfpipeline._decode_raw_stream`: defensive fallback for raw image streams,
  not exercised by tests (`pragma: no cover`).
- GUI preview still uses `enhance_image` (Phase-1 preview); the "Run" path is
  correctly routed through `process_pdf`.
- Image replacement discards SMask (transparency) – smartboard screenshots are
  opaque (documented in ADR 0001).
- rerasterize: vector text becomes a bitmap at `--dpi` (documented trade-off,
  ADR 0001); use `--dpi 300` for sharper output.
- Legacy default output name `<stem>_inverted.pdf` kept for single-file runs
  without `--output` (backward compatibility).
- CI workflow (`.github/workflows/ci.yml`, coverage gate 80 %) runs on the
  GitHub remote (private repo `univie-henrikjurek/smartinvert`); current
  status green.
- Non-fatal CI annotations: Node.js 20 deprecation warnings for
  `actions/checkout@v4` / `actions/setup-python@v5` (update action versions
  when the newer majors are stable).
- GUI needs Tkinter (on Debian/Ubuntu: `sudo apt install python3-tk`); not
  available in the headless dev container, so the GUI was verified by
  syntax/compile checks only (logic follows the existing thread-safe pattern).

## Next Step
None – project is DONE. Repo pushed as v0.3.0.
