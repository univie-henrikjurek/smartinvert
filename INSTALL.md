# Installation & Start – Smartboard PDF Inverter

Dieses Dokument führt Schritt für Schritt zum ersten Lauf. Einzige
Voraussetzung ist **Python 3.10 oder neuer** – das Start-Script (`start.bat`
bzw. `start.sh`) erledigt den Rest automatisch (eigene virtuelle Umgebung,
Abhängigkeiten, Command).

---

## 1. Python installieren (falls noch nicht vorhanden)

Kurz-Check in einem Terminal: `python --version` (Windows) bzw.
`python3 --version` (Linux/macOS) – es muss **3.10 oder neuer** kommen.

### Windows
1. Installer von <https://www.python.org/downloads/> laden
   (3.10 oder neuer, „Windows installer 64-bit“).
2. **Wichtig:** Im ersten Installationsfenster den Haken setzen bei
   **☑ Add python.exe to PATH**, dann *Install Now*.
3. **Neues** Terminal öffnen (alte Fenster kennen den neuen PATH nicht) und
   prüfen: `python --version`.

> Die Tkinter-GUI ist im Windows-Installer von python.org bereits enthalten –
> es ist nichts extra zu installieren.

### macOS
`python3 --version` – falls vorhanden, fertig. Sonst Python von
<https://www.python.org/downloads/> (Graphical installer) oder
`brew install python`.

### Linux (Ubuntu/Debian)
`python3 --version` – ist meist vorhanden. Falls die virtuelle Umgebung
fehlt: `sudo apt install python3-venv`.
Für die **GUI** zusätzlich: `sudo apt install python3-tk`.

---

## 2. Projekt holen (eine der beiden Varianten)

### Variante A: ohne Git (ZIP-Download)
1. Repo im Browser öffnen: <https://github.com/univie-henrikjurek/smartinvert>
2. Grünen Button **Code → Download ZIP** klicken.
3. ZIP-Datei entpacken (Rechtsklick → *Alle extrahieren*).

### Variante B: mit Git
[Git for Windows](https://git-scm.com/download/win) installieren (falls nicht
vorhanden), dann:

```powershell
git clone https://github.com/univie-henrikjurek/smartinvert.git
cd smartinvert
```

Danach alle Befehle **im Projektordner** ausführen (dort liegen
`start.bat`, `start.sh`, `inputs/` …).

---

## 3. Starten – ein Befehl

### Windows

PowerShell oder Eingabeaufforderung im Projektordner öffnen (Tipp: im
Explorer im Ordner auf die Adressleiste klicken, `powershell` eingeben,
Enter).

```powershell
# eine Datei verarbeiten (Beispiel mit der mitgelieferten Testdatei)
.\start.bat -i inputs\test.pdf -o outputs\test.pdf

# eigenes PDF
.\start.bat -i test_input.pdf -o test_output.pdf

# Batch: alle PDFs eines Ordners (gleiche Namen im Zielfenster)
.\start.bat -i inputs\ -o outputs\

# GUI öffnen (oder einfach start.bat per Doppelklick starten)
.\start.bat
```

### Linux / macOS

```bash
./start.sh -i test_input.pdf -o test_output.pdf
./start.sh -i inputs/ -o outputs/
./start.sh                    # GUI
```

**Erster Lauf:** Das Script legt `.venv/` an und installiert die
Abhängigkeiten (PyMuPDF, OpenCV, NumPy, Pillow). Das dauert je nach
Internetverbindung **1–3 Minuten**. Alle weiteren Starts sind sofort
fertig – `.venv/` einfach stehen lassen.

---

## 4. Die GUI

`start.bat` / `start.sh` **ohne Argumente** (oder Doppelklick) öffnet das
Fenster:

- **PDF…** – eine Datei wählen, oder **Ordner…** – einen Ordner mit
  mehreren PDFs (Batch, gleiche Namen im Zielfenster)
