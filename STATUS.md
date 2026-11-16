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
  public history; the `.pyc` files embedded development-container build
  paths, not user-machine paths).
- History rewritten + force-pushed (master + tags v0.3.0/v0.4.0/v0.4.1),
  verified from an independent fresh clone: exactly the 25 project files,
  pattern scan clean, CI green (run 43725025521).
- Authorship unified: the 9 Phase-1/2 commits (and old `pyproject.toml`
  author fields in history) used a placeholder bot identity (name
  "Smartboard Bot" plus a placeholder e-mail). Rewritten via `git
  filter-repo` (`--commit-callback` + `--replace-text`) to Henrik Jurek /
  GitHub noreply e-mail; history force-pushed again and re-verified from a
  fresh clone (24/24 commits by Henrik Jurek, no placeholder e-mail left in
  any blob, no tokens or keys anywhere).

**v0.5.0 – crop + color options (merged 2026-11-15, tag v0.5.0).** Two
independent features, developed on parallel branches and merged in order
(crop first per user request, then colors rebased on top):

**ADR 0003 – crop to board rect** (`--crop` / `--no-crop`, default off):
- Post-stage `_save_cropped()` in `pdfpipeline.py` (in-memory round-trip,
  `show_pdf_page` + `clip`, vector-exact 1:1): every page with a detected
  board is re-sized to exactly that rectangle; pages without a board (incl.
  all rotated pages, A-11) keep full size; no board anywhere → page-faithful
  output + WARNING (never an empty file). CLI + JSON config key `crop`,
  GUI checkbox. `rect_pt` stored before the `do_something` fork so
  `--no-invert --crop` works. Detection, the 3 output methods, verification
  and debug are untouched.
- ADR correction (2026-11-15): the D2 r=90 derotation formula/value in the
  first draft confounded x and y (350×350 square for a 200×350 rect);
  corrected to `u = (v.y0, H−v.x1, v.y1, H−v.x0)`, empirically verified.
  Production code unaffected (uses `remove_rotation()`, not the formula).
- Review: 0 critical / 0 moderate; small pre-commit fixes (None guard,
  stale notes).

**ADR 0002 – target background + preserved marker colours**
(`--bg-target {complement|R,G,B}`, `--keep-colors {red,green,blue,yellow|none}`):
- `bg_target=complement` (default) = strict `255−v`, bit-identical to v0.4.1;
  `R,G,B` = linear per-channel remap `v' = T_c·(255−v)/(255−B_c)`,
  B_c = p25 per channel in the region clamped [0,220] — a dark-gray board
  can land on pure white instead of beige (user request).
- `keep_colors` default `red,green` (deliberate breaking change vs. v0.4.1,
  P3-D-1): marker pixels keep their ORIGINAL values (mask: dominant channel
  ≥ 80 and ≥ 40 above the others; computed on the original, applied last →
  precedence over complement/remap). Exact v0.4.1: `--bg-target complement
  --keep-colors none`.
- Core: one central pixel op `processing.invert_or_remap` (+ `color_mask`,
  `validate_bg_target`) — all four former `np.bitwise_not` sites route
  through it. JSON config keys `bg_target` / `keep_colors` (null = default).
  GUI: "Zielhintergrund" combobox (Complement/Reinweiß) + "Rot/Grün erhalten"
  checkboxes (both default on); combobox stays readonly after runs.
- The two features are orthogonal (crop = output stage, colors = pixel stage,
  mask/reference are region-local) and merge in either order.
- Review: 0 critical; both moderate findings fixed (Unicode-digit guard in
  `parse_bg_target` → clean error; central `validate_bg_target` in the public
  API). Known debt (small, documented): `parse_keep_colors("")` silently =
  none (fixed by test as implemented); some GUI labels German in an otherwise
  English UI (ADR-specified).

**Combined verification after rebase:** full suite green (colors 165 +
crop 20, GUI module headless-skipped), coverage gate met; CLI smoke with all
three flags (`--crop --bg-target 255,255,255 --keep-colors red,green`) and
GUI instantiation verified. Tagged **v0.5.0**.

**v0.6.0 – keep-hex (2026-11-16, tag v0.6.0).** Neue Option `--keep-hex`
(CLI + JSON-Config `keep_hex` + GUI-Textfeld „Zusätzliche Hex-Farben",
ADR 0004): explizite Hex-Farben und -bereiche, die zusätzlich zu den
Namens-Farben `--keep-colors` von der Inversion ausgenommen werden.

