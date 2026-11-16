"""Smartboard Inversion Package

Detects the rectangular smartboard area inside each PDF page and inverts its
colours strictly inside that rectangle, leaving the surrounding page
untouched.  By default the inversion is the strict complement (``255 − v``);
optionally the background can be remapped to a target colour (``bg_target``,
ADR 0002), selected marker colours (``keep_colors``) are preserved
unchanged, and explicit hex colours / ranges (``keep_segments``, ADR 0004)
are excluded from the inversion.

Public API:
    - :func:`detect_smartboard_region` / :class:`DetectionResult`
    - :func:`process_pdf` / :class:`ProcessResult` / :class:`PageResult`
    - :func:`pdf_to_images`, :func:`invert_region`,
      :func:`enhance_image` / :func:`enhance_image_ex`, :func:`images_to_pdf`
    - :func:`invert_or_remap`, :func:`color_mask`, :func:`hex_keep_mask`
      (core pixel operation)
    - :class:`SmartboardError`
"""

from .detection import DetectionResult, Rect, detect_smartboard_region
from .pdfpipeline import PageResult, ProcessResult, process_pdf
from .processing import (
    SmartboardError,
    color_mask,
    enhance_image,
    enhance_image_ex,
    hex_keep_mask,
    images_to_pdf,
    invert_or_remap,
    invert_region,
    pdf_to_images,
    validate_keep_segments,
)

__version__ = "0.6.0"  # keep in sync with the `version` in pyproject.toml

__all__ = [
    "DetectionResult",
    "Rect",
    "detect_smartboard_region",
    "PageResult",
    "ProcessResult",
    "process_pdf",
    "SmartboardError",
    "color_mask",
    "enhance_image",
    "enhance_image_ex",
    "hex_keep_mask",
    "images_to_pdf",
    "invert_or_remap",
    "invert_region",
    "pdf_to_images",
    "validate_keep_segments",
    "__version__",
]