- **Output (optional)** – Ziel angeben; leer lassen → bei einer Datei
  erscheint `<name>_inverted.pdf` neben der Eingabe (Ordner-Input verlangt
  ein Zielfenster)
- **DPI**-Schieberegler (Standard 150 – für schärfere Ausgabe z. B. 300
  wählen, dauert dann länger)
- **Preview first page** – Original | invertiert nebeneinander
- **Run** – verarbeitet mit Fortschrittsbalken; am Ende zeigt das Fenster
  den Ablageort an

---

## 5. Was das Tool macht / wo die Ergebnisse liegen

- Pro Seite wird das rechteckige Smartboard-Bild automatisch erkannt und
  **nur dieses Rechteck** invertiert; die weiße Seite drumherum, die
  Seitengröße und die Position bleiben exakt erhalten.
- Ausgabe-PDF am mit `-o` angegebenen Ort (Standard s. o.).
- Mit `--debug` (CLI) liegen zusätzlich Probenbilder unter
  `<Zielordner>/debug/<name>_pNN_debug.png` (Original | Original+Rechteck |
  Ergebnis).
- Der Eingabepfad wird **nie** verändert oder überschrieben.

### Wichtige CLI-Optionen

| Flag | Bedeutung |
| --- | --- |
| `-i`, `--input` | PDF-Datei oder Verzeichnis |
| `-o`, `--output` | Zieldatei oder Zielverzeichnis |
| `--dpi N` | Auflösung für Erkennung + Ausgabe (20–600, Default 150) |
| `--no-invert` | Erkennung ohne Invertierung (nur Debug/Analyse) |
| `--debug` | Debug-Composites schreiben |
| `-v` / `-vv` | ausführliche / sehr ausführliche Logs |
| `--version` | Versionsnummer anzeigen |

Vollständige Optionsliste: `.\start.bat --help` bzw. `./start.sh --help`.

---

## 6. Optional: `smartinvert` direkt im PATH

Wenn du das Command ohne `start.bat`/`start.sh` aufrufen willst, die
virtuelle Umgebung aktivieren:

```powershell
# Windows
.venv\Scripts\activate
smartinvert -i test_input.pdf -o test_output.pdf
```

```bash
# Linux/macOS
source .venv/bin/activate
smartinvert -i test_input.pdf -o test_output.pdf
```

(Das Fenster danach mit `deactivate` wieder verlassen; die Aktivierung ist
nur pro Terminal-Sitzung nötig.)

---

## 7. Problemlösungen

| Problem | Lösung |
| --- | --- |
| `'python' is not recognized as an internal or external command` | Python mit Haken **Add python.exe to PATH** (neu) installieren, danach **neues** Terminal öffnen |
| `error: Python 3.10+ not found` (beim Start) | Python ist installiert, aber zu alt → Version 3.10+ nachinstallieren |
| Doppelklick auf `start.bat`: Fenster flackert und schließt sich | `start.bat` in der PowerShell ausführen, um die Meldung zu sehen (meist fehlendes/zu altes Python) |
| Erster Lauf dauert lange | Normal: einmaliger Download von ~60–90 MB; danach sofort |
| `ModuleNotFoundError: No module named 'tkinter'` (nur bei der GUI) | Linux (Ubuntu/Debian): `sudo apt install python3-tk`. Windows/macOS: Python von python.org verwenden (enthält Tkinter) |
| Windows Smart Screen: „Ihr PC wurde geschützt“ | Auf **Weitere Informationen → Trotzdem ausführen** klicken (die Scripte sind lokal und nicht signiert – das ist normal) |
| GUI startet nicht in einer Remote-Session/SSH ohne Anzeige | GUI braucht ein Desktop; dort stattdessen die CLI nutzen (`start.bat -i … -o …`) |

---

## 8. Deinstallieren

Einfach den Projektordner (inklusive `.venv`) löschen. Es wird sonst
nichts im System installiert.
