"""Smartboard Inversion Package

Detects the rectangular smartboard area inside each PDF page and inverts its
colours (``255 − v``) strictly inside that rectangle, leaving the surrounding
page untouched.

Public API:
    - :func:`detect_smartboard_region` / :class:`DetectionResult`
    - :func:`process_pdf` / :class:`ProcessResult` / :class:`PageResult`
    - :func:`pdf_to_images`, :func:`invert_region`,
      :func:`enhance_image` / :func:`enhance_image_ex`, :func:`images_to_pdf`
    - :class:`SmartboardError`
"""

from .detection import DetectionResult, Rect, detect_smartboard_region
from .pdfpipeline import PageResult, ProcessResult, process_pdf
from .processing import (
    SmartboardError,
    enhance_image,
    enhance_image_ex,
    images_to_pdf,
    invert_region,
    pdf_to_images,
)

__version__ = "0.4.1"  # keep in sync with the `version` in pyproject.toml

__all__ = [
    "DetectionResult",
    "Rect",
    "detect_smartboard_region",
    "PageResult",
    "ProcessResult",
    "process_pdf",
    "SmartboardError",
    "enhance_image",
    "enhance_image_ex",
    "images_to_pdf",
    "invert_region",
    "pdf_to_images",
    "__version__",
]
