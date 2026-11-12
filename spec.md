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
| **A‑6** | The program will be distributed as a **wheel** and an entry‑point script `smartboard-invert`. | Eases installation via `pip`.
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
