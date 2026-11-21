# ADR 0010: BYO-env — Tool mit der eigenen Python-Umgebung des Users starten

*Status:* accepted (2026-11-21, User-Anfrage: Power-User sollen ihre eigene
Python-Installation / venv nutzen können, statt der isolierten `.venv/`)
*Entscheider:* Supervisor

## Kontext

Der Standard-Weg (`start.sh` / `start.bat` → uv → isolierte `.venv/`) ist für
Anfänger optimal. Ein Segment entschlossener Power-User arbeitet aber bereits
mit eigenen Python-Umgebungen (eigene venvs, conda-Envs, eigene
Abhängigkeits-Verwaltung) und will diese wiederverwenden — ohne dass das Tool
in ihr Umfeld installiert oder dieses verändert wird (z. B. weil die Umgebung
versionierte, geteilte oder reproduzierbare Abhängigkeiten enthält).

Wichtig ist die heute **ohne jeden Code** mögliche Basis-Funktionalität:
`python -m smartboard_invert …` aus dem Projekt-Root lädt das Tool direkt aus
dem Checkout (das aktuelle Verzeichnis steht an Position 1 von `sys.path`) —
das Paket muss in der fremden Umgebung **nicht installiert** sein; nur die
vier Laufzeit-Abhängigkeiten (PyMuPDF, opencv-python-headless, numpy, Pillow)
müssen vorhanden sein (verifiziert mit externem venv: CLI + GUI laufen,
`method=vector-invert`, Umgebung bleibt unverändert).

Alternativen, die verworfen wurden:

- **Frage beim Start** („Eigene Installation wählen?"): belästigt Standard-User
  bei jedem Start und vergrößert die kognitive Last genau der Zielgruppe, die
  das Feature nicht braucht (ADR-0005-Philosophie: weniger Optionen, Defaults
  sind gut).
- **Auto-Erkennung** fremder Umgebungen (PATH-Suche, „welches python3 hat
  fitz?"): nicht deterministisch, Support-Fläche wächst („warum wurde gerade
  diese Umgebung genommen?"), falsche Treffer möglich.
- **Installation des Pakets in die fremde Umgebung** (`pip install .` dorthin):
  verletzt die Kernaussage „deine Umgebung bleibt unangetastet" und erzeugt
  eine Kopie des Codes außerhalb des Checkouts, die sich bei Updates
  veraltet.

## Entscheidung

* **BYO-env-Modus** („bring your own environment") wird **einmalig, explizit
  und persistent** gesteuert:
  - `./start.sh --use-env /pfad` (Linux/macOS) bzw.
    `start.bat --use-env "C:\Pfad"` (Windows) aktiviert den Modus.
  - `/pfad` ist der **Umfeld-Ordner** (venv: `<root>/bin/python` bzw.
    `<root>\Scripts\python.exe`; conda-Envs: `<root>/python` bzw.
    `<root>\python.exe`) **oder** der direkte Pfad zur Python-Executable.
  - Das Flag ist position-unabhängig und kann mit normalen Tool-Argumenten
    kombiniert werden (`--use-env /venv -i in.pdf -o out.pdf`).
* Der Starter **validiert, installiert aber niemals**: Python ≥ 3.9 muss
  vorhanden sein und `import fitz, cv2, numpy, PIL` muss gelingen; sonst
  klare Fehlermeldung mit Installations-Hinweis, den der User **selbst**
  ausführt. In die fremde Umgebung wird nichts geschrieben.
* Die validierte Wahl wird in der **git-ignorierten, checkout-lokalen Datei**
  `.smartinvert_env` gespeichert (`PYTHON=<absoluter Pfad>`) und bei späteren
  Starts **still wiederverwendet** — jeweils mit erneuter Validierung (die
  Umgebung kann verschoben oder gelöscht worden sein).
* `./start.sh --use-standard` (bzw. `start.bat --use-standard`) entfernt die
  Datei und stellt den Standard-Weg (uv/`.venv/`) wieder her.
* In BYO-env-Modus wird die uv/`.venv/`-Maschinerie **komplett übersprungen**;
  der Start erfolgt als `<deine-python> -m smartboard_invert [args…]` (CLI)
  bzw. `<deine-python> -m smartboard_invert.gui` (GUI) aus dem Projekt-Root —
  der Tool-Code kommt aus dem Checkout, die Umgebung des Users wird
  **nicht verändert**.
* **Kein Auto-Detection, kein Start-Prompt:** Wer das Feature will, ruft es
  einmal aktiv ab; alle anderen merken nichts (Default-Verhalten bleibt
  unverändert).

## Konsequenzen

* `start.sh`: neue Sektion `[0] BYO-env mode` (Flag-Parser vor der
  uv-Maschinerie), Helpers `resolve_python_path` / `validate_python_env`;
  gespeicherte Wahl wird als absoluter Pfad abgelegt.
* `start.bat`: gleiches Verhalten; Windows-Layouts `Scripts\python.exe`
  (venv) und `python.exe` im Ordner-Root (conda); die Starter-Flags werden vor
  dem Tool-Start herausgefiltert, damit z. B. `--use-standard` nicht als
  unbekanntes Argument an das CLI durchgereicht wird.
* `.gitignore`: `.smartinvert_env`.
* `INSTALL.md`: neuer Abschnitt „Advanced: use your own Python environment"
  (Anleitung); `README.md`: kurzer Hinweis mit Link.
* Tests: `tests/test_starter_byo_env.py` (Linux/macOS; Validierungs- und
  Persistenzverhalten von `start.sh` per Subprocess).
* Version: `0.9.0-dev` (neues User-Feature).

## Bekannte Einschränkungen

1. **`start.bat` nur statisch geprüft:** In der Linux-Entwicklungsumgebung
   nicht ausführbar — Review ohne Laufzeittest.
2. **Windows: Metazeichen im Pfad:** Pfade, die cmd-Metazeichen enthalten
   (`&`, `|`, `<`, `>`, `^`), werden nicht unterstützt (Anzeigemeldungen
   brechen auf; die ENV-Datei wird korrekt geschrieben, da die Metazeichen
   beim Schreiben escaped werden).
3. **Windows: 9-Token-Limit beim Flag-Combining:** cmd stellt einem
   Batch-Skript nur `%1`–`%9` zur Verfügung. Wenn ein Starter-Flag
   (`--use-env`/`--use-standard`) in der Zeile steht, werden höchstens 9
   Kommandozeilen-Tokens insgesamt verarbeitet; ohne Starter-Flag gilt der
   klassische Durchreichungsweg (`%*`, beliebig viele Argumente). Da die
   Wahl persistent ist, wird das Flag ohnehin nur einmal benötigt.
4. **Windows: unbalancierte Klammern im Pfad** können das Batch-
   Fehlerbehandlungs-Block aufbrechen (pathologisch, z. B. `C:\env)1`).
