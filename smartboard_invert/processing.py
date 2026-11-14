"""Core processing utilities for the Smartboard Inversion tool.

Public functions:

1. ``pdf_to_images`` – rasterises each page of a PDF to a NumPy ``ndarray``.
2. ``invert_region`` – strict ``255 − v`` pixel inversion inside a rectangle.
3. ``enhance_image`` / ``enhance_image_ex`` – detect the smartboard area
   (via :mod:`smartboard_invert.detection`) and apply (optional CLAHE /
   cleaning /) inversion **only inside** it.
4. ``images_to_pdf`` – assembles a list of processed images into a PDF (pages
   sized to the images; used by the GUI preview and legacy flows – the main
   pipeline lives in :mod:`smartboard_invert.pdfpipeline`).

All functions raise ``SmartboardError`` (a thin subclass of ``Exception``) on
failure so that the CLI/GUI can present a clean error message.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

try:  # PyMuPDF >= 1.24 recommends the `pymupdf` import name
    import pymupdf as fitz
except ImportError:  # pragma: no cover - older PyMuPDF versions
    import fitz  # type: ignore

from .detection import Rect, detect_smartboard_region
from .detection import DetectionResult

logger = logging.getLogger(__name__)


class SmartboardError(Exception):
    """Custom exception type for all processing-related errors."""


def pdf_to_images(pdf_path: "str | Path", dpi: int = 150) -> List[np.ndarray]:
    """Render each page of *pdf_path* to a list of OpenCV images.

    Parameters
    ----------
    pdf_path:
        Path to the input PDF.
    dpi:
        Rendering resolution. Higher DPI yields larger images and slower
        processing.

    Returns
    -------
    List[np.ndarray]
        One ``uint8`` BGR image per page.

    Raises
    ------
    SmartboardError
        If the file cannot be opened, the DPI is out of range, or a page
        fails to render.
    """
    if not 20 <= int(dpi) <= 600:
        raise SmartboardError(f"dpi must be between 20 and 600 (got {dpi})")
    dpi = int(dpi)
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise SmartboardError(f"PDF file not found: {pdf_path}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise SmartboardError(f"Unable to open PDF {pdf_path}: {e}") from e

    images: List[np.ndarray] = []
    try:
        for page_number in range(doc.page_count):
            page = doc.load_page(page_number)
            # Zoom factor to achieve the required DPI (72 is the default DPI in MuPDF)
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            # Convert the pixmap to a NumPy array (BGR for OpenCV compatibility)
            img = np.frombuffer(pix.samples, dtype=np.uint8)
            img = img.reshape(pix.height, pix.width, 3)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            images.append(img)
            logger.debug(
                "Rendered page %d to image %dx%d",
                page_number + 1,
                pix.width,
                pix.height,
            )
    finally:
        doc.close()
    return images


def invert_region(img: np.ndarray, rect: Rect, pad: int = 0) -> np.ndarray:
    """Return a copy of *img* with only the pixels inside *rect* inverted.

    The inversion is the strict pixel transformation
    ``channel_new = 255 − channel_old`` for every channel, which naturally
    handles anti-aliasing, grey scales and colour marks.  Pixels outside the
    rectangle are copied unchanged.

    Parameters
    ----------
    img:
        ``uint8`` BGR image (3 channels).
    rect:
        ``(x0, y0, x1, y1)`` rectangle (x1/y1 exclusive); it is clamped to
        the image bounds.
    pad:
        Optional extra padding (pixels) around *rect*, clamped to the bounds.
    """
    if img is None or not isinstance(img, np.ndarray) or img.dtype != np.uint8:
        raise SmartboardError("invert_region expects a uint8 ndarray")
    if img.ndim != 3 or img.shape[2] != 3:
        raise SmartboardError("invert_region expects a BGR image with 3 channels")
    height, width = img.shape[:2]
    x0 = max(0, min(width, int(rect[0]) - pad))
    y0 = max(0, min(height, int(rect[1]) - pad))
    x1 = max(0, min(width, int(rect[2]) + pad))
    y1 = max(0, min(height, int(rect[3]) + pad))
    out = img.copy()
    if x1 > x0 and y1 > y0:
        # bitwise_not on uint8 is exactly 255 − v (no overflow, no rounding)
        out[y0:y1, x0:x1] = np.bitwise_not(out[y0:y1, x0:x1])
    return out


def _process_region(region: np.ndarray, apply_clahe: bool, clean: bool) -> np.ndarray:
    """Apply the optional (legacy) CLAHE / morphological cleaning to a region."""
    region = region.copy()
    if apply_clahe:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        region = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        logger.debug("Applied CLAHE inside detected region")
    if clean:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        region = cv2.morphologyEx(region, cv2.MORPH_OPEN, kernel, iterations=1)
        region = cv2.morphologyEx(region, cv2.MORPH_CLOSE, kernel, iterations=1)
        logger.debug("Applied morphological cleaning inside detected region")
    return region


def enhance_image_ex(
    img: np.ndarray,
    invert: bool = True,
    apply_clahe: bool = False,
    clean: bool = False,
) -> Tuple[np.ndarray, DetectionResult]:
    """Detect the smartboard area and enhance **only that region**.

    Pipeline: detect → (optional CLAHE) → (optional cleaning) → strict
    ``255 − v`` inversion – all limited to the detected rectangle.  When no
    unambiguous region is found the image is returned unchanged (a warning is
    logged).

    Returns
    -------
    (ndarray, DetectionResult)
        The processed image and the detection result (for logging/debug).
    """
    if img is None or not isinstance(img, np.ndarray) or img.dtype != np.uint8:
        raise SmartboardError("enhance_image_ex expects a uint8 ndarray")
    if img.ndim != 3 or img.shape[2] != 3:
        raise SmartboardError("enhance_image expects a BGR image with 3 channels")

    detection = detect_smartboard_region(img)
    if not detection.found:
        logger.warning(
            "No unambiguous smartboard region detected (%s) – image returned "
            "unchanged",
            detection.message,
        )
        return img.copy(), detection

    x0, y0, x1, y1 = detection.rect
    result = img.copy()
    region = result[y0:y1, x0:x1]
    region = _process_region(region, apply_clahe, clean)
    if invert:
        region = np.bitwise_not(region)
        logger.debug("Inverted colours inside detected region %s", detection.rect)
    result[y0:y1, x0:x1] = region
    return result, detection


def enhance_image(
    img: np.ndarray,
    invert: bool = True,
    apply_clahe: bool = False,
    clean: bool = False,
) -> np.ndarray:
    """Convenience wrapper around :func:`enhance_image_ex` (image only)."""
    result, _ = enhance_image_ex(img, invert=invert, apply_clahe=apply_clahe, clean=clean)
    return result


def images_to_pdf(images: List[np.ndarray], output_path: "str | Path") -> None:
    """Assemble a list of BGR images into a PDF file.

    Each page is created with the size of the corresponding image (pixels are
    used as points).  This helper is kept for the GUI preview / legacy flows;
    the main pipeline uses :func:`smartboard_invert.pdfpipeline.process_pdf`,
    which preserves the original page sizes.

    Parameters
    ----------
    images:
        Image list in the order they should appear in the PDF.
    output_path:
        Destination PDF file.
    """
    if not images:
        raise SmartboardError("No images supplied for PDF generation")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        for idx, img in enumerate(images):
            if img.ndim != 3 or img.shape[2] != 3:
                raise SmartboardError(f"Image at index {idx} is not a valid BGR image")
            height, width = img.shape[:2]
            # Create a new page with the same size as the image (points, 72 DPI).
            page = doc.new_page(width=width, height=height)
            # Encode the image to PNG bytes – PyMuPDF can embed directly.
            success, png_bytes = cv2.imencode(".png", img)
            if not success:
                raise SmartboardError(f"Failed to encode image {idx} to PNG")
            png_data = png_bytes.tobytes()
            rect = fitz.Rect(0, 0, width, height)
            page.insert_image(rect, stream=png_data)
            logger.debug("Inserted image %d into PDF", idx + 1)
        doc.save(str(output_path), garbage=3, deflate=True)
    finally:
        doc.close()
    logger.info("Saved processed PDF to %s", output_path)
