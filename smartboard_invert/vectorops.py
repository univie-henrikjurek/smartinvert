"""Vector-preserving content-stream colour rewriting (ADR 0008).

The pipeline's page copies (``pdfpipeline._add_page_copy`` →
``show_pdf_page``) keep vector content as a Form-XObject tree under the
page (``/fzFrm0`` → ``/fullpage`` → possibly nested Forms; an offset
MediaBox is normalised via a ``/Matrix`` translation).  This module
rewrites the colour operators of that tree so the in-region
transformation (strict ``255 − v`` complement, ``bg_target`` remap and
keep-exclusions — *identical* math to
:func:`smartboard_invert.processing.invert_or_remap`, applied per flat
colour) happens at the vector level instead of rasterising the page.

Every paint operator (path fill/stroke, text show) is decided
geometrically: its bounding box × the CTM chain down the XObject tree is
compared with the detected board rectangle (in the copy page's
(0,0,W,H) space — the same space as ``rect_pt``), so page-margin content
is never touched.  A full-page near-white fill is a background plate
(kept); anything else inside/straddling the board is inverted.

Original colour operands are never modified.  The rewriter tracks the
colour currently in effect (original vs. an inserted inversion) per
graphics state; whenever a paint's decision contradicts it, an explicit
colour operator is inserted before the paint's first operand — order-safe
for shared operands, and (for text) outside the ``string … show`` pair so
MuPDF's text extraction keeps working.

Anything that cannot be handled exactly raises
:class:`VectorUnsupported`; the caller falls back to the proven raster
path (self-healing, ADR 0008 D2).
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import AbstractSet, Dict, List, Optional, Tuple

import numpy as np

from . import processing

logger = logging.getLogger(__name__)

__all__ = [
    "VectorUnsupported",
    "FlatColorTransform",
    "rewrite_page_tree",
    "aa_band_px",
    "board_bg_levels",
]

#: Identity 3x2 matrix (a, b, c, d, e, f) — row-vector convention:
#: ``x' = a·x + c·y + e``, ``y' = b·x + d·y + f``.
IDENTITY: Tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

#: A path covering at least this fraction of the page is a page-background
#: element (plate rule).
FULLPAGE_COVERAGE: float = 0.95

#: Minimum channel (0–255) for a full-page fill to count as a near-white
#: background plate.  Detection requires board interiors to be clearly
#: dark (contrast ≥ 60 below a p95 ≥ 200 background), so no board fill can
#: sit at/above this level.
PLATE_MIN_CHANNEL: int = 200

#: Whitespace + delimiter byte sets (PDF 7.3.2.2).
_WS = {0x20, 0x09, 0x0A, 0x0D, 0x0C, 0x00}
_DELIMS = _WS | {0x28, 0x29, 0x3C, 0x3E, 0x5B, 0x5D, 0x7B, 0x7D, 0x2F, 0x25}
_NUM_RE = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

#: device colour operators: op → (space, n_components, is_fill)
_COLOR_OPS: Dict[str, Tuple[str, int, bool]] = {
    "g": ("gray", 1, True),
    "G": ("gray", 1, False),
    "rg": ("rgb", 3, True),
    "RG": ("rgb", 3, False),
    "k": ("cmyk", 4, True),
    "K": ("cmyk", 4, False),
}


class VectorUnsupported(Exception):
    """A content construct the v1 vector rewrite cannot handle exactly."""


def aa_band_px(dpi: int) -> int:
    """Antialiasing band around the board rect (render pixels).

    Board-edge blending differs fundamentally between vector semantics
    (inverted colours blended with the *non-inverted* white canvas) and
    raster semantics (inversion of the blend); the band is excluded from
    verification and used as the geometry decision tolerance.
    """
    return max(4, dpi // 36 + 2)


# ---------------------------------------------------------------------------
# flat colour math — exact counterpart of processing.invert_or_remap
# ---------------------------------------------------------------------------


def _quant(f: float) -> int:
    """Quantise a PDF colour component (0–1) to 0–255.

    The renderer quantises flat fills with ``floor(v·255)`` (calibrated,
    ADR 0008); replicating it keeps vector and raster outputs on the same
    8-bit grid.
    """
    v = int(f * 255)
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def _fmt(v: int) -> bytes:
    """0–255 → PDF number literal that quantises back to *v*.

    Ceil to 6 decimals with a 0.01 safety margin so that
    ``floor(parseFloat(literal)·255) == v`` holds despite binary float
    noise (the margin is far below the 1/255 grid step).
    """
    if v >= 255:
        return b"1"
    d = math.ceil((v + 0.01) * 1e6 / 255) / 1e6
    return f"{d:.6f}".encode("ascii")


def _cmyk_to_rgb_u8(c: int, m: int, y: int, k: int) -> Tuple[int, int, int]:
    """CMYK 0–255 → RGB 0–255 (standard subtractive model)."""
    k1 = k / 255.0
    return (
        int((1.0 - c / 255.0) * (1.0 - k1) * 255),
        int((1.0 - m / 255.0) * (1.0 - k1) * 255),
        int((1.0 - y / 255.0) * (1.0 - k1) * 255),
    )


def _rgb_to_cmyk_u8(r: int, g: int, b: int) -> Tuple[int, int, int, int]:
    """RGB 0–255 → CMYK 0–255 (exact inverse of :func:`_cmyk_to_rgb_u8`)."""
    r1, g1, b1 = r / 255.0, g / 255.0, b / 255.0
    k = 1.0 - max(r1, g1, b1)
    if k >= 1.0:
        return (0, 0, 0, 255)
    c = (1.0 - r1 - k) / (1.0 - k)
    m = (1.0 - g1 - k) / (1.0 - k)
    y = (1.0 - b1 - k) / (1.0 - k)
    return (int(c * 255), int(m * 255), int(y * 255), int(k * 255))


def _to_bgr_u8(space: str, q: Tuple[int, ...]) -> Tuple[int, int, int]:
    if space == "gray":
        return (q[0], q[0], q[0])
    if space == "rgb":
        return (q[2], q[1], q[0])
    r, g, b = _cmyk_to_rgb_u8(q[0], q[1], q[2], q[3])
    return (b, g, r)


class FlatColorTransform:
    """Per-flat-colour counterpart of :func:`processing.invert_or_remap`.

    Quantises the float PDF components to the renderer's 8-bit grid
    (``floor(v·255)``), applies the keep-exclusions (``color_mask`` /
    ``hex_keep_mask`` on a 1×1 BGR image — the same code path as the raster
    pipeline) and the complement / remap.  ``apply`` returns
    ``(space, 0–255 ints)`` or ``None`` ("keep unchanged").
    """

    def __init__(
        self,
        bg_target: Optional[Tuple[int, int, int]],
        keep_colors: AbstractSet[str],
        keep_segments: "Tuple[Tuple[Tuple[int, int, int], Tuple[int, int, int]], ...]",
        bg_levels: Optional[np.ndarray],
    ):
        self._bg_target = bg_target
        self._keep_colors = keep_colors
        self._keep_segments = keep_segments
        self._scale: Optional[np.ndarray] = None
        if bg_target is not None:
            # BGR order (bg_target is user-facing RGB); same formula as
            # invert_or_remap.
            t = np.array([bg_target[2], bg_target[1], bg_target[0]], dtype=np.float32)
            self._scale = t / (255.0 - np.asarray(bg_levels, dtype=np.float32))

    def apply(self, space: str, comps: Tuple[float, ...]) -> Optional[Tuple[str, Tuple[int, ...]]]:
        q = tuple(_quant(c) for c in comps)
        bgr = _to_bgr_u8(space, q)
        if self._keep_colors or self._keep_segments:
            region = np.asarray(bgr, dtype=np.uint8).reshape(1, 1, 3)
            m = np.zeros((1, 1), dtype=bool)
            if self._keep_colors:
                m |= processing.color_mask(region, self._keep_colors)
            if self._keep_segments:
                m |= processing.hex_keep_mask(region, self._keep_segments)
            if bool(m.all()):
                return None
        if self._bg_target is None:
            new = (255 - bgr[0], 255 - bgr[1], 255 - bgr[2])
        else:
            new = tuple(
                int(min(255.0, max(0.0, math.floor((255.0 - float(v)) * float(s) + 0.5))))
                for v, s in zip(bgr, self._scale)  # type: ignore[union-attr]
            )
        if self._bg_target is None:
            if space == "gray":
                return ("gray", (new[0],))
            if space == "rgb":
                return ("rgb", (new[2], new[1], new[0]))
            return ("cmyk", _rgb_to_cmyk_u8(new[2], new[1], new[0]))
        # remap: per-channel scales can differ → emit DeviceRGB
        return ("rgb", (new[2], new[1], new[0]))


# ---------------------------------------------------------------------------
# matrix / bbox helpers (row-vector convention, bottom-origin page space)
# ---------------------------------------------------------------------------


def _compose(m1: Tuple[float, ...], m2: Tuple[float, ...]) -> Tuple[float, ...]:
    """``m1 ∘ m2`` for row-vector points (``p·m1·m2``)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _transform_bbox(
    bbox: Tuple[float, float, float, float], m: Tuple[float, ...]
) -> Tuple[float, float, float, float]:
    a, b, c, d, e, f = m
    pts = ((bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[0], bbox[3]), (bbox[2], bbox[3]))
    xs = [a * x + c * y + e for x, y in pts]
    ys = [b * x + d * y + f for x, y in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_bottom_to_topleft(
    bbox: Tuple[float, float, float, float], page_h: float
) -> Tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (x0, page_h - y1, x1, page_h - y0)


def _decide(
    bbox_tl: Optional[Tuple[float, float, float, float]],
    color_space: str,
    comps_q: Tuple[int, ...],
    board_rect: Tuple[float, float, float, float],
    page_size: Tuple[float, float],
    tol_pt: float,
) -> str:
    """``"invert"`` or ``"keep"`` for one paint (top-left page coordinates)."""
    if bbox_tl is None:
        return "keep"
    x0, y0, x1, y1 = bbox_tl
    bx0, by0, bx1, by1 = board_rect
    t = tol_pt
    if x1 <= bx0 - t or x0 >= bx1 + t or y1 <= by0 - t or y0 >= by1 + t:
        return "keep"  # fully outside (with tolerance)
    pw, ph = page_size
    ox0, oy0 = max(0.0, x0), max(0.0, y0)
    ox1, oy1 = min(pw, x1), min(ph, y1)
    if ox1 > ox0 and oy1 > oy0 and (ox1 - ox0) * (oy1 - oy0) >= FULLPAGE_COVERAGE * pw * ph:
        if color_space == "gray":
            bright = comps_q[0] >= PLATE_MIN_CHANNEL
        elif color_space == "rgb":
            bright = min(comps_q) >= PLATE_MIN_CHANNEL
        else:
            bright = min(_cmyk_to_rgb_u8(*comps_q)) >= PLATE_MIN_CHANNEL
        if bright:
            return "keep"  # near-white full-page fill = background plate
        # full-page dark fill = the board itself (a full-bleed board is
        # impossible in page-mode detection, so this is a board with a thin
        # margin) → invert
        return "invert"
    if x0 >= bx0 - t and y0 >= by0 - t and x1 <= bx1 + t and y1 <= by1 + t:
        return "invert"  # fully inside (with tolerance)
    # straddles the board edge: board content bleeding slightly past the
    # detected rect is more common than margin content invading the board
    # (the verification gate, ADR 0008 D2, protects against mis-decisions).
    return "invert"


# ---------------------------------------------------------------------------
# tokenizer
# ---------------------------------------------------------------------------


@dataclass
class _Tok:
    kind: str  # num | name | string | hex | array | dict | op
    value: object  # float / str / List[_Tok] / None
    start: int
    end: int


def _scan_string(data: bytes, i: int) -> int:
    """``i`` at the opening ``(``; return index after the matching ``)``."""
    n = len(data)
    depth = 0
    j = i
    while j < n:
        c = data[j]
        if c == 0x5C:  # backslash escapes the next byte
            j += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise VectorUnsupported("unterminated literal string in content stream")


def _scan_dict(data: bytes, i: int) -> int:
    """``i`` at ``<<``; return index after the matching ``>>``."""
    n = len(data)
    depth = 0
    j = i
    while j < n:
        if data[j] == 0x3C and data[j + 1 : j + 2] == b"<":  # <<
            depth += 1
            j += 2
        elif data[j] == 0x3E and data[j + 1 : j + 2] == b">":  # >>
            depth -= 1
            if depth == 0:
                return j + 2
            j += 2
        elif data[j] == 0x28:  # ( — strings inside dicts
            j = _scan_string(data, j)
        else:
            j += 1
    raise VectorUnsupported("unterminated dictionary in content stream")


def _parse_one(data: bytes, i: int) -> Tuple[Optional[_Tok], int]:
    """Parse a single token (or whitespace/comment → ``None``) at ``i``."""
    n = len(data)
    while i < n:
        c = data[i]
        if c in _WS:
            return None, i + 1
        if c == 0x25:  # % comment
            j = data.find(b"\n", i)
            return None, (n if j < 0 else j)
        if c == 0x28:  # (
            j = _scan_string(data, i)
            return _Tok("string", None, i, j), j
        if c == 0x3C:  # <
            if data[i + 1 : i + 2] == b"<":
                j = _scan_dict(data, i)
                return _Tok("dict", None, i, j), j
            j = data.find(b">", i)
            if j < 0:
                raise VectorUnsupported("unterminated hex string")
            return _Tok("hex", None, i, j + 1), j + 1
        if c == 0x5B:  # [
            start = i
            i += 1
            items: List[_Tok] = []
            while True:
                tok, i = _parse_one(data, i)
                if tok is None:
                    if i >= n:
                        raise VectorUnsupported("unterminated array")
                    continue
                if tok.kind == "op" and tok.value == "]":
                    return _Tok("array", items, start, tok.end), tok.end
                items.append(tok)
            # unreachable
        if c == 0x2F:  # /
            j = i + 1
            while j < n and data[j] not in _DELIMS:
                j += 1
            return _Tok("name", data[i + 1 : j].decode("latin-1"), i, j), j
        m = _NUM_RE.match(data, i)
        if m:
            return _Tok("num", float(m.group(0)), i, m.end()), m.end()
        j = i
        while j < n and data[j] not in _DELIMS:
            j += 1
        if j == i:
            j = i + 1  # stray byte — consume defensively
        op = data[i:j].decode("latin-1")
        if op == "BI":
            raise VectorUnsupported("inline image (BI … EI) in content")
        return _Tok("op", op, i, j), j
    raise VectorUnsupported("unexpected end of content stream")


def _tokenize(data: bytes) -> List[_Tok]:
    toks: List[_Tok] = []
    i, n = 0, len(data)
    while i < n:
        tok, i = _parse_one(data, i)
        if tok is not None:
            toks.append(tok)
    return toks


# ---------------------------------------------------------------------------
# XObject tree helpers
# ---------------------------------------------------------------------------


def _resource_xobjects(doc, owner_xref: int) -> Dict[str, int]:
    """``{name: xref}`` for /Resources /XObject of *owner_xref*."""
    try:
        kind, val = doc.xref_get_key(owner_xref, "Resources")
    except Exception:
        return {}
    if kind == "xref":
        try:
            obj = doc.xref_object(int(val.split()[0]))
        except Exception:
            raise VectorUnsupported("unresolvable /Resources reference")
    elif kind == "dict":
        obj = val
    else:
        return {}
    m = re.search(r"/XObject\s*<<", obj)
    if not m:
        return {}
    inner = obj[m.end() - 2 :]
    try:
        end = _scan_dict(inner.encode("latin-1"), 0)
    except VectorUnsupported:
        return {}
    inner = inner[:end]
    out: Dict[str, int] = {}
    for name, num in re.findall(r"/([A-Za-z0-9_+\-.]+)\s+(\d+)\s+0\s+R", inner):
        out[name] = int(num)
    return out


def _xobject_subtype(doc, xref: int) -> str:
    try:
        kind, val = doc.xref_get_key(xref, "Subtype")
    except Exception:
        raise VectorUnsupported("XObject without readable /Subtype")
    if kind != "name":
        raise VectorUnsupported("XObject with non-name /Subtype")
    return val.lstrip("/")


_BBOX_RE = re.compile(r"/BBox\s*\[\s*([^\]]+)\]")
_MATRIX_RE = re.compile(r"/Matrix\s*\[\s*([^\]]+)\]")


def _xobject_bbox(doc, xref: int) -> Optional[Tuple[float, float, float, float]]:
    try:
        obj = doc.xref_object(xref)
    except Exception:
        return None
    m = _BBOX_RE.search(obj)
    if not m:
        return None
    try:
        vals = [float(v) for v in m.group(1).split()]
    except ValueError:
        return None
    if len(vals) != 4:
        return None
    return tuple(vals)  # type: ignore[return-value]


def _xobject_matrix(doc, xref: int) -> Tuple[float, ...]:
    try:
        obj = doc.xref_object(xref)
    except Exception:
        return IDENTITY
    m = _MATRIX_RE.search(obj)
    if not m:
        return IDENTITY
    try:
        vals = [float(v) for v in m.group(1).split()]
    except ValueError:
        raise VectorUnsupported("malformed XObject /Matrix")
    if len(vals) != 6:
        raise VectorUnsupported("malformed XObject /Matrix")
    return tuple(vals)  # type: ignore[return-value]


def _xobject_stream(doc, xref: int) -> bytes:
    try:
        data = doc.xref_stream(xref)
    except Exception:
        raise VectorUnsupported("unreadable XObject stream")
    return data if data is not None else b""


# ---------------------------------------------------------------------------
# stream rewriter
# ---------------------------------------------------------------------------


@dataclass
class _ColorState:
    """The colour the stream currently paints with (original values)."""

    space: str
    comps_q: Tuple[int, ...]
    orig: bytes  # the original operand+operator bytes (or the default)


#: "the stream currently paints the *original* colour" / "an inverted colour
#: inserted by the rewriter is in effect"
EFF_ORIG = "orig"
EFF_INV = "inverted"


class _StreamRewriter:
    """Rewrites one content stream (in memory; nothing is written yet).

    Original colour operands are never modified: for every paint whose
    geometric decision contradicts the colour currently in effect, an
    explicit colour operator is inserted before the paint's first operand.
    Inserting (instead of rewriting shared operands in place) is order-safe
    for any sequence of paints, and keeping the insertion outside the
    ``string Tj`` pair keeps MuPDF's text extraction working.
    """

    def __init__(
        self,
        doc,
        data: bytes,
        transform: FlatColorTransform,
        board_rect: Tuple[float, float, float, float],
        page_size: Tuple[float, float],
        tol_pt: float,
        res: Dict[str, int],
        ctm0: Tuple[float, ...] = IDENTITY,
    ):
        self.doc = doc
        self.data = data
        self.transform = transform
        self.board_rect = board_rect
        self.page_size = page_size
        self.tol_pt = tol_pt
        self.res = res
        self.toks = _tokenize(data)
        # output: token index -> insertions to place before that token
        self.insert_before: Dict[int, List[bytes]] = {}
        # graphics state
        self.stack: List[tuple] = []
        self.fill_space = "rgb"  # PDF default: DeviceRGB
        self.stroke_space = "rgb"
        self.fill_color: Optional[_ColorState] = None
        self.stroke_color: Optional[_ColorState] = None
        self.fill_eff = EFF_ORIG  # "orig" | "inverted"
        self.stroke_eff = EFF_ORIG
        self.ctm = ctm0
        # path
        self.pts: List[Tuple[float, float]] = []
        # text (rough estimate for the bbox decision)
        self.font_size = 12.0
        self.leading = 0.0
        self.tm = IDENTITY  # text matrix (axis-aligned enforced)
        # collected XObject descents: (name, xref, ctm_full_at_do)
        self.dos: List[Tuple[str, int, Tuple[float, ...]]] = []
        self._run()

    # -- helpers -------------------------------------------------------------

    def _lookback(self, idx: int, count: int) -> List[float]:
        vals = []
        j = idx - 1
        for _ in range(count):
            if j < 0 or self.toks[j].kind != "num":
                raise VectorUnsupported("malformed numeric operands")
            vals.append(self.toks[j].value)
            j -= 1
        vals.reverse()
        return vals

    def _page_bbox(self, bbox_local: Optional[Tuple[float, float, float, float]]):
        """Local path bbox → top-left page coordinates (None passthrough)."""
        if bbox_local is None:
            return None
        _, ph = self.page_size
        if self.ctm is not IDENTITY:
            bbox_local = _transform_bbox(bbox_local, self.ctm)
        return _bbox_bottom_to_topleft(bbox_local, ph)

    def _set_color(self, idx: int, op: str, space: str, ncomp: int, is_fill: bool) -> None:
        comps = self._lookback(idx, ncomp)
        first = idx - ncomp
        q = tuple(_quant(v) for v in comps)
        st = _ColorState(
            space=space,
            comps_q=q,
            orig=self.data[self.toks[first].start : self.toks[idx].end],
        )
        if is_fill:
            self.fill_color = st
            self.fill_eff = EFF_ORIG
        else:
            self.stroke_color = st
            self.stroke_eff = EFF_ORIG

    def _inverted_bytes(self, st: _ColorState) -> Optional[bytes]:
        """Encoded inverted colour for *st* (None: keep-exclusion applies)."""
        res = self.transform.apply(st.space, tuple(c / 255.0 for c in st.comps_q))
        if res is None:
            return None
        space, comps = res
        op = {"gray": b"g", "rgb": b"rg", "cmyk": b"k"}[space]
        return b" ".join(_fmt(v) for v in comps) + b" " + op

    def _decide_paint(self, idx: int, part: str, bbox_page, anchor: Optional[int] = None) -> None:
        is_fill = part == "fill"
        st = self.fill_color if is_fill else self.stroke_color
        if st is None:
            # PDF default colour (black DeviceRGB) never set explicitly
            st = _ColorState(space="rgb", comps_q=(0, 0, 0), orig=b"0 0 0 rg")
        eff = self.fill_eff if is_fill else self.stroke_eff
        decision = _decide(
            self._page_bbox(bbox_page),
            st.space,
            st.comps_q,
            self.board_rect,
            self.page_size,
            self.tol_pt,
        )
        want = decision == "invert"
        where = anchor if anchor is not None else idx

        def _insert(new_eff: str, b: bytes) -> None:
            self.insert_before.setdefault(where, []).append(b)
            if is_fill:
                self.fill_eff = new_eff
            else:
                self.stroke_eff = new_eff

        if want:
            new_bytes = self._inverted_bytes(st)
            if new_bytes is None:
                # keep-exclusion (colour mask / hex): the colour stays
                # original — restore it if an insertion is in effect
                if eff == EFF_INV:
                    _insert(EFF_ORIG, b" " + st.orig + b" ")
                return
            if eff == EFF_ORIG:
                _insert(EFF_INV, b" " + new_bytes + b" ")
        elif eff == EFF_INV:
            _insert(EFF_ORIG, b" " + st.orig + b" ")

    # -- main pass -------------------------------------------------------------

    def _run(self) -> None:
        for idx, tok in enumerate(self.toks):
            if tok.kind != "op":
                continue
            op = tok.value
            if op == "q":
                self.stack.append(
                    (
                        self.fill_space,
                        self.stroke_space,
                        self.fill_color,
                        self.stroke_color,
                        self.fill_eff,
                        self.stroke_eff,
                        self.ctm,
                    )
                )
            elif op == "Q":
                if self.stack:
                    (
                        self.fill_space,
                        self.stroke_space,
                        self.fill_color,
                        self.stroke_color,
                        self.fill_eff,
                        self.stroke_eff,
                        self.ctm,
                    ) = self.stack.pop()
            elif op == "cm":
                a, b, c, d, e, f = self._lookback(idx, 6)
                self.ctm = _compose((a, b, c, d, e, f), self.ctm)
            elif op in _COLOR_OPS:
                space, n, is_fill = _COLOR_OPS[op]
                self._set_color(idx, op, space, n, is_fill)
            elif op in ("sc", "SC"):
                space = self.fill_space if op == "sc" else self.stroke_space
                n = {"gray": 1, "rgb": 3, "cmyk": 4}[space]
                self._set_color(idx, op, space, n, op == "sc")
            elif op in ("scn", "SCN"):
                raise VectorUnsupported("scn/SCN (extended colour values)")
            elif op in ("cs", "CS"):
                if idx < 1 or self.toks[idx - 1].kind != "name":
                    raise VectorUnsupported("malformed colour space selection")
                nm = self.toks[idx - 1].value
                sp = {
                    "DeviceGray": "gray",
                    "DeviceRGB": "rgb",
                    "DeviceCMYK": "cmyk",
                }.get(nm)
                if sp is None:
                    raise VectorUnsupported(f"unsupported colour space /{nm}")
                if op == "cs":
                    self.fill_space = sp
                else:
                    self.stroke_space = sp
            elif op == "gs":
                raise VectorUnsupported("ExtGState (transparency/blend) in content")
            elif op == "sh":
                raise VectorUnsupported("shading operator")
            elif op == "BI":
                raise VectorUnsupported("inline image (BI … EI) in content")
            elif op == "Do":
                self._handle_do(idx)
            elif op in ("m", "l"):
                x, y = self._lookback(idx, 2)
                self.pts.append((x, y))
            elif op == "c":
                v = self._lookback(idx, 6)
                for p in range(3):
                    self.pts.append((v[2 * p], v[2 * p + 1]))
            elif op == "re":
                x, y, w, h = self._lookback(idx, 4)
                self.pts.extend([(x, y), (x + w, y), (x, y + h), (x + w, y + h)])
            elif op in ("f", "f*"):
                self._decide_paint(idx, "fill", self._path_bbox())
                self.pts = []
            elif op == "S":
                self._decide_paint(idx, "stroke", self._path_bbox())
                self.pts = []
            elif op in ("s", "b", "b*"):
                self._decide_paint(idx, "fill", self._path_bbox())
                self._decide_paint(idx, "stroke", self._path_bbox())
                self.pts = []
            elif op in ("n", "F", "W", "W*"):
                self.pts = []
            elif op == "BT":
                self.font_size = 12.0
                self.leading = 0.0
                self.tm = IDENTITY
            elif op == "ET":
                pass
            elif op == "Tf":
                if idx >= 2 and self.toks[idx - 1].kind == "num":
                    self.font_size = float(self.toks[idx - 1].value)
            elif op == "TL":
                self.leading = self._lookback(idx, 1)[0]
            elif op in ("Td", "TD"):
                tx, ty = self._lookback(idx, 2)
                self.tm = _compose((1.0, 0.0, 0.0, 1.0, tx, ty), self.tm)
            elif op == "Tm":
                a, b, c, d, e, f = self._lookback(idx, 6)
                if abs(b) > 1e-6 or abs(c) > 1e-6:
                    raise VectorUnsupported("rotated/skewed text matrix")
                self.tm = (a, 0.0, 0.0, d, e, f)
            elif op == "T*":
                self.tm = _compose(
                    (1.0, 0.0, 0.0, 1.0, 0.0, -self.leading or -self.font_size), self.tm
                )
            elif op in ("Tj", "TJ", "'", '"'):
                self._text_paint(idx)
            # everything else: ignore (operands stay untouched in the stream)

    def _path_bbox(self):
        if not self.pts:
            return None
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def _text_paint(self, idx: int) -> None:
        """Decision for a text-showing operator (rough bbox estimate)."""
        # string content: the single leading operand (Tj / ' / ") or the
        # array (TJ) — count characters for a width estimate.  Colour
        # insertions are anchored at this token: between the string and the
        # show operator would break MuPDF's text extraction.
        j = idx - 1
        while j >= 0 and self.toks[j].kind not in ("string", "hex", "array"):
            j -= 1
        if j < 0:
            raise VectorUnsupported("malformed text-showing operands")
        anchor = j
        t = self.toks[j]
        nchars = 0
        if t.kind == "string":
            nchars = max(1, (t.end - t.start) - 2)
        elif t.kind == "hex":
            nchars = max(1, (t.end - t.start - 2) // 2)
        elif t.kind == "array":
            for e in t.value:  # type: ignore[union-attr]
                if e.kind == "string":
                    nchars += max(1, (e.end - e.start) - 2)
                elif e.kind == "hex":
                    nchars += max(1, (e.end - e.start - 2) // 2)
        size = self.font_size
        a, _b, _c, d, e, f = self.tm
        sx, sy = size * a, size * d
        w_est = nchars * 0.5 * abs(sx)
        x0, x1 = (e, e + w_est) if sx >= 0 else (e - w_est, e)
        # top-left: text y is bottom-origin; flip via the local bbox helper
        bbox_local = (x0, f - 0.3 * abs(sy), x1, f + 0.9 * abs(sy))
        self._decide_paint(idx, "fill", bbox_local, anchor=anchor)
        self._decide_paint(idx, "stroke", bbox_local, anchor=anchor)
        # advance the text position for the next chunk
        self.tm = _compose(
            (1.0, 0.0, 0.0, 1.0, nchars * 0.5 * sx, 0.0), self.tm
        )

    def _handle_do(self, idx: int) -> None:
        if idx < 1 or self.toks[idx - 1].kind != "name":
            raise VectorUnsupported("malformed Do operator")
        nm = self.toks[idx - 1].value
        xref = self.res.get(nm)
        if xref is None:
            raise VectorUnsupported(f"unknown XObject /{nm}")
        sub = _xobject_subtype(self.doc, xref)
        if sub == "Form":
            self.dos.append((nm, xref, self.ctm))
        elif sub == "Image":
            # an image XObject has no /BBox: it occupies the unit square of
            # the current user space, so the CTM chain alone places it
            placed = _transform_bbox((0.0, 0.0, 1.0, 1.0), self.ctm)
            # an image is a raster: inside/near the board it would need
            # per-pixel inversion → v1 refuses (raster fallback)
            if _decide(
                _bbox_bottom_to_topleft(placed, self.page_size[1]),
                "rgb",
                (0, 0, 0),
                self.board_rect,
                self.page_size,
                self.tol_pt,
            ) != "keep":
                raise VectorUnsupported("image XObject inside/near board rect")
        else:
            raise VectorUnsupported(f"XObject subtype /{sub}")

    # -- output ----------------------------------------------------------------

    def result(self) -> bytes:
        d = self.data
        chunks: List[bytes] = []
        pos = 0
        for i, tok in enumerate(self.toks):
            chunks.append(d[pos : tok.start])
            if i in self.insert_before:
                chunks.extend(self.insert_before[i])
            chunks.append(d[tok.start : tok.end])
            pos = tok.end
        chunks.append(d[pos:])
        return b"".join(chunks)


# ---------------------------------------------------------------------------
# page-tree rewrite
# ---------------------------------------------------------------------------


def board_bg_levels(region: np.ndarray) -> np.ndarray:
    """p25 per BGR channel of *region*, clamped to ``[0, 220]``.

    Mirrors the ``B_c`` computation in
    :func:`smartboard_invert.processing.invert_or_remap` so the flat-colour
    remap matches the raster path exactly.
    """
    return np.clip(np.percentile(region, 25, axis=(0, 1)), 0.0, 220.0).astype(
        np.float32
    )


def rewrite_page_tree(
    doc,
    page,
    transform: FlatColorTransform,
    board_rect: Tuple[float, float, float, float],
    page_size: Tuple[float, float],
    tol_pt: float,
) -> List[Tuple[str, object, bytes]]:
    """Rewrite the page stream and every referenced Form XObject (recursive).

    Returns write-back instructions: ``("page", None, new_bytes)`` for the
    page content and ``("xref", xref, new_bytes)`` per XObject.  The caller
    applies them only after the whole tree has been rewritten without error
    (self-healing, ADR 0008 D2).

    *board_rect* is the detected board rect in top-left page coordinates of
    the copy page (the same space as ``rect_pt``).
    """
    page.clean_contents()
    page_res = _resource_xobjects(doc, page.xref)
    rw = _StreamRewriter(
        doc,
        page.read_contents(),
        transform,
        board_rect,
        page_size,
        tol_pt,
        res=page_res,
        ctm0=IDENTITY,
    )
    results: List[Tuple[str, object, bytes]] = [("page", None, rw.result())]

    seen: set = set()
    pending = list(rw.dos)
    while pending:
        name, xref, ctm_at_do = pending.pop()
        if xref in seen:
            continue
        seen.add(xref)
        matrix = _xobject_matrix(doc, xref)
        ctm0 = _compose(ctm_at_do, matrix)
        data = _xobject_stream(doc, xref)
        res = _resource_xobjects(doc, xref)
        sub_rw = _StreamRewriter(
            doc,
            data,
            transform,
            board_rect,
            page_size,
            tol_pt,
            res=res,
            ctm0=ctm0,
        )
        results.append(("xref", xref, sub_rw.result()))
        pending.extend(sub_rw.dos)
    return results
