# ADR 0006: Crop als Default (v0.7.1)

*Status:* accepted (2026-11-16)
*Entscheider:* Supervisor (User-Anforderung)

## Kontext

User-Feedback zu v0.7.0: Im Standard-Run bleibt die Seite in ihrer
Originalgröße (z. B. A4); das Board ist nur ein Teilrechteck und die
Seitengrenzen stimmen nicht mit dem sichtbaren Inhalt überein. Der Nutzer
will per Default, dass die Seitengrenzen **nur den sichtbaren Bereich**
beinhalten — das ist exakt das, was der Crop-Post-Stage (ADR 0003) leistet,
die bisher opt-in war (Default: aus).

## Entscheidung

**Crop ist ab v0.7.1 standardmäßig AN** — konsistent in allen Schichten:

- `process_pdf(..., crop=True)` (Signatur-Default),
- CLI: `--crop` bleibt, `--no-crop` schaltet aus; `REAL_DEFAULTS["crop"] =
  True`, Help-Texte entsprechend,
- GUI: Checkbox „Auf Board zuschneiden (Rand entfernen)" standardmäßig
  angehakt (`IntVar(value=1)`).

Verhalten der Seiten bleibt unverändert (ADR 0003): nur Seiten **mit**
erkanntem Board werden zugeschnitten (exakt auf das Rechteck); Seiten ohne
Board (inkl. aller rotierten Seiten, A-11) behalten ihre volle Größe.
Degenerate Rechtecke → Seite bleibt in voller Größe (existierende
Sicherheitslogik in `_save_cropped`).

## Konsequenzen

- Tests, die das seitengetreue (crop=off) Verhalten prüfen, müssen
  `crop=False` explizit übergeben; der Pipeline-Test-Helfer `process()`
  pinnt deshalb crop=False, es sei denn ein Test fragt Crop explizit ab.
- Neue Regressionstests: Default-Run == expliziter `crop=True`-Run
  (Pipeline + CLI); GUI-Default liefert `crop=True`.
- Breaking Change für CLI-User, die auf `--no-crop`-Default angewiesen
  waren: jetzt `--no-crop` angeben (0.x-Linie, dokumentiert in README,
  spec P5-FR-1/P5-D-1 und Version 0.7.1).
