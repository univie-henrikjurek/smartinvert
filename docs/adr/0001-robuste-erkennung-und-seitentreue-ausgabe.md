# ADR 0001: Robuste Smartboard-Rechteckerkennung und seitentreue Ausgabe-Erzeugung

*Status:* accepted (2026-11-14)
*Entscheider:* Supervisor (Phase 2)

## Kontext

Phase 1 invertierte das „größte dunkle Kontur-Areal" einer Seite (Otsu + größte
externe Kontur) und erzeugte die Ausgabe-PDF mit Seiten in **Pixelgröße**
(A4@150dpi → 1240×1755 pt). Beides verletzt die Phase-2-Anforderungen:

1. Die Erkennung muss dunkelgraue Hintergründe finden, darf nicht durch einzelne
   dunkle Zeichen/Zeichnungen auslöstbar sein, braucht Konfidenz- und
   Plausibilitätsprüfungen und muss bei Ambiguität abbrechen (Warnung, Seite
   unverändert).
2. Die Seitengröße (MediaBox) und die Position des Smartboard-Bereichs müssen
   exakt erhalten bleiben; alles außerhalb des Rechtecks bleibt pixelgenau.

**Wichtige Beobachtung aus der Analyse von `inputs/test.pdf`:** Die Beispieldatei
enthält **keine Bild-XObjects** – der „Smartboard" ist eine Vektorgrafik (ein
dunkles Rechteck + weiße Pfade). Echte Smartboard-Exporte sind typischerweise
ein einzelnes **Bild** pro Seite. Der Pipeline-Design muss **beide** Fälle abdecken.

## Entscheidung

### D1: Erkennung auf hochauflösendem Seiten-Render + (falls Bild vorhanden) auf dem nativen Bild

- **Primär-Erkennung** läuft auf dem Seiten-Render bei `--dpi` (Default 150):
  `gray = cvtColor(GaussianBlur(bgr))`, Hintergrund-Helligkeit `B = p95(gray)`,
  adaptiver, hintergrundbezogener Schwellwert
  `T = B − max(30, 0.25·(B − p25(gray)))` (p25 ≈ Board-Helligkeit; der
  30-Level-Boden hält normale schwarze Zeichen auf weißer Seite "dunkel", ein
  Board muss aber deutlich dunkler sein), dunkle Maske `gray < T`,
  morphologisches Closing (Kernel ∝ Bildgröße, füllt Text-Löcher/brückt
  AA-Lücken), dann `connectedComponentsWithStats` (8-zusammenhängend).
  *Hinweis:* `cv2.threshold(..., THRESH_OTSU)` wird bewusst **nicht** verwendet
  – bei strikt bimodalen Histogrammen (flache Farben, typisch für
  Smartboard-Screenshots) degeneriert der Otsu-Wert in OpenCV ≥ 5 (z. B. auf
  0.0) und wäre unzuverlässig. Die Prozentil-Formel ist deterministisch und
  stabil für flache Farbbereiche.
