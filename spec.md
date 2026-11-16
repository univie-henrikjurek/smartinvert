## PDF Whiteboard Inversion Program – Specification

### 1. Goal
Create a small, cross‑platform Python application that loads a PDF (typically a scanned whiteboard or presentation), converts each page into an image, applies an “inversion” / “enhancement” pipeline that makes dark‑on‑light handwritten or printed content more readable, and writes the processed pages back to a new PDF. The tool should be usable both as a **CLI** for batch processing and as a **simple GUI** (single‑window) for interactive use.

### 2. Functional Requirements

| # | Requirement | Description |
|---|-------------|-------------|
| **FR‑1** | Input handling | Accept a PDF file path (or a folder of PDFs). Validate that the file can be opened with PyMuPDF. |
| **FR‑2** | Page‑wise rasterisation | Render each PDF page to an image (preferably PNG) using PyMuPDF at a configurable DPI (default = 150 dpi). |
| **FR‑3** | Image preprocessing | For each rasterised page, apply the following OpenCV steps (configurable): <br>1. Convert to grayscale.<br>2. Adaptive histogram equalization (CLAHE) to improve contrast.<br>3. Adaptive threshold or Otsu to obtain a binary mask.<br>4. Invert mask (white → black, black → white) **or** apply a “negative” transformation depending on user selection.<br>5. Optional morphological operations (open/close) to clean noise. |
| **FR‑4** | Output PDF generation | Re‑assemble the processed images into a PDF preserving original page order, using PyMuPDF. Output path is user‑specified or defaults to `<input‑name>_inverted.pdf`. |
| **FR‑5** | CLI interface | Provide a `smartboard-invert` command with flags: <br>`--input`, `--output`, `--dpi`, `--invert` (boolean), `--clean` (morphology), `--verbose`. |
| **FR‑6** | GUI interface | Simple tkinter (or PySimpleGUI) window with: <br>- File selector (PDF).<br>- DPI slider.<br>- Checkboxes for "Invert colours", "Apply CLAHE", "Clean noise".<br>- “Preview” button that shows the first page before/after processing.<br>- “Run" button to start batch conversion and show progress bar. |
| **FR‑7** | Logging | Emit progress information to stdout (CLI) and to a scrolling text widget (GUI). Errors must be reported clearly. |
| **FR‑8** | Error handling | Gracefully handle corrupted PDFs, missing fonts, unsupported page sizes, and report meaningful messages without crashing. |
| **FR‑9** | Configuration file (optional) | Allow a JSON/YAML config file that stores default options (DPI, processing flags). CLI flag `--config` loads it. |
| **FR‑10** | Unit‑testable API | Core processing logic (PDF → image → enhanced image → PDF) must be exposed as importable Python functions/classes so that automated tests can invoke them without UI. |

### 3. Non‑Functional Requirements

| # | Requirement | Target |
|---|-------------|--------|
| **NFR‑1** | **Portability** | Works on Windows, macOS, Linux with Python 3.9+. |
| **NFR‑2** | **Performance** | Typical 8‑page 8 MB whiteboard PDF processed at ≤ 5 seconds on a modern laptop (150 dpi, default pipeline). |
| **NFR‑3** | **Memory usage** | Process pages sequentially; max RAM ≤ 200 MB for a 30‑page document. |
| **NFR‑4** | **Usability** | GUI must be intuitive – < 2 clicks from file selection to start. |
| **NFR‑5** | **Reliability** | Exit code 0 on success, non‑zero on failure. No unhandled exceptions. |
| **NFR‑6** | **Maintainability** | Code follows PEP 8, typed with `typing` hints, and includes docstrings. |
| **NFR‑7** | **Testing coverage** | ≥ 80 % line coverage for core processing functions. |
| **NFR‑8** | **Licensing** | All dependencies are MIT/BSD‑compatible; the project will be released under MIT. |

### 4. Technology Stack

| Component | Library / Tool | Reason |
|-----------|----------------|--------|
| **Language** | Python ≥ 3.9 | Wide ecosystem, easy for scientific image processing |
| **PDF handling** | **PyMuPDF** (`fitz`) | Fast rasterisation, easy PDF creation |
| **Image processing** | **OpenCV‑Python** (`cv2`) | Mature, efficient, provides all required ops |
| **GUI** | **Tkinter** (built‑in) *or* **PySimpleGUI** (thin wrapper) | No extra heavy dependencies, cross‑platform |
| **CLI parsing** | `argparse` (std lib) or `click` (optional) | Simple argument handling |
| **Logging** | `logging` (std lib) | Configurable verbosity |
| **Testing** | `pytest`, `pytest-cov` | Popular, easy coverage reporting |
| **Packaging** | `setuptools`/`poetry` | Create installable wheel & entry‑point script |

