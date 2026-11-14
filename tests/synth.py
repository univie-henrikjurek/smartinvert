"""Builders for synthetic test PDFs and images.

These fixtures are independent of ``inputs/test.pdf`` so the detection logic
can be tested against known ground-truth rectangles.  Two board styles are
supported, mirroring the two pipeline paths (ADR 0001, D2):

* ``image``  – the board is an embedded image XObject (typical smartboard
  export).
* ``vector`` – the board is drawn with vector paths (like ``inputs/test.pdf``).

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
) -> np.ndarray:
    """Create a synthetic smartboard screenshot (BGR ``uint8``).

    A dark background (``bg``), optional white "text" bars (deterministic via
    ``seed``) and an optional white border inside the image.
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
    return img


def make_pdf(path: "str | Path", pages: Sequence[dict]) -> List[dict]:
    """Create a synthetic PDF and return per-page ground truth.

    Each entry of *pages* is a dict with:

    ``{"kind": "image", "rect": (x, y, w, h) in pt, "bg": (b, g, r),
       "text": bool, "border": int (image px), "scale": float (image px/pt)}``
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
        elif kind == "vector":
            x, y, w, h = spec["rect"]
            bg = spec.get("bg", (20, 20, 25))
            shape = page.new_shape()
            shape.draw_rect(fitz.Rect(x, y, x + w, y + h))
            shape.finish(color=None, fill=tuple(c / 255.0 for c in bg))
            if spec.get("lines", True):
                yy = y + h * 0.10
                while yy < y + h * 0.90:
                    shape.draw_line(fitz.Point(x + w * 0.10, yy), fitz.Point(x + w * 0.90, yy))
                    shape.finish(color=(1.0, 1.0, 1.0), width=1.5)
                    yy += h * 0.08
            shape.commit()
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
