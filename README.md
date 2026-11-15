# Smartboard PDF Inverter

Ein Python-Tool, das in PDF-Seiten das rechteckige Smartboard-Bild
automatisch erkennt und **nur dieses Rechteck** invertiert (`255 − v` pro
Kanal). Die weiße PDF-Seite außerhalb des Rechtecks, die Seitengröße, die
Position des Boards und die Seitenreihenfolge bleiben exakt erhalten.
Mehrseitige PDFs werden seitenweise und unabhängig verarbeitet; ein ganzes
Verzeichnis lässt sich per Batch in einem Aufruf verarbeiten.

## Funktionsweise

1. **Erkennung** – jede Seite wird mit dem eingestellten DPI gerendert;
   eine robuste Hintergrund-Relative-Schwelle (`T = B − max(30, 0.25·(B − p25))`,
   `B = p95`) plus Morphologie und Connected-Components-Gates (Fläche,
   Seitenverhältnis, Ausdehnung, Randabstand, Kontrast, Zweideutigkeit)
   liefert das Board-Rechteck mit Konfidenz. Details:
   [ADR 0001](docs/adr/0001-robuste-erkennung-und-seitentreue-ausgabe.md).
2. **Transformation** – ausschließlich innerhalb des Rechtecks wird invertiert
   (strikt `255 − v`); optional (Legacy-Optionen) CLAHE und morphologische
   Reinigung.
3. **Seite-treue Ausgabe** – pro Seite eine von drei Methoden:
   * `copy` – nichts erkannt (oder keine Transformation): verlustfreie Kopie.
   * `image-replace` – das Board ist ein Bild-XObject: Bild extrahieren,
     innerhalb des Rechtecks invertieren, verlustfrei (PNG) am selben Ort
     ersetzen.
   * `rerasterize` – sonst (z. B. Vektorinhalte wie `inputs/test.pdf`):
     die Seite wird gerendert, invertiert und in **Original-Größe** eingebettet.
4. **Verifikation & Debug** – nach jeder Seite wird geprüft, dass außerhalb
   des Rechtecks nichts verändert wurde; `--debug` schreibt pro Seite ein
   Composite (`original | original+BBox | ergebnis`) nach
   `<output>/debug/<name>_pNN_debug.png`.

**Fail-Safes:** Wird kein eindeutiges Rechteck gefunden, bleibt die Seite
unverändert (Warnung). Seiten mit `/Rotate ≠ 0` werden unverändert kopiert.
`output == input` wird abgelehnt; eine defekte Datei beendet den Batch nicht.

## Quickstart (ein Befehl)

Voraussetzung: Python 3.9+ (`python3` im PATH).

```bash
git clone https://github.com/univie-henrikjurek/smartinvert.git
cd smartinvert
./start.sh -i test_input.pdf -o test_output.pdf    # Linux/macOS
start.bat -i test_input.pdf -o test_output.pdf     # Windows
```

Der erste Lauf legt `.venv/` an und installiert die Abhängigkeiten
(PyMuPDF, OpenCV (headless), NumPy, Pillow – GUI zusätzlich Tkinter); das
dauert einmalig ~1–2 Minuten, danach ist jeder Start sofort fertig.
**Ohne Argumente öffnet `./start.sh` die GUI** (Datei oder Ordner wählen).

```bash
# Batch: alle PDFs in einem Ordner (gleiche Dateinamen)
./start.sh -i inputs/ -o outputs/ --debug

# höhere Ausgabequalität (Detection + Einbettung)
./start.sh -i inputs/test.pdf -o out.pdf --dpi 300
```

Ohne `-o` wird bei einer einzelnen Datei `<name>_inverted.pdf` neben der
Eingabedatei angelegt (Legacy-Verhalten).

### Optionen (`smartinvert`)

Nach der Installation ist das Tool auch direkt als `smartinvert`-Command
verfügbar (`.venv/bin/smartinvert` bzw. nach `pip install .` im PATH).

### Optionen

| Flag | Bedeutung |
| --- | --- |
| `--input`, `-i` | PDF-Datei oder Verzeichnis (Default: `inputs/`) |
| `--output`, `-o` | Zieldatei (Datei-Input) oder Zielfenster/Verzeichnis; Default `outputs/` mit gleichem Dateinamen |
| `--dpi N` | Render-DPI für Erkennung und Ausgabe (Default 150, Bereich 20–600) |
| `--invert` / `--no-invert` | Inversion an/aus (Default: an) |
| `--clahe` / `--no-clahe` | CLAHE im Rechteck (Legacy, Default: aus) |
| `--clean` / `--no-clean` | Morphologische Reinigung im Rechteck (Legacy, Default: aus) |
| `--debug` | Debug-Composites nach `<output>/debug/` |
| `--config path.json` | JSON-Config; CLI-Flags haben Vorrang |
| `-v` / `-vv` | Logstufe INFO / DEBUG |

Exit-Code `0` bei Erfolg, `1` wenn mindestens eine Datei fehlschlug.

## GUI

```bash
./start.sh                # ohne Argumente (Linux/macOS)
start.bat                 # Windows
# oder direkt: .venv/bin/python -m smartboard_invert.gui
```

**PDF…** oder **Ordner…** wählen (Ordner = Batch), optional ein
**Output**-Ziel angeben, DPI/Optionen einstellen, Vorschaubild der ersten
Seite ansehen und **Run** klicken.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -e .          # editierbare Installation
.venv/bin/pip install pytest pytest-cov
.venv/bin/pytest --cov=smartboard_invert
```

## Tests

```bash
pytest --cov=smartboard_invert --cov-report=term-missing --cov-fail-under=80
```

88 Tests (Erkennung, Verarbeitung, End-to-End-Pipeline inkl. der 8
Pflichtszenarien, CLI) bei ≥ 90 % Coverage; CI-Workflow in
`.github/workflows/ci.yml` mit Coverage-Gate 80 %.

## Projektstruktur

```
smartboard_invert/
  detection.py    # Rechteck-Erkennung (Schwelle, Gates, Konfidenz, Refinement)
  processing.py   # Bild-Transformationen (255-v, CLAHE, Cleaning), PDF<->Bilder
  pdfpipeline.py  # process_pdf(): 3 Ausgabemethoden, Verifikation, Debug
  cli.py          # Batch-CLI mit Config
  gui.py          # Tkinter-GUI
  __main__.py     # python -m smartboard_invert
docs/adr/         # Architektur-Entscheidungen
tests/            # pytest-Suite inkl. synthetischer PDFs mit Ground Truth
```

## Lizenz

MIT – siehe LICENSE.
