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

## Phase 5 (2026‑11‑16): Crop als Default (v0.7.1)

Phase 5 macht das Zuschneiden auf das Board-Rechteck (ADR 0003) zum
Standardverhalten: die Seitengrenzen sollen per Default **nur den
sichtbaren Bereich** enthalten (User-Feedback 2026‑11‑16). Grundlage:
[ADR 0006](docs/adr/0006-crop-als-default.md).

### 5.1 Geänderte Anforderungen (ersetzen P2‑FR‑8/ADR 0003 D4 teilweise)

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P5‑FR‑1** | Crop default AN (v0.7.1) | `process_pdf(crop=True)`, CLI-Default `crop=True` (`--no-crop` deaktiviert), GUI-Checkbox „Auf Board zuschneiden (Rand entfernen)" default angehakt. Seitenverhalten unverändert (ADR 0003): nur Seiten mit erkanntem Board werden zugeschnitten (exakt auf das Rechteck), Seiten ohne Board (inkl. rotierter Seiten, A‑11) behalten die volle Größe. Ältere CLI-User, die seitengetreue Ausgabe wollen: `--no-crop` (Breaking Change in 0.x, dokumentiert). |

### 5.2 Abweichungen (dokumentiert)

| # | Abweichung | Begründung |
|---|------------|------------|
| **P5‑D‑1** | Seitengetreue Ausgabe (Original-Seitengröße inkl. Seitenrand um das Board) ist jetzt **opt-in** (`--no-crop` / Checkbox abhaken); der Standard-Run liefert zugechnittene Seiten. | User-Anforderung (2026‑11‑16): „die Grenzen des Dokuments [sollten] nur den sichtbaren Bereich beinhalten" — im Standard-Run deckten sich Seitengrenzen (A4) nicht mit dem sichtbaren Board. Crop liefert exakt dieses Verhalten (seit v0.5.0 verifiziert: Seite = Inhalt, < 0,5 pt Abweichung). Die Suite pinnt in den page-faithful-Tests `crop=False` explizit; der Pipeline-Test-Helfer `process()` defaultet auf `crop=False` (Test-Kontrakt, nicht Produkt-Default). |

---

*Phase 5 addendum:* 2026‑11‑16, **Supervisor**

---

## Phase 6 (2026‑11‑16): Crop-Robustheit + GUI-Ordner-Batch + Fehlerdialoge (v0.7.2)

