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
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        # Convert the pixmap to a NumPy array (BGR for OpenCV compatibility)
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        img = img.reshape(pix.height, pix.width, 3)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        images.append(img)
        logger.debug("Rendered page %d to image %s ({}x{})", page_number + 1, pdf_path.name, pix.width, pix.height)
    return images


def _mask_dark_region(img: np.ndarray) -> np.ndarray | None:
    """Return a binary mask (uint8) where the dark whiteboard region is 255.

    The algorithm:
    1. Convert to grayscale.
    2. Apply Otsu threshold **on the original (non‑inverted) image** – this yields a
       binary image where the *dark* board becomes black (0) and the white margin
       becomes white (255).
    3. Invert the binary image so the board becomes white (255). This makes it
       easier to find the largest contour.
    4. Find external contours, keep the largest one that occupies a reasonable
       portion of the page (at least 5 % of total area) and is roughly rectangular.
    5. Create a mask filled with that contour (255 inside, 0 outside).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Step 2: Otsu threshold – dark board = 0, background = 255
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Step 3: Invert so the board becomes white (255)
    inv = cv2.bitwise_not(binary)
    # Find contours on the inverted image
    contours, _ = cv2.findContours(inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    img_area = img.shape[0] * img.shape[1]
    best_cnt = None
    best_area = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 0.05 * img_area:
            continue  # ignore tiny blobs
        # Approximate shape – we only need the largest contour, not strict rectangle
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if area > best_area:
            best_cnt = approx
            best_area = area
    if best_cnt is None:
        return None
    # Create mask
    mask = np.zeros_like(gray, dtype=np.uint8)
    cv2.drawContours(mask, [best_cnt], -1, 255, thickness=cv2.FILLED)
    logger.debug("Created mask for dark region (area %d)", best_area)
    return mask



def enhance_image(
    img: np.ndarray,
    invert: bool = True,
    apply_clahe: bool = True,
    clean: bool = True,
) -> np.ndarray:
    """Enhance a page image by inverting **only** the detected whiteboard region.

    Updated pipeline:
    1. Detect the rectangular whiteboard area.
    2. Extract that region from the original image.
    3. Optionally apply CLAHE, cleaning, and inversion **inside** the region.
    4. Paste the processed region back, leaving the surrounding margin untouched.
    """
    if img.ndim != 3 or img.shape[2] != 3:
        raise SmartboardError("enhance_image expects a BGR image with 3 channels")

    mask = _mask_dark_region(img)
    if mask is None:
        logger.warning("No dark region detected; returning original image unchanged")
        return img.copy()

    # Work on a copy to keep the original unchanged
    result = img.copy()
    # Extract the region using the mask
    region = cv2.bitwise_and(result, result, mask=mask)

    # Optional CLAHE inside the region (operate on grayscale then back to BGR)
    if apply_clahe:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        region = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        logger.debug("Applied CLAHE inside dark region")

    # Optional morphological cleaning inside the region
    if clean:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        region = cv2.morphologyEx(region, cv2.MORPH_OPEN, kernel, iterations=1)
        region = cv2.morphologyEx(region, cv2.MORPH_CLOSE, kernel, iterations=1)
        logger.debug("Applied morphological cleaning inside dark region")

    # Inversion inside the dark region
    if invert:
        region = 255 - region
        logger.debug("Inverted colours inside dark region")

    # Combine inverted region back, preserving original outside
    # Use mask to place only the changed pixels
    inv_mask = cv2.bitwise_not(mask)
    result = cv2.bitwise_and(result, result, mask=inv_mask)  # keep outer area
    result = cv2.add(result, region)  # add processed inner area
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
