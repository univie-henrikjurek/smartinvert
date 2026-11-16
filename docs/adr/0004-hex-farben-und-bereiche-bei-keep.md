# ADR 0004: Hex-Farben und -bereiche für die Inversions-Ausschlussliste

*Status:* accepted (2026-11-16)
*Entscheider:* Supervisor (Phase 6, v0.6.0)

## Kontext

`--keep-colors` (ADR 0002) exclusiviert nur die vier groben Farbnamen
red/green/blue/yellow über Dominanz-Masken. Der Nutzer möchte **explizite
Farbcodes und -bereiche** in Drucker-Notation angeben können:
`FF0000, 00FF00, 000001-0000FF` — also exakt Rot, exakt Grün, und der
ganze blaue Bereich „vom dunkelsten bis zum hellsten Blau". Zusätzlich
ein **Textfeld in der GUI** für dieselbe Syntax.

## Entscheidung

### D1: Neue Option `--keep-hex` (orthogonal zu `--keep-colors`)

- CLI-Flag `--keep-hex VALUE` (default leer/aus), JSON-Config-Key `keep_hex`
  (String), GUI-Textfeld (default leer). Keine `--no-`-Variante: leer = aus.
- Parser `parse_keep_hex` in `cli.py` (Chokepoint wie `parse_keep_colors`):
  kommasepariert, Whitespace-tolerant, leere Einträge ignoriert; je Eintrag
  `RRGGBB` (Punkt) oder `RRGGBB-RRGGBB` (Bereich, Endpunkte dürfen vertauscht
  sein → normalisiert); optionaler `#`-Prefix und 3-stellige Kurzform
  (jede Ziffer verdoppelt). Sonst `SmartboardError` (CLI: `[ERROR]` + exit 1;
  GUI: Error-Dialog **vor** Start des Workers, Controls bleiben betätigbar).
- Ergebnis: Tupel von `(a, b)`-Endpaaren (RGB, ints 0–255; `a == b` bei
  Punkt). Zentrale Validierung `validate_keep_segments` in `processing.py`
  (Public-API-Chokepoint wie `validate_bg_target`).

### D2: Matching-Semantik — Strecken-Distanz + Chroma-Guard

Ein Pixel wird exkludiert (behält Originalwerte), wenn **beides** gilt:

1. **Abstand** — der euklidische Abstand des Pixels zur **Strecke** `[a, b]`
   im RGB-Raum ist ≤ `HEX_TOL = 50` (bei `a == b`: Abstand zum Punkt).
   Vektorisiert: `t = clip(((p−a)·(b−a)) / |b−a|², 0, 1)`,
   `d = ‖p − (a + t(b−a))‖`.
2. **Chroma-Guard** — `max − min` der Kanäle des Pixels ist ≥
   `HEX_MIN_CHROMA = 24`.

Begründung:

- *Toleranz statt Gleichheit:* gescannte Marker sind nie exakt `FF0000`
  (Rauschen/Kompression); `≤ 50` liegt über Scan-Noise und unter der
  Distanz zu einer anderen Markerfarbe.
- *Strecke statt Endpunkte:* „000001-0000FF" bedeutet für den Nutzer die
  ganze blaue Achse — nur die Strecken-Semantik fängt auch das mittlere
  Blau (0,0,128) und verrauschte Blautöne (15,10,180) ein.
- *Chroma-Guard:* Bereiche, die am neutralen Ursprung ansetzen (blaue
  Achse bei (0,0,0)), hätten sonst **neutrale Grautöne** mitgefangen —
  also den dunklen Board-Hintergrund (Chroma ≈ 0), der invertiert werden
  soll. Sichtbare Marker haben Chroma ≫ 40 und sind nie gefährdet.
  *Caveat (dokumentiert):* praktisch unsichtbare Extremwerte (z. B.
  (0,0,8), Chroma 8 < 24) werden bewusst nicht exkludiert — auf dem
  dunklen Board sind sie nicht vom Hintergrund zu unterscheiden.
  Neutrale Bereiche (z. B. `202020-303030` für Graumarker) werden dadurch
  ebenfalls nicht unterstützt — falls nötig, später über eine Option.

### D3: Zusammenspiel

- Union der Masken: `keep_colors` (Namen) ODER `keep_hex` (Spezifikationen)
  → exkludiert. Beides am **Ende** auf `original` angewendet, Vorrang vor
  Complement und Remap (wie ADR 0002).
- `keep_hex` leer → `hex_keep_mask` liefert all-False ohne Rechenaufwand;
  Verhalten **bit-identisch zu v0.5.0** (Regressionstest).
- Keine Wechselwirkung mit `--crop` (Post-Stage) und `detection.py`.
- Umsetzung: `hex_keep_mask` + `validate_keep_segments` in `processing.py`;
  `invert_or_remap` erhält `keep_segments=()`; `process_pdf`/`_process_page`/
  `_transform_render`/`_try_image_replace` nur Plumbing; CLI/GUI/Config wie D1.
- GUI-Feld wird nach einem Run **nicht geleert** (Wiederverwendbarkeit).
- Version 0.5.0 → 0.6.0 (neue Option = Minor-Bump).

## Konsequenzen

- `processing.py`: `HEX_TOL`, `HEX_MIN_CHROMA`, `hex_keep_mask`,
  `validate_keep_segments`, `invert_or_remap(keep_segments=)`;
  `__init__.py` exportiert `hex_keep_mask`.
- `cli.py`: `parse_keep_hex` (+ Regex-Helfer), Flag, `REAL_DEFAULTS`,
  `_CONFIG_TYPES`, `resolve_options`, `main`.
- `gui.py`: Entry + Help-Label (rows 8/9, Fenster 660×830), Parse im
  Hauptthread vor dem Worker, Plumbing an `process_pdf`.
- Doku: README (CLI/GUI/Config), spec.md P3-FR-11/P3-D-3.
- Tests: Parser (alle Formen + Fehlerfälle), Maske (Punkt, Rauschen, blaue
  Achse, **Grauschutz**, Chroma-Guard), Zusammenspiel (Union, Vorrang,
  leer = bit-identisch v0.5.0), CLI/Config e2e, Integration mit
  synthetischem Board (synth `marks`), GUI-Flows.