- Kandidaten-Filter (harte Gates): Fläche ≥ 1 % der Seite, BBox-Breite/Höhe
  ≥ 4 % der Seitenachse, **Extent** (Fläche/BBox-Fläche) ≥ 0.85 (Rechteckigkeit),
  Randabstand ≥ 0.5 % der Achse (Seite darf nie „komplett" erkannt werden),
  Kontrast-Check: mittlere Helligkeit innerhalb der BBox < `B − 60` (das Board
  muss *deutlich* dunkler sein als die Seite).
- **Bounding-Box-Refinement:** Die geschlossene (geblurte) Maske trägt einen
  Halo von ~1–3 px in den Rand; die BBox wird deshalb aus der *unblurten*
  dunklen Maske des gewinnenden Connected Components neu berechnet (mit
  Kernel-skalierter Plausibilitätstoleranz).
- **Eindeutigkeit:** der zweitgrößte Kandidat darf < 60 % der Fläche des
  Besten haben, sonst wird abgebrochen (Warnung „mehrere gleichgroße dunkle
  Bereiche").
- **Konfidenz** (0..1, gewichtet): Extent 30 %, Flächenscore 20 % (Idealfeld
  5–90 %), Kontrast 30 %, Randabstand 20 %. Mindest-Konfidenz 0.5.
- **Sicherheitsnetz:** Seiten-Hintergrund nicht hell (`p95 < 200`) → Abbruch mit
  Warnung. Damit kann die (weiße) Seite prinzipiell nie komplett invertiert
  werden: der Randabstands-Gate + der B-Check schließen diesen Fall doppelt zu.
- Zusätzlich (nur für die Bild-Ersetzung, D2): eine **zweite Erkennung auf dem
  nativen Bild** (höchste Auflösung, `allow_full_coverage=True` – dort ist ein
  Board, das das ganze Bild füllt, korrekt). Beide Rechtecke müssen sich über
  ≥ 80 % decken (Overlap in Seitenkoordinaten), sonst Fallback.

Begründung: Der hintergrundbezogene Prozentil-Schwellwert ist robust bei
dunkelgrauen Boards und bei Seiten mit nur wenigen dunklen Zeichen (die
scheitern an den Flächen-/Extent-/Kontrast-Gates) und umgeht die
Otsu-Degeneration von OpenCV ≥ 5 bei strikt bimodalen Histogrammen. Closing vor den
Connected Components füllt weiße Text-Löcher im Board auf, so dass Extent ≈ 1
bleibt. Alles deterministisch, keine ML-Abhängigkeiten.

### D2: Ausgabe-Erzeugung mit exakter Seitentreue – zwei Pfade

Pro Seite (unabhängig voneinander):

| Fall | Pfad | Seitentreue |
|------|------|-------------|
| Nichts erkannt | **copy**: `show_pdf_page` kopiert die Seite verlustfrei in ein neues Dokument mit identischer Größe | exakt (kein Pixel verändert) |
| Erkannt + passendes Bild-XObject (BBox deckt das Rechteck, axis-aligned, ≥ 50 % der Rechteckfläche) | **image-replace**: Seite kopieren, Bild aus dem XObject extrahieren, nativ erkennen + **nur im Rechteck** invertieren, als PNG (verlustfrei) neu encodieren, `Page.replace_image(xref, stream=…)` | exakt (MediaBox + Plazierung + Außenbereich unverändert) |
| Erkannt, aber kein passendes Bild (z. B. Vektorgrafik wie `inputs/test.pdf`) | **rerasterize**: Seite in Original-Größe (595×842 pt) anlegen, gerenderte Seite mit nur-im-Rechteck-invertierten Pixeln als volles Seitenbild einbetten | Größe/Position exakt; Außenbereich = Render der Originalseite (verifikations-nah, s. D3) |
| **`/Rotate ≠ 0`** (Fehlerseite) | **copy (fail-safe)**: Seite wird unverändert kopiert, Warnung im Log. Die Pixel↔Punkt-Mapping für Erkennung/Invertierung ist auf rotierten Seiten nicht gültig – eine falsche Invertierung wäre schlimmer als keine. | Visuelle Seitengröße erhalten; MediaBox kann getauscht sein (dokumentiert) |

**Invertierungs-Invariante im Image-Replacement-Pfad:** In Bildkoordinaten wird
immer das **Seiten-Rechteck** (auf Bildkoordinaten gemappt) invertiert – nicht
das nativ erkannte Rechteck. Damit bleibt alles außerhalb des erkannten
Rechtecks unverändert, auch wenn das Bild einen hellen Innenrand enthält (der
nativen Full-Coverage-Erkennung wird in dem Fall der Rand mitgeliefert).

Begründung: `replace_image` ist der qualitätsbeste Pfad (kein zweites
Rasterisieren, Außenbereich buchstäblich unverändert). Der Re-Raster-Fallback
ist nötig, weil die Beispieldatei vektoriell ist; einbetten in **Original-
Größe** (statt Pixelgröße wie Phase 1) erfüllt die Seitengrößen-Anforderung.
Rotierte/schiefe Bild-Platzierungen (Transform mit Shear/Rotation) werden nicht
mapped → sicherer Fallback.

### D3: Technische Verifikation pro Seite

Nach der Erzeugung wird die neue Seite mit demselben DPI neu gerendert und mit
dem Original-Render verglichen:

- **copy/image-replace:** Außenbereich (außerhalb des Rechtecks) muss
  pixelgenau übereinstimmen (Max-Diff = 0 erwartet).
- **rerasterize:** Re-Render eines eingebetteten Rasters kann bei nicht-
  ganzzahligem Seiten-Skalierfaktor ≤ 1–2 px Resampling-Drift haben →
  Toleranz: Max-Diff ≤ 8, Mean-Diff < 0.5 (andernfalls Warnung im Log).
- Innenbereich: Mean-Diff > 20 erwartet (Invertierung hat stattgefunden).

Die Werte landen im Log und in `PageResult`; `--debug` schreibt zusätzlich ein
Composite-Bild (Original | Original + BBox | Ergebnis) nach `<output>/debug/`.

### D4: CLI/Dateiverträge

- `python -m smartboard_invert` (neues `__main__.py`) + Console-Script bleiben.
- Default: `inputs/` → `outputs/` (Batch, alle `*.pdf`, sortiert).
- `--input` Datei **oder** Verzeichnis; `--output` Datei (nur bei Datei-Input)
  oder Verzeichnis. Bei Verzeichnis-Output: **gleicher Dateiname**
  (`inputs/Test.pdf` → `outputs/Test.pdf`).
- Guard: `output == input` (resolved) → Fehler, Input wird nie überschrieben.
- `--clahe`/`--clean` bleiben, sind jetzt **default AUS** (reine `255 − v`-
  Invertierung gemäß P2-FR-3). `--debug` neu.
- Exit 0 wenn alle Dateien verarbeitet, sonst 1; pro Seite INFO/DEBUG, bei
  Erkennungs-Fehlschlag WARNING (Datei wird weiterhin ausgegeben, Seite
  unverändert).

## Konsequenzen

- Neu: `smartboard_invert/detection.py`, `smartboard_invert/pdfpipeline.py`,
  `smartboard_invert/__main__.py`; Umbau `cli.py`, Update `processing.py`
  (`invert_region`, `enhance_image[_ex]`, fitz-Compat `import pymupdf`).
- Rerasterize-Pfad rastert Vektor-Inhalt (Text wird Bitmap) – dokumentierter
  Trade-off, nötig für seitenweiche Treue bei Vektor-Boards.
- Ersetzte Bilder werden als PNG neu encodiert (Dateigröße kann steigen;
  Qualität verlustfrei).
- Transparenz (SMask) wird bei der Bild-Ersetzung verworfen (Smartboard-
  Screenshots sind opak; dokumentiert als Einschränkung).
- GUI „Run" wird auf `process_pdf` umgestellt (behebt deren Seitengrößen-Bug).
