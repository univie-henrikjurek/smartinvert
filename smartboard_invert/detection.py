"""Robust detection of the rectangular smartboard content area.

The smartboard area is a large, roughly rectangular region that is clearly
darker than the (usually white) page background.  A single dark glyph or a
small drawing must never trigger the detection, and an ambiguous situation
(several large dark regions) must lead to ``found = False`` instead of a
guessed rectangle.

Algorithm (see ADR 0001, D1):

1. Grayscale conversion + small Gaussian blur (suppresses anti-aliasing noise).
2. Background brightness estimate ``B = percentile(gray, 95)``.
3. Adaptive threshold ``T = min(Otsu(gray), B - 25)`` and dark mask
   ``gray < T``.
4. Morphological closing (kernel scaled to image size) to fill white text
   holes inside the board and to bridge thin anti-aliased gaps.
5. ``connectedComponentsWithStats`` (8-connectivity) followed by hard
   plausibility gates: minimum area, minimum bounding-box dimensions,
   rectangularity (extent), minimum margin to the image edge (page mode),
   contrast against the background, and uniqueness (no comparable second
   dark region).
6. Weighted confidence score; below the minimum the result is rejected.

The module is pure image analysis – no PDF handling in here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

#: Rectangle as ``(x0, y0, x1, y1)`` – x1/y1 exclusive.
Rect = Tuple[int, int, int, int]


@dataclass
class DetectionResult:
    """Outcome of :func:`detect_smartboard_region`."""

    found: bool
    rect: Optional[Rect] = None
    #: Confidence score in ``[0, 1]`` (0 when nothing was found).
    confidence: float = 0.0
    #: Threshold (grayscale value) used for the dark mask.
    threshold: int = 0
    #: Estimated background brightness (grayscale, 0-255).
    background_level: float = 0.0
    #: Statistics of the best candidates (for debugging / logging).
    candidates: List[dict] = field(default_factory=list)
    #: Human readable explanation (reason for acceptance or rejection).
    message: str = ""


def clamp_rect(rect: Rect, width: int, height: int) -> Rect:
    """Clamp *rect* into the image bounds ``(0, 0, width, height)``."""
    x0 = max(0, min(width, int(rect[0])))
    y0 = max(0, min(height, int(rect[1])))
    x1 = max(0, min(width, int(rect[2])))
    y1 = max(0, min(height, int(rect[3])))
    return (x0, y0, x1, y1)


def rect_overlap_fraction(rect_a: Rect, rect_b: Rect) -> float:
    """Fraction of *rect_a* that overlaps *rect_b* (0.0 .. 1.0)."""
    x0 = max(rect_a[0], rect_b[0])
    y0 = max(rect_a[1], rect_b[1])
    x1 = min(rect_a[2], rect_b[2])
    y1 = min(rect_a[3], rect_b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    overlap = (x1 - x0) * (y1 - y0)
    area_a = max(1, (rect_a[2] - rect_a[0]) * (rect_a[3] - rect_a[1]))
    return overlap / area_a


def _odd_kernel(value: int, minimum: int, maximum: int) -> int:
    """Round *value* to an odd integer clamped to ``[minimum, maximum]``."""
    k = max(minimum, min(maximum, value))
    if k % 2 == 0:
        k += 1
    return k


def detect_smartboard_region(
    img: np.ndarray,
    *,
    min_area_fraction: float = 0.01,
    min_dim_fraction: float = 0.04,
    min_extent: float = 0.85,
    min_confidence: float = 0.5,
    min_margin_fraction: float = 0.005,
    min_contrast: float = 60.0,
    ambiguity_ratio: float = 0.6,
    allow_full_coverage: bool = False,
) -> DetectionResult:
    """Detect the rectangular smartboard area in *img*.

    Parameters
    ----------
    img:
        BGR (or grayscale) ``uint8`` image, e.g. a rendered PDF page or an
        extracted image XObject.
    min_area_fraction:
        Minimum dark-area fraction of the whole image for a candidate.
    min_dim_fraction:
        Minimum bounding-box width/height relative to the image axes.
    min_extent:
        Minimum ``area / bbox_area`` (rectangularity) for a candidate.
    min_confidence:
        Minimum weighted confidence score for acceptance.
    min_margin_fraction:
        In page mode the rectangle must stay at least this fraction of the
        image size away from every edge (a "full page" detection is
        impossible by construction).
    min_contrast:
        The mean brightness inside the bbox must be at least this much below
        the estimated background brightness.
    ambiguity_ratio:
        A second candidate with an area of at least this fraction of the best
        candidate makes the detection ambiguous.
    allow_full_coverage:
        When ``False`` (page mode) rectangles touching the page edge or
        covering (almost) the whole image are rejected.  When ``True``
        (native image mode) a board covering the whole image is accepted –
        the image itself is the board.

    Returns
    -------
    DetectionResult
        ``found`` is ``True`` only when exactly one plausible rectangular
        dark region was found with sufficient confidence.
    """
    if img is None or not isinstance(img, np.ndarray) or img.dtype != np.uint8:
        return _reject("image must be a uint8 ndarray")
    if img.ndim == 2:
        gray = img
    elif img.ndim == 3 and img.shape[2] == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    elif img.ndim == 3 and img.shape[2] == 4:
        gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    else:
        return _reject(f"unsupported image shape {img.shape}")
    h, w = gray.shape[:2]
    if w < 32 or h < 32:
        return _reject(f"image too small for detection ({w}x{h})")

    # -- Step 1: blur (kernel scaled to image size, keeps AA noise down) ----
    blur_k = _odd_kernel(2 * max(2, min(w, h) // 200) + 1, 3, 15)
    blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)

    # -- Step 2: background brightness --------------------------------------
    background = float(np.percentile(blurred, 95))
    if not allow_full_coverage and background < 200.0:
        return _reject(
            f"page background is not light (p95={background:.0f}); "
            "refusing to guess an inversion area",
            threshold=0,
            background=background,
        )
    if allow_full_coverage and background < 200.0:
        # Image mode: the image itself is mostly dark (e.g. the board covers
        # the whole image, possibly with sparse light content).  In that case
        # the board *is* the image – invert the whole image.
        median = float(np.percentile(blurred, 50))
        dark_share = float((blurred < 128).mean())
        if median < 128.0 and dark_share > 0.80:
            result = DetectionResult(
                found=True,
                rect=(0, 0, w, h),
                confidence=0.75,
                threshold=128,
                background_level=background,
                candidates=[{"bbox": (0, 0, w, h), "area": w * h,
                             "area_fraction": 1.0, "extent": 1.0}],
                message="board image is dark over its whole area – inverting the whole image",
            )
            logger.debug("%s", result.message)
            return result

    # -- Step 3: adaptive threshold -----------------------------------------
    # Background-relative adaptive threshold:  T = B − max(30, 0.25·(B − p25)).
    # The 25th percentile is a robust estimate of the (dark) board brightness;
    # the 30-level floor keeps ordinary black text/markings on a white page
    # "dark" while a board must be clearly darker than the background.  This
    # is deterministic and – unlike cv2 Otsu (which degenerates on strictly
    # bimodal histograms, e.g. OpenCV ≥ 5) – stable for flat-colour boards.
    low = float(np.percentile(blurred, 25))
    delta = max(30.0, 0.25 * (background - low))
    threshold = int(max(10, min(250, background - delta)))
    dark = (blurred < threshold).astype(np.uint8)
    # Unblurred dark mask – used later to refine the bounding box, so that the
    # blur halo (a few px of margin pulled into the threshold) does not
    # enlarge the detected rectangle.
    raw_dark = gray < threshold
    if dark.sum() == 0:
        return _reject("no dark pixels found", threshold, background)

    # -- Step 4: close (fill text holes / bridge gaps) -----------------------
    close_k = _odd_kernel(2 * max(3, min(w, h) // 120) + 1, 7, 31)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_k, close_k))
    closed = cv2.morphologyEx(dark * 255, cv2.MORPH_CLOSE, kernel)

    # -- Step 5: connected components + plausibility gates -------------------
    n_comp, labels, stats, _cent = cv2.connectedComponentsWithStats(closed, connectivity=8)
    candidates: List[dict] = []
    for label in range(1, n_comp):
        area = int(stats[label, cv2.CC_STAT_AREA])
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        bw = int(stats[label, cv2.CC_STAT_WIDTH])
        bh = int(stats[label, cv2.CC_STAT_HEIGHT])
        if area < min_area_fraction * w * h:
            continue
        if bw < min_dim_fraction * w or bh < min_dim_fraction * h:
            continue
        extent = area / float(max(1, bw * bh))
        if extent < min_extent:
            continue
        if not allow_full_coverage:
            margin = min_margin_fraction
            if (
                left < margin * w
                or top < margin * h
                or (left + bw) > (1 - margin) * w
                or (top + bh) > (1 - margin) * h
            ):
                continue  # touches the page edge – never invert "the whole page"
        candidates.append(
            {
                "label": label,
                "bbox": (left, top, left + bw, top + bh),
                "area": area,
                "area_fraction": area / float(w * h),
                "extent": extent,
            }
        )

    candidates.sort(key=lambda c: c["area"], reverse=True)
    for cand in candidates[:5]:
        logger.debug("candidate: %s", cand)
    if not candidates:
        return _reject(
            "no sufficiently large, rectangular dark region found",
            threshold,
            background,
        )

    # -- Uniqueness -----------------------------------------------------------
    best = candidates[0]
    if len(candidates) > 1 and candidates[1]["area"] >= ambiguity_ratio * best["area"]:
        return _reject(
            "multiple dark regions of comparable size – not unambiguous",
            threshold,
            background,
            candidates[:5],
        )

    # -- Contrast check --------------------------------------------------------
    x0, y0, x1, y1 = best["bbox"]
    inner_mean = float(blurred[y0:y1, x0:x1].mean())
    if inner_mean > background - min_contrast:
        return _reject(
            f"contrast to background too low (inner={inner_mean:.0f}, "
            f"background={background:.0f})",
            threshold,
            background,
            candidates[:5],
        )

    # -- Confidence ------------------------------------------------------------
    extent_c = min(1.0, max(0.0, (best["extent"] - min_extent) / (1.0 - min_extent)))
    a = best["area_fraction"]
    if 0.05 <= a <= 0.90:
        area_c = 1.0
    elif a < 0.05:
        area_c = a / 0.05
    else:
        area_c = max(0.0, (1.0 - a) / 0.10)
    contrast_c = min(1.0, max(0.0, (background - inner_mean) / max(1.0, background)))
    if allow_full_coverage:
        margin_c = 1.0
    else:
        margin_px = min(x0, y0, w - x1, h - y1)
        margin_c = min(1.0, margin_px / (0.02 * min(w, h)))
    confidence = 0.30 * extent_c + 0.20 * area_c + 0.30 * contrast_c + 0.20 * margin_c

    if confidence < min_confidence:
        return _reject(
            f"confidence too low ({confidence:.2f} < {min_confidence:.2f})",
            threshold,
            background,
            candidates[:5],
        )

    # -- Bounding-box refinement ------------------------------------------------
    # The blur (step 1) smears the board edge a few pixels into the white
    # margin, so the closed-mask bbox can be slightly larger than the true
    # dark area.  Recompute the bbox from the *unblurred* dark pixels of the
    # winning component so the rectangle does not grow into the margin.
    rect = _refine_bbox(raw_dark, labels, int(best["label"]), best["bbox"])

    result = DetectionResult(
        found=True,
        rect=tuple(int(v) for v in rect),
        confidence=float(confidence),
        threshold=threshold,
        background_level=background,
        candidates=candidates[:5],
        message=(
            f"smartboard region detected: bbox={rect}, "
            f"area={a:.1%}, extent={best['extent']:.2f}, "
            f"confidence={confidence:.2f}"
        ),
    )
    logger.debug("%s", result.message)
    return result


def _refine_bbox(
    raw_dark: np.ndarray,
    labels: np.ndarray,
    label: int,
    bbox: Rect,
    tolerance: int = 2,
) -> Rect:
    """Refine *bbox* using the unblurred dark mask of component *label*.

    Falls back to *bbox* when the component has no unblurred dark pixels or
    the refined box deviates by more than *tolerance* pixels (plausibility
    guard).
    """
    mask = raw_dark & (labels == label)
    if not mask.any():
        return bbox
    ys, xs = np.nonzero(mask)
    refined = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    cx0, cy0, cx1, cy1 = bbox
    if (
        cx0 - tolerance <= refined[0] <= cx0 + tolerance
        and cy0 - tolerance <= refined[1] <= cy0 + tolerance
        and cx1 - tolerance <= refined[2] <= cx1 + tolerance
        and cy1 - tolerance <= refined[3] <= cy1 + tolerance
    ):
        return refined
    return bbox


def _reject(
    message: str,
    threshold: int = 0,
    background: float = 0.0,
    candidates: Optional[List[dict]] = None,
) -> DetectionResult:
    logger.warning("detection failed: %s", message)
    return DetectionResult(
        found=False,
        confidence=0.0,
        threshold=threshold,
        background_level=background,
        candidates=candidates or [],
        message=message,
    )
