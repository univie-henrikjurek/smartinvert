# ADR 0007: Crop per Render-Slice (Offset-MediaBox-Fix) + GUI-Ordner-Batch & robuste Fehlerdialoge

*Status:* accepted (2026-11-16)
*Entscheider:* Supervisor (User-Bugreports v0.7.1)

## Kontext

Zwei User-Bugreports zu v0.7.1:

1. **Crop-Output auf echten Dokumenten kaputt:** „pixeldünner Rahmen, dann
   viel gelöschter Rand, dann ein Streifen Dokument in der Mitte".
   Reperatur am Beispiel (Repro bestätigt): Seiten, deren **MediaBox/CropBox
   nicht bei (0,0) ansetzt** (üblich bei Handy-/App-Exporten), produzieren
   ein **falsch geklipptes** Seitenstück. Ursache: `rect_pt` wird als
   `rect_px × (page.rect/render)` berechnet — ohne den Seitenursprung-Offset.
   Für origin-(0,0)-Seiten stimmt das (alle bisherigen Tests); für
   versetzte Seiten ist der Clip versetzt. PyMuPDF 2.1 verschärft das
   Problem: `page.rect` wird normalisiert (Ursprung (0,0)),
   `get_image_info`-Bboxen und `show_pdf_page(clip=…)` (nach
   Re-Serialisierung im Crop-Post-Stage) interpretieren die Koordinaten
   inkonsistent zu den Render-Koordinaten — eine zuverlässige
   Pixel→Seitenraum-Brücke ist in dieser Version nicht herstellbar
   (empirisch verifiziert: origin-0,0-Page: crop == faithful-Slice, Diff 0;
   Offset-Page: Mismatch).
2. **GUI-Crash bei Ordner-Input:** Der Worker überreicht den Ordner an
   `process_pdf`, das nur Dateien akzeptiert → Fehler. Der Fehlerdialog
   selbst crasht: `lambda: messagebox.showerror("Error", str(e))` wird nach
   dem `except`-Block ausgeführt, wo `e` laut PEP 3110 bereits
   ungebunden ist → `NameError` (verdeckt den eigentlichen Fehler).
   Zusätzlich: Die GUI bewirbt Ordner-Input (Texte, `_resolve_input`),
   hat aber nie eine Ordner-Batch-Verarbeitung implementiert
   (CLI hat sie via `_plan_jobs`).

## Entscheidung

### D1: Crop per Render-Slice statt `show_pdf_page(clip=…)`

`_save_cropped` rendert die faithful-Seite mit dem Processing-DPI,
schneidet exakt `pr.rect_px` aus (dieselbe Pixel-Rechteck, das auch
Transformation und Verifikation genutzt haben) und embedet den Slice 1:1
in eine neue Seite der Größe `rect_pt` (Breite/Höhe). Neue Seiten haben
immer Ursprung (0,0) → keine Koordinatenraum-Probleme mehr,
Version-unabhängig, deterministisch.

Qualitäts-Folgewirkung (dokumentiert): Board-Seiten enthalten nach der
Transformation ohnehin nur Raster-Content (image-replace = Raster-XObject;
rerasterize = Raster-Seite) → **kein Qualitätsverlust** für den Board-Bereich.
Fremder Vektor-Content *innerhalb* des Board-Rechtecks (z. B. Annotationen
auf gescannten Boards) wird jetzt statt vektor-exakt mit dem Processing-DPI
gerastert — dokumentierter Trade-off; `--dpi 300` für schärfere Ausgabe.
ADR 0003 „vector-exact" wird entsprechend ergänzt.

### D2: GUI-Ordner-Batch über `cli._plan_jobs`

Der GUI-Worker plant Jobs mit demselben Helper wie die CLI
(same semantics: sortierte `*.pdf`, Output-Ordner, pro Datei
`<out>/<name>.pdf`, kein Rekurs). Einzel-Datei: unverändert
(page-level Progress). Batch: file-level Progress, fortlaufend bei
Einzel-Fehlern (wie CLI), am Ende Summary-Dialog (OK bzw. „N of M failed"
mit Detail-Liste). Main-thread-Validierung bleibt: leeres Input, Ordner
ohne Output-Ordner, Hex-Feld.

### D3: Robuste Fehlerdialoge

Alle `messagebox`-Lambdas binden ihre Nachricht **eager**
(`msg = str(e); lambda m=msg: …`) — PEP 3110: `e` ist am Ende des
`except`-Blocks ungebunden; die Lambdas laufen später im Main-Thread.
Betrifft `_process_worker` (beide except-Zweige). `preview()` zeigt
Dialoge direkt im Main-Thread (kein Bug, unverändert).

## Konsequenzen

- `pdfpipeline._save_cropped(faithful_doc, output_path, result, dpi)` —
  neuer `dpi`-Parameter; Call-Site in `process_pdf`.
- `gui._process_worker(pdf_path, out_field, options)` — neue Signatur
  (rohe Felder; Job-Planning im Worker via `_plan_jobs`);
  `start_processing` übergibt `out_field` statt vor-berechnetem `out_path`.
- Regressionstests: Offset-MediaBox- und Offset-CropBox-Seiten
  (crop-Render == faithful-Slice, Seitengröße == rect-Größe); GUI:
  Ordner-Batch ruft `process_pdf` pro Datei auf, Fehler-Dialog enthält
  die Nachricht (kein NameError), Ordner ohne Output → Warning, kein Worker.
- Version 0.7.2; README/spec (Phase 6) aktualisieren.
