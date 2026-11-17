"""Builders for synthetic test PDFs and images.

These fixtures are independent of ``inputs/test.pdf`` so the detection logic
can be tested against known ground-truth rectangles.  Two board styles are
supported, mirroring the two pipeline paths (ADR 0001, D2):

* ``image``  – the board is an embedded image XObject (typical smartboard
  export).
* ``vector`` – the board is drawn with vector paths (like ``inputs/test.pdf``).
* ``xobj``   – the board is drawn inside a Form XObject (typical editor /
  "save as PDF" output — the vector-invert path of ADR 0008).
* ``vector-<construct>`` – a vector board plus one PDF construct the v1
  vector rewrite refuses (ADR 0008, self-healing raster fallback):
  ``vector-inline-image``, ``vector-shading``, ``vector-extgstate``,
  ``vector-rotated-text``.  (Non-device ``cs`` colour spaces are covered by
  the rewriter unit tests in ``tests/test_vectorops.py`` — MuPDF 1.28 cannot
  render pattern/ICCBased spaces reliably, so there is no fixture kind for
  them.)

Any spec may set ``"offset": (dx, dy)`` to shift the page's MediaBox
(``[dx dy W+dx H+dy]``) — the real-world "offset page box" scenario from
ADR 0007.

``make_pdf`` returns the ground truth (dark-area rectangle in render pixels at
``DPI`` and in page points) for every page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from smartboard_invert.processing import fitz

#: A4 portrait in points (the page size used by all fixtures).
A4_W, A4_H = 595.0, 842.0
#: Render resolution used by the tests.
DPI = 150
PX_PER_PT = DPI / 72.0


def pt2px(value: float) -> float:
    """Convert a page-point distance to render pixels at ``DPI``."""
    return value * PX_PER_PT


def board_image(
    width: int,
    height: int,
    bg: Tuple[int, int, int] = (20, 20, 25),
    text: bool = True,
    border: int = 0,
    seed: int = 0,
    marks: Sequence[Tuple[Tuple[int, int, int, int], Tuple[int, int, int]]] = (),
) -> np.ndarray:
    """Create a synthetic smartboard screenshot (BGR ``uint8``).

    A dark background (``bg``), optional white "text" bars (deterministic via
    ``seed``), an optional white border inside the image, and optional marker
    ``marks``: a list of ``(rect_px, color)`` pairs where ``rect_px`` is
    ``(x, y, w, h)`` in image pixels (same coordinate space as the existing
    drawings) and ``color`` is a BGR tuple.  Each mark is drawn as a filled
    rectangle on top of the board.
    """
    img = np.full((height, width, 3), bg, dtype=np.uint8)
    if border > 0:
        img[:border, :] = 255
        img[-border:, :] = 255
        img[:, :border] = 255
        img[:, -border:] = 255
    if text:
        rng = np.random.default_rng(seed)
        inner_w = max(10, width - 2 * border)
        inner_h = max(10, height - 2 * border)
        row_h = max(4, int(inner_h * 0.03))
        y = border + int(inner_h * 0.12)
        while y < border + int(inner_h * 0.85):
            x = border + int(inner_w * 0.10)
            while x < border + int(inner_w * 0.80):
                length = int(rng.integers(inner_w // 12, max(inner_w // 12 + 1, inner_w // 5)))
                cv2.rectangle(
                    img,
                    (x, y),
                    (min(x + length, width - border - 1), y + row_h),
                    (255, 255, 255),
                    -1,
                )
                x += length + int(inner_w // 12)
            y += int(inner_h * 0.09)
    for (x, y, w, h), color in marks:
        cv2.rectangle(img, (x, y), (x + w - 1, y + h - 1), color, -1)
    return img


def _draw_vector_board(page, spec: dict) -> None:
    """Draw the dark board rectangle + white lines with vector paths (top-left
    ``rect`` in pt, BGR ``bg``).

    Optional ``marks``: ``[(x, y, w, h) in pt top-left, (b, g, r)]`` vector
    rectangles (e.g. a red "marker" rect for keep-colour tests); optional
    ``text``: ``[(x, y, string)]`` inserted in black (y = text top, pt) —
    lecture-style vector content.
    """
    x, y, w, h = spec["rect"]
    bg = spec.get("bg", (20, 20, 25))  # BGR (fixture convention) -> RGB
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(x, y, x + w, y + h))
    shape.finish(color=None, fill=(bg[2] / 255.0, bg[1] / 255.0, bg[0] / 255.0))
    if spec.get("lines", True):
        yy = y + h * 0.10
        while yy < y + h * 0.90:
            shape.draw_line(fitz.Point(x + w * 0.10, yy), fitz.Point(x + w * 0.90, yy))
            shape.finish(color=(1.0, 1.0, 1.0), width=1.5)
            yy += h * 0.08
    shape.commit()
    for (mx, my, mw, mh), color in spec.get("marks", ()):
        # color is BGR (fixture convention) -> RGB for PyMuPDF
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(mx, my, mx + mw, my + mh))
        shape.finish(color=None, fill=(color[2] / 255.0, color[1] / 255.0, color[0] / 255.0))
        shape.commit()
    for (tx, ty, text) in spec.get("text", ()):
        page.insert_text(fitz.Point(tx, ty), text, fontsize=14)


def _draw_xobj_board(doc, page, x: float, y: float, w: float, h: float, bg, lines: bool) -> None:
    """Draw the board inside a Form XObject (editor-style export).

    The form content uses absolute page coordinates (bottom-origin), the form
    BBox equals the board rect and the page content is a single ``/Fm0 Do`` —
    i.e. the board only exists inside the XObject tree (the ADR 0008 layout).
    """
    r, g, b = (c / 255.0 for c in (bg[2], bg[1], bg[0]))  # bg is BGR
    y0, y1 = A4_H - (y + h), A4_H - y  # bottom-origin
    stream = [f"{b:.3f} {g:.3f} {r:.3f} rg {x:.3f} {y0:.3f} {w:.3f} {h:.3f} re f"]
    if lines:
        yy_frac = 0.10
        while yy_frac < 0.90:
            ypdf = A4_H - (y + h * yy_frac)
            stream.append(
                f"1 1 1 RG 1.5 w {x + w * 0.10:.3f} {ypdf:.3f} m "
                f"{x + w * 0.90:.3f} {ypdf:.3f} l S"
            )
            yy_frac += 0.08
    fxref = doc.get_new_xref()
    doc.update_object(
        fxref,
        f"<< /Type /XObject /Subtype /Form /BBox [{x:.3f} {y0:.3f} "
        f"{x + w:.3f} {y1:.3f}] /Resources << >> /Length 0 >>",
    )
    doc.update_stream(fxref, ("\n".join(stream)).encode("latin-1"))
    cxref = doc.get_new_xref()
    doc.update_object(cxref, "<< /Length 0 >>")
    doc.update_stream(cxref, b"/Fm0 Do")
    page.set_contents(cxref)
    doc.xref_set_key(page.xref, "Resources", f"<< /XObject << /Fm0 {fxref} 0 R >> >>")


def _contents_xref(doc, page) -> int:
    kind, val = doc.xref_get_key(page.xref, "Contents")
    return page.xref if kind == "stream" else int(val.split()[0])


def _append_raw(page, doc, ops: bytes, resources: str = "") -> None:
    """Append raw content-stream operators to a vector-drawn fixture page.

    The vector board is plain paths (no /Font, /XObject, ...), so the page's
    empty /Resources dict can be replaced wholesale.
    """
    page.clean_contents()
    doc.update_stream(_contents_xref(doc, page), page.read_contents() + b"\n" + ops)
    if resources:
        doc.xref_set_key(page.xref, "Resources", f"<< {resources} >>")


def _append_vector_construct(doc, page, kind: str, x: float, y: float, w: float, h: float) -> None:
    """Append one vector-unsupported PDF construct (ADR 0008 fallback cases)
    at the centre of the board (``x, y, w, h`` top-left in pt)."""
    sz = 40.0
    cx = x + w / 2.0
    cy = A4_H - (y + h / 2.0)  # centre, bottom-origin
    x0, y0 = cx - sz / 2.0, cy - sz / 2.0
    if kind == "vector-inline-image":
        payload = bytes((i * 7) % 256 for i in range(16 * 16 * 3))
        ops = (
            f"q {sz:.3f} 0 0 {sz:.3f} {x0:.3f} {y0:.3f} cm "
            f"BI /W 16 /H 16 /CS /RGB /BPC 8 ID ".encode("latin-1")
            + payload
            + b" EI Q"
        )
        _append_raw(page, doc, ops)
    elif kind == "vector-shading":
        sxref = doc.get_new_xref()
        doc.update_object(
            sxref,
            f"<< /Type /Shading /ShadingType 2 /ColorSpace /DeviceRGB "
            f"/Coords [{x0:.3f} {y0:.3f} {x0 + sz:.3f} {y0 + sz:.3f}] "
            f"/Function << /FunctionType 2 /Domain [0 1] /C0 [1 1 1] /C1 [0 0 0] "
            f"/BitsPerSample 8 /Matrix [1 0 0 1 0 0] >> /Extend [true true] >>",
        )
        _append_raw(
            page, doc,
            f"{x0:.3f} {y0:.3f} {sz:.3f} {sz:.3f} re W n /Sh0 sh".encode("latin-1"),
            resources=f"/Shading << /Sh0 {sxref} 0 R >>",
        )
    elif kind == "vector-extgstate":
        _append_raw(
            page, doc,
            f"q /GS0 gs 1 1 1 rg {x0:.3f} {y0:.3f} {sz:.3f} {sz:.3f} re f Q".encode("latin-1"),
            resources="/ExtGState << /GS0 << /Type /ExtGState /ca 0.5 /CA 0.5 >> >>",
        )
    elif kind == "vector-rotated-text":
        _append_raw(
            page, doc,
            f"BT /F1 14 Tf 0.7071 0.7071 -0.7071 0.7071 {cx:.3f} {cy:.3f} "
            f"Tm (Hallo) Tj ET".encode("latin-1"),
            resources="/Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >>",
        )
    else:  # pragma: no cover - defensive
        raise ValueError(f"unknown vector construct: {kind}")


def make_pdf(path: "str | Path", pages: Sequence[dict]) -> List[dict]:
    """Create a synthetic PDF and return per-page ground truth.

    Each entry of *pages* is a dict with:

    ``{"kind": "image", "rect": (x, y, w, h) in pt, "bg": (b, g, r),
       "text": bool, "border": int (image px), "scale": float (image px/pt),
       "marks": [(rect_px (x, y, w, h) in image px, BGR color), ...]}``
    ``{"kind": "vector", "rect": (x, y, w, h) in pt, "bg": (b, g, r),
       "lines": bool}``
    ``{"kind": "blank", "marks": [(x, y, w, h) in pt, ...]}``

    The returned list has one entry per page:
    ``{"kind": ..., "rect_px": (x0, y0, x1, y1) or None, "rect_pt": (...) or None}``
    where ``rect_px`` is the ground-truth dark rectangle in render pixels at
    ``DPI``.
    """
    doc = fitz.open()
    truths: List[dict] = []
    for spec in pages:
        kind = spec["kind"]
        page = doc.new_page(width=A4_W, height=A4_H)
        if kind == "image":
            rects: Sequence[Tuple[float, float, float, float]] = (
                spec["rect"] if isinstance(spec["rect"], (list, tuple)) and spec.get("multi") else [spec["rect"]]
            )
            scale = float(spec.get("scale", 2.0))
            border_px = int(spec.get("border", 0))
            rect_pts: List[Optional[Tuple[float, float, float, float]]] = []
            rect_px_list: List[Optional[Tuple[float, float, float, float]]] = []
            for (x, y, w, h) in rects:
                bw, bh = int(w * scale), int(h * scale)
                img = board_image(
                    bw,
                    bh,
                    bg=spec.get("bg", (20, 20, 25)),
                    text=bool(spec.get("text", True)),
                    border=border_px,
                    seed=int(spec.get("seed", 0)),
                    marks=spec.get("marks", ()),
                )
                ok, png = cv2.imencode(".png", img)
                assert ok, "failed to encode synthetic board image"
                page.insert_image(fitz.Rect(x, y, x + w, y + h), stream=png.tobytes())
                sx = pt2px(w) / bw  # render px per image px
                rect_pts.append((x, y, x + w, y + h))
                rect_px_list.append(
                    (
                        x * PX_PER_PT + border_px * sx,
                        y * PX_PER_PT + border_px * sx,
                        (x + w) * PX_PER_PT - border_px * sx,
                        (y + h) * PX_PER_PT - border_px * sx,
                    )
                )
            # Ground truth: a single rect when there is one board, otherwise a
            # list (the caller expects ambiguity / no single detection).
            if len(rect_pts) == 1:
                rect_pt = rect_pts[0]
                rect_px = rect_px_list[0]
            else:
                rect_pt = rect_pts  # type: ignore[assignment]
                rect_px = rect_px_list  # type: ignore[assignment]
        elif kind in (
            "vector",
            "xobj",
            "vector-inline-image",
            "vector-shading",
            "vector-extgstate",
            "vector-rotated-text",
        ):
            x, y, w, h = spec["rect"]
            bg = spec.get("bg", (20, 20, 25))
            if kind == "xobj":
                _draw_xobj_board(doc, page, x, y, w, h, bg, bool(spec.get("lines", True)))
            else:
                _draw_vector_board(page, spec)
                if kind.startswith("vector-"):
                    _append_vector_construct(doc, page, kind, x, y, w, h)
            rect_pt = (x, y, x + w, y + h)
            rect_px = (pt2px(x), pt2px(y), pt2px(x + w), pt2px(y + h))
        elif kind == "blank":
            for mx, my, mw, mh in spec.get("marks", []):
                shape = page.new_shape()
                shape.draw_rect(fitz.Rect(mx, my, mx + mw, my + mh))
                shape.finish(color=None, fill=(0.0, 0.0, 0.0))
                shape.commit()
            rect_pt = None
            rect_px = None
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown page kind: {kind}")
        off = spec.get("offset")
        if off and rect_pt is not None:
            dx, dy = off
            doc.xref_set_key(
                page.xref, "MediaBox", f"[{dx} {dy} {A4_W + dx} {A4_H + dy}]"
            )
            # the visible window shifts, so the board moves (−dx, +dy) in
            # top-left render coordinates
            rect_pt = (
                rect_pt[0] - dx,
                rect_pt[1] + dy,
                rect_pt[2] - dx,
                rect_pt[3] + dy,
            )
            rect_px = (
                rect_px[0] - dx * PX_PER_PT,
                rect_px[1] + dy * PX_PER_PT,
                rect_px[2] - dx * PX_PER_PT,
                rect_px[3] + dy * PX_PER_PT,
            )
        truths.append({"kind": kind, "rect_px": rect_px, "rect_pt": rect_pt})

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return truths


def page_render(pdf_path: "str | Path", dpi: int = DPI) -> np.ndarray:
    """Render the first page of a PDF to a BGR image at *dpi*."""
    from smartboard_invert.processing import pdf_to_images

    return pdf_to_images(pdf_path, dpi=dpi)[0]


def changed_bbox(img_a: np.ndarray, img_b: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Bounding box of all pixels that differ between two images (or None)."""
    diff = cv2.absdiff(img_a, img_b).max(axis=2) > 0
    if not diff.any():
        return None
    ys, xs = np.nonzero(diff)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def outside_mask(rect: Tuple[float, float, float, float], shape: Tuple[int, int], inflate: int = 0) -> np.ndarray:
    """Boolean mask of all pixels *outside* *rect* (with optional inflation)."""
    height, width = shape
    x0 = max(0, int(rect[0]) - inflate)
    y0 = max(0, int(rect[1]) - inflate)
    x1 = min(width, int(rect[2]) + inflate)
    y1 = min(height, int(rect[3]) + inflate)
    mask = np.ones((height, width), dtype=bool)
    mask[y0:y1, x0:x1] = False
    return mask
