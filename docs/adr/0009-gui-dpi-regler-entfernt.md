# ADR 0009: GUI ohne DPI-Regler (fester interner Wert 150 dpi)

*Status:* accepted (2026-11-19, User-Anfrage: „DPI Regler entfernen, den
brauchen wir nicht mehr im GUI")
*Entscheider:* Supervisor

## Kontext

Seit v0.8.0-dev (ADR 0008) bestimmt das Processing-DPI **nicht mehr die
Qualität** von Vektor-Board-Seiten: `vector-invert` + Vector-Crop halten
den Content als Vektor, scharf in jeder Vergrößerung. Der DPI-Regler
(50–300, Default 150) im GUI hat daher zwei Probleme:

1. **Verwirrung statt Nutzen:** Die User-Frage „Welchen Wert soll ich
   einstellen?" hat bei Vektor-Content keine gute Antwort („höher =
   besser" galt nur für den Raster-Pfad), und der User sieht das so
   („den brauchen wir nicht mehr").
2. **ADR-0005-Philosophie** („weniger Optionen, die Defaults sind
   gut"): Der Default 150 dpi war für den Raster-Pfad bereits als
   gutes Quality/Speed-Verhältnis dokumentiert (spec.md A-5); ein
   interner Default erfüllt den Bedarf für Raster-Dokumente, ohne
   die GUI zu vergrößern.

Power-User behalten den Zugriff: das CLI-Flag `--dpi` (Range 20–600)
bleibt unverändert.

## Entscheidung

* Der DPI-Regler wird aus dem GUI **vollständig entfernt** (Widget,
  `dpi_var`, Value-Label, `_on_dpi_change`-Callback).
* Die GUI rendert die Vorschau und verarbeitet mit dem **Pipeline-
  Default von 150 dpi** (`pdf_to_images(dpi=150)` bzw.
  `process_pdf(dpi=150)` als Signature-Defaults — die GUI übergibt
  keinen `dpi`-Parameter mehr).
* Neue GUI-Optionen: keine. CLI unverändert.

## Konsequenzen

* `smartboard_invert/gui.py`: Options-Frame ohne DPI-Zeile (Grid-Reihen
  neu nummeriert), `DoubleVar`-Import entfernt, `preview()` und
  `_process_worker()` ohne dpi-Parameter.
* Tests: `tests/test_gui.py::TestSimplifiedOptions` — die Attribute
  `dpi_var`/`dpi_slider`/`dpi_value` dürfen nicht mehr existieren;
  `process_pdf` darf keinen `dpi`-Keyword erhalten (neuer Test).
* README (GUI-Abschnitt): DPI-Zeile entfernt.
* Ersetzt den Punkt „Bleibt: DPI-Slider" aus ADR 0005 (historisch
  unverändert gelassen; dieses ADR geht vor).