### 5. UI Expectations
#### 5.1 CLI
```
smartboard-invert --input board.pdf --output board_fixed.pdf \
    --dpi 200 --invert --clean --verbose
```
* Should print a progress line per page (e.g., “Processing page 3/12 …”).
* On error, prints a concise message and exits with non‑zero code.
#### 5.2 GUI
* **Main window** (≈ 400 × 300 px) containing:
  * File‑chooser entry + “Browse” button.
  * DPI slider (50 – 300).
  * Checkboxes: “Invert colours”, “Apply CLAHE”, “Clean noise”.
  * “Preview first page” button → opens a side‑by‑side view (original vs processed).
  * “Run” button → disables inputs, shows a progress bar, then a success dialog with output path.
* All controls must have tool‑tips describing their effect.

### 6. Testing Approach
1. **Unit tests** for each processing function:
   * `pdf_to_images(pdf_path, dpi)` → list of `numpy.ndarray`.
   * `enhance_image(img, invert, clahe, clean)` → processed `numpy.ndarray`.
   * `images_to_pdf(images, out_path)` → file existence & page count check.
2. **Integration tests** using small fixture PDFs (1‑3 pages, known content). Verify that the output PDF is **visually different** (pixel‑hash comparison) and that the page count matches.
3. **CLI tests** with `subprocess.run` to confirm exit codes and stdout messages.
4. **GUI sanity test** (optional) using `pytest-qt` or similar – at least ensure the main window launches without error.
5. **Performance test** – measure processing time on a generated 10‑page dummy PDF; assert < 5 s.
6. **Coverage** – enforce ≥ 80 % line coverage via `pytest --cov=smartboard_invert`.

### 7. Assumptions (Documented Decisions)
| # | Assumption | Rationale |
|---|------------|-----------|
| **A‑1** | Input PDFs are **single‑layer** scans (no existing vector text). | Inversion mainly benefits rasterised handwriting/markers. |
| **A‑2** | Users want **binary** or **negative** output, not colour preservation. | Simplifies pipeline; colour versions can be added later.
| **A‑3** | The GUI will be **single‑window**; no multi‑document tabs. | Keeps complexity low for the MVP.
| **A‑4** | Processing is **page‑by‑page**, no parallelism. | Lower memory footprint; parallelism can be added if needed.
| **A‑5** | The default DPI of **150** provides a good trade‑off between quality and speed. | Commonly used for scanned documents.
| **A‑6** | The program will be distributed as a **wheel** and an entry‑point script (renamed `smartinvert` in v0.3.0, was `smartboard-invert`). | Eases installation via `pip`.
| **A‑7** | No OCR or text extraction is required. | Out of scope for the inversion focus. |

### 8. Acceptance Criteria
* **AC‑1** – All functional requirements (FR‑1 – FR‑10) are implemented and demonstrable.
* **AC‑2** – CLI processes a sample 5‑page PDF in ≤ 4 seconds on a reference machine (Intel i5, 8 GB RAM).
* **AC‑3** – GUI loads, allows preview, and completes conversion with a progress bar.
* **AC‑4** – Unit and integration test suite passes with ≥ 80 % coverage.
* **AC‑5** – Application exits with code 0 on success, non‑zero on any error (e.g., corrupted PDF).
* **AC‑6** – Documentation (README) explains installation, usage (CLI & GUI) and how to run tests.

---

*Document version:* 2026‑11‑12, **Planner v1.0**

---

## Phase 2 (2026‑11‑14): Selektive Smartboard-Invertierung mit automatischer Bereichserkennung

Phase 2 ersetzt das Kernverhalten von Phase 1: Das Tool invertiert **nicht** mehr die
gesamte Seite bzw. ein beliebig dunkles Kontur-Areal, sondern erkennt pro Seite das
rechteckige Smartboard-Bild und invertiert **ausschließlich** dieses Rechteck.

