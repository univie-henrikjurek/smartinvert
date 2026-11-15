# ADR 0003: Crop-Ausgabe – Seiten exakt in der Größe des erkannten Board-Rechtecks

*Status:* proposed (2026-11-15)
*Entscheider:* Supervisor
*Branch:* `feature/crop-to-board` (auf v0.4.1; kein Versions-Bump – 0.5.0 ist durch
`feature/color-options` beansprucht)

## Kontext

Kern-Design von ADR 0001 ist die **seitentreue** Ausgabe: gleiche Seitengröße, Board an
gleicher Position, umgebender Seitenrand (weißer Rand) erhalten. Anwender wünschen für
ihre Ausgabe aber Seiten, die **nur das Board** zeigen: Jede Seite mit erkanntem
Board wird eine eigene Seite in exakt der Größe des Board-Rechtecks (in pt); der
umgebende Rand wird weggeschnitten. Seitenreihenfolge und -anzahl bleiben erhalten.
Um eine Breaking-Change zu vermeiden, bleibt die seitentreue Ausgabe **Default** –
Crop ist opt-in (`--crop` / Checkbox).

Abgewogene Alternativen:
- **Pixel-Crop am Render:** nur auf dem rerasterize-Pfad sinnvoll, verlustbehaftet
  (Re-Rasterisierung) und würde bei copy/image-replace den Vektor-/Bildpfad
  umgehen → abgelehnt.
- **Crop-Integration in jede der 3 Ausgabemethoden:** 3× Aufwand, greift in den
  verifizierten Kern (Erkennung, 3 Methoden, Verifikation, Debug) ein → abgelehnt.

## Entscheidung

### D1: Crop als eigenständige Post-Processing-Stufe nach der seitentreuen Ausgabe

`process_pdf(..., crop: bool = False)` baut das seitentreue Dokument **exakt wie
bisher** (Erkennung, 3 Methoden, Verifikation, Debug bleiben 100 % unverändert).
Bei `crop=True` verpackt eine neue Stufe `_save_cropped(faithful_doc, output_path,
result)` das fertige Dokument **in-memory** neu:
`src = fitz.open(stream=faithful_doc.write(), filetype="pdf")` (throwaway-Kopie –
`show_pdf_page` verlangt ein anderes Dokument-Objekt als das Ziel; Quelle muss das
seitentreue **Output** sein, denn eretzte Bilder / eingebettete Raster existieren
nur dort):

- Seite i **mit** Board-Rect (`pr.detected ∧ pr.rect_pt ≠ None`):
  `new_page = final.new_page(width=clip.width, height=clip.height)` (pt, Floats
  1:1, kein Runden) + `new_page.show_pdf_page(new_page.rect, src, i, clip=clip)` –
  vektor-exakt, kein Re-Rasterisieren; Ziel-Rect und Clip haben identische
  Abmaße → exakte 1:1-Mapping (keep_proportion).
- Seite **ohne** Board (inkl. aller `/Rotate ≠ 0`-Seiten, A-11):
  `final.insert_pdf(src, from_page=i, to_page=i)` – Seite bleibt in voller Größe
  (kein Inhaltsverlust), pro Seite ein WARNING im Log. `insert_pdf` (nicht
  `show_pdf_page`) übernimmt auch das `/Rotate` verlustfrei (ADR 0001, D2).
- **Kein Board auf keiner Seite:** Ausgabe = automatisch das seitentreue Dokument
  (alle Seiten 1:1) + Summary-WARNING; es wird nie eine leere Datei erzeugt.

### D2: Koordinatenraum von `clip` – unrotiert; im Primärweg kein Problem

PyMuPDF-Doku: Eingabe-Koordinaten aller Methoden (damit auch `clip`) gelten im
**unrotierten** Seitenraum (seit v1.17); nur `Page.rect` reflektiert `/Rotate`.
Zusätzlich wirkt das `/Rotate` der Quellseite auch auf die **dargestellten Inhalte**
(Doku-Warning: „be wary about source page rotation“; empfohlene Lösung:
`remove_rotation()` vor `show_pdf_page`).

- **Primärweg (Kontrakt):** Per A-11 existiert `rect_pt` nur auf Seiten mit
  `/Rotate = 0` (dort visual == unrotiert) → `clip := rect_pt` direkt,
  keine Transformation, Versions-unsabhängig (PyMuPDF 1.26.5 und 2.x).
- **Defensiver Zweig** (Kontraktverletzung, z. B. falls A-11 künftig gelockert
  wird): `rect_pt` liegt im visuellen Raum → auf der throwaway-Kopie
  `page.remove_rotation()` (offiziell empfohlen; dreht den Inhalt ein,
  MediaBox wird der alte visuelle Kasten) – danach ist `rect_pt` per Konstruktion
  im unrotierten Raum; Fehler → Seite wird voll kopiert + WARNING.
- Defensive Klammer: `clip = clip & page.rect` (nach optionaler remove_rotation);
  entartetes Ergebnis (Fläche 0) → Seite voll + WARNING (kann via
  `detection.found`-Gate nicht auftreten).

