"""Core processing utilities for the Smartboard Inversion tool.

Public functions:

1. ``pdf_to_images`` – rasterises each page of a PDF to a NumPy ``ndarray``.
2. ``color_mask`` – boolean mask of pixels matching the requested marker
   colours (BGR, see :data:`KEEPABLE_COLORS`).
3. ``hex_keep_mask`` – boolean mask of pixels excluded via explicit hex
   colours / ranges (user-facing RGB, see ADR 0004).
4. ``validate_bg_target`` / ``validate_keep_segments`` – central validation
   choke points for the public API options.
5. ``invert_or_remap`` – the single in-region pixel operation: strict
   ``255 − v`` (default) or a linear per-channel remap onto a target
   background colour, with optional exclusion of marker colours and hex
   specs.
6. ``invert_region`` – applies the in-region pixel operation inside a
   rectangle (strict ``255 − v`` by default).
7. ``enhance_image`` / ``enhance_image_ex`` – detect the smartboard area
   (via :mod:`smartboard_invert.detection`) and apply (optional CLAHE /
   cleaning /) inversion or target-background remap **only inside** it.
8. ``images_to_pdf`` – assembles a list of processed images into a PDF (pages
   sized to the images; used by the GUI preview and legacy flows – the main
   pipeline lives in :mod:`smartboard_invert.pdfpipeline`).

All functions raise ``SmartboardError`` (a thin subclass of ``Exception``) on
failure so that the CLI/GUI can present a clean error message.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import AbstractSet, FrozenSet, List, Optional, Tuple

import cv2
import numpy as np

try:  # PyMuPDF >= 1.24 recommends the `pymupdf` import name
    import pymupdf as fitz
except ImportError:  # pragma: no cover - older PyMuPDF versions
    import fitz  # type: ignore

from .detection import Rect, detect_smartboard_region
from .detection import DetectionResult

logger = logging.getLogger(__name__)

#: Marker colours that may be preserved (excluded from the inversion/remap)
#: via the ``keep_colors`` option.  Unknown names are rejected with
#: :class:`SmartboardError` (see :func:`color_mask`).
KEEPABLE_COLORS: FrozenSet[str] = frozenset({"red", "green", "blue", "yellow"})

#: Minimum channel dominance for a pixel to count as a marker of a colour
#: (well above screenshot noise ≤ 10, well below real marker differences ≥ 100).
COLOR_DELTA: int = 40

#: Minimum value of the dominant channel (well above dark board noise ≤ 60,
#: well below saturated markers ≥ 150).
COLOR_MIN: int = 80

#: Maximum euclidean distance in RGB space between a pixel and a hex
#: segment/point for the pixel to be excluded from the transformation
#: (ADR 0004, D2).  Above scan/render noise, below the distance to any
#: other marker colour.
HEX_TOL: float = 50.0

#: Minimum pixel chroma (``max(channel) − min(channel)``) for a pixel to be
#: excluded via a hex spec (ADR 0004, D2).  Keeps neutral grays — in
#: particular the dark board background — out of ranges that start near the
#: RGB origin (e.g. ``000001-0000FF``).
HEX_MIN_CHROMA: int = 24

#: A single user-facing RGB colour (ints 0–255).
RGBTriple = Tuple[int, int, int]
#: One ``--keep-hex`` spec: a segment ``((r1, g1, b1), (r2, g2, b2))`` in
#: user-facing **RGB** order; ``a == b`` denotes a single colour.  A keep
#: list is a ``Tuple[HexSegment, ...]`` (empty = feature off).
HexSegment = Tuple[RGBTriple, RGBTriple]


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


def color_mask(region: np.ndarray, colors: AbstractSet[str]) -> np.ndarray:
    """Boolean mask of the pixels in *region* matching any of *colors*.

    A pixel counts as a marker of a colour when its dominant channel exceeds
    the other channels by at least :data:`COLOR_DELTA` **and** reaches
    :data:`COLOR_MIN` (see ADR 0002, D2):

    * ``red``:    ``R > G + Δ`` ∧ ``R > B + Δ`` ∧ ``R ≥ R_min``
    * ``green``:  ``G > R + Δ`` ∧ ``G > B + Δ`` ∧ ``G ≥ R_min``
    * ``blue``:   ``B > R + Δ`` ∧ ``B > G + Δ`` ∧ ``B ≥ R_min``
    * ``yellow``: ``R > B + Δ`` ∧ ``G > B + Δ`` ∧ ``R, G ≥ R_min``

    The result is the OR over all requested colours, so white chalk
    (R ≈ G ≈ B) and dark noise never match.  Channels are compared as
    ``int16`` to avoid uint8 overflow.

    Parameters
    ----------
    region:
        ``uint8`` BGR image (3 channels; internally channel 0 = B, 1 = G,
        2 = R).
    colors:
        Subset of :data:`KEEPABLE_COLORS`; any unknown name raises
        :class:`SmartboardError`.

    Returns
    -------
    np.ndarray
        Boolean mask of shape ``(H, W)``.
    """
    if region is None or not isinstance(region, np.ndarray) or region.dtype != np.uint8:
        raise SmartboardError("color_mask expects a uint8 ndarray")
    if region.ndim != 3 or region.shape[2] != 3:
        raise SmartboardError("color_mask expects a BGR image with 3 channels")
    unknown = set(colors) - KEEPABLE_COLORS
    if unknown:
        raise SmartboardError(
            f"unknown color(s) in keep_colors: {', '.join(sorted(unknown))} "
            f"(allowed: {', '.join(sorted(KEEPABLE_COLORS))})"
        )
    # BGR order; int16 so that e.g. ``r - b`` cannot overflow.
    b = region[..., 0].astype(np.int16)
    g = region[..., 1].astype(np.int16)
    r = region[..., 2].astype(np.int16)
    delta = COLOR_DELTA
    mask = np.zeros(region.shape[:2], dtype=bool)
    if "red" in colors:
        mask |= (r > g + delta) & (r > b + delta) & (r >= COLOR_MIN)
    if "green" in colors:
        mask |= (g > r + delta) & (g > b + delta) & (g >= COLOR_MIN)
    if "blue" in colors:
        mask |= (b > r + delta) & (b > g + delta) & (b >= COLOR_MIN)
    if "yellow" in colors:
        mask |= (r > b + delta) & (g > b + delta) & (r >= COLOR_MIN) & (g >= COLOR_MIN)
    return mask


def hex_keep_mask(region: np.ndarray, segments: "Tuple[HexSegment, ...]") -> np.ndarray:
    """Boolean mask of the pixels in *region* excluded by the hex specs.

    A pixel is excluded (i.e. it keeps its original values during the
    transformation) when **both** hold (ADR 0004, D2):

    1. **Distance** — its euclidean distance to the segment ``[a, b]`` in
       RGB space is ≤ :data:`HEX_TOL` (``a == b``: distance to the point).
    2. **Chroma guard** — ``max(channel) − min(channel)`` is ≥
       :data:`HEX_MIN_CHROMA`.  This keeps neutral grays — in particular the
       dark board background — out of ranges that start near the RGB origin
       (e.g. ``000001-0000FF``).  Documented caveat: nearly invisible
       extreme values (e.g. RGB ``(0, 0, 8)``, chroma 8 < 24) are
       deliberately **not** excluded, and neutral gray "marker" ranges are
       not supported.

    The result is the OR over all segments.

    Parameters
    ----------
    region:
        ``uint8`` BGR image (3 channels; internally channel 0 = B, 1 = G,
        2 = R).
    segments:
        ``--keep-hex`` specs as validated by
        :func:`validate_keep_segments`: pairs of user-facing **RGB**
        endpoints (``a == b`` = single colour).  The endpoints are swapped
        to BGR internally — the distance math itself is channel-agnostic.
        Empty = all-False mask (feature off).

    Returns
    -------
    np.ndarray
        Boolean mask of shape ``(H, W)``.
    """
    if region is None or not isinstance(region, np.ndarray) or region.dtype != np.uint8:
        raise SmartboardError("hex_keep_mask expects a uint8 ndarray")
    if region.ndim != 3 or region.shape[2] != 3:
        raise SmartboardError("hex_keep_mask expects a BGR image with 3 channels")
    segments = validate_keep_segments(segments)
    mask = np.zeros(region.shape[:2], dtype=bool)
    if not segments:
        return mask
    # Internal arrays are BGR; the user-facing specs are RGB.  Swap the
    # endpoint channel order so the distance math below is channel-agnostic.
    p = region.astype(np.float32)
    tol2 = HEX_TOL * HEX_TOL
    for a, b in segments:
        a_bgr = np.array([a[2], a[1], a[0]], dtype=np.float32)
        b_bgr = np.array([b[2], b[1], b[0]], dtype=np.float32)
        d = b_bgr - a_bgr
        len2 = float(d @ d)
        if len2 == 0.0:
            # Single colour: euclidean distance to the point.
            diff = p - a_bgr
        else:
            # Closest point of the segment [a, b] to each pixel.
            t = np.clip(((p - a_bgr) * d).sum(axis=2) / len2, 0.0, 1.0)
            diff = p - (a_bgr + t[..., None] * d)
        mask |= (diff * diff).sum(axis=2) <= tol2
    # Chroma guard on the union (int16 to avoid uint8 wrap-around).
    chroma = region.max(axis=2).astype(np.int16) - region.min(axis=2).astype(np.int16)
    mask &= chroma >= HEX_MIN_CHROMA
    return mask


def validate_keep_segments(segments: "Tuple[HexSegment, ...] | None") -> "Tuple[HexSegment, ...]":
    """Validate hex keep-specs and return them as normalized tuples.

    Central choke point (analogous to :func:`validate_bg_target`) for the
    public API and ``process_pdf``.  Each entry must be a pair of RGB
    endpoints ``((r1, g1, b1), (r2, g2, b2))`` — tuples or lists — with all
    channels ints 0–255 (booleans rejected); ``a == b`` denotes a single
    colour.  ``None`` is rejected (use an empty tuple for "no hex specs").
    The endpoint order within a pair and the order of the pairs are
    preserved as given (endpoint order is semantically irrelevant for
    matching).
    """
    if segments is None:
        raise SmartboardError(
            "keep_segments must be a tuple of (a, b) RGB endpoint pairs — "
            "use an empty tuple for 'no hex specs', not None"
        )
    try:
        raw = list(segments)
    except TypeError:
        raise SmartboardError(
            "keep_segments must be an iterable of (a, b) RGB endpoint pairs "
            f"(got {type(segments).__name__})"
        )
    normalized: List[HexSegment] = []
    for idx, pair in enumerate(raw):
        try:
            length = len(pair)
        except TypeError:
            length = -1  # not indexable at all (e.g. an int)
        if length != 2:
            raise SmartboardError(
                f"keep_segments[{idx}] must be a pair of RGB endpoints "
                f"((r1, g1, b1), (r2, g2, b2)), got {pair!r}"
            )
        endpoints = [pair[0], pair[1]]
        channel_tuples: List[Tuple[int, int, int]] = []
        for endpoint in endpoints:
            try:
                channels = tuple(endpoint)
            except TypeError:
                channels = ()
            if len(channels) != 3 or any(
                isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255
                for v in channels
            ):
                raise SmartboardError(
                    f"keep_segments[{idx}] has an invalid RGB endpoint "
                    f"{endpoint!r}: expected a 3-tuple of ints 0-255"
                )
            channel_tuples.append(channels)
        normalized.append((channel_tuples[0], channel_tuples[1]))
    return tuple(normalized)


def validate_bg_target(bg_target: Optional[Tuple[int, int, int]]) -> Optional[Tuple[int, int, int]]:
    """Validate a user-facing ``bg_target`` and return it as a normalized tuple.

    ``None`` (the strict ``255 − v`` complement) passes through.  Anything
    else must be exactly 3 ints in 0–255 (lists are accepted and converted,
    booleans are rejected); otherwise :class:`SmartboardError` is raised.
    Single choke point for the public API and for ``process_pdf``.
    """
    if bg_target is None:
        return None
    try:
        channels = tuple(bg_target)
    except TypeError:
        channels = ()
    if len(channels) != 3 or any(
        isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255
        for v in channels
    ):
        raise SmartboardError(
            f"bg_target must be a 3-tuple (R, G, B) of ints 0-255 "
            f"(got {bg_target!r})"
        )
    return channels


def invert_or_remap(
    region: np.ndarray,
    original: Optional[np.ndarray] = None,
    *,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> np.ndarray:
    """Apply the in-region pixel operation to *region* (see ADR 0002, D1/D2).

    Semantics:

    * ``bg_target is None`` → strict ``255 − v`` (``np.bitwise_not``),
      bit-identical to v0.4.1.
    * ``bg_target = (R, G, B)`` (user-facing **RGB**) → linear per-channel
      remap ``v' = T_c · (255 − v) / (255 − B_c)`` where ``B_c`` is the p25
      of channel c in *region* (i.e. after any optional CLAHE/cleaning),
      clamped to ``[0, 220]`` so the denominator stays ≥ 35.  Computed in
      float32 with round-half-up, clipped to 0–255.  Anchors: ``v = B_c →
      T_c`` (the board background lands exactly on the target colour) and
      ``v = 255 → 0`` (white stays black).
    * ``keep_colors`` → pixels matching any of the requested marker colours
      keep their **original** values.
    * ``keep_segments`` → pixels matching any of the explicit hex colours /
      ranges (see :func:`hex_keep_mask`, ADR 0004) keep their **original**
      values.
      The exclusion mask is the union of both, computed on *original*
      (default: *region*, i.e. before any pre-processing) and applied
      **last** — it takes precedence over both complement and remap.  An
      empty ``keep_segments`` (the default) adds no overhead.

    Parameters
    ----------
    region:
        ``uint8`` BGR image (3 channels) to transform.
    original:
        Original (pre-CLAHE/clean) version of *region* used for the
        keep-colour exclusion; must have the same shape (defaults to
        *region*).
    bg_target:
        Target background as ``(R, G, B)`` ints 0–255, or ``None`` for the
        strict ``255 − v`` complement.
    keep_colors:
        Subset of :data:`KEEPABLE_COLORS` to exclude from the transformation.
    keep_segments:
        Explicit hex colours / ranges (pairs of user-facing RGB endpoints,
        see :func:`hex_keep_mask`) to exclude from the transformation.
        Default empty = v0.5.0 behaviour (bit-identical).

    Returns
    -------
    np.ndarray
        Transformed ``uint8`` BGR image, same shape as *region*.
    """
    if region is None or not isinstance(region, np.ndarray) or region.dtype != np.uint8:
        raise SmartboardError("invert_or_remap expects a uint8 ndarray")
    if region.ndim != 3 or region.shape[2] != 3:
        raise SmartboardError("invert_or_remap expects a BGR image with 3 channels")
    orig = region if original is None else original
    if original is not None and (
        orig is None
        or not isinstance(orig, np.ndarray)
        or orig.dtype != np.uint8
        or orig.shape != region.shape
    ):
        raise SmartboardError(
            "original must be a uint8 BGR ndarray with the same shape as region"
        )
    bg_target = validate_bg_target(bg_target)
    # Normalize/validate up front (analogous to bg_target): this also makes
    # invalid specs (incl. None) fail fast in the public API.
    keep_segments = validate_keep_segments(keep_segments)
    if bg_target is None:
        # The legacy path: bitwise_not on uint8 is exactly 255 − v (no
        # overflow, no rounding) and must stay bit-identical to v0.4.1.
        transformed = np.bitwise_not(region)
    else:
        # p25 per channel of the remap input (BGR order), clamped so that
        # the denominator 255 − B_c never degenerates (≥ 35).
        b = np.clip(np.percentile(region, 25, axis=(0, 1)), 0.0, 220.0).astype(np.float32)
        # bg_target is user-facing RGB, internal arrays are BGR.
        t = np.array([bg_target[2], bg_target[1], bg_target[0]], dtype=np.float32)
        scale = t / (255.0 - b)
        # round-half-up: floor(x + 0.5) (x ≥ 0 here).
        transformed = np.clip(
            np.floor((255.0 - region.astype(np.float32)) * scale + 0.5), 0, 255
        ).astype(np.uint8)
    if keep_colors or keep_segments:
        # Exclusion is the LAST step: kept pixels get their original values,
        # taking precedence over complement and remap.
        m = np.zeros(region.shape[:2], dtype=bool)
        if keep_colors:
            m |= color_mask(orig, keep_colors)
        if keep_segments:
            m |= hex_keep_mask(orig, keep_segments)
        transformed = np.where(m[..., None], orig, transformed)
    return transformed


def invert_region(
    img: np.ndarray,
    rect: Rect,
    pad: int = 0,
    *,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> np.ndarray:
    """Return a copy of *img* with only the pixels inside *rect* transformed.

    The default transformation is the strict pixel inversion
    ``channel_new = 255 − channel_old`` for every channel, which naturally
    handles anti-aliasing, grey scales and colour marks.  With
    *bg_target*/*keep_colors* the in-region operation is
    :func:`invert_or_remap` (target-background remap and/or preserved marker
    colours) instead.  Pixels outside the rectangle are copied unchanged.

    Parameters
    ----------
    img:
        ``uint8`` BGR image (3 channels).
    rect:
        ``(x0, y0, x1, y1)`` rectangle (x1/y1 exclusive); it is clamped to
        the image bounds.
    pad:
        Optional extra padding (pixels) around *rect*, clamped to the bounds.
    bg_target:
        Target background ``(R, G, B)`` (0–255) or ``None`` for the strict
        ``255 − v`` complement (default).
    keep_colors:
        Marker colours to exclude from the transformation (see
        :func:`invert_or_remap`).
    keep_segments:
        Explicit hex colours / ranges to exclude from the transformation
        (see :func:`invert_or_remap`).
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
        # original == region here (no pre-processing), so no `original` needed
        out[y0:y1, x0:x1] = invert_or_remap(
            out[y0:y1, x0:x1],
            bg_target=bg_target,
            keep_colors=keep_colors,
            keep_segments=keep_segments,
        )
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
    *,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> Tuple[np.ndarray, DetectionResult]:
    """Detect the smartboard area and enhance **only that region**.

    Pipeline: detect → (optional CLAHE) → (optional cleaning) → strict
    ``255 − v`` inversion or target-background remap (:func:`invert_or_remap`)
    – all limited to the detected rectangle.  When no unambiguous region is
    found the image is returned unchanged (a warning is logged).

    Parameters
    ----------
    img:
        ``uint8`` BGR image (3 channels).
    invert:
        Apply the in-region transformation (default: on).
    apply_clahe / clean:
        Optional (legacy) pre-processing inside the region.
    bg_target:
        Target background ``(R, G, B)`` (0–255) for a linear per-channel
        remap, or ``None`` for the strict ``255 − v`` complement (default).
    keep_colors:
        Marker colours to exclude from the transformation (their original
        pixels are kept; see :func:`invert_or_remap`).
    keep_segments:
        Explicit hex colours / ranges to exclude from the transformation
        (their original pixels are kept; see :func:`invert_or_remap`).

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
    # The keep-colour exclusion must be computed on the original (pre-CLAHE/
    # clean) pixels.
    region_orig = region.copy() if invert else None
    region = _process_region(region, apply_clahe, clean)
    if invert:
        region = invert_or_remap(
            region,
            original=region_orig,
            bg_target=bg_target,
            keep_colors=keep_colors,
            keep_segments=keep_segments,
        )
        logger.debug("Inverted colours inside detected region %s", detection.rect)
    result[y0:y1, x0:x1] = region
    return result, detection


def enhance_image(
    img: np.ndarray,
    invert: bool = True,
    apply_clahe: bool = False,
    clean: bool = False,
    *,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> np.ndarray:
    """Convenience wrapper around :func:`enhance_image_ex` (image only)."""
    result, _ = enhance_image_ex(
        img,
        invert=invert,
        apply_clahe=apply_clahe,
        clean=clean,
        bg_target=bg_target,
        keep_colors=keep_colors,
        keep_segments=keep_segments,
    )
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
