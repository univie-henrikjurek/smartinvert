"""Command‑line interface for the Smartboard Inversion tool.

The CLI is thin – it parses arguments, forwards them to the core processing
functions and handles logging / error reporting.
"""

import argparse
import logging
import sys
from pathlib import Path

from . import processing
from .processing import SmartboardError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartboard-invert",
        description="Invert the inner whiteboard area of PDF pages using OpenCV and PyMuPDF.",
    )
    parser.add_argument("--input", "-i", required=True, help="Path to the input PDF.")
    parser.add_argument(
        "--output",
        "-o",
        required=False,
        help="Path for the output PDF. Defaults to <input>_inverted.pdf",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Rendering DPI for PDF → image conversion (default: 150).",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        default=True,
        help="Invert colours inside the detected region (default: enabled).",
    )
    parser.add_argument(
        "--no-invert",
        dest="invert",
        action="store_false",
        help="Disable colour inversion.",
    )
    parser.add_argument(
        "--clahe",
        action="store_true",
        default=True,
        help="Apply CLAHE contrast enhancement (default: enabled).",
    )
    parser.add_argument(
        "--no-clahe",
        dest="clahe",
        action="store_false",
        help="Disable CLAHE.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=True,
        help="Apply morphological cleaning to remove noise (default: enabled).",
    )
    parser.add_argument(
        "--no-clean",
        dest="clean",
        action="store_false",
        help="Disable morphological cleaning.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Optional JSON configuration file that can override the command‑line flags.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase output verbosity (can be used multiple times).",
    )
    return parser


def load_config(path: Path) -> dict:
    import json
    if not path.is_file():
        raise SmartboardError(f"Config file not found: {path}")
    with path.open() as fp:
        return json.load(fp)


def merge_args_with_config(args: argparse.Namespace, config: dict) -> dict:
    # Command‑line args take precedence over config values.
    merged = vars(args).copy()
    for key, value in config.items():
        if key not in merged or merged[key] is None:
            merged[key] = value
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging level.
    log_level = logging.WARNING
    if args.verbose == 1:
        log_level = logging.INFO
    elif args.verbose >= 2:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format="[%(levelname)s] %(message)s")

    # Load optional config file.
    if args.config:
        try:
            cfg = load_config(args.config)
            args_dict = merge_args_with_config(args, cfg)
        except SmartboardError as e:
            parser.error(str(e))
    else:
        args_dict = vars(args)

    input_path: Path = Path(args_dict["input"]).expanduser().resolve()
    output_path: Path = (
        Path(args_dict.get("output")).expanduser().resolve()
        if args_dict.get("output")
        else input_path.with_name(input_path.stem + "_inverted.pdf")
    )

    try:
        images = processing.pdf_to_images(input_path, dpi=args_dict["dpi"])
        processed = [
            processing.enhance_image(
                img,
                invert=args_dict["invert"],
                apply_clahe=args_dict["clahe"],
                clean=args_dict["clean"],
            )
            for img in images
        ]
        processing.images_to_pdf(processed, output_path)
    except SmartboardError as exc:
        logging.error("Processing failed: %s", exc)
        return 1
    except Exception as exc:  # unexpected errors
        logging.exception("Unexpected error")
        return 1

    logging.info("Successfully wrote %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