- Syntax: Kommaliste aus `RRGGBB` (Punkt; optionaler `#`, 3-stellige
  Kurzform `F00` → `FF0000`) oder `RRGGBB-RRGGBB` (Bereich, Endpunkte in
  beliebiger Reihenfolge, aufsteigend normalisiert). Beispiel (Nutzerfall):
  `FF0000, 00FF00, 000001-0000FF` = exakt Rot, exakt Grün, ganze blaue Achse
  vom dunkelsten bis zum hellsten Blau.
- Semantik (ADR 0004 D2): ein Pixel wird exkludiert, wenn sein euklidischer
  Abstand zur **Strecke** zwischen den Endpunkten ≤ `HEX_TOL` (50) ist
  (Punkt: Abstand zum Punkt) **und** der Chroma-Guard (max−min der Kanäle ≥
  `HEX_MIN_CHROMA` = 24) erfüllt ist. Der Guard verhindert, dass der dunkle
  Board-Hintergrund (neutrales Grau, Chroma ≈ 0) von Bereichen „verschluckt"
  wird, die am RGB-Ursprung ansetzen — er bleibt invertiert. Dokumentierter
  Caveat: praktisch unsichtbare Extremwerte (Chroma < 24, z. B. (0,0,8))
  werden bewusst nicht exkludiert; neutrale Graubereiche werden nicht
  unterstützt.
- Union mit der `--keep-colors`-Maske, letzter Schritt auf dem Original
  (Vorrang vor Complement/Remap, ADR 0002). Leer (Default) = aus,
  **bit-identisch zu v0.5.0** (Regressionstest auf Rendering-Ebene).
- Kern: `hex_keep_mask` + `validate_keep_segments` (zentr. Chokepoint,
  `processing.py`); `parse_keep_hex` in `cli.py` (Regex über ASCII-Hex —
  Unicode-Ziffern-Falle ausgeschlossen). `process_pdf`/`enhance_image[_ex]`/
  `invert_region` erhalten `keep_segments` (Keyword; Validierung in
  `process_pdf` vor jeder Datei-Operation).
- GUI: Textfeld Zeile 8 (Fenster 660×830), Validierung im Hauptthread **vor**
  Worker-Start (Fehlerdialog, Controls bleiben betätigbar, kein Worker);
  Feld wird nach einem Run nicht geleert; Preview validiert ebenfalls zuerst.
- Tests: 83 neue (Parser inkl. Unicode-Digit-Fall, Maske inkl. Grauschutz +
  Caveat, Union/Vorrang, bit-identische Regression, CLI/Config-e2e,
  Pipeline-E2E mit synthetischem Board inkl. reinem blauen Mark, GUI-Flows).
  268 passed + 1 skipped (headless), GUI-Modul 10 passed unter Xvfb,
  Coverage 91.59 % (Gate 80 %). GUI-E2E (echtes Tk-Fenster) grün inkl. beider
  neuer Flows.
- Hinweis: Subagent-Tool in der Implementierungs-Session nicht verfügbar
  (Backend-Fehler beim Session-Start) — Supervisor hat die
  Coder/Tester/Reviewer-Schritte direkt ausgeführt; Workflow (ADR →
  Implementierung → Tests → Review → PR/CI/Tag) unverändert.

**v0.7.0 – Optionen vereinfachen (2026-11-16, tag v0.7.0).** User-Feedback
nach v0.6.0: (1) „Noise cleaning (legacy)" lässt Inhalte verschwinden,
(2) „Rot/Grün erhalten" ist durch das Hex-Feld redundant, (3) „Apply CLAHE"
ist unverständlich. ADR 0005 (accepted):

- **D1 (breaking):** CLAHE + morphologisches Cleaning komplett entfernt —
  GUI, CLI (`--clahe/--no-clahe`, `--clean/--no-clean`), JSON-Config
  (`clahe`/`clean`), Backend (`processing._process_region` weg;
  `apply_clahe`/`clean`-Parameter aus `process_pdf`,
  `enhance_image[_ex]` und dem gesamten Pipeline-Plumbing entfernt;
  `do_something` reduziert auf `invert`). Begründung: Cleaning frisst
  dünne Striche/Text (User-Beobachtung), CLAHE ist für Farbinhalte
  destruktiv (Graustufen-Rundgang); beide waren seit v0.3.0 „legacy",
  default AUS. Ältere Configs mit diesen Keys laufen weiter (unbekannte
  Keys = Debug-Log, kein Fehler). `--clahe` am CLI → sauberes
  argparse-Error (exit 2).