### 2.1 Neue/veränderte Anforderungen (govern Phase 2)

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P2‑FR‑1** | Automatische Rechteckerkennung | Pro Seite selbstständige Erkennung des rechteckigen Smartboard-Inhaltsbereichs via Helligkeitsanalyse, adaptivem Thresholding, Connected Components, Bounding-Box-/Rechteck-Analyse. Muss auch dunkelgraue Hintergründe erkennen, darf nicht durch einzelne dunkle Zeichen/Zeichnungen ausgelöst werden, toleriert leichte Rand-Schatten. |
| **P2‑FR‑2** | Fail-safe | Wenn kein **eindeutiger** Bereich erkannt werden kann: verständliche Warnung, Seite bleibt **unverändert**. Es darf **niemals** die gesamte (weiße) Seite invertiert werden und der Inhalt nie außerhalb seines ursprünglichen Rechtecks erscheinen/beschnitten werden. |
| **P2‑FR‑3** | Selektive Invertierung | Nur innerhalb der erkannten Bounding Box: `kanal_neu = 255 − kanal_alt` (RGB, pixelbasiert). Alles außerhalb bleibt pixelgenau unverändert. Anti-Aliasing/Graustufen/Farben werden damit natürlich übernommen. |
| **P2‑FR‑4** | Seitengröße & Position | Ursprüngliche Seitengröße (MediaBox) und Position des Smartboard-Bereichs müssen exakt erhalten bleiben. Kein Zuschneiden, keine neue Seitengröße. |
| **P2‑FR‑5** | Batch & Dateinamen | Alle PDFs in `inputs/` verarbeiten; Ausgabe im Output-Verzeichnis **unter demselben Dateinamen** (`inputs/Test.pdf` → `outputs/Test.pdf`). Originaldateien dürfen nie überschrieben/geändert werden. |
| **P2‑FR‑6** | Mehrseitigkeit | Jede Seite wird unabhängig analysiert; Reihenfolge und Anzahl der Seiten bleiben erhalten. |
| **P2‑FR‑7** | Debug-Visualisierung | Option (`--debug`): pro Seite ein Composite-Bild (Original \| Original mit BBox \| Ergebnis) unter `outputs/debug/`. |
| **P2‑FR‑8** | CLI | `python -m smartboard_invert` (Default: `inputs/` → `outputs/`); `--input`, `--output` (Datei **oder** Verzeichnis), `--dpi`, `--verbose`; `--clahe`/`--clean` bleiben als Optionen erhalten, sind aber **default AUS** (reine Invertierung). |

### 2.2 Abweichungen zu Phase 1 (dokumentiert)

| # | Abweichung | Begründung |
|---|------------|------------|
| **P2‑D‑1** | CLAHE & Morphology default **aus** | Phase-2-Invertierung ist strikt `255 − v`; Vor-Verarbeitung würde Pixelwerte verfälschen. Beide bleiben als opt-in Flags (Rückwärtskompatibilität). |
| **P2‑D‑2** | Output heißt wie Input (im Output-Verzeichnis), nicht `<stem>_inverted.pdf` | Vorgabe Phase 2 (Batch-Verarbeitung). Einzelne Datei-→-Datei-Konvertierung bleibt möglich. |
| **P2‑D‑3** | Ausgabe-PDF-Erzeugung: Image-XObject-Ersetzung (Primärpfad) bzw. Re-Rasterisierung **in Original-Größe** (Fallback) statt „Bildgröße = Seitengröße in pt“ | Phase-1-Verfahren erzeugte Seiten in Pixelgröße (A4@150dpi → 1240×1755 pt) und verstieß gegen P2‑FR‑4. |
| **P2‑D‑4** | Erkennung läuft auf hochauflösendem Seiten-Render **und** (falls vorhanden) auf dem nativen Bild-XObject | Die Beispieldatei `inputs/test.pdf` enthält **keine** Bild-XObjects, sondern Vektor-Grafik (ein dunkles Rechteck + weiße Pfade). Echte Smartboard-Exporte sind typischerweise ein einzelnes Bild pro Seite. Beide Fälle müssen funktionieren. |

### 2.3 Pflichttest-Szenarien (Phase 2)

1. Weißer Seitenhintergrund + schwarzes Smartboard-Rechteck.
2. Weißer Seitenhintergrund + dunkelgrauem Smartboard-Rechteck.
3. Weißer Seitenhintergrund + Rechteck in unterschiedlicher Position.
4. Mehrseitige PDF (jede Seite eigenständig).
5. PDF **ohne** erkennbaren Smartboard-Bereich → Warnung, Seite unverändert.
6. Pixel außerhalb des erkannten Bereichs bleiben unverändert.
7. Weiße Schrift im Board wird nach der Invertierung dunkel.
8. PDF-Seitengröße bleibt unverändert.

Alle Szenarien werden mit **synthetischen** PDFs/Bildern getestet (unabhängig von
`inputs/test.pdf`).

---

*Phase 2 addendum:* 2026‑11‑14, **Supervisor**

---

