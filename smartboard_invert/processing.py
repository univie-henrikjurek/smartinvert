"""Core processing utilities for the Smartboard Inversion tool.

This module contains three public functions:

1. ``pdf_to_images`` – rasterises each page of a PDF to a NumPy ``ndarray``.
2. ``enhance_image`` – applies optional CLAHE, thresholding and colour inversion.
3. ``images_to_pdf`` – assembles a list of processed images back into a PDF.

All functions raise ``SmartboardError`` (a thin subclass of ``Exception``) on failure so that the CLI/GUI can present a clean error message.
"""

from __future__ import annotations

import logging
import io
from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class SmartboardError(Exception):
    """Custom exception type for all processing‑related errors."""


def pdf_to_images(pdf_path: str | Path, dpi: int = 150) -> List[np.ndarray]:
    """Render each page of *pdf_path* to a list of OpenCV images.

    Parameters
    ----------
    pdf_path: str | Path
        Path to the input PDF.
    dpi: int, optional
        Rendering resolution. Higher DPI yields larger images and slower processing.

    Returns
    -------
    List[np.ndarray]
        One ``uint8`` BGR image per page.

    Raises
    ------
    SmartboardError
        If the file cannot be opened or a page fails to render.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise SmartboardError(f"PDF file not found: {pdf_path}")

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise SmartboardError(f"Unable to open PDF {pdf_path}: {e}") from e

    images: List[np.ndarray] = []
    for page_number in range(doc.page_count):
        page = doc.load_page(page_number)
        # Zoom factor to achieve the required DPI (72 is the default DPI in MuPDF)
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.PDF_COLORSPACE_RGB)
        # Convert the pixmap to a NumPy array (BGR for OpenCV compatibility)
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img.reshape(pix.height, pix.width, 3)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        images.append(img)
        logger.debug("Rendered page %d to image %s ({}x{})", page_number + 1, pdf_path.name, pix.width, pix.height)
    return images


def enhance_image(
    img: np.ndarray,
    invert: bool = True,
    apply_clahe: bool = True,
    clean: bool = True,
) -> np.ndarray:
    """Apply the enhancement pipeline to a single image.

    Parameters
    ----------
    img: np.ndarray
        Input BGR image as produced by :func:`pdf_to_images`.
    invert: bool, default ``True``
        Whether to perform colour inversion (negative).
    apply_clahe: bool, default ``True``
        Apply CLAHE (Contrast Limited Adaptive Histogram Equalisation) on the
        grayscale version before thresholding. Helps when the original scan has
        uneven lighting.
    clean: bool, default ``True``
        Perform a morphological opening‑closing sequence to remove speckle noise.

    Returns
    -------
    np.ndarray
        Processed BGR image of the same shape as the input.
    """
    if img.ndim != 3 or img.shape[2] != 3:
        raise SmartboardError("enhance_image expects a BGR image with 3 channels")

    # Convert to grayscale – most whiteboard content is monochrome after rendering.
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    logger.debug("Converted to grayscale, shape=%s", gray.shape)

    # Optional CLAHE for contrast improvement.
    if apply_clahe:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        logger.debug("Applied CLAHE")

    # Adaptive threshold – we keep the image in grayscale for now; the final
    # step will re‑convert to BGR after optional inversion.
    # Use Otsu's method for a global threshold that works for most scans.
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    logger.debug("Applied Otsu threshold")

    # Optional morphological cleaning to remove small artifacts.
    if clean:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
        logger.debug("Performed morphological cleaning")

    # Inversion if requested – note that after threshold the image is binary, so
    # the negative simply flips black ↔ white.
    if invert:
        thresh = cv2.bitwise_not(thresh)
        logger.debug("Inverted colours")

    # Convert back to BGR so the output matches the input format expected by the
    # PDF assembly step.
    result = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
    return result


def images_to_pdf(images: List[np.ndarray], output_path: str | Path) -> None:
    """Assemble a list of BGR images into a PDF file.

    Parameters
    ----------
    images: List[np.ndarray]
        Image list in the order they should appear in the PDF.
    output_path: str | Path
        Destination PDF file.
    """
    if not images:
        raise SmartboardError("No images supplied for PDF generation")

    output_path = Path(output_path)
    doc = fitz.open()
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
    doc.save(str(output_path))
    doc.close()
    logger.info("Saved processed PDF to %s", output_path)
