# ADR 0011: GUI-QoL — einklappbare erweiterte Optionen, klare Sonderfall-Meldungen, „Speicherordner öffnen"

*Status:* accepted (2026-11-22, User-Anfrage: GUI-Verbesserungen —
„einklappbare erweiterte optionen und sowas", klare Sonderfall-Meldungen,
„öffne location im explorer" im Erfolgspopup)
*Entscheider:* Supervisor
*Branch:* `feature/gui-qol` (gedockt auf `feature/byo-env`)

## Kontext

Drei Reibungspunkte der Zielgruppe (Lehrende ohne Python-Vorkenntnisse):

1. **GUI-Ansicht**: Die vier sichtbaren Optionen (Invert, Crop,
   Zielhintergrund, Hex-Farben) vermischen Alltags- und Power-Optionen.
   Gleichzeitig ist `--keep-colors` (Markerfarben) in der GUI gar nicht
   ansprechbar (fix hart-codiert `red,green`).
2. **Sonderfälle**: Defekte Eingaben erzeugen Rohtext statt Erklärungen.
3. **„Wo ist mein File?"**: Der Done-Dialog nennt nur den Pfad als Text —
   Anfänger wissen nicht, wie sie dorthin navigieren.

### Beobachtetes Verhalten (Probe 2026-11-22, Code @ `034cf81`)

* **Verschlüsseltes PDF** (User-Passwort, AES-256): fitz öffnet es
  (`needs_pass=1`), `load_page` wirft `ValueError("document closed or
  encrypted")` → CLI: roher Traceback + „1 file(s) failed"; GUI:
  „unexpected error (see log)".
* **Kaputte Datei** (Nicht-PDF-Bytes): `SmartboardError("unable to open PDF …
  Failed to open file … as type pdf.")` — rohe MuPDF-Meldung, kaum
  verständlich.
* **0-Seiten-PDF** (handgefertigt; PyMuPDF kann selbst keine speichern):
  `ValueError("cannot save with zero pages")` beim fitz-Save → roher Traceback.
* **Output-Pfad durch eine Datei** (`-o /pfad/datei.txt/out.pdf`):
  `FileExistsError` aus `output_path.parent.mkdir(...)` in `process_pdf` →
  roher Traceback.
* **Kein Board auf keiner Seite**: drei WARNING-Zeilen + abschließende
  `OK <output>`-Zeile → für Anfänger unklar („OK?! — aber nichts wurde
  invertiert").

## Entscheidung

### D1: Einklappbarer „Erweiterte Optionen"-Bereich (Feature A)

* **Sichtbar bleiben** (Anfänger-Ansicht): „Auf Board zuschneiden" +
  „Zielhintergrund" (die Alltags-Optionen).
* **Einklappbar** (collapsed by default, Toggle-Button
  „▸ Erweiterte Optionen" / „▾ Erweiterte Optionen"):
  - Checkbox „Invert colours" (aus dem Hauptbereich **verschoben**; Default
    an wie heute).
  - **Neu:** vier Checkboxen „Markerfarben erhalten: Rot / Grün / Blau /
    Gelb" (Default: Rot + Grün angehackt = exakt das heutige
    `keep_colors={red, green}`) — macht `--keep-colors` GUI-ansprechbar.
  - Entry „Zusätzliche Hex-Farben" (aus dem Hauptbereich **verschoben**,
    Verhalten unverändert).