## Phase 3 (2026‑11‑15): Ziel-Hintergrundfarbe & erhaltene Markerfarben

Phase 3 erweitert die In-Region-Transformation, ohne Erkennung, Ausgabemethoden
(copy/image-replace/rerasterize), Verifikation oder Debug zu ändern: optionales
lineares Remap auf eine Ziel-Hintergrundfarbe statt strikter `255 − v` sowie die
Möglichkeit, Markerfarben (z. B. rot/grün für Weggestrichenes/Angehaktes)
**nicht** zu invertieren. Grundlage:
[ADR 0002](docs/adr/0002-farbeziele-und-erhaltene-farben.md).

### 3.1 Neue Anforderungen (govern Phase 3)

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P3‑FR‑9** | Ziel-Hintergrundfarbe (`--bg-target`) | Default `complement` = strikt `255 − v` (bit-identisch zu v0.4.1). `R,G,B` (jeweils 0–255): lineares pro-Kanal-Remap `v' = T_c·(255−v)/(255−B_c)`; `B_c` = p25 des Kanals im Remap-Input (nach optionalem CLAHE/clean), geclampt auf `[0, 220]` (Nenner ≥ 35); float32, round-half-up, clip 0–255. Anker: `v = B_c → T_c` (Board-Hintergrund landet exakt auf der Zielfarbe), `v = 255 → 0` (Weiß bleibt Schwarz). |
| **P3‑FR‑10** | Erhaltene Markerfarben (`--keep-colors`) | Pixel passender Markerfarben behalten ihre **Originalwerte** – Exklusion wird auf dem Original (vor CLAHE/clean/Inversion) berechnet und hat **Vorrang** vor Complement und Remap (letzter Schritt). Maske: Kanaldominanz Δ = 40 und dominanter Kanal ≥ 80 (yellow: R, G ≥ 80, beide > B + 40); OR über die angefragten Farben aus red,green,blue,yellow (unbekannt → Fehler). Default `red,green`; `none` = alles invertieren (v0.4.1-Verhalten). |
| **P3‑FR‑11** | Hex-Farben und -bereiche (`--keep-hex`, GUI-Textfeld) | Freie Angabe weiterer von der Transformation ausgenommener Farben (Zusatz zu `--keep-colors`, ADR 0004): Kommalist, pro Eintrag `RRGGBB` (Punkt; `#`-Prefix und 3-stellige Kurzform erlaubt) oder `RRGGBB-RRGGBB` (Bereich; Endpunkte in beliebiger Reihenfolge, aufsteigend normalisiert). Ein Pixel ist exkludiert, wenn der euklidische Abstand zur **Strecke** zwischen den Endpunkten ≤ 50 ist (Punkt: Abstand zum Punkt) **und** der Chroma-Guard (max−min der Kanäle ≥ 24) erfüllt ist. Union mit der `--keep-colors`-Maske, letzter Schritt auf dem Original (Vorrang wie P3‑FR‑10). Leer (Default) = aus, Verhalten bit-identisch zu v0.5.0. Beispiel: `FF0000, 00FF00, 000001-0000FF` = exakt Rot, exakt Grün, ganze blaue Achse vom dunkelsten bis zum hellsten Blau. |

### 3.2 Abweichungen (dokumentiert)

| # | Abweichung | Begründung |
|---|------------|------------|
| **P3‑D‑1** | **Bewusster Default-Wechsel (breaking):** Default ist jetzt `complement` + `red,green`, d. h. ≠ v0.4.1 (dort: reine `255 − v`, keine Farben erhalten) | User-Entscheidung: sehr dunkle Boards sollen nicht „beige“ wirken (Remap-Option) und rot/grüne Marker (Weggestrichenes, Angehaktes) sollen lesbar bleiben. Exaktes v0.4.1-Verhalten bleibt reproduzierbar und als Regression gesichert: `smartinvert -i in.pdf -o out.pdf --bg-target complement --keep-colors none` → bit-exact `np.bitwise_not`. |
| **P3‑D‑2** | Neue Config-Keys `bg_target` / `keep_colors` (String, CLI-Syntax: `"complement"` bzw. `"R,G,B"`; `"none"` bzw. Kommasetz aus red,green,blue,yellow) in `REAL_DEFAULTS` + `_CONFIG_TYPES` | Zentrale Parser `parse_bg_target`/`parse_keep_colors` in `cli.py` als einziger Chokepoint für CLI-Flag und JSON-Config; `process_pdf`/`enhance_image[_ex]`/`invert_region` erhalten die Optionen als Keyword-Parameter (Default = v0.4.1-Verhalten). |
| **P3‑D‑3** | Neues Flag `--keep-hex` + Config-Key `keep_hex` (String, CLI-Syntax; `""` = aus) und GUI-Textfeld (Default leer, wird nach einem Run nicht geleert) als **orthogonales** Option zu `--keep-colors` (ADR 0004) | Namens-Farben bleiben die grobe Heuristik (Dominanz-Maske); explizite Hex-Spezifikationen geben exakte Kontrolle (Nutzerfall: exakt Rot, exakt Grün, ganze blaue Achse `000001-0000FF`). Parser `parse_keep_hex` in `cli.py` (Chokepoint; Regex über ASCII-Hex, Unicode-Ziffern ausgeschlossen); zentrale Validierung `validate_keep_segments` in `processing.py`; `process_pdf`/`enhance_image[_ex]`/`invert_region` erhalten `keep_segments` als Keyword-Parameter. Bewusste Einschränkung (dokumentiert, ADR 0004 D2): der Chroma-Guard (≥ 24) schließt neutrale Grautöne — v. a. den dunklen Board-Hintergrund — aus; Graubereiche werden dadurch nicht unterstützt. |

