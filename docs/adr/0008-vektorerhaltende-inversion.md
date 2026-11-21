# ADR 0008: Vektorerhaltende Inversion (`vector-invert`) für Vektor-Board-Seiten

*Status:* accepted (2026-11-17, nach Implementierung + grüner Test-Suite)
*Entscheider:* Supervisor (User-Feature-Wunsch: „SVG/Schrift-Content komplett
übernehmen – Original ist klar, Konvertiertes auf 300 DPI pixelig")

## Kontext

Seiten, deren Board-Content **vektoriell** vorliegt (Vorschau-SVG/Vector-
Zeichnungen statt Screenshot, z. B. per App exportierte Vorlesungs-Skripte),
laufen heute über `rerasterize` (Seite wird beim Processing-DPI gerendert und
als Raster eingebettet) und – bei `crop=True` (Default seit v0.7.1) –
zusätzlich über die Render-Slice-Crop-Stage (ADR 0007, D1). Beides zerstört
die Vektorqualität: egal welches DPI, die Ausgabe ist Raster → pixelig.

ADR 0007 dokumentierte diesen Trade-off („fremder Vektor-Content wird mit dem
Processing-DPI gerastert"); dieser Use-Case ist jetzt der *Haupt*-Content.

Empirische Grundlagen (PyMuPDF 2.1, in `/tmp/opencode/vectest*` verifiziert):

1. `show_pdf_page(clip=…)` ist auf **Vektor**-Seiten pixel-exakt – auch für
   Offset-MediaBox-Seiten (Diff 0, in-memory und nach Re-Serialisierung).
   Der v0.7.2-Crop-Bug war spezifisch für Bild-XObject-Placements auf
   Offset-Seiten. → Ein **vektorerhaltender Crop** ist möglich.
2. Content-Streams dieser Dokumente sind sauber tokenisierbar
   (DeviceGray/DeviceRGB-Farb-Operatoren `g/G/rg/RG/k/K`, Pfade `m/l/c/re +
   f/S`, Text `BT…ET`; Farb-Operatoren sind positionsunabhängig setzbar).
3. Farb-Roundtrip-Write-back: `get_new_xref` + `update_object("<< /Length 0
   >>")` + `update_stream` + `page.set_contents(xref)` (PyMuPDF 2.1:
   `set_contents` erwartet ein XRef, keine Bytes) rendert korrekt und ist
   save+reopen-stabil.
4. Flat-Color-Quantisierung des Renderers = **`floor(v·255)`**
   (0.5→127, 0.999→254) → die Vektor-Farbmathematik kann exakt die
   Raster-Semantik (uint8, `255−v` bzw. bg_target-Remap, Keep-Ausschlüsse)
   reproduzieren.
5. Page-Modus-Detection (detection.py) akzeptiert Boards nie
   full-bleed (Rand-Minimum 0,5 %; Hintergrund p95 ≥ 200) → echte
   Dokumente haben einen (dünnen) Rand; „Vollläche" bedeutet in der
   Praxis ≈98–99 % Coverage.
6. **Text-Extraktion ist empfindlich gegenüber der Insertions-Position:**
   Wird ein eingeschobener Farb-Operator *zwischen* String-Operand und
   Text-Show-Operator gesetzt (`… (abc) 1 1 1 rg Tj`), rendert MuPDF korrekt,
   aber `get_text()` liefert leer. Vor dem String-Operand (`… 1 1 1 rg (abc) Tj`)
   bleibt die Extraktion intakt. → Farb-Inserts bei Text werden am
   String-/Array-Operand verankert.
7. **Bild-XObjects belegen die Unit-Square** (0,0)-(1,1) des aktuellen
   User-Space; sie haben kein `/BBox` (nur Forms). Ihre Platzierung folgt
   allein der CTM-Kette → die Geometrie-Entscheidung für `Do` auf Images
   transformiert `(0,0,1,1)` mit der CTM-Kette.
8. `page.clean_contents()` normalisiert *referenzierte* Form-XObjects mit
   (q/Q-Hülle, Zahlen-Format). Bei einem unauflösbaren XObject-Referenz
   darin leert MuPDF dessen Content still. Im Pipeline-Kontext folgenlos:
   jeder Fallback leert die Seite ohnehin (`_clear_page`), und der
   erfolgreiche Weg wird per D2-Verifikation abgesichert.
9. MuPDF 1.28 rendert Pattern- und ICCBased-Farb-Räume nicht zuverlässig
   (beobachtet: gesamte Seite wird blau gefüllt bzw. Fill wird still
   weggelassen). Dementsprechend gibt es dafür **keine** synthetischen
   Fixture-Seiten – die `cs`-Refusal wird auf Rewriter-Ebene unit-geprüft.

## Entscheidung

### D1: Neue Methode `vector-invert` (automatisch, mit Raster-Fallback)

Vor dem `rerasterize`-Fallback versucht der Pipeline per Seite einen
vektorerhaltenden Weg: **die Farb-Operatoren des Content-Streams werden
umgeschrieben** (Geometrie, Texte, Fonts bleiben 1:1 Vektor). Die
Farboperation pro Flat-Color ist exakt dieselbe Mathematik wie auf
Pixel-Ebene (Quantisierung `floor(v·255)`, dann `255−v` / bg_target-Remap mit
demselben `B_c` (p25 des Board-Renders), Keep-Ausschlüsse
`color_mask`/`hex_keep_mask` auf einem 1×1-Bild). Inversion/Remap kommutiert
mit Normal-Blending → Anti-Aliasing bleibt konsistent.

**Wichtige empirische Eigenschaft des Fidelity-Copies:**
`_add_page_copy` (`show_pdf_page`, ohne Clip) importiert die Seite als
Form-XObject-Baum (`/fzFrm0` → `/fullpage` → evtl. verschachtelte Forms;
Offset-MediaBox wird per `/Matrix`-Translation normalisiert). Es gibt also
genau **einen** zu bearbeitenden XObject-Baum unter der Seite; `page.rect`
des Fidelity-Copies ist (0,0,W,H) = derselbe Koordinatenraum wie `rect_pt`.

**Entscheidung pro Paint-Operator (einfaches, einheitliches Schema –
keine Scope-Verzweigung):** Der Tokenizer trackt die Grafik-Zustände
(`q/Q`-Stack, `cm`-CTM, `cs/CS`-Farb-Räume, Pfade `m/l/c/re`, Text-Matrix
`BT/Tm/Td/Tf/Tj/TJ/ET`) und entscheidet bei jedem Paint-Operator
(Füllung/Stroke/Text) anhand der **geometrischen BBox** (Pfad- bzw.
Text-BBox × CTM-Kette, in Seiten-Koordinaten umgerechnet):

* BBox vollständig außerhalb von `rect_pt` (± AA-Toleranz) → **behalten**
* BBox bedeckt ≥ 95 % der Seite **und** Farbe ist nah-weiß (alle Kanäle
  ≥ 200) → **behalten** (Background-Plate: das klassische SVG-Export-Muster
  „volle Weißfläche unter dem Board")
* BBox innerhalb von `rect_pt` (± AA-Toleranz) oder straddelt den Rand →
  **invertieren** (straddelnd: Board-Content, der über den Rand blutet, ist
  wahrscheinlicher als Rand-Content, der ins Board rückt; die
  Verifikationsschleuse schützt)

Weil Farb-Operatoren im Stream **geteilt** sein können (z. B. Weiß für
Plate UND weiße Board-Linien), werden **keine Original-Operanden umge-
schrieben** (ein in-place Rewrite würde frühere Paints desselben Operanden
korrigieren müssen – order-unsicher). Stattdessen trackt der Rewriter pro
Grafik-Zustand, welche Farbe *effektiv* gilt (Original oder eingescho-
bene Inversion), und **schiebt explizite Farb-Operatoren vor das erste
Operand des Paints ein**, wenn dessen Entscheidung mit der effektiven
Farbe widerspricht (beim Text: vor dem String-/Array-Operand, empirische
Eigenschaft 6). Immer gültiges PDF, order-sicher für jede Paint-Folge.

**Unterstützte XObjects:** Form-XObjects werden **rekursiv** umgeschrieben
(CTM-Kette aus `cm` bei `Do` × Form-`/Matrix` wird in die Geometrie-
Entscheidung übernommen). Ein **Image-XObject** innerhalb/nah am Board
(± AA-Toleranz) wird abgelehnt (Raster-Fallback); ein Bild *vollständig
außerhalb* des Boards (z. B. Logo im Rand) ist unproblematisch und wird
belassen.

**Nicht unterstützt in v1 → Raster-Fallback** (alle als
`VectorUnsupported` markiert): Inline-Images (`BI`), Shadings (`sh`),
ExtGState-Nutzung (`gs`, d. h. Transparenz/Blend-Modes), `scn/SCN`,
nicht-Device-Farbraum-Auswahl (`cs/CS` auf ICCBased/Pattern/…),
rotierte/schiefe Text-Matrizen (`Tm` mit b/c ≠ 0), Image-XObject
innerhalb/nah am Board. CMYK-Flächen werden mit der Standard-Subtraktiv-
Konversion umgewandelt (nicht injektiv auf 8-bit; Doppelkonversion stabil
innerhalb 1 Level – wird von der D2-Toleranz abgedeckt).

### D2: Selbstheilung durch Verifikation gegen die Raster-Grundwahrheit

Nach dem Write-back wird die Seite gerendert und mit der **Raster-
Grundwahrheit** verglichen (Original mit der Transformation nur innerhalb
`rect_px` – exakt das, was der Raster-Pfad produzieren würde):

* ein ±AA-Band um `rect_px` (`max(4, dpi/36+2)` px) wird aus dem Vergleich
  herausgenommen – dort unterscheiden sich Vektor- und Raster-Semantik
  fundamental (Blending an der Board-Kante mit dem nicht-invertierten
  weißen Canvas);
* Rest: max-Diff ≤ 3 pro Kanal.

Scheitert der Check (oder jeder Schritt davor) → die Seite wird geleert und
der **bewährte Raster-Pfad** läuft (`method` wird `rerasterize`), mit
Log-Grund. Die Ausgabe kann also nie schlechter werden als heute.

### D3: Vektor-Crop für `vector-invert`-Seiten

Die Crop-Stage (Default an) bevorzugt für `vector-invert`-Seiten
`show_pdf_page(clip=rect_pt)` in die neue Seite (vektorerhaltend; empirisch
pixel-exakt für Vektor-Content, Punkt 1). Sicherheitsnetz: das
Vector-Crop-Ergebnis wird gegen die etablierte Render-Slice-Grundwahrheit
verglichen (max-Diff ≤ 2); bei Abweichung wird die Seite verworfen und der
Raster-Slice eingebettet (heutiger Weg). Für alle anderen Seiten:
unverändert (Render-Slice bzw. 1:1-Kopie).

### D4: Keine neuen Optionen

Der Vektor-Weg ist **automatisch** (Conditionen + Fallback). Kein CLI-Flag,
keine GUI-Checkbox (ADR 0005-Philosophie: weniger Optionen). Die Methode ist
in `PageResult.method` („vector-invert") und den Logs sichtbar.

## Konsequenzen

* Neues Modul `smartboard_invert/vectorops.py`: Content-Stream-Tokenizer
  (binarsicher: Strings/Hex/Arrays/Dicts/Comments; unmodifizierte Spans
  1:1 übernommen), `FlatColorTransform` (per-Flat-Color-Korrespondent von
  `processing.invert_or_remap`, identische Mathematik), `aa_band_px`,
  `board_bg_levels`, `rewrite_page_tree` (rekursiv über den
  Form-XObject-Baum; Farb-Insertion mit CTM-/Pfad-/Text-Tracking) und
  `VectorUnsupported`.
* `pdfpipeline.py`: `_try_vector_invert` (Orchestrierung: Rewrite,
  Write-back, D2-Verifikation gegen die Raster-Grundwahrheit), Method-
  Dispatch in `_process_page`, `_try_vector_crop` + Vector-Branch in
  `_save_cropped` (D3), AA-Band-Exklusion in `_verify_page` für
  `vector-invert`.
* `PageResult.method` erhält den Wert `"vector-invert"`; die D2-
  Verifikation läuft im `_try_vector_invert`, die generelle
  Außen-Verifikation (`_verify_page`) toleriert für `vector-invert` das
  AA-Band (sonst Toleranz 0, für `rerasterize` 8).
* Tests: `tests/test_vectorops.py` (Tokenizer, `_fmt`/`_quant`-Roundtrip,
  CMYK-Stabilität, `FlatColorTransform`-Complement/Remap/Keep, `_decide`-
  Geometrie inkl. Plate-Regel, Stream-Rewriter-Insertion inkl.
  geteilte Operanden in beiden Reihenfolgen, q/Q-Restore, CTM, Text-
  Anker, `cs`/`scn`/`gs`/`sh`/BI/rotierte-Tm → Refusal, Image-Do
  innen/außen, `rewrite_page_tree` flach/verschachtelt/`/Matrix` +
  „nichts-geschrieben-bei-Refusal"), `tests/test_pipeline.py::
  TestVectorInvert` (vector/xobj/Offset → vector-invert, Keep-Colors,
  bg_target, invert-off → copy, 300-DPI-Vorlesungs-Szenario mit
  Textextraktion als Vektor-Nachweis, Crop vector-exakt + Offset,
  Raster-Fallback-Fälle: Inline-Image/Shading/ExtGState/rotierter Text).
  Neue Fixture-Kinds in `tests/synth.py`: `xobj`, `vector-<construct>`,
  `offset`, `marks`, `text`.
* Version 0.8.0-dev; README (Qualitätsabschnitt) + spec.md (Phase 7)
  aktualisieren.
* Bekannte Limitationen (dokumentiert): Transparenz/Blend, Shadings,
  Inline-Images, nicht-Device-Farbräume, rotierte/schiefe Texte → Raster-
  Fallback; Image im Board → Raster-Fallback; Pattern/ICCBased sind in
  MuPDF 1.28 nicht renderbar (nur unit-geprüft); CMYK-Doppelkonversion
  ±1 Level.

---

## Revision 2026-11-19 (v0.8.0-dev, User-Feedback: „immer noch pixelig")

**Hintergrund:** Der User testete `feature/svg-implement` mit dem
Eigensample `inputs/test.pdf` → Output weiterhin pixelig. Diagnose am
echten Dokument (Debug-Log + Content-Stream-Analyse): Der Rewriter hatte
die Seite abgelehnt (`VectorUnsupported`) und auf `rerasterize`
umgeschaltet — **die Vektor-Inversion lief nie**. `inputs/test.pdf` ist
ein echter App-Export mit 1229 Vektorpfaden, der drei „v1-Nicht-
Unterstütztes"-Konstrukte verwendet, die sich als harmlos bzw. trivial
unterstützbar herausstellten:

* **Empirische Eigenschaft 10:** App-Export-PDFs setzen pro Pfad einen
  *Identitäts-ExtGState* (`/GSa` mit `/ca 1 /CA 1 /SMask /None`, plus
  nur-Type-3-Text-spezifische Keys `/SA`/`/SM`) — d. h. **keine**
  Transparenz. Zusätzlich wird die Farbe über einen **benannten**
  Device-Farbraum gesetzt (`/CSp cs` + `R G B scn`, wobei `/CSp` im
  `/Resources /ColorSpace` auf `/DeviceRGB` zeigt), mit umgekehrter
  App-Space-CTM (`0.24 0 0 -0.24 10.08 831.92`), Even-Odd-Clip (`W* n`)
  und Even-Odd-Fills (`f*`).
* **Empirische Eigenschaft 11:** Ein Clip-Import (`show_pdf_page(clip=…)`)
  rastert *Vektor*-Kanten in einer leicht anderen Subpixel-Phase als der
  Vollseiten-Render (auf dem 1229-Pfad-Dokument: max-Diff 16 auf
  0,003 % der Pixel, verstreut — wahrnehmungsunwesentlich; dieselbe
  Kategorie wie das D1/D2-Board-Rand-AA-Band). „Pixel-identisch zum
  Render-Slice" ist für Vektor-Content also **nicht** das richtige
  Crop-Kriterium.

### D1-Extension: gs / benannte Device-Farbräume / scn werden unterstützt

* **`gs`** wird nicht mehr pauschal abgelehnt: Der Referenzierte
  ExtGState wird aufgelöst und analysiert. **Harmlos** (→ Operator wird
  unverändert durchgelassen) = voll opak (`/ca` und `/CA` == 1 oder
  abwesend), kein `/SMask` (oder `/SMask /None`) und kein `/BM` ≠
  `/Normal`. Alle übrigen Keys (Linienbreite, Dash, Caps, Miter,
  Flatness, Rendering Intent, …) beeinflussen die Farb-Umschreibung nie.
  Echte Transparenz/Blend/Soft-Mask oder Unauflösbarkeit → weiterhin
  `VectorUnsupported` (Raster-Fallback, D2).
* **`cs`/`CS`** löst den Namen nun auch über `/Resources /ColorSpace`
  auf (literale Device-Namen **und** indirekte Referenzen auf Device-
  Namen). `scn`/`SCN` werden für alle getrackten Device-Räume akzeptiert
  ( Operand-Semantik identisch zu `sc`/`SC`). ICCBased/Pattern/sonstige
  Räume → weiterhin Refusal.
* **Bugfix:** `F` (Even-Odd-Fill) und `B`/`B*` (Fill+Stroke) wurden als
  Nicht-Paint-Operatoren behandelt → ihre Fills/Stroke erhielten keine
  Farb-Entscheidung (die D2-Verifikation prüft nur *außerhalb* des
  Boards → wäre unentdeckt geblieben). Jetzt wie `f*` bzw. `s`/`b`.
* **Kosmetik:** `_fmt(0)` liefert `0` statt `0.000040` (beides
  quantisiert auf dem Renderer-Grid zu 0; symmetrisch zum `v>=255 → 1`-
  Sonderfall).

### D3-Revision: „Geometrie + grobe Fidelity" statt Pixel-Identität

Das Vector-Crop-Sicherheitsnetz vergleicht das Clip-Import-Ergebnis
gegen die Render-Slice-Grundwahrheit jetzt mit: **max-Diff ≤ 32**
(schlechtester Pixel: schützt vor falschen Farben/fehlendem Content/
Versatz) **und** Anteil abweichender Pixel (Diff > 2) **≤ 0,1 %**
(schützt vor systematischem Fehlauschnitt — der ADR-0007-Offset-Bug
abweicht über ganze Kantenregionen → scheitert an beiden Caps → Raster-
Slice). Ein Crop kann weiterhin nie falsch sein.

### Ergebnis der Revision

* `inputs/test.pdf` (150 und 300 DPI, `crop=True` Default):
  `method=vector-invert`, **0 Bild-XObjects** im Output, **1229 Vektor-
  Drawings erhalten**, Outside-Verifikation max-Diff 0, vector-exact
  Crop; Scharfheit (Laplacian-Varianz) @600 dpi: **693.6** (Vektor) vs.
  **118.8** (altes Bitmap-Output) → das Pixel-Problem des Users ist
  beseitigt.
* Regressionstest `tests/test_pipeline.py::TestRealSampleVectorInvert`
  läuft das echte `inputs/test.pdf` end-to-end durch (method, 0 Images,
  ≥ 1000 Drawings, heller Board-Hintergrund) — die Klasse von „Fix
  funktioniert nur auf synthetischen Fixtures" ist damit abgedeckt.
* Neue Unit-Tests: `TestResourceResolution` (ColorSpace-Map literal/
  indirekt/Pattern/ICCBased/Compact-Serialisierung, ExtGState-harmless-
  Analyse inkl. alle Refusal-Gründe) + `TestStreamRewriterAppExport`
  (harmless/harmful `gs`, `scn` in Device-Räumen, benannter Farbraum
  via Resources, Pattern-Refusal, Mini-Replik des test.pdf-Streams,
  `F`/`B`/`B*`).
* Suite: **413 passed + 1 skipped** (headless), 16 GUI (Xvfb), Coverage
  90.54 %.
* **Unverändert (weiterhin Raster-Fallback):** echte Transparenz
  (`/ca`/`/CA` < 1), Blend-Modes (`/BM` ≠ Normal), Soft-Masks, Shadings,
  Inline-Images, ICCBased/Pattern-Farbräume, rotierte/schiefe Texte,
  Bild im Board. Inline-Dict-ExtGState-Definitionen (statt Referenz)
  werden sicher abgelehnt (konservative Richtung).