Phase 6 behebt zwei User-Bugreports zu v0.7.1: (1) Crop produzierte auf
Dokumenten mit **versetztem MediaBox/CropBox** (Ursprung ≠ (0,0)) falsch
geklippte Seiten („dünner Rahmen, viel Weiß, Streifen in der Mitte");
(2) die GUI crashte bei Ordner-Input — der Fehlerdialog selbst war kaputt
(`NameError` durch späte Bindung der `except`-Variable, PEP 3110), und
Ordner-Batch war in der GUI nie implementiert (CLI hatte sie).
Grundlage: [ADR 0007](docs/adr/0007-crop-render-slice-und-gui-ordner-batch.md).

### 6.1 Geänderte Anforderungen

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P6‑FR‑1** | Crop per Render-Slice | `_save_cropped` rendert die faithful-Seite mit dem Processing-DPI und schneidet exakt `rect_px` aus (dasselbe Rechteck wie Transformation/Verifikation); der Slice wird 1:1 in eine Seite der Größe `rect_pt` eingebettet. Keine Pixel→Seitenraum-Transformation (der frühere `show_pdf_page(clip=…)`-Weg brach an PyMuPDF-2.x-Koordinatenraum-Inkonsistenzen bei versetzten Seiten). Qualitäts-Trade-off: fremder Vektor-Content *innerhalb* des Board-Rechtecks wird statt vektor-exakt mit dem Processing-DPI gerastert (Board-Bereich selbst ist nach der Transformation ohnehin Raster; `--dpi 300` für schärfere Ausgabe). |
| **P6‑FR‑2** | GUI-Ordner-Batch | Ordner-Input verarbeitet die GUI wie die CLI (`_plan_jobs`-Semantik: sortierte `*.pdf` des Ordners → Output-Ordner, pro Datei `<name>.pdf`, kein Rekurs; Einzel-Fehler unterbrechen nicht den Batch). Einzel-Datei: unverändert (page-level Progress). Batch: file-level Progress + Summary-Dialog („Saved N file(s) to …" bzw. „N of M failed" mit Details). Ordner ohne Output-Ordner → Warning im Hauptthread, kein Worker. |
| **P6‑FR‑3** | Robuste GUI-Fehlerdialoge | Alle `messagebox`-Lambdas im Worker binden ihre Nachricht eager (`lambda t=title, m=message, f=fn: f(t, m)`); `except ... as e`-Variablen sind am Ende des Blocks ungebunden (PEP 3110) und durften nicht mehr als Free Variable verzögert gelesen werden. |

### 6.2 Abweichungen (dokumentiert)

| # | Abweichung | Begründung |
|---|------------|------------|
| **P6‑D‑1** | ADR 0003 „vector-exact" für den Crop-Post-Stage wird revidiert (P6‑FR‑1): Board-Seiten enthalten nach der Transformation nur Raster-Content im Board-Bereich → kein Qualitätsverlust dort; Vektor außerhalb des Rechtecks wird weggeschnitten; Vektor *innerhalb* des Rechtecks (selten) wird gerastert. | Repariert den User-Report (falsch geklippte Offset-MediaBox-Seiten); PyMuPDF 2.1 berichtet `page.rect`/`get_image_info`/`show_pdf_page(clip=…)` in inkonsistenten Koordinatenräumen (empirisch verifiziert: origin-(0,0)-Seite: crop == faithful-Slice mit Diff 0; Offset-Seite: Mismatch). Der Render-Slice ist version-unabhängig und deterministisch (Regressionstests: Offset-MediaBox- und Offset-CropBox-Seiten, crop-Render == faithful-Slice, Diff ≤ 8 im 2-px-erodierten Inneren). |

---

*Phase 6 addendum:* 2026‑11‑16, **Supervisor**

---

## Phase 7 (2026‑11‑17): Vektorerhaltende Inversion (v0.8.0)

Phase 7 erfüllt den User-Wunsch „das SVG, das von der Schrift gespeichert
wird, komplett übernehmen": Vektor-Board-Seiten (z. B. exportierte
Vorlesungs-Skripte) kamen bisher über `rerasterize` → auf 300 DPI pixelig,
obwohl das Original scharf ist. Ab jetzt werden sie **vektorerhaltend**
invertiert. Grundlage:
[ADR 0008](docs/adr/0008-vektorerhaltende-inversion.md).

### 7.1 Neue/veränderte Anforderungen

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P7‑FR‑1** | Neue Methode `vector-invert` | Vektor-Board-Seiten ohne Bild-XObject werden vor dem Raster-Fallback per Content-Stream-Umschreibung invertiert: die Farb-Operatoren des Fidelity-Copy-XObject-Baums (Form-`/fzFrm0` → `/fullpage` → evtl. verschachtelte Forms) werden pro Paint (Pfad-Füllung/-Stroke, Text) geometrisch entschieden (BBox × CTM-Kette vs. `rect_pt`: außerhalb → behalten; nah-weiße Vollläche → Background-Plate, behalten; innen/straddling → invertieren). Farb-Mathematik = exakt dieselbe wie Raster-Pfad (`floor(v·255)`-Quantisierung, `255−v` / bg_target-Remap mit gleichem `B_c`, Keep-Ausschlüsse `color_mask`/`hex_keep_mask` auf 1×1). Original-Farb-Operanden werden **nie** umgeschrieben — bei Widerspruch wird ein expliziter Farb-Operator vor dem ersten Operand des Paints eingeschoben (bei Text vor dem String-/Array-Operand, sonst bricht MuPDFs Text-Extraktion). Geometrie, Texte, Fonts bleiben 1:1 Vektor. `PageResult.method = "vector-invert"`. |
| **P7‑FR‑2** | Selbstheilender Raster-Fallback | Alles, was die v1-Umschreibung nicht exakt vermag (`VectorUnsupported`: Inline-Images `BI`, Shadings `sh`, ExtGState `gs`, `scn/SCN`, nicht-Device-Farbräume `cs/CS`, rotierte/schiefe Text-Matrizen, Image-XObject innerhalb/nah am Board), schlägt die Seite auf den bewährten Raster-Pfad um (`method = "rerasterize"`, volle D2-/P2-Außengarantien). Die Ausgabe kann nie schlechter werden als ohne P7. |
| **P7‑FR‑3** | Verifikation gegen Raster-Grundwahrheit (D2) | Nach dem Write-back wird die Seite gerendert und mit dem Raster-Transform-Ergebnis (Original + Inversion nur in `rect_px`) verglichen; ein ±AA-Band um `rect_px` (`max(4, dpi/36+2)` px) ist ausgenommen (fundamentaler Semantik-Unterschied an der Board-Kante), Rest: max-Diff ≤ 3. `_verify_page` exkludiert für `vector-invert` dasselbe Band (sonst Toleranz 0). |
| **P7‑FR‑4** | Vektor-exakter Crop (D3) | Die Crop-Stage bevorzugt für `vector-invert`-Seiten `show_pdf_page(clip=rect_pt)` (Clip auf das Render-Pixel-Gitter quantisiert) — bleibt Vektor, empirisch pixel-exakt (inkl. Offset-MediaBox). Sicherheitsnetz: Vergleich gegen die Render-Slice-Grundwahrheit (3-px-Rand, max ≤ 2); bei Abweichung → Raster-Slice (P6‑FR‑1). |
| **P7‑FR‑5** | Keine neuen Optionen | Der Vektor-Weg ist automatisch (Conditionen + Fallback); kein CLI-Flag, keine GUI-Checkbox (ADR 0005-Philosophie). Sichtbar nur über `PageResult.method` und Logs. |