Hinweis: Die Annahme **A‑2** („binary/negative output, no colour preservation“)
ist damit **teilweise ersetzt** — selektive Farb-Erhaltung ist Teil des neuen
Default-Verhaltens. Blue/yellow und freie `R,G,B`-Ziele bleiben CLI-only; die
GUI bietet Combobox (Complement/Reinweiß) + Checkboxen „Rot/Grün erhalten“ +
Textfeld „Zusätzliche Hex-Farben“ (P3‑FR‑11).

---

*Phase 3 addendum:* 2026‑11‑15, **Coder**

---

## Phase 4 (2026‑11‑16): Optionen vereinfachen (v0.7.0)

Phase 4 entfernt überflüssige/verwirrende Legacy-Optionen (keine neue
User-Feature): das CLAHE-Kontrast-Enhancement und die morphologische
Noise-Cleaning (seit v0.3.0 „legacy" und default AUS) werden komplett
entfernt, die GUI wird auf die relevanten Optionen reduziert. Grundlage:
[ADR 0005](docs/adr/0005-optionen-vereinfachen.md).

### 4.1 Geänderte Anforderungen (ersetzen Phase 2/3 teilweise)

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P4‑FR‑1** | Optionsatz (v0.7.0) | CLI: `--input`, `--output`, `--dpi`, `--invert/--no-invert`, `--crop/--no-crop`, `--bg-target`, `--keep-colors`, `--keep-hex`, `--debug`, `--config`, `-v`, `--version`. **Entfernt (breaking):** `--clahe/--no-clahe`, `--clean/--no-clean` sowie Config-Keys `clahe`/`clean` (unbekannte Keys werden ignoriert, kein Fehler). GUI: DPI, „Invert colours", „Auf Board zuschneiden", „Zielhintergrund", „Zusätzliche Hex-Farben" — **entfernt:** „Apply CLAHE (legacy)", „Noise cleaning (legacy)", „Rot erhalten", „Grün erhalten". (Ersetzt FR‑3/FR‑5/FR‑6 bzw. P2‑FR‑8 in den entfallenen Punkten; die GUI-Notiz am Ende des Phase‑3‑Addendums zu den Checkboxen gilt damit nicht mehr.) |

### 4.2 Abweichungen (dokumentiert)

| # | Abweichung | Begründung |
|---|------------|------------|
| **P4‑D‑1** | **Breaking Change (v0.7.0):** CLAHE und morphologisches Cleaning aus GUI, CLI, Config und Backend entfernt (`_process_region` weg; `do_something` reduziert auf `invert`). Die GUI übergibt `keep_colors` **fix** als `{red, green}` (bisheriger Default — keine Verhaltensänderung). | User-Feedback (2026‑11‑16): Noise-Cleaning „lässt alles verschwinden" (Morphologie frisst dünne Striche/Text); CLAHE ist Endnutzern unverständlich und für Farbinhalte destruktiv (Graustufen-Rundgang). Beide Optionen waren seit v0.3.0 „legacy", default AUS und für den Use-Case (saubere Smartboard-PDFs) unnötig; die Red/Grün-Checkboxen waren durch das Hex-Feld (ADR 0004) redundant. Breaking Changes in der 0.x-Linie zulässig und dokumentiert (README, Config-Kompatibilitäts-Hinweis). |

---

*Phase 4 addendum:* 2026‑11‑16, **Supervisor**

---
