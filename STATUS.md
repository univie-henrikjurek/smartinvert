# Project Status – Smartboard Inversion

## Overview
This repository implements a PDF whiteboard/smartboard inversion tool (CLI + GUI)
using PyMuPDF, OpenCV and NumPy.

**Phase 1** (completed): render page → invert largest dark region → re-assemble PDF.
**Phase 2** (in progress): robust automatic detection of the rectangular smartboard
area per page + strictly selective inversion inside that rectangle, with exact
preservation of page size/position and fail-safe behaviour (never invert the whole
page, never move/crop content).

## Current Phase
- **Phase 2 – Implementation**: in progress.
- spec.md extended with a Phase 2 addendum (requirements P2-FR-1 … P2-FR-8).
- Analysis of existing code and of `inputs/test.pdf` is complete (see below).

## Phase 2 – Analysis Results (2026-11-14)

### Existing code (Phase 1)
- `smartboard_invert/processing.py`: `pdf_to_images` (render at DPI),
  `enhance_image` (CLAHE + morphology + inversion inside an Otsu/largest-contour
  mask), `images_to_pdf` (new page sized to image pixels in **pt** → **wrong page
  size**, e.g. A4@150dpi becomes a 1240×1755 pt page).
- `smartboard_invert/cli.py`: single-file CLI only (`--input` required as file,
  default output `<stem>_inverted.pdf`), no directory batch, no `--debug`.
- `smartboard_invert/gui.py`: Tkinter GUI around `enhance_image` (works, but its
  "Run" path re-uses the page-size bug of `images_to_pdf`).
- Detection (Phase 1): Otsu threshold + largest external contour only. Not robust
  for dark-gray backgrounds, no confidence, no ambiguity handling, no plausibility
  checks, can be triggered by large dark vector content.
- CLAHE/morphology were ON by default → distorts pixel values (conflicts with the
  strict `255 − v` requirement of Phase 2).
- Tests: 3 smoke tests only; no synthetic fixtures; no scenario coverage.
- Repo hygiene: `__pycache__/*.pyc` and `outputs/test_inverted.pdf` were tracked in
  git; no `.gitignore`.

### `inputs/test.pdf` (technical inspection)
- 1 page, A4 portrait, MediaBox `[0 0 595 842]` (595×842 pt), no rotation.
- **No image XObjects, no text** – content is 1229 vector paths.
- Smartboard background = one large vector-filled rectangle, fill
  RGB ≈ (19, 21, 25), size 299.4×821.8 pt at (147.7, 10.1)–(447.1, 831.9)
  → page-relative: x 24.8 %–75.1 %, y 1.2 %–98.7 %.
- On top: 1179 white paths (text/strokes), 48 salmon shapes RGB ≈ (247, 88, 88),
  1 blue shape RGB ≈ (25, 133, 232).
- Rendered @150dpi: 1240×1755 px; grayscale p5 = p25 = 21, p50–p95 = 255;
  dark (<128) = 48.2 % of the page; dark bbox px (308, 21, 931, 1733).
- **Consequence:** the pipeline must support **both** board types:
  (a) image-based (typical real smartboard export: one image per page) and
  (b) vector-based (like this sample). → dual-path design (see ADR 0001).

### Environment
- Project venv `.venv` (Python 3.13.5): PyMuPDF 2.1 (`import fitz` deprecated →
  prefer `import pymupdf`, compat shim added), opencv-python 5.0.0.93, numpy 2.5.4,
  Pillow 13.0.0; `pytest`/`pytest-cov` were missing and have been installed.
- CI (GitHub Actions) pins Python 3.9 → code must stay 3.9-compatible
  (`from __future__ import annotations`, no 3.10+-only syntax).

## Phase 2 – TODO Tracker
| ID | Description | Owner | Status | Notes |
|----|-------------|-------|--------|-------|
| T-20 | Analyse bestehendes Projekt + `inputs/test.pdf`, Ergebnisse dokumentieren | Supervisor | completed | see above |
| T-21 | Repo-Hygiene: `.gitignore`, pyc/outputs untracken, Baseline-Commit | Supervisor | in_progress | |
| T-22 | ADR 0001: Erkennungsstrategie + Image-Replacement vs. Re-Rasterisierung | Architect | pending | `docs/adr/0001-*.md` |
| T-23 | `detection.py` (DetectionResult + robust detection) + fitz-compat + `invert_region`/`enhance_image` update | Coder | pending | |
| T-24 | Unit-Tests `detection.py` (synthetic images, all fail-safe cases) | Tester | pending | |
| T-25 | `pdfpipeline.py` (process_pdf, image replacement + re-raster fallback, debug viz, verification) | Coder | pending | |
| T-26 | Pipeline-Tests (8 mandatory scenarios incl. multi-page, no-board, size) | Tester | pending | |
| T-27 | CLI rework (dir batch, `python -m smartboard_invert`, `--debug`) + GUI fix | Coder | pending | |
| T-28 | CLI-Tests (batch, same-name output, input untouched, `--debug`) | Tester | pending | |
| T-29 | Full test suite green | Tester | pending | |
| T-30 | Real run on `inputs/test.pdf` + technical/visual verification | Coder/Supervisor | pending | output: `outputs/test.pdf` |
| T-31 | Reviewer diff review, fix critical findings | Reviewer | pending | |
| T-32 | README + STATUS final update (DONE) | Supervisor | pending | |

(Phase 1 tracker T-01 … T-18: completed, see git history / commit `ef9e5ab`.)

## Assumptions (Phase 2, documented decisions)
| # | Assumption | Rationale |
|---|------------|-----------|
| A-8 | The sample file is `inputs/test.pdf` (task text says `Test.pdf`; Linux is case-sensitive and only the lowercase file exists). | Observed file system state. |
| A-9 | Default pipeline is pure `255 − v` inversion; CLAHE/morphology are opt-in (`--clahe`, `--clean`, default off). | Phase-2 spec requires strict pixel inversion (P2-FR-3). |
| A-10 | Replaced image XObjects are re-encoded as PNG (lossless). | Preserves anti-aliasing exactly; file size acceptable. |
| A-11 | Pages with non-zero rotation or unusual structure are handled by the re-rasterization fallback with a warning. | Rare edge case; fail-safe over fancy handling. |
| A-12 | `outputs/` and `__pycache__/` are generated artifacts → untracked, `.gitignore` added. | Repo hygiene; inputs/ (sample) stays tracked. |
| A-13 | Detection DPI = output render DPI = `--dpi` (default 150). | One knob, Phase-1 default preserved; 150 dpi is sufficient for robust rectangle detection (board areas are hundreds of px). |
| A-14 | "Pixelgenau unverändert außerhalb des Rechtecks" is verified against re-renderings of input and output at the same DPI (PDFs are vector/raster mixed; exact byte-equality of untouched pages is guaranteed by lossless page copy where applicable). | Practical, reproducible verification method. |

## Blockers
- None at the moment.

## Known Debt (carried over / minor)
- GUI "Run" path will be routed through `process_pdf` (fixes its page-size bug);
  GUI preview keeps using `enhance_image`.
- Old default-output naming `<stem>_inverted.pdf` is only kept for single-file
  runs without `--output` (backward compatibility).

## Next Step
Commit baseline (T-21), then ADR 0001 (T-22), then implementation T-23…T-28.