Äquivalente offene Rechnung (unrotierte Seite W×H, visuelles Rect v;
verifiziert am Doku-Beispiel 90°: A4 → `page.rect (0,0,842,595)`,
unrotiert (0,0) → visual (842,0)):
- r=90: u = (v.y0, H−v.x1, v.y1, H−v.x0)  (empirisch verifiziert:
  v=(100,50,300,400) → u=(50,542,400,742); Flächentreue 350×200)
- r=180: u = (W−v.x1, H−v.y1, W−v.x0, H−v.y0)
- r=270: u = (W−v.y1, v.x0, W−v.y0, v.x1)
(in PyMuPDF: `u = fitz.Rect(*v) * page.derotation_matrix`)

### D3: Rect für jede erkannte Seite + `cropped`-Flag

`PageResult.rect_pt` wird gesetzt, sobald `detection.found` – **unabhängig von der
Transformation** (kleiner Move in `_process_page` vor der `do_something`-Zweigung,
Rechnung unverändert). Damit schneidet `--crop` auch erkannte, nicht
transformierte Seiten (`--no-invert --crop`) – gemäß Anforderung „jede Seite mit
erkanntem Board“. Neues Feld `PageResult.cropped: bool = False`. Debug-Composites
bleiben seitenweit (unverändert); die Verifikation läuft weiter auf dem
seitentreuen Dokument (unverändert).

### D4: CLI / Config / GUI

- CLI: `--crop` / `--no-crop` (`store_true`/`store_false`, `default=None`-Sentinel,
  Stil von `--invert`/`--clean`); `REAL_DEFAULTS["crop"] = False`;
  `_CONFIG_TYPES["crop"] = bool`; `resolve_options` nimmt „crop“ auf.
- GUI: Checkbox **„Auf Board zuschneiden (Rand entfernen)“** (Default AUS),
  Option fließt `start_processing` → `process_pdf(crop=…)`; Preview unverändert
  (bleibt seitenweites Pixel-Preview, keine Dokument-Ausgabe).
- `ProcessResult.summary()` hängt bei N > 0 „, N cropped to board rect“ an.

### D5: Grenzfälle

- Rect mit 0.1-pt-Bruchteilen → `new_page(width=…, height=…)` akzeptiert Floats
  (legale MediaBox); keine Rundung, Toleranz in Tests ±0.5 pt.
- Board ≈ komplette Seite: in Page-Mode unmöglich (Randabstands-Gate ≥ 0.5 %,
  ADR 0001 D1) – kein Sonderpfad nötig.
- Mehrere Seiten: jede unabhängig, 1:1-Seiten-Korrespondenz, Reihenfolge erhalten.
- Alle 3 Methoden × Crop: identischer Mechanismus (copy = geclippter Vektor,
  image-replace = geclipptes Bild-XObject, rerasterize = Clip des eingebetteten
  Rasters); orthogonal zu `--bg-target`/`--keep-colors` (deren Pixel wirken nur IM
  Rechteck der seitentreuen Stufe) → merge-sicher.
- `crop=False`: Code-Pfad byte-identisch zu v0.4.1 (direktes `out_doc.save`) –
  die existierenden Tests sind die Regression.

## Konsequenzen

- `process_pdf` erhält Keyword-Parameter `crop: bool = False` (additiv,
  rückwärtskompatibel); neue Modul-Funktion `_save_cropped` in `pdfpipeline.py`;
  CLI/GUI/README-Plumbing. Keine Änderung an Erkennung, 3 Methoden, Verifikation
  oder Debug.
- Dateigröße der Crop-Ausgabe sinkt nicht zwingend: zugrunde liegende volle
  Bild-XObjects werden nicht physisch beschnitten (nur Display-Clip) – Vektor-
  bleibt Vektor, verlustfrei.
- Ein zusätzlicher Speicher-Byte-Roundtrip (`write()`/`open(stream=…)`) pro
  Dokument bei `crop=True` (negligibel ggü. Render/Erkennung).
- **Kein Versions-Bump** auf diesem Branch (bleibt 0.4.1).
- Tests (Plan für Tester): (1) Seitengröße == Rect ±0.5 pt (alle 3 Methoden;
  No-Board-Seiten bleiben voll); (2) Pixel-Vergleich Crop-Render vs. geclippter
  Render des seitentreuen Dokuments: strikt Innen (2 px erodiert) Max-Diff = 0,
  Vollregion Mean < 0.5 und < 1 % Pixel abweichend (Rand-Interpolationsphase ≤ 1 px);
  (3) Mixed-Doc mit `/Rotate=90`-Seite: rotierte Seite voll + pixelidentisch,
  Board-Seite gecropt; (4) kein Board + `--crop` → seitentreue Ausgabe + WARNING,
  keine leere Datei; (5) `--crop` aus → existierende 88 Tests unverändert grün;
  (6) CLI/Config/GUI-Plumbing.