### 7.2 Abweichungen (dokumentiert)

| # | Abweichung | Begründung |
|---|------------|------------|
| **P7‑D‑1** | P6‑D‑1 („Vektor innerhalb des Rechtecks wird gerastert") gilt nur noch für den **Raster-Fallback**; die primäre Vektor-Seite ist jetzt vektor-exakt transformiert *und* gecropt (P7‑FR‑1/4). | User-Feature-Wunsch (scharfe Ausgabe statt 300-DPI-Raster). |
| **P7‑D‑2** | CMYK-Flächen laufen über die Standard-Subtraktiv-Konversion (RGB-Zwischenstufe); die Doppelkonversion ist auf 8-bit nicht injektiv (stabil innerhalb 1 Level). | Von der D2-Toleranz (≤ 3) abgedeckt; DeviceRGB/DeviceGray (Praxisfall) sind exakt. |

---

*Phase 7 addendum:* 2026‑11‑17, **Supervisor**

---

### 7.3 Revision (2026‑11‑19) — App-Export-PDFs (`gs`/`scn`/benannte Farbräume)

User-Test mit dem Eigensample `inputs/test.pdf` (1229 Vektorpfade) fiel
trotz v0.8.0-dev in den Raster-Fallback → Output pixelig. Ursache: der
Rewriter lehnte harmlose, aber in App-Exports übliche Konstrukte ab.
Revision (ADR 0008, „Revision 2026‑11‑19"; diese Punkte ersetzen die
betreffenden Formulierungen in P7‑FR‑2/4):

| # | Anforderung (revidiert) | Beschreibung |
|---|-------------|--------------|
| **P7‑FR‑2r** | Self-healing Fallback — revidierte Abweisung | `gs` wird nur abgewiesen, wenn der ExtGState **echte** Farb-Semantik hat (`/ca`/`/CA` < 1, `/SMask` ≠ `/None`, `/BM` ≠ `/Normal`); Identitäts-ExtGState (App-Export-Usus) wird durchgelassen. `cs`/`CS` akzeptiert Device-Räume auch **benannt** über `/Resources /ColorSpace` (Literal + indirekte Referenz); `scn`/`SCN` gilt in getrackten Device-Räumen. Abgewiesen bleiben: Inline-Images, Shadings, ICCBased/Pattern-Farbräume, rotierte/schiefe Texte, Bild im Board. |
| **P7‑FR‑4r** | Vektor-Crop-Kontrakt revidiert | Vergleich gegen die Render-Slice-Grundwahrheit mit „Geometrie + grobe Fidelity": max-Diff ≤ 32 (schlechtester Pixel) **und** Anteil abweichender Pixel ≤ 0,1 % — ein Clip-Import rastert Vektor-Kanten in leicht anderer Subpixel-Phase (empirisch: max-Diff 16 auf 0,003 % der Pixel, wahrnehmungsunwesentlich). Systematischer Fehlauschnitt scheitert an beiden Caps → Raster-Slice. |
| **P7‑FR‑6** | Regression am echten Sample | `tests/test_pipeline.py::TestRealSampleVectorInvert` läuft `inputs/test.pdf` end-to-end: `method=vector-invert`, 0 Bild-XObjects im Output, ≥ 1000 Vektor-Drawings, heller Board-Hintergrund. |

---

*Phase 7 revision addendum:* 2026‑11‑19, **Supervisor**

---

## Phase 8 — GUI ohne DPI-Regler (v0.8.0, 2026-11-19)

User-Anfrage: „DPI Regler entfernen, den brauchen wir nicht mehr im
GUI." Grundlage: [ADR 0009](docs/adr/0009-gui-dpi-regler-entfernt.md).
Seit P7 (vector-invert) bestimmt das Processing-DPI die Qualität von
Vektor-Content nicht mehr; der Regler ist verlässlich überflüssig
(ADR-0005-Philosophie: weniger Optionen).

### 8.1 Anforderungen

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P8‑FR‑1** | GUI ohne DPI-Option | Der DPI-Regler (Widget, Variable, Readout, Callback) wird aus dem GUI entfernt. Die GUI rendert die Vorschau und verarbeitet mit dem Pipeline-Default (**150 dpi**, Signature-Default von `pdf_to_images`/`process_pdf`); es wird kein `dpi`-Parameter mehr übergeben. |
| **P8‑FR‑2** | CLI unverändert | Das CLI-Flag `--dpi` (20–600) und die Config-File-Option `dpi` bleiben für Power-User erhalten. |

---

*Phase 8 addendum:* 2026‑11‑19, **Supervisor**

---

## Phase 9 — BYO-env: eigene Python-Umgebung des Users (v0.9.0-dev, 2026-11-21)

User-Anfrage: Power-User sollen ihre eigene Python-Installation / venv für den
Start nutzen können, statt der isolierten `.venv/`, die der Starter anlegt.
Grundlage: [ADR 0010](docs/adr/0010-byo-eigene-python-umgebung.md).

Der Tool-Code wird aus dem Checkout geladen (`python -m smartboard_invert …`,
weil das aktuelle Verzeichnis an Position 1 von `sys.path` steht); die fremde
Umgebung muss nur die vier Laufzeit-Abhängigkeiten enthalten, **nie** das Tool
selbst — und wird vom Starter **niemals verändert** (keine Installation, keine
Schriftzug-Änderungen).

### 9.1 Anforderungen

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P9‑FR‑1** | `--use-env PFAD` | Starter-Flag (vor dem Tool-Code, position-unabhängig, kombinierbar mit Tool-Argumenten): aktiviert den BYO-env-Modus. `PFAD` = Umfeld-Ordner (venv/conda) oder direkte Python-Executable. |
| **P9‑FR‑2** | Validierung ohne Installation | Python ≥ 3.9 muss vorhanden sein und `import fitz, cv2, numpy, PIL` muss gelingen; sonst Fehlermeldung mit Hinweis, die Abhängigkeiten selbst zu installieren. Der Starter installiert in die fremde Umgebung **nichts**. |
| **P9‑FR‑3** | Persistenz | Die validierte Wahl wird in der git-ignorierten, checkout-lokalen Datei `.smartinvert_env` gespeichert (`PYTHON=<absoluter Pfad>`); spätere Starts verwenden sie still, jeweils mit erneuter Validierung. |
| **P9‑FR‑4** | `--use-standard` | Entfernt `.smartinvert_env` und stellt den Standard-Weg (uv/`.venv/`) wieder her. |
| **P9‑FR‑5** | BYO-Start | Die uv/`.venv/`-Maschinerie wird übersprungen; Start via `<deine-python> -m smartboard_invert [args…]` (CLI) bzw. `<deine-python> -m smartboard_invert.gui` (GUI) aus dem Projekt-Root. |
| **P9‑FR‑6** | Plattformen | Linux/macOS (`start.sh`) und Windows (`start.bat`; venv-Layout `Scripts\python.exe` + conda-Layout `python.exe` im Ordner-Root). Kein Auto-Detection, kein Start-Prompt; Default-Verhalten bleibt unverändert. |

### 9.2 Abgrenzung

* Die fremde Umgebung wird **nicht** angefasst (kein `pip install .` dorthin,
  keine Änderungen an `pyvenv.cfg`/`conda-meta`).
* Die `smartinvert`-Kommando-Datei der fremden Umgebung existiert (im Normalfall)
  nicht — der Starter verwendet immer `python -m smartboard_invert …` aus dem
  Projekt-Root, was ohne Installation funktioniert.
* Befindet sich die gespeicherte Umgebung nicht mehr / sind Abhängigkeiten
  verschwunden, verweigert der Starter den Start und verweist auf
  `--use-standard` (fail-safe, kein stiller Fallback).

---

## Phase 10 — GUI-QoL: erweiterte Optionen, Sonderfall-Meldungen, Speicherort öffnen (v0.9.0-dev, 2026-11-22)

User-Anfrage: GUI-Verbesserungen — einklappbare erweiterte Optionen, klare
Sonderfall-Meldungen, „Speicherordner öffnen"-Button im Erfolgspopup.
Grundlage: [ADR 0011](docs/adr/0011-gui-qo-erweiterte-optionen-sonderfaelle-speicherort.md).
Branch `feature/gui-qol` (gedockt auf `feature/byo-env`). **Presets und
Tkinter-Politur sind bewusst ausgeklammert** (Phase 11+); ein browser-basiertes
GUI ist verworfen.

### 10.1 Anforderungen

| # | Anforderung | Beschreibung |
|---|-------------|--------------|
| **P10‑FR‑1** | Einklappbare erweiterte Optionen | Der GUI-Optionsbereich zeigt standardmäßig nur „Auf Board zuschneiden" + „Zielhintergrund". Ein Toggle-Button („Erweiterte Optionen") zeigt/versteckt: „Invert colours"-Checkbox (Default an), vier Markerfarben-Checkboxen Rot/Grün/Blau/Gelb (Default Rot+Grün = heutiges `keep_colors`) und das Hex-Farben-Entry (Default leer). **DPI bleibt aus dem GUI** (ADR 0009). |
| **P10‑FR‑2** | Default-Verhalten unverändert | Bei ungeänderten Defaults ergibt sich exakt der heutige `process_pdf`-Aufruf (invert=True, crop=True, bg_target=None, keep_colors={red,green}, keep_segments=(), kein dpi-Parameter). |
| **P10‑FR‑3** | Sonderfall: passwortgeschützt | Ein verschlüsseltes PDF (User-Passwort) erzeugt eine klare Meldung („is password-protected … remove the password first") statt Traceback/„unexpected error". CLI: Datei zählt als Failure (Batch fährt weiter), exit=1. GUI (Single-File): Dialog **vor** Worker-Start. |
| **P10‑FR‑4** | Sonderfall: ungültige / leere Datei | Nicht-PDF-Bytes → „not a valid PDF (damaged or not a PDF at all)"; 0-Seiten-PDF → „contains no pages". Gleiche CLI/GUI-Semantik wie P10-FR-3. |
| **P10‑FR‑5** | Sonderfall: Output nicht anlegbar | Das Output-Verzeichnis lässt sich nicht anlegen (z. B. Pfad durch eine Datei) → klare Meldung „cannot create output directory …". |
| **P10‑FR‑6** | „Kein Board"-Zusammenfassung | Wurde auf keiner Seite ein Board erkannt, gibt die CLI eine Abschluss-Warnung („output is an unchanged copy of the input") aus; das GUI zeigt die Info zusätzlich im Done-Dialog. |
| **P10‑FR‑7** | „Speicherordner öffnen" | Der Done-Dialog (eigener Toplevel statt messagebox) bietet den Button „Speicherordner öffnen": Windows `explorer /select` (Datei markiert), macOS `open -R`, Linux `xdg-open <ordner>`; Batch → Output-Ordner. Fehlender Opener → sanfte Log-Warnung, kein Crash. |

### 10.2 Abgrenzung

* CLI-Verhalten bei gültigen Eingaben bleibt unverändert (neue Meldungen sind
  additive).
* Das Hex-Feld bleibt ein schreibbares `Entry` und die Preview rendert das
  Original weiter — Architektur-Vorbereitung für den späteren Farb-Picker
  (ADR 0011, D4; jetzt nicht implementiert).

---
