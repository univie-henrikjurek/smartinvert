"""Command-line interface for the Smartboard Inversion tool.

Usage examples:

    python -m smartboard_invert                          # inputs/ -> outputs/
    python -m smartboard_invert --input inputs --output outputs
    python -m smartboard_invert -i myboard.pdf -o out.pdf --debug -v

``--input`` may be a PDF file or a directory (all PDF files, sorted, are
processed).  ``--output`` may be a PDF file (single file input) or a directory
(results are stored under the **same file name** as the input).  The input
files are never modified.

Exit code: 0 when all files were processed, 1 when at least one file failed.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from . import __version__
from .pdfpipeline import process_pdf
from .processing import HexSegment, KEEPABLE_COLORS, SmartboardError

logger = logging.getLogger(__name__)

#: Defaults used when neither the CLI flag nor the config file provides a value.
#: ``output`` stays ``None``: for a *directory* input the default output
#: directory is "outputs" (same file names), for a *single file* input the
#: legacy default "<stem>_inverted.pdf" next to the input is used.
#: ``bg_target``/``keep_colors``/``keep_hex`` are stored in CLI syntax and
#: parsed by :func:`parse_bg_target`/:func:`parse_keep_colors` /
#: :func:`parse_keep_hex` (single choke point for flags and config).
REAL_DEFAULTS: Dict[str, Any] = {
    "input": "inputs",
    "output": None,
    "dpi": 150,
    "invert": True,
    "crop": False,
    "debug": False,
    "bg_target": "complement",
    "keep_colors": "red,green",
    "keep_hex": "",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartinvert",
        description=(
            "Detect the smartboard rectangle on every PDF page and invert only "
            "that area (255 - v). Page size and position are preserved; "
            "everything outside the rectangle stays untouched. If no "
            "unambiguous region is found, the page is left unchanged and a "
            "warning is printed."
        ),
    )
    parser.add_argument(
        "--input",
        "-i",
        default=None,
        help="Input PDF file or directory (default: inputs/).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help=(
            "Output PDF file (single input) or directory. Default for a "
            "directory input is outputs/ (same file names); default for a "
            "single file without --output is <name>_inverted.pdf next to the "
            "input (legacy behaviour)."
        ),
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="Rendering DPI for detection and output (default: 150, range 20-600).",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        default=None,
        help="Invert the detected region (default: enabled).",
    )
    parser.add_argument(
        "--no-invert",
        dest="invert",
        action="store_false",
        help="Disable colour inversion.",
    )
    parser.add_argument(
        "--crop",
        action="store_true",
        default=None,
        help=(
            "Size each output page to its detected board rectangle (removes the "
            "surrounding page margin). Pages without a detected board are kept "
            "in full size. Default: off (page-faithful output)."
        ),
    )
    parser.add_argument(
        "--no-crop",
        dest="crop",
        action="store_false",
        help="Keep the full page size (default).",
    )
    parser.add_argument(
        "--bg-target",
        dest="bg_target",
        default=None,
        help=(
            "Ziel-Hintergrund des Boards: 'complement' (Default, strikt 255−v) "
            "oder 'R,G,B' (jeweils 0–255), z.B. '255,255,255' = reinweiß."
        ),
    )
    parser.add_argument(
        "--keep-colors",
        dest="keep_colors",
        default=None,
        help=(
            "Markerfarben, die unverändert bleiben (kommaseparat aus "
            "red,green,blue,yellow; 'none' = alles invertieren). "
            "Default: red,green."
        ),
    )
    parser.add_argument(
        "--keep-hex",
        dest="keep_hex",
        default=None,
        help=(
            "Zusätzliche Farben/Farbbereiche (Hex) die unverändert bleiben, "
            "kommasepariert, z.B. 'FF0000, 00FF00, 000001-0000FF'. "
            "Leer = aus (Default)."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="Write per-page debug composites to <output dir>/debug/.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional JSON config file; CLI flags take precedence over config values.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase output verbosity (-v INFO, -vv DEBUG).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def parse_bg_target(value: str) -> Optional[Tuple[int, int, int]]:
    """Parse a ``--bg-target`` flag / config value (single choke point).

    ``"complement"`` (case-insensitive) → ``None`` (strict ``255 − v``);
    ``"R,G,B"`` (whitespace-tolerant) → 3-tuple of ints 0–255.  Anything
    else raises :class:`SmartboardError`.
    """
    text = str(value).strip()
    if text.lower() == "complement":
        return None
    parts = [p.strip() for p in text.split(",")]
    channels: List[int] = []
    for part in parts:
        # isascii() guards against Unicode digits (e.g. "²") for which
        # str.isdigit() is True but int() raises ValueError.
        if not (part.isascii() and part.isdigit()):
            raise SmartboardError(
                f"invalid --bg-target '{value}': expected 'complement' or "
                f"'R,G,B' with each channel an integer 0-255"
            )
        channel = int(part)
        if not 0 <= channel <= 255:
            raise SmartboardError(
                f"invalid --bg-target '{value}': each channel must be 0-255"
            )
        channels.append(channel)
    if len(channels) != 3:
        raise SmartboardError(
            f"invalid --bg-target '{value}': expected 'complement' or "
            f"'R,G,B' with exactly 3 channels"
        )
    return tuple(channels)


def parse_keep_colors(value: str) -> FrozenSet[str]:
    """Parse a ``--keep-colors`` flag / config value (single choke point).

    ``"none"`` → empty frozenset (everything gets transformed); otherwise a
    comma-separated subset of :data:`KEEPABLE_COLORS` (case-insensitive,
    whitespace-tolerant).  Unknown names raise :class:`SmartboardError`.
    """
    text = str(value).strip().lower()
    if text == "none":
        return frozenset()
    colors = frozenset(part.strip() for part in text.split(",") if part.strip())
    unknown = colors - KEEPABLE_COLORS
    if unknown:
        raise SmartboardError(
            f"invalid --keep-colors '{value}': unknown color(s) "
            f"{', '.join(sorted(unknown))} (allowed: "
            f"{', '.join(sorted(KEEPABLE_COLORS))} or 'none')"
        )
    return colors


#: One ``--keep-hex`` token: optional single leading ``#``, a 6- or 3-digit
#: hex colour, optionally followed by ``-`` and a second (range) endpoint.
#: The explicit ``[0-9A-Fa-f]`` classes also rule out Unicode digits.
_HEX3 = r"[0-9A-Fa-f]{3}"
_HEX6 = r"[0-9A-Fa-f]{6}"
_KEEP_HEX_TOKEN = re.compile(rf"^#?({_HEX6}|{_HEX3})(?:-({_HEX6}|{_HEX3}))?$")


def parse_keep_hex(value: str) -> Tuple[HexSegment, ...]:
    """Parse a ``--keep-hex`` flag / config value (single choke point).

    Empty string → ``()`` (feature off).  Otherwise a comma-separated list
    of colour specs (whitespace-tolerant, empty entries ignored):

    * ``RRGGBB`` — a single colour (``#`` prefix allowed),
    * ``RGB`` — 3-digit shorthand (each digit doubled, ``F00`` → ``FF0000``),
    * ``RRGGBB-RRGGBB`` (or shorthand endpoints) — a colour range; the
      endpoints are normalized to ascending order (they may be given in
      either order).

    The result is a tuple of user-facing RGB endpoint pairs (see
    :class:`~smartboard_invert.processing.HexSegment`).  Anything else
    raises :class:`SmartboardError`.
    """
    text = str(value).strip()
    if not text:
        return ()
    segments: List[HexSegment] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        match = _KEEP_HEX_TOKEN.match(token)
        if match is None:
            raise SmartboardError(
                f"invalid --keep-hex '{value}': expected 'RRGGBB' or "
                f"'RRGGBB-RRGGBB' (comma-separated; optional '#' prefix; "
                f"3-digit shorthand allowed)"
            )
        first, second = match.group(1), match.group(2)
        endpoints = [first, second] if second is not None else [first, first]
        values: List[Tuple[int, int, int]] = []
        for part in endpoints:
            if len(part) == 3:
                part = "".join(ch * 2 for ch in part)
            packed = int(part, 16)  # ASCII-only by the regex above
            values.append(((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF))
        if values[0] > values[1]:  # normalize: ascending endpoint order
            values.reverse()
        segments.append((values[0], values[1]))
    return tuple(segments)


#: Allowed config keys with their expected types (``null``/missing = default).
_CONFIG_TYPES: Dict[str, Any] = {
    "input": str,
    "output": str,
    "dpi": int,
    "invert": bool,
    "crop": bool,
    "debug": bool,
    "bg_target": str,
    "keep_colors": str,
    "keep_hex": str,
}


def load_config(path: Path) -> dict:
    """Load and validate a JSON configuration file."""
    if not path.is_file():
        raise SmartboardError(f"Config file not found: {path}")
    with path.open() as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise SmartboardError(f"Config file must contain a JSON object: {path}")
    for key, value in data.items():
        if key not in _CONFIG_TYPES:
            logger.debug("ignoring unknown config key: %s", key)
            continue
        if value is not None and not isinstance(value, _CONFIG_TYPES[key]):
            raise SmartboardError(
                f"config key '{key}' must be of type "
                f"{_CONFIG_TYPES[key].__name__} (got {type(value).__name__})"
            )
    return data


def resolve_options(args: argparse.Namespace, config: dict) -> dict:
    """Merge CLI flags, config file values and real defaults.

    Precedence: explicit CLI flag > config file > built-in default.  Because
    argparse flags use ``None`` sentinels, a missing flag is distinguishable
    from an explicit one.
    """
    resolved: Dict[str, Any] = {}
    for name in (
        "input",
        "output",
        "dpi",
        "invert",
        "crop",
        "debug",
        "bg_target",
        "keep_colors",
        "keep_hex",
    ):
        value = getattr(args, name)
        if value is None:
            value = config.get(name, REAL_DEFAULTS[name])
        resolved[name] = value
    return resolved


def _plan_jobs(
    input_path: Path,
    output_path: Optional[Path],
) -> List[Tuple[Path, Path]]:
    """Plan (input, output) file pairs from the CLI arguments."""
    if input_path.is_dir():
        pdfs = sorted(p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
        if not pdfs:
            raise SmartboardError(f"no PDF files found in input directory: {input_path}")
        if output_path is not None and output_path.exists() and output_path.is_file():
            raise SmartboardError("output must be a directory when the input is a directory")
        out_dir = (output_path if output_path is not None else Path("outputs")).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        return [(p, out_dir / p.name) for p in pdfs]

    if not input_path.is_file():
        raise SmartboardError(f"input PDF not found: {input_path}")
    if output_path is None:
        # Backward compatible single-file default: <stem>_inverted.pdf
        return [(input_path, input_path.with_name(input_path.stem + "_inverted.pdf"))]
    if output_path.is_dir():
        return [(input_path, output_path / input_path.name)]
    if output_path.exists() and output_path.is_file():
        return [(input_path, output_path)]
    # Not existing yet: ".pdf" suffix → file, otherwise directory.
    if output_path.suffix.lower() == ".pdf":
        return [(input_path, output_path)]
    return [(input_path, output_path / input_path.name)]


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging level.
    if args.verbose == 0:
        log_level = logging.WARNING
    elif args.verbose == 1:
        log_level = logging.INFO
    else:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format="[%(levelname)s] %(message)s")

    config: dict = {}
    if args.config is not None:
        try:
            config = load_config(args.config)
            logger.debug("Loaded config from %s", args.config)
        except SmartboardError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 1
        except (json.JSONDecodeError, OSError) as e:
            print(f"[ERROR] could not read config file: {e}", file=sys.stderr)
            return 1

    opts = resolve_options(args, config)
    input_path = Path(opts["input"]).expanduser().resolve()
    output_path = Path(opts["output"]).expanduser() if opts["output"] is not None else None

    # Parse the transformation options (same choke point for flag and config;
    # a JSON ``null`` falls back to the real default, like for other keys).
    try:
        bg_target = parse_bg_target(
            opts["bg_target"] if opts["bg_target"] is not None else REAL_DEFAULTS["bg_target"]
        )
        keep_colors = parse_keep_colors(
            opts["keep_colors"] if opts["keep_colors"] is not None else REAL_DEFAULTS["keep_colors"]
        )
        keep_hex = parse_keep_hex(
            opts["keep_hex"] if opts["keep_hex"] is not None else REAL_DEFAULTS["keep_hex"]
        )
    except SmartboardError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    try:
        jobs = _plan_jobs(input_path, output_path)
    except SmartboardError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    # Safety guard: never overwrite an input file.
    for src, dst in jobs:
        if src.resolve() == dst.resolve():
            print(f"[ERROR] refusing to overwrite the input file: {src}", file=sys.stderr)
            return 1

    debug_dir = None
    if opts["debug"]:
        debug_dir = jobs[0][1].parent / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for src, dst in jobs:
        logger.info("Processing %s -> %s", src, dst)
        try:
            result = process_pdf(
                src,
                dst,
                dpi=opts["dpi"],
                invert=bool(opts["invert"]),
                crop=bool(opts["crop"]),
                debug_dir=debug_dir,
                bg_target=bg_target,
                keep_colors=keep_colors,
                keep_segments=keep_hex,
            )
            logger.info("Done: %s", result.summary())
        except SmartboardError as exc:
            logger.error("Failed to process %s: %s", src, exc)
            failures += 1
        except Exception:  # unexpected errors must not crash the batch
            logger.exception("Unexpected error while processing %s", src)
            failures += 1

    if failures:
        logger.error("%d file(s) failed", failures)
        return 1
    # Success summary on stdout (independent of the log level).
    for _src, dst in jobs:
        print(f"OK  {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