* **DPI kommt nicht ins GUI** — ADR 0009 bleibt bestehen („den brauchen wir
  nicht mehr im GUI"); CLI `--dpi` bleibt der Power-User-Weg.
* Ersetzt den ADR-0005-D2-Punkt „Rot/Grün-Checkboxen entfernt (redundant)":
  Die Checkboxen kehren zurück — aber im einklappbaren Advanced-Segment und
  mit vier Farben statt zwei. (Historisch unverändert gelassen; dieses ADR
  geht vor, wie ADR 0009 vor ADR 0005 „Bleibt: DPI-Slider".)
* **Default-Verhalten bleibt byte-identisch**: invert an, crop an,
  complement, `keep_colors={red,green}`, kein Hex, 150 dpi, kein
  `dpi`-Parameter an `process_pdf`.

### D2: Klare Sonderfall-Meldungen (Feature B)

* Neues Modul `smartboard_invert/diagnostics.py` mit
  `diagnose_pdf(path) -> Optional[str]`: öffnet die Datei **read-only** mit
  fitz und erkennt drei Datei-Level-Probleme mit klarer Meldung (Single
  Source of Truth für CLI und GUI):
  1. passwortgeschützt (`doc.needs_pass`) →
     `'<name>' is password-protected (encrypted). Remove the password first,
     then run again.`
  2. nicht lesbar / kein gültiges PDF (fitz-Open-Fehler) →
     `cannot read '<name>': the file is not a valid PDF (it may be damaged or
     not a PDF at all)`
  3. keine Seiten (`page_count == 0`) → `'<name>' contains no pages`
  * Die Diagnose verändert die Datei nicht. Owner-Passwort-only-
    Verschlüsselung (ohne User-Passwort) ist nutzbar → wird **nicht**
    gemeldet.
* **Pipeline-Guards** in `process_pdf` (decken auch den GUI-Direkt-Pfad):
  * `output_path.parent.mkdir(...)` in try/except OSError →
    `SmartboardError("cannot create output directory '<dir>': <Grund>")`.
  * nach `fitz.open(...)`: `page_count == 0` →
    `SmartboardError("'<name>' contains no pages")`.
* **CLI**: Im Job-Loop wird bei Fehlschlag einer Datei (SmartboardError
  *oder* unexpected Error) `diagnose_pdf(src)` konsultiert; bei Treffer
  ersetzt die klare Meldung die Rohmeldung bzw. „unexpected error (see
  log)". Batch fährt weiter wie heute. Nach dem Loop: wurde auf **keiner**
  Seite eines Jobs ein Board erkannt → zusätzliche Abschluss-Warnzeile
  `WARNING: no smartboard region detected on any page — the output is an
  unchanged copy of the input.`
* **GUI**:
  * Single-File-Input: Precheck `diagnose_pdf` im Main-Thread in
    `start_processing()` **vor** Controls-Disable/Worker → bei Problem:
    Fehlerdialog, Run wird abgebrochen (Fail-fast).
  * Folder-Input: wie im CLI — pro Datei im Worker-Loop nach Fehlschlag
    klären (keine harte Sperre: der Worker-Loop bleibt für die
    Job-Planungs-Semantik unverändert).
  * „Kein Board auf keiner Seite": zusätzliche Zeile im Done-Dialog (D3).
* **Sprachkonvention** (bestehende Praxis bestätigt, nicht neu erfunden):
  Meldungs-Body englisch (wie alle heutigen Dialog-/CLI-Meldungen, z. B.
  „Please select an input PDF or folder first."), Dialog-Titel wie heute
  (Mixed). Neuer deutscher UI-Text: Button-Label **„Speicherordner öffnen"**
  (explizite User-Angabe; passt zu „Zielhintergrund" & Co.).
  Vollständige Sprachkonsistenz bleibt Phase-11-Politur.

### D3: „Speicherordner öffnen"-Button im Fertig-Dialog (Feature C)

* Der Erfolgspfad des Workers ersetzt `messagebox.showinfo` durch einen
  eigenen `Toplevel`-Dialog („Done"): Text wie heute („Saved to …" +
  Summary) + Buttons **„Speicherordner öffnen"** und „OK" (modal via
  `grab_set()`, `transient(master)`).
* Neues Modul `smartboard_invert/reveal.py`:
  * `reveal_output(target: Path)` — öffnet den Dateimanager bei der
    Output-Datei bzw. dem Output-Ordner.
  * `reveal_command(target: Path) -> Optional[Union[str, list[str]]]` —
    reine Command-Konstruktion (ohne Prozess-Start testbar); liefert
    exakt das, was `subprocess.Popen` bekommt:
    - `win32`: Datei → `explorer /select,"<abs>"` (Datei wird **markiert**);
      Ordner → `explorer "<abs>"` — übergeben als **Commandline-String**,
      keine Liste: `Popen` übergibt Strings unverändert an
      `CreateProcess`, eine Liste dagegen durch `list2cmdline`, das die
      eingebetteten Doppel-Quotes von `/select,"<path>"` erneut
      an-quote/backslash-escapec — das kann Explorer nicht parsen und
      öffnet „Dieser PC" statt den Dateifolder (Regression-Fix
      2026-11-22, User-Report).
    - `darwin`: Datei → `open -R "<abs>"`; Ordner → `open "<abs>"`
      (argv-Liste; eingebettete Quotes sind dort nicht nötig)
    - `linux`: `xdg-open "<Ordner>"` (Datei → ihr Elternordner; xdg-open
      kennt kein standardmäßiges Datei-Markieren) (argv-Liste)
  * Aufruf via `subprocess.Popen` (non-blocking); fehlender Opener /
    headless → `logger.warning`, kein Crash.
* Der Fehler-Dialog („Some files failed") bleibt MessageBox ohne Button.
* Batch-Erfolg: Button öffnet den Output-**Ordner**.

### D4: Follow-up (dran denken, jetzt NICHT implementieren)

* **Farb-Picker in der Preview**: Klick auf einen Pixel des Originals →
  dessen Hex-Wert wird in das Hex-Feld übernommen (keep-hex).
  Architektur-Vorbereitung, die diese Phase bewusst aufrechterhält: das
  Hex-Feld bleibt ein **schreibbares `Entry`** (kein Read-only-Dropdown),
  die Preview rendert das Original-Array weiter (spätere Pixel-Abstastung
  möglich), und `parse_keep_hex` akzeptiert bereits genau die Token-Form
  (`RRGGBB`), die ein Picker erzeugen würde.

## Konsequenzen

* `smartboard_invert/gui.py`: Advanced-Frame + Toggle,
  Markerfarben-Variablen (`keep_red_var` … `keep_yellow_var`), dynamische
  `keep_colors` in `_transform_options()`, Precheck in `start_processing()`,
  Worker-Failure-Klärung, Done-Toplevel + Button.
* `smartboard_invert/diagnostics.py` (neu), `smartboard_invert/reveal.py`
  (neu).
* `smartboard_invert/cli.py`: Failure-Klärung im Job-Loop +
  „kein Board"-Abschlusswarnung.
* `smartboard_invert/pdfpipeline.py`: zwei kleine Guards (mkdir +
  zero-page).
* Tests: `tests/test_gui.py` erweitert (Advanced-Sektion, Precheck,
  Done-Dialog/Button); neue `tests/test_diagnostics.py` +
  `tests/test_reveal.py`; die `_dummy_pdf`-Fixture erzeugt ab jetzt ein
  **echtes** Minimal-PDF (1 Seite, fitz-erzeugt), damit der neue Precheck in
  den existierenden Worker-Tests durchläuft.
  `TestSimplifiedOptions::test_removed_controls_do_not_exist` wird angepasst:
  `keep_red_var`/`keep_green_var` dürfen jetzt wieder existieren (ADR 0011 D1
  geht vor ADR 0005 D2); `clahe_var`/`clean_var`/`dpi_*` bleiben
  entfernen-pflichtig.
* Doku: README (GUI-Abschnitt), INSTALL.md §3 + Troubleshooting-Zeile für
  passwortgeschützte PDFs.
* Version: keine Änderung (bleibt `0.9.0-dev` auf dem gedockten Branch).

## Bekannte Einschränkungen

1. `xdg-open` markiert die Datei nicht (nur Ordner öffnen) —
   Linux-Systembeschränkung.
2. Windows-Pfade mit Anführungszeichen brechen
   `explorer /select,"…"` (pathologisch; wie bei start.bat dokumentiert).
3. Headless-Betrieb (SSH ohne Desktop): Fehlt der Opener (typisch
   headless), meldet der Button sanft „could not open the file manager"
   im Log (kein Crash). Ist `xdg-open` installiert, aber keine
   Desktop-Session aktiv, startet `Popen` erfolgreich und der Button tut
   still nix (Rückgabe `True`) — für GUI-Nutzer praktisch irrelevant
   (GUI-User haben per Definition einen Desktop).
4. Doppel-Fehler-Edge-Case: Ist die Eingabe defekt **und** der
   Output-Pfad blockiert, feuert der Output-Guard zuerst (korrekte
   Kausalität), die Diagnose meldet aber die Dateiproblematik („not a
   valid PDF") statt „cannot create output directory" — die
   Datei-Meldung ist wahr, verdeckt aber die Ursache dieses konkreten
   Laufs.
5. Die Preview rendert Sonderfall-Dateien (verschlüsselt/kaputt) noch
   mit rohen Meldungen — der ADR-Scope von D2 deckt nur den Run-Pfad ab
   (Phase-11-Kandidat: `diagnose_pdf`-Precheck auch in `preview()`).
6. Root-Permissionstests sind in der Dev-Box wertlos → der
   Output-Fehlerfall wird über „Pfad durch eine Datei" getestet.
