# ADR 0002: Ziel-Hintergrundfarbe und erhaltene Markerfarben

*Status:* accepted (2026-11-15)
*Entscheider:* Architekt (Phase 3)

## Kontext

v0.4.1 invertiert strikt `255 − v`. Zwei Probleme: (1) sehr dunkle Boards
(RGB ≈ 30) werden ≈ 225 → wirken "beige" statt weiß; (2) rot/grüne Marker
(Weggestrichenes, Angehaktes) werden verfälscht. Beides ist eine reine
Pixel-Operation im erkannten Rechteck: Erkennung, die 3 Ausgabemethoden
(copy/image-replace/rerasterize), Verifikation und Debug konsumieren das
Region-Bild weiterhin nur als RGB-ndarray und bleiben unverändert
(bestätigt: `pdfpipeline._transform_render`/`_try_image_replace` arbeiten
auf `img.copy()` bzw. `native.copy()`).

## Entscheidung

### D1: Eine zentrale Pixel-Operation `invert_or_remap` (processing.py)

Alle 4 `np.bitwise_not`-Stellen (`invert_region`, `enhance_image_ex`,
`pdfpipeline._transform_render`/`_try_image_replace`) rufen statt dessen:

    invert_or_remap(region, original=None, *, bg_target=None,
                    keep_colors=frozenset()) -> np.ndarray

- `bg_target=None` → `np.bitwise_not` (bit-identisch zu v0.4.1).
- `bg_target=(R,G,B)` → pro Kanal `v' = T_c·(255−v)/(255−B_c)`;
  `B_c` = p25 des Kanals im Remap-Input (nach optionalem CLAHE/clean;
  Default-Config = Original), geclampt auf [0, 220] (Nenner ≥ 35);
  float32, round-half-up, clip 0–255. Anker: `v=B_c → T_c`, `v=255 → 0`.
- Exklusion (D2) wird auf dem **Original** berechnet (`original`,
  Default = region); exkludierte Pixel erhalten am Ende
  `out[m] = original[m]` — Vorrang vor Complement und Remap.

B_c = p25, **nicht** die `background_level` der Erkennung: diese ist p95 der
**Seite** (≈ 255 → Nenner degeneriert). p25 ≈ Board-Helligkeit ist die
bewährte Konvention aus ADR 0001 (D1) — robust gegen helle Schrift/Marker,
die in den oberen Perzentilen liegen.

### D2: Farbmasken `color_mask(region, colors) -> bool (H×W)` (BGR, int16)

`COLOR_DELTA Δ = 40`, `COLOR_MIN R_min = 80` (Modul-Konstanten),
`KEEPABLE_COLORS = {red, green, blue, yellow}` (unbekannt → SmartboardError):
red: `R>G+Δ ∧ R>B+Δ ∧ R≥R_min`; green/blue analog;
yellow: `R>B+Δ ∧ G>B+Δ ∧ R,G≥R_min`.

Begründung: Δ=40 liegt weit über Screenshot-Rauschen (≤ 10) und weit unter
echten Marker-Kanaldifferenzen (≥ 100); R_min=80 liegt über dunklem
Board-Rauschen (≤ 60) und unter gesättigten Markern (≥ 150). Weißes
Kreide-Gray (R≈G≈B) und dunkles Rauschen werden nie exkludiert.
numpy-only, deterministisch.

### D3: CLI / GUI / Config / API

- `--bg-target {complement|R,G,B}` (Default `complement`),
  `--keep-colors {red,green,blue,yellow|none}` (Default `red,green`).
  Zentrales Parsing in `cli.py` (`parse_bg_target`/`parse_keep_colors`,
  Fehler → `SmartboardError`); dieselben Parser für Flag und JSON-Config;
  Config-Keys `bg_target`/`keep_colors` (String) in `REAL_DEFAULTS` +
  `_CONFIG_TYPES` ergänzt.
- `process_pdf`, `enhance_image[_ex]`, `invert_region` erhalten
  `bg_target`/`keep_colors` (Keyword, Default = v0.4.1-Verhalten) und
  reichen sie bis `invert_or_remap` weiter; `process_pdf` validiert
  `keep_colors ⊆ KEEPABLE_COLORS`. **`detection.py`: unverändert.**
- GUI: `create_widgets` → `opts_frame`, rows 4–6 nach den 3 Checkboxes:
  Combobox "Zielhintergrund" (readonly: "Complement (255 − v)", "Reinweiß
  (255,255,255)") + Checkboxen "Rot erhalten"/"Grün erhalten" (default AN);
  Fenster 660×560 → 660×690; `StringVar` importieren. Werte fließen in
  `preview()` (enhance_image_ex) und `start_processing()` (process_pdf).
  Blue/yellow und freie R,G,B bleiben CLI-only.

### D4: Bewusster Default-Wechsel (breaking)

Default `complement` + `red,green` ≠ v0.4.1 (User-Entscheidung, dokumentiert
in README + spec.md-Addendum). Exakt v0.4.1: `--bg-target complement
--keep-colors none` — als Regressionstest bit-exact gegen
`np.bitwise_not`. Version 0.4.1 → 0.5.0.

## Konsequenzen

- `processing.py`: neu `invert_or_remap`, `color_mask`, `KEEPABLE_COLORS`,
  `COLOR_DELTA`, `COLOR_MIN`; Signatur-Erweiterungen backward-kompatibel.
  `pdfpipeline.py`: nur Parameter-Plumbing (`process_pdf`/`_process_page`/
  `_transform_render`/`_try_image_replace`); Strategie-Auswahl,
  Verifikation, Debug unverändert.
- `cli.py`: 2 Flags, 2 Parser, `REAL_DEFAULTS`/`_CONFIG_TYPES`/
  `resolve_options`/`main`. `gui.py`: 3 Controls, 2 Aufrufstellen,
  `StringVar`-Import, Fensterhöhe.
- `tests/synth.py`: `board_image`/`make_pdf` (image-kind) bekommen
  `marks: [(rect_px, BGR-Farbe), …]` (gefüllte Rechtecke); Ground Truth
  `rect_px` unverändert.
- Doku: README (CLI/GUI/Config + Default-Hinweis), spec.md-Addendum
  Phase 3 (P3-FR-9/10, P3-D-1 Default-Wechsel; A-2 teilweise ersetzt).
- Tests (Plan, Tester): Remap (B_c→target, 255→0, Monotonie, Clamp,
  complement ≡ strikt); Masken (4 reine Farben, White-Gray + Rauschen <
  R_min nicht exkludiert, Δ-Grenze); Integration: graues Board +
  rot/grüne Marker + weiße Kreide → Pipeline → Hintergrund ≈ target,
  Kreide dunkel, Marker ≈ Original; Regression bit-exact v0.4.1.
