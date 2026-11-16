# ADR 0005: Optionen vereinfachen – CLAHE/Noise-Cleaning entfernen, GUI reduzieren

*Status:* accepted (2026-11-16)
*Entscheider:* Supervisor (Phase 4, v0.7.0)

## Kontext

User-Feedback nach v0.6.0:

- „Noise cleaning (legacy)" lässt **Inhalte verschwinden** (morphologisches
  Open/Close frisst dünne Striche/Text).
- „Apply CLAHE" ist für Endnutzer unverständlich (wtf is applyCLAHE); CLAHE
  wandelt die Region in **Graustufen** um und zerstört damit die Farben eines
  Farb-Smartboards.
- Die Checkboxen „Rot erhalten"/„Grün erhalten" sind durch das Hex-Feld
  (ADR 0004) redundant.

## Entscheidung

### D1: CLAHE und morphologisches Cleaning komplett entfernen (breaking)

- Weg aus GUI, CLI (`--clahe/--no-clahe`, `--clean/--no-clean`), JSON-Config
  (`clahe`, `clean`) und Backend (`_process_region`; die
  `apply_clahe`/`clean`-Parameter von `process_pdf`, `enhance_image[_ex]`
  und des gesamten Pipeline-Plumbings).
- Begründung: beide Optionen waren seit v0.3.0 „legacy" und default AUS;
  Cleaning zerstort nachweislich Inhalte (User-Beobachtung), CLAHE ist für
  Farbinhalte destruktiv (Graustufen-Rundgang). In der 0.x-Linie sind
  Breaking Changes zulässig und werden dokumentiert (README, spec-Addendum).
  `--invert`/`--no-invert` bleiben erhalten.
- Die `do_something = invert or apply_clahe or clean`-Logik reduziert sich
  auf `invert` (invert aus = Seite wird unverändert kopiert, wie bisher).

### D2: GUI – Reduktion auf die relevanten Optionen

- Weg: Checkboxen „Apply CLAHE (legacy)", „Noise cleaning (legacy)",
  „Rot erhalten", „Grün erhalten".
- Bleibt: DPI-Slider, „Invert colours", „Auf Board zuschneiden",
  „Zielhintergrund" (Combobox), „Zusätzliche Hex-Farben" (Entry).
- Die GUI übergibt `keep_colors` **fix als `{"red", "green"}`** (= bisheriger
  Default, keine Verhaltensänderung); das Hex-Feld ist die einzige
  Feinstuerung (Union mit rot/grün). Der GUI-Hilfstext dokumentiert, dass
  rot/grün zusätzlich immer erhalten bleiben.
- Fensterhöhe 830 → 700 (4 Zeilen weniger).

### D3: Kompatibilität

- Bestehende JSON-Configs mit `clahe`/`clean`-Keys: unbekannte Keys werden
  (wie bisher) mit Debug-Log ignoriert – kein Fehler.
- Version 0.6.0 → **0.7.0** (Entfernung = breaking → Minor-Bump in 0.x,
  dokumentiert).

## Konsequenzen

- `processing.py`: `_process_region` weg; Signaturen von
  `enhance_image`/`enhance_image_ex` reduziert (CLAHE/clean-Parameter
  entfallen); Docstrings aktualisiert.
- `pdfpipeline.py`: `process_pdf`/`_process_page`/`_transform_render`/
  `_try_image_replace` ohne `apply_clahe`/`clean`; Kommentare angepasst.
- `cli.py`: Flags, `REAL_DEFAULTS`, `_CONFIG_TYPES`, `resolve_options`,
  `main` gesäubert.
- `gui.py`: Checkboxen, `_transform_options`, `start_processing`,
  `preview`, `_process_worker`, Fenstergröße, Modul-Docstring.
- Doku: README (CLI-Block, How-it-works, GUI-Sektion, Config, Project
  layout), spec.md Addendum (P4-FR-1, P4-D-1).
- Tests: bestehende clahe/clean-Tests entfernt, GUI-Tests angepasst
  (fixes `keep_colors`, keine Checkboxen); die bit-identische Regression
  (Complement-/Keep-Pfade) bleibt unberührt und grün.