- **D2:** GUI reduziert auf: DPI, „Invert colours", „Auf Board
  zuschneiden", „Zielhintergrund", „Zusätzliche Hex-Farben". Die
  Checkboxen „Apply CLAHE (legacy)", „Noise cleaning (legacy)", „Rot
  erhalten", „Grün erhalten" sind weg. `keep_colors` wird von der GUI
  **fix** als `{red, green}` übergeben (= bisheriger Default, keine
  Verhaltensänderung; `gui.GUI_KEEP_COLORS`); Hilfstext des Hex-Felds:
  „rot/grün bleiben immer erhalten". Fenster 660×830 → 660×700.
- Tests: 1 CLAHE-Test durch `test_invert_false_returns_unchanged` ersetzt
  (invert aus = bit-identisch), 2 Pipeline-Tests angepasst, 3 neue
  GUI-Tests (`TestSimplifiedOptions`: entfernte Widgets existieren nicht,
  verbleibende existieren, `keep_colors` erreicht `process_pdf` als
  `{red, green}`). **268 passed + 1 skipped** (headless), **13 GUI** unter
  Xvfb, Coverage **91.55 %** (Gate 80 %), GUI-E2E (Xvfb) ALL OK, CLI-Smoke
  (`--help` ohne clahe/clean, Real-Run mit `--keep-hex` +
  `--bg-target 255,255,255`, alte Config-Kompatibilität) ok.
- Doku: README (How-it-works, CLI-Block, GUI-Sektion, Config-Kompatibilität,
  Project layout), spec.md Phase-4-Addendum (P4-FR-1, P4-D-1).
- Branch `feature/simplify-options` → PR #4 → CI grün (3.9 + 3.13) →
  Rebase-Merge nach master.

**v0.7.1 – Crop als Default (2026-11-16, tag v0.7.1).** User-Feedback: im
Standard-Run stimmen die Seitengrenzen (A4) nicht mit dem sichtbaren
Board-Bereich überein; die Grenzen sollen nur den sichtbaren Bereich
beinhalten. ADR 0006 (accepted):

- Crop (ADR 0003) ist jetzt **Default AN** in allen Schichten:
  `process_pdf(crop=True)`, CLI `REAL_DEFAULTS["crop"] = True`
  (`--no-crop` für seitengetreue A4-Ausgabe), GUI-Checkbox „Auf Board
  zuschneiden (Rand entfernen)" standardmäßig angehakt.
- Seitenverhalten unverändert: nur Seiten mit erkanntem Board werden
  zugeschnitten (exakt auf das Rechteck); Seiten ohne Board (inkl.
  rotierter, A-11) bleiben in voller Größe; degenerate Rechtecke →
  volle Seite.
- Breaking Change für CLI-User mit A4-Erwartung: `--no-crop` angeben
  (0.x-Linie, dokumentiert: ADR 0006, spec P5-FR-1/P5-D-1, README).
- Tests: page-faithful-Tests pinnen jetzt `crop=False` explizit; der
  Pipeline-Test-Helfer `process()` defaultet `crop=False` (Test-Kontrakt).
  Neu: CLI-Default-Run-Test (crops ohne Flag),
  `TestCropRegression.test_default_run_matches_explicit_crop` (Default ==
  explizit crop=True, pixel-identisch; crop=False bleibt A4),
  GUI-Default-Tests (Checkbox 1, `crop=True` erreicht `process_pdf`).
  **269 passed + 1 skipped**, 13 GUI unter Xvfb, Coverage 91,55 %.
- Verifikation am Sample: Default-Run → Seite 299,4 × 821,4 pt (= Board),
  `--no-crop` → 595 × 842 pt (A4).
- Branch `feature/crop-default-on` → PR #5 → CI grün → Rebase-Merge.

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
None – **v0.7.1 released** (Crop als Default: Seitengrenzen = sichtbarer
Board-Bereich; PR #5 merged, tag `v0.7.1`). Distribution via the usual
ZIP/clone + `start.sh`/`start.bat`. Offen: Nutzer-Windows-Test der
v0.7.1-ZIP (neuer Default-Output: zugeschnittene Seiten).
