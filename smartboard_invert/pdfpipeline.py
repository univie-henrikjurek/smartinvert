"""High-level PDF pipeline: detect + selective inversion + page-faithful output.

:func:`process_pdf` opens an input PDF, analyses every page independently
(detection on the rendered page, optionally a second detection on the native
board image) and writes a new PDF in which:

* the original page sizes (MediaBox) and page order are preserved,
* the white margin / everything outside the detected rectangle is unchanged,
* the detected smartboard rectangle is inverted strictly inside its original
  position (never moved, never cropped).

With ``crop=True`` a final post-stage re-wraps the document so every page
with a detected board is sized to exactly that rectangle (ADR 0003); pages
without a board keep their full size.

Three output methods exist per page (see ADR 0001, D2):

``copy``
    No region detected – the page is copied losslessly (``show_pdf_page``).
``image-replace``
    The board is an image XObject – the image is extracted, inverted inside
    the detected rectangle, re-encoded losslessly (PNG) and replaced in place.
``rerasterize``
    No suitable image XObject (e.g. vector content) – the page is rendered,
    inverted inside the rectangle and re-embedded at the **original** page
    size.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import AbstractSet, Callable, List, Optional, Tuple

import cv2
import numpy as np

from . import processing
from .detection import DetectionResult, Rect, clamp_rect, detect_smartboard_region, rect_overlap_fraction
from .processing import HexSegment, KEEPABLE_COLORS, SmartboardError, fitz

logger = logging.getLogger(__name__)

#: Progress callback: ``(page_number_1based, total_pages)`` after each page.
ProgressCallback = Callable[[int, int], None]


@dataclass
class PageResult:
    """Outcome of processing one page."""

    page_index: int  # 0-based
    detected: bool
    #: "copy" | "image-replace" | "rerasterize"
    method: str = "copy"
    #: Detected rectangle in render (pixel) coordinates at the used DPI.
    rect_px: Optional[Rect] = None
    #: Detected rectangle in page (point) coordinates.
    rect_pt: Optional[Tuple[float, float, float, float]] = None
    confidence: float = 0.0
    message: str = ""
    #: Verification numbers (outside_max_diff / outside_mean_diff /
    #: inside_mean_diff / max_diff) – see ADR 0001, D3.
    verification: dict = field(default_factory=dict)
    #: True if the optional crop post-stage (ADR 0003) cropped this page.
    cropped: bool = False


@dataclass
class ProcessResult:
    """Outcome of :func:`process_pdf`."""

    input_path: Path
    output_path: Path
    pages: List[PageResult] = field(default_factory=list)

    def summary(self) -> str:
        detected = sum(1 for p in self.pages if p.detected)
        cropped = sum(1 for p in self.pages if p.cropped)
        s = (
            f"{self.output_path.name}: {len(self.pages)} page(s), "
            f"{detected} with smartboard region"
        )
        if cropped > 0:
            s += f", {cropped} cropped to board rect"
        return s


def process_pdf(
    input_path: "str | Path",
    output_path: "str | Path",
    dpi: int = 150,
    invert: bool = True,
    crop: bool = False,
    debug_dir: Optional["str | Path"] = None,
    progress: Optional[ProgressCallback] = None,
    *,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> ProcessResult:
    """Process a whole PDF (see module docstring).

    Parameters
    ----------
    input_path:
        Source PDF (never modified).
    output_path:
        Destination PDF.  Must differ from *input_path*.
    dpi:
        Rendering resolution for detection, verification and (for the
        rerasterize fallback) the embedded page image.  Range 20–600.
    invert:
        Apply the in-region transformation (strict ``255 − v`` inversion
        or target-background remap, default: on).
    crop:
        When True, the final output is re-wrapped so every page with a
        detected board is sized to exactly that rectangle; pages without a
        board (incl. all rotated pages, A-11) keep their full size.
        Default False (page-faithful, unchanged).
    debug_dir:
        Optional directory for per-page debug composites
        (original | original+bbox | result).
    progress:
        Optional callback invoked after each page: ``(n, total)``.
    bg_target:
        Target background of the board as ``(R, G, B)`` (ints 0–255) for a
        linear per-channel remap, or ``None`` for the strict ``255 − v``
        complement (default; bit-identical to v0.4.1).
    keep_colors:
        Marker colours (subset of :data:`processing.KEEPABLE_COLORS`) whose
        pixels keep their original values – exclusion takes precedence over
        complement/remap.  Empty (default) = everything is transformed
        (v0.4.1 behaviour).
    keep_segments:
        Explicit hex colours / ranges (pairs of user-facing RGB endpoints,
        see :func:`processing.hex_keep_mask`, ADR 0004) whose pixels keep
        their original values – same precedence as *keep_colors*.  Empty
        (default) = v0.5.0 behaviour (no hex exclusion).

    Raises
    ------
    SmartboardError
        On invalid paths, unreadable PDFs, invalid option values or
        page-level failures.
    """
    if not 20 <= int(dpi) <= 600:
        raise SmartboardError(f"dpi must be between 20 and 600 (got {dpi})")
    dpi = int(dpi)

    unknown = set(keep_colors) - KEEPABLE_COLORS
    if unknown:
        raise SmartboardError(
            f"unknown color(s) in keep_colors: {', '.join(sorted(unknown))} "
            f"(allowed: {', '.join(sorted(KEEPABLE_COLORS))})"
        )
    keep_segments = processing.validate_keep_segments(keep_segments)
    bg_target = processing.validate_bg_target(bg_target)

    input_path = Path(input_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    if not input_path.is_file():
        raise SmartboardError(f"input PDF not found: {input_path}")
    if input_path == output_path:
        raise SmartboardError("output path must differ from the input path")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if debug_dir is not None:
        Path(debug_dir).expanduser().mkdir(parents=True, exist_ok=True)

    try:
        src = fitz.open(str(input_path))
    except Exception as e:
        raise SmartboardError(f"unable to open PDF {input_path}: {e}") from e

    out_doc = fitz.open()
    result = ProcessResult(input_path=input_path, output_path=output_path)
    try:
        total = src.page_count
        for pno in range(total):
            page_result = _process_page(
                src,
                out_doc,
                pno,
                dpi=dpi,
                invert=invert,
                debug_dir=debug_dir,
                stem=input_path.stem,
                bg_target=bg_target,
                keep_colors=keep_colors,
                keep_segments=keep_segments,
            )
            result.pages.append(page_result)
            if progress is not None:
                progress(pno + 1, total)
        if crop:
            _save_cropped(out_doc, output_path, result)
        else:
            out_doc.save(str(output_path), garbage=3, deflate=True)
    finally:
        # Close both documents on every path (including errors).
        out_doc.close()
        src.close()
    logger.info("Wrote %s (%s)", output_path, result.summary())
    return result


# ---------------------------------------------------------------------------
# per-page processing
# ---------------------------------------------------------------------------


def _render_page(page, dpi: int) -> np.ndarray:
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB)
    img = np.frombuffer(pix.samples, dtype=np.uint8)
    img = img.reshape(pix.height, pix.width, 3)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def _process_page(
    src,
    out_doc,
    pno: int,
    *,
    dpi: int,
    invert: bool,
    debug_dir: Optional[Path],
    stem: str,
    bg_target: Optional[Tuple[int, int, int]],
    keep_colors: AbstractSet[str],
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> PageResult:
    page = src.load_page(pno)
    page_rect = page.rect
    if page.rotation not in (0,):
        # Fail-safe (A-11): pages with /Rotate are copied unchanged.  The
        # pixel<->point mapping used for detection/inversion is not valid for
        # rotated pages, and a wrong inversion would be worse than none.
        logger.warning(
            "Page %d has rotation %d – not processed (fail-safe), page copied "
            "unchanged",
            pno + 1,
            page.rotation,
        )
        img_orig = _render_page(page, dpi)
        pr = PageResult(
            page_index=pno,
            detected=False,
            method="copy",
            message=f"page has rotation {page.rotation} – copied unchanged (fail-safe)",
        )
        new_page = _add_page_copy(out_doc, src, pno, page_rect)
        _write_debug(
            debug_dir, stem, pno, img_orig,
            DetectionResult(found=False, message=pr.message),
            img_orig,
        )
        _verify_page(new_page, img_orig, None, dpi, pr)
        return pr

    img_orig = _render_page(page, dpi)
    height, width = img_orig.shape[:2]
    scale_x = page_rect.width / width
    scale_y = page_rect.height / height

    # 1) detection on the rendered page -------------------------------------
    detection = detect_smartboard_region(img_orig)
    pr = PageResult(
        page_index=pno,
        detected=detection.found,
        method="copy",
        confidence=detection.confidence,
        message=detection.message,
    )

    # Store the detected rect (render + page coordinates) on the PageResult
    # whenever it exists – independent of the transformation – so that the
    # optional crop post-stage (ADR 0003) can use it.
    if detection.found and detection.rect is not None:
        rect_px = detection.rect
        rect_pt = (
            rect_px[0] * scale_x,
            rect_px[1] * scale_y,
            rect_px[2] * scale_x,
            rect_px[3] * scale_y,
        )
        pr.rect_px = rect_px
        pr.rect_pt = tuple(rect_pt)  # type: ignore[assignment]

    do_something = invert

    if not detection.found or not do_something:
        if detection.found and not do_something:
            logger.info(
                "Page %d: region detected but no transformation requested – "
                "page copied unchanged",
                pno + 1,
            )
        else:
            logger.warning(
                "Page %d: no unambiguous smartboard region detected (%s) – "
                "page left unchanged",
                pno + 1,
                detection.message,
            )
        new_page = _add_page_copy(out_doc, src, pno, page_rect)
        _write_debug(debug_dir, stem, pno, img_orig, detection, img_orig)
        _verify_page(new_page, img_orig, None, dpi, pr)
        return pr

    # rect_px / rect_pt were stored on pr above (detection.found is True here)

    # 2) prefer replacing the board image XObject ---------------------------
    replaced = False
    candidate = _find_board_image(page, rect_pt)
    if candidate is not None:
        new_page = _add_page_copy(out_doc, src, pno, page_rect)
        replaced = _try_image_replace(
            out_doc,
            new_page,
            rect_pt,
            dpi=dpi,
            invert=invert,
            bg_target=bg_target,
            keep_colors=keep_colors,
            keep_segments=keep_segments,
        )
        if not replaced:
            # fall back: clear the copied content, embed the full-page image
            _clear_page(new_page, out_doc)
            processed = _transform_render(
                img_orig, rect_px, invert,
                bg_target=bg_target, keep_colors=keep_colors,
                keep_segments=keep_segments,
            )
            _embed_full_page_image(new_page, page_rect, processed)
    else:
        new_page = out_doc.new_page(width=page_rect.width, height=page_rect.height)
        processed = _transform_render(
            img_orig, rect_px, invert,
            bg_target=bg_target, keep_colors=keep_colors,
            keep_segments=keep_segments,
        )
        _embed_full_page_image(new_page, page_rect, processed)

    pr.method = "image-replace" if replaced else "rerasterize"
    logger.info(
        "Page %d: smartboard detected (confidence %.2f) – method=%s rect_pt=(%s)",
        pno + 1,
        detection.confidence,
        pr.method,
        ", ".join(f"{v:.1f}" for v in rect_pt),
    )

    # 3) debug + verification -------------------------------------------------
    img_out = _render_page(new_page, dpi)
    _write_debug(debug_dir, stem, pno, img_orig, detection, img_out)
    _verify_page(new_page, img_orig, rect_px, dpi, pr, img_out=img_out)
    return pr


def _transform_render(
    img: np.ndarray,
    rect: Rect,
    invert: bool,
    *,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> np.ndarray:
    """Apply the in-region transformation to a full-page render."""
    if not invert:
        return img.copy()
    x0, y0, x1, y1 = rect
    out = img.copy()
    out[y0:y1, x0:x1] = processing.invert_or_remap(
        out[y0:y1, x0:x1],
        bg_target=bg_target,
        keep_colors=keep_colors,
        keep_segments=keep_segments,
    )
    return out


# ---------------------------------------------------------------------------
# page building helpers
# ---------------------------------------------------------------------------


def _add_page_copy(out_doc, src, pno: int, page_rect) -> "fitz.Page":
    """Append a lossless copy of ``src[pno]``.

    Non-rotated pages: ``page.rect`` is the CropBox, a same-sized page plus
    ``show_pdf_page`` maps the content 1:1.

    Rotated pages (``/Rotate != 0``): ``show_pdf_page`` does *not* carry the
    source's ``/Rotate`` attribute over – the content would render
    unrotated.  Those pages are copied with ``insert_pdf`` instead, which
    preserves MediaBox, ``/Rotate`` and the content stream losslessly.
    """
    if src.load_page(pno).rotation not in (0,):
        out_doc.insert_pdf(src, from_page=pno, to_page=pno)
        return out_doc.load_page(out_doc.page_count - 1)
    new_page = out_doc.new_page(width=page_rect.width, height=page_rect.height)
    new_page.show_pdf_page(new_page.rect, src, pno)
    return new_page


def _clear_page(page, doc) -> None:
    """Empty the content stream(s) of *page* (keeps its size)."""
    for xref in page.get_contents():
        doc.update_stream(xref, b"")


def _embed_full_page_image(page, page_rect, img: np.ndarray) -> None:
    success, png_bytes = cv2.imencode(".png", img)
    if not success:  # pragma: no cover - defensive (PNG encoding does not fail for valid ndarrays)
        raise SmartboardError("failed to encode full-page image to PNG")
    page.insert_image(page_rect, stream=png_bytes.tobytes())


# ---------------------------------------------------------------------------
# image-replacement path
# ---------------------------------------------------------------------------


def _pick_board_image(infos: List[dict], rect: "fitz.Rect", tol: float = 2.0):
    """Pick the image XObject (get_image_info entry) that *is* the board.

    The image bbox must cover the detected rectangle (small tolerance), be at
    least half as large as the rectangle and be axis-aligned (no rotation or
    shear in the placement transform).  The largest matching image wins.
    """
    best = None
    for info in infos:
        ib = fitz.Rect(info["bbox"])
        if not (
            ib.x0 <= rect.x0 + tol
            and ib.y0 <= rect.y0 + tol
            and ib.x1 >= rect.x1 - tol
            and ib.y1 >= rect.y1 - tol
        ):
            continue
        # width*height instead of Rect.get_area(): compatible with both
        # PyMuPDF 1.x (Python 3.9) and 2.x
        if ib.width * ib.height < 0.5 * rect.width * rect.height:
            continue
        transform = info.get("transform")
        if transform is not None:
            # (a, b, c, d, e, f): axis-aligned => b == 0 and c == 0
            if abs(transform[1]) > 1e-3 or abs(transform[2]) > 1e-3:
                logger.debug("image %s is not axis-aligned – skipping", info.get("xref"))
                continue
        if best is None or ib.width * ib.height > fitz.Rect(
            best["bbox"]
        ).width * fitz.Rect(best["bbox"]).height:
            best = info
    return best


def _find_board_image(page, rect_pt: Tuple[float, float, float, float]):
    """Board image XObject on *page*, or ``None``."""
    rect = fitz.Rect(*rect_pt)
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("get_image_info failed: %s", e)
        return None
    return _pick_board_image(infos, rect)


def _decode_extracted_image(info: dict) -> np.ndarray:
    """Decode ``doc.extract_image(xref)`` output to a BGR uint8 ndarray."""
    data = info["image"]
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        return img
    return _decode_raw_stream(info)


def _decode_raw_stream(info: dict) -> np.ndarray:
    # pragma: no cover - defensive fallback for raw (uncompressed) image
    # streams; extract_image() normally yields a container format that
    # cv2.imdecode handles above.
    width, height = int(info["width"]), int(info["height"])
    n = int(info.get("colorspace", 3))
    raw = np.frombuffer(info["image"], np.uint8)
    if raw.size != width * height * n:
        raise SmartboardError("raw image stream has unexpected size")
    if n == 1:
        gray = raw.reshape(height, width)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if n == 3:
        rgb = raw.reshape(height, width, 3)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if n == 4:
        cmyk = raw.reshape(height, width, 4)
        return cv2.cvtColor(cmyk, cv2.COLOR_CMYK2BGR)
    raise SmartboardError(f"unsupported image colorspace (n={n})")


def _try_image_replace(
    out_doc,
    page,
    rect_pt: Tuple[float, float, float, float],
    *,
    dpi: int,
    invert: bool,
    bg_target: Optional[Tuple[int, int, int]] = None,
    keep_colors: AbstractSet[str] = frozenset(),
    keep_segments: "Tuple[HexSegment, ...]" = (),
) -> bool:
    """Replace the board image XObject with its inverted version.

    Returns ``True`` on success, ``False`` when the fallback (rerasterize)
    must be used.
    """
    rect = fitz.Rect(*rect_pt)
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("get_image_info failed on copied page: %s", e)
        return False
    candidate = _pick_board_image(infos, rect)
    if candidate is None:
        logger.debug("no board image found on copied page")
        return False
    xref = int(candidate["xref"])

    try:
        info = out_doc.extract_image(xref)
        native = _decode_extracted_image(info)
    except Exception as e:
        logger.warning("could not extract/decode board image (xref %d): %s", xref, e)
        return False

    nat_h, nat_w = native.shape[:2]
    ib = fitz.Rect(candidate["bbox"])

    # Second, higher-resolution detection on the native image.  The board may
    # cover the whole image (the image itself is the board) → allow it.
    det = detect_smartboard_region(native, allow_full_coverage=True)
    if not det.found:
        logger.warning(
            "board image (xref %d) has no detectable dark region internally – "
            "falling back to re-rasterization",
            xref,
        )
        return False

    # Cross-check: map the native rect to page coordinates and require strong
    # overlap with the rect found on the page render.
    sx = ib.width / nat_w
    sy = ib.height / nat_h
    if sx <= 0 or sy <= 0:
        logger.warning("board image has invalid placement scale – falling back")
        return False
    nx0, ny0, nx1, ny1 = det.rect
    native_rect_pt = (
        ib.x0 + nx0 * sx,
        ib.y0 + ny0 * sy,
        ib.x0 + nx1 * sx,
        ib.y0 + ny1 * sy,
    )
    overlap = rect_overlap_fraction(native_rect_pt, tuple(rect_pt))
    if overlap < 0.8:
        logger.warning(
            "native board rect only %.0f%% overlaps the page-level rect – "
            "falling back to re-rasterization",
            100 * overlap,
        )
        return False

    # The inversion follows the **page-level** rectangle mapped into image
    # space (not the native detection rect).  This guarantees that everything
    # outside the detected rectangle – including any light border that might
    # be part of the image – stays untouched (P2-FR-3).
    #
    # Start coordinates are rounded *outward* (ceil) and end coordinates
    # *inward* (floor): the mapping from the (sub-pixel) page rect to image
    # pixels is then conservative, so every inverted native pixel lies fully
    # inside the detected rect.  Without this, ``round()`` can pull in a
    # border row/column that belongs to the untouched margin (off-by-one).
    inv_rect = clamp_rect(
        (
            int(math.ceil((rect.x0 - ib.x0) / sx)),
            int(math.ceil((rect.y0 - ib.y0) / sy)),
            int(math.floor((rect.x1 - ib.x0) / sx)),
            int(math.floor((rect.y1 - ib.y0) / sy)),
        ),
        nat_w,
        nat_h,
    )
    if (
        inv_rect[2] - inv_rect[0] < 0.5 * nat_w
        or inv_rect[3] - inv_rect[1] < 0.5 * nat_h
    ):
        logger.warning(
            "page-level rect maps to a degenerate area inside the board image "
            "– falling back to re-rasterization",
        )
        return False
    x0, y0, x1, y1 = inv_rect

    # Transform only inside the mapped rect, then replace the XObject (PNG:
    # lossless, same dimensions).
    region = native[y0:y1, x0:x1]
    if invert:
        region = processing.invert_or_remap(
            region,
            bg_target=bg_target,
            keep_colors=keep_colors,
            keep_segments=keep_segments,
        )
    processed = native.copy()
    processed[y0:y1, x0:x1] = region

    success, png_bytes = cv2.imencode(".png", processed)
    if not success:
        logger.warning("failed to encode replaced board image to PNG – falling back")
        return False
    try:
        page.replace_image(xref, stream=png_bytes.tobytes())
    except Exception as e:
        logger.warning("replace_image failed (xref %d): %s – falling back", xref, e)
        return False
    logger.debug(
        "replaced board image xref=%d (native %dx%d, confidence %.2f, overlap %.0f%%)",
        xref,
        nat_w,
        nat_h,
        det.confidence,
        100 * overlap,
    )
    return True


# ---------------------------------------------------------------------------
# crop post-stage (ADR 0003)
# ---------------------------------------------------------------------------


def _save_cropped(faithful_doc, output_path: Path, result: ProcessResult) -> None:
    """Re-wrap the page-faithful output so each page shows only its board rect.

    Post-stage for ``crop=True`` (ADR 0003): pages with a detected board
    rectangle become new pages of exactly that size (``show_pdf_page`` with
    ``clip`` – vector-exact, 1:1 mapping because target rect and clip have
    identical dimensions).  Pages without a board (including all rotated
    pages, A-11) are copied 1:1 via ``insert_pdf`` (no content loss,
    ``/Rotate`` preserved).  When no page has a board the result is the
    unchanged page-faithful document (never an empty file).

    ``faithful_doc`` is serialized and reopened because ``show_pdf_page``
    requires a *different* document object as source.
    """
    src = fitz.open(stream=faithful_doc.write(), filetype="pdf")
    final = fitz.open()
    try:
        for i, pr in enumerate(result.pages):
            page = src.load_page(i)
            if pr.detected and pr.rect_pt is not None:
                if page.rotation:
                    # Defensive path – by contract (A-11) rect_pt only exists
                    # on unrotated pages, where visual == unrotated.  If a
                    # rotated page ever carries a rect (visual coordinates),
                    # bake the rotation into the throwaway copy first
                    # (officially recommended before show_pdf_page); the old
                    # visual coordinates are then unrotated coordinates.
                    try:
                        page.remove_rotation()
                    except Exception as e:
                        logger.warning(
                            "Page %d: remove_rotation failed (%s) – page "
                            "copied in full", i + 1, e,
                        )
                        final.insert_pdf(src, from_page=i, to_page=i)
                        continue
                # ``clip`` is unrotated-space (ADR 0003, D2); for rotation 0
                # (the only case with rects) rect_pt is already in that space.
                clip = fitz.Rect(*pr.rect_pt) & page.rect
                if clip.width > 0 and clip.height > 0:
                    new_page = final.new_page(width=clip.width, height=clip.height)
                    new_page.show_pdf_page(new_page.rect, src, i, clip=clip)
                    pr.cropped = True
                    logger.info(
                        "Page %d: cropped to board rect (%.1f x %.1f pt)",
                        i + 1, clip.width, clip.height,
                    )
                    continue
                logger.warning(
                    "Page %d: degenerate crop rect %s – page copied in full",
                    i + 1, clip,
                )
            else:
                logger.warning(
                    "Page %d: no board rectangle – page copied in full "
                    "(not cropped)", i + 1,
                )
            final.insert_pdf(src, from_page=i, to_page=i)
        if not any(p.cropped for p in result.pages):
            logger.warning(
                "--crop: no page has a detected board – output stays "
                "page-faithful"
            )
        final.save(str(output_path), garbage=3, deflate=True)
    finally:
        final.close()
        src.close()


# ---------------------------------------------------------------------------
# debug visualization + verification (ADR 0001, D3)
# ---------------------------------------------------------------------------


def _write_debug(
    debug_dir: Optional[Path],
    stem: str,
    pno: int,
    img_orig: np.ndarray,
    detection: DetectionResult,
    img_result: np.ndarray,
) -> None:
    if debug_dir is None:
        return
    debug_dir = Path(debug_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    panels = [img_orig.copy()]
    overlay = img_orig.copy()
    if detection.found and detection.rect is not None:
        x0, y0, x1, y1 = detection.rect
        cv2.rectangle(overlay, (x0, y0), (max(x0, x1 - 2), max(y0, y1 - 2)), (0, 255, 0), 3)
        label = (
            f"conf={detection.confidence:.2f} T={detection.threshold} "
            f"B={detection.background_level:.0f}"
        )
        cv2.putText(
            overlay,
            label,
            (x0, max(24, y0 - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
    else:
        cv2.putText(
            overlay,
            f"NO REGION: {detection.message[:60]}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
    panels.append(overlay)
    panels.append(img_result.copy())

    # Scale panels to a common height and stack horizontally.
    max_h = 1200
    scaled = []
    for panel in panels:
        h, w = panel.shape[:2]
        if h > max_h:
            scale = max_h / h
            panel = cv2.resize(panel, (max(1, int(w * scale)), max_h), interpolation=cv2.INTER_AREA)
        scaled.append(panel)
    target_h = max(p.shape[0] for p in scaled)
    padded = []
    for panel in scaled:
        if panel.shape[0] < target_h:
            pad = np.full((target_h - panel.shape[0], panel.shape[1], 3), 255, np.uint8)
            panel = np.vstack([panel, pad])
        padded.append(panel)
    widths = sum(p.shape[1] + 10 for p in padded) - 10
    combined = np.full((target_h, widths, 3), 200, np.uint8)
    x = 0
    for panel in padded:
        combined[:, x : x + panel.shape[1]] = panel
        x += panel.shape[1] + 10
    out_path = debug_dir / f"{stem}_p{pno + 1:02d}_debug.png"
    if cv2.imwrite(str(out_path), combined):
        logger.info("Debug image written: %s", out_path)
    else:  # pragma: no cover - defensive
        logger.warning("failed to write debug image: %s", out_path)


def _verify_page(
    page,
    img_orig: np.ndarray,
    rect_px: Optional[Rect],
    dpi: int,
    pr: PageResult,
    img_out: Optional[np.ndarray] = None,
) -> None:
    """Compare the rendered original and output pages (ADR 0001, D3)."""
    if img_out is None:
        img_out = _render_page(page, dpi)
    h, w = img_orig.shape[:2]
    if img_out.shape[:2] != (h, w):
        pr.verification["note"] = (
            f"render size mismatch: original {w}x{h}, output {img_out.shape[1]}x{img_out.shape[0]}"
        )
        logger.warning("Page %d: %s", pr.page_index + 1, pr.verification["note"])
        return
    diff = cv2.absdiff(img_orig, img_out)
    if rect_px is None:
        pr.verification["max_diff"] = int(diff.max())
        if pr.verification["max_diff"] > 0:
            logger.warning(
                "Page %d: unchanged page differs (max diff %d)",
                pr.page_index + 1,
                pr.verification["max_diff"],
            )
        else:
            logger.debug("Page %d verified: page is pixel-identical", pr.page_index + 1)
        return
    x0, y0, x1, y1 = clamp_rect(rect_px, w, h)
    outside = np.ones((h, w), dtype=bool)
    outside[y0:y1, x0:x1] = False
    outside_diff = diff[outside]
    inside_diff = diff[y0:y1, x0:x1]
    pr.verification["outside_max_diff"] = int(outside_diff.max())
    pr.verification["outside_mean_diff"] = round(float(outside_diff.mean()), 4)
    pr.verification["inside_mean_diff"] = round(float(inside_diff.mean()), 2)
    # Re-rasterized pages may show up to a few grey levels of resampling drift
    # outside the rectangle (non-integer page scale).  Copy/image-replace must
    # be exact.
    tolerance = 8 if pr.method == "rerasterize" else 0
    if pr.verification["outside_max_diff"] > tolerance:
        logger.warning(
            "Page %d: pixels OUTSIDE the detected region changed (max diff %d, "
            "tolerance %d) – inspect the debug image",
            pr.page_index + 1,
            pr.verification["outside_max_diff"],
            tolerance,
        )
    else:
        logger.info(
            "Page %d verified: outside max diff=%d (tol %d), inside mean diff=%.1f",
            pr.page_index + 1,
            pr.verification["outside_max_diff"],
            tolerance,
            pr.verification["inside_mean_diff"],
        )
