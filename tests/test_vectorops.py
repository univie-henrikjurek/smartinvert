"""Unit tests for the vector-preserving content-stream rewrite (ADR 0008).

Covers the tokenizer, the flat-colour math (exact counterpart of
``processing.invert_or_remap``), the geometry decision, the stream rewriter
(including shared colour operands, graphics-state save/restore, CTMs, text)
and the recursive page/XObject-tree rewrite.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from smartboard_invert import processing, vectorops
from smartboard_invert.vectorops import FlatColorTransform, VectorUnsupported

fitz = processing.fitz

#: A4 page, top-left board rect (same space as ``rect_pt``).
PAGE = (595.0, 842.0)
BOARD = (150.0, 150.0, 450.0, 550.0)

#: the encoded inversion of a flat 0.1/0.1/0.1 fill (quant 25 -> 230)
_INV_01 = b" ".join(vectorops._fmt(255 - vectorops._quant(0.1)) for _ in range(3)) + b" rg"


def _transform(
    bg_target=None,
    keep_colors=frozenset(),
    keep_segments=(),
    bg_levels=None,
) -> FlatColorTransform:
    return FlatColorTransform(bg_target, keep_colors, keep_segments, bg_levels)


def rewrite(data: bytes, **kw) -> bytes:
    """Run the stream rewriter (page level, no XObjects) and return output."""
    rw = vectorops._StreamRewriter(
        None, data, _transform(**kw), BOARD, PAGE, 2.0, res={}
    )
    return rw.result()


# ---------------------------------------------------------------------------
# tokenizer
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_mixed_tokens(self):
        toks = vectorops._tokenize(
            b"1.5 -2 .3 3e-2 /Name (str) <ab> [1 2] << /a 1 >> op"
        )
        assert [(t.kind, t.value) for t in toks if t.kind != "array"] == [
            ("num", 1.5),
            ("num", -2.0),
            ("num", 0.3),
            ("num", 0.03),
            ("name", "Name"),
            ("string", None),
            ("hex", None),
            ("dict", None),
            ("op", "op"),
        ]
        arr = [t for t in toks if t.kind == "array"][0]
        assert [(e.kind, e.value) for e in arr.value] == [("num", 1.0), ("num", 2.0)]

    def test_string_escapes_and_nesting(self):
        data = b"(a\\)b(c)d)"
        toks = vectorops._tokenize(data)
        assert len(toks) == 1
        assert toks[0].kind == "string"
        assert toks[0].end == len(data)

    def test_comment_skipped(self):
        toks = vectorops._tokenize(b"1 % a comment ( with parens\n2")
        assert [(t.kind, t.value) for t in toks] == [("num", 1.0), ("num", 2.0)]

    def test_array_with_nested_structures(self):
        toks = vectorops._tokenize(b"[(a) 1 /x] [2]")
        assert len(toks) == 2
        assert all(t.kind == "array" for t in toks)
        assert [e.kind for e in toks[0].value] == ["string", "num", "name"]

    def test_inline_image_raises(self):
        with pytest.raises(VectorUnsupported, match="inline image"):
            vectorops._tokenize(b"BI /W 8 /H 8 /CS /RGB /BPC 8 ID " + b"\x00" * 192 + b" EI")

    def test_unterminated_string_raises(self):
        with pytest.raises(VectorUnsupported, match="unterminated literal string"):
            vectorops._tokenize(b"(abc")

    def test_empty_stream(self):
        assert vectorops._tokenize(b"") == []


# ---------------------------------------------------------------------------
# flat colour math
# ---------------------------------------------------------------------------


class TestQuantAndFmt:
    @pytest.mark.parametrize("v, expect", [(0.0, 0), (0.5, 127), (0.999, 254), (1.0, 255), (1.5, 255), (-0.5, 0)])
    def test_quant_floor(self, v, expect):
        assert vectorops._quant(v) == expect

    @pytest.mark.parametrize("v", list(range(0, 256, 7)) + [0, 127, 128, 254, 255])
    def test_fmt_roundtrip(self, v):
        """The emitted literal must quantise back to the exact 8-bit value."""
        assert math.floor(float(vectorops._fmt(v)) * 255) == v

    def test_cmyk_rgb_exact_anchors(self):
        # the subtractive model is not injective at 8-bit, but anchors are exact
        for c, m, y, k in [(0, 0, 0, 0), (255, 0, 0, 0), (0, 0, 0, 255)]:
            r, g, b = vectorops._cmyk_to_rgb_u8(c, m, y, k)
            assert vectorops._rgb_to_cmyk_u8(r, g, b) == (c, m, y, k)

    def test_cmyk_rgb_double_conversion_stable(self):
        """The CMYK→RGB→CMYK→RGB double conversion is stable within 1 level
        (documented limitation; the raster ground-truth verification in the
        pipeline tolerates it, ADR 0008 D2)."""
        import itertools

        for c, m, y, k in itertools.product(range(0, 256, 17), repeat=4):
            rgb1 = vectorops._cmyk_to_rgb_u8(c, m, y, k)
            rgb2 = vectorops._cmyk_to_rgb_u8(*vectorops._rgb_to_cmyk_u8(*rgb1))
            assert max(abs(a - b) for a, b in zip(rgb1, rgb2)) <= 1


class TestFlatColorTransform:
    def test_complement_gray(self):
        t = _transform()
        assert t.apply("gray", (0.0,)) == ("gray", (255,))
        assert t.apply("gray", (1.0,)) == ("gray", (0,))

    def test_complement_rgb(self):
        t = _transform()
        # 0.1/0.2/0.3 quantise to (25, 51, 76) -> BGR (76, 51, 25)
        assert t.apply("rgb", (0.1, 0.2, 0.3)) == ("rgb", (230, 204, 179))

    def test_complement_cmyk(self):
        t = _transform()
        # CMYK (0,0,0,0) is white (no ink) -> black
        assert t.apply("cmyk", (0.0, 0.0, 0.0, 0.0)) == ("cmyk", (0, 0, 0, 255))
        assert t.apply("cmyk", (1.0, 0.0, 0.0, 0.0)) == ("cmyk", (0, 255, 255, 0))  # cyan -> red

    def test_keep_color_exclusion(self):
        t = _transform(keep_colors={"red"})
        assert t.apply("rgb", (1.0, 0.0, 0.0)) is None  # pure red stays
        assert t.apply("rgb", (0.5, 0.0, 0.0)) is None  # dominant red stays
        assert t.apply("rgb", (0.0, 1.0, 0.0)) == ("rgb", (255, 0, 255))  # green -> magenta

    def test_keep_hex_segment_point(self):
        t = _transform(keep_segments=(((255, 0, 0), (255, 0, 0)),))
        assert t.apply("rgb", (0.99, 0.01, 0.0)) is None  # near red: excluded
        assert t.apply("rgb", (0.0, 0.99, 0.01)) == ("rgb", (255, 3, 253))  # green: transformed

    def test_keep_hex_chroma_guard(self):
        """Neutral gray is never excluded by a hex spec (chroma guard)."""
        t = _transform(keep_segments=(((127, 127, 127), (127, 127, 127)),))
        assert t.apply("gray", (0.5,)) == ("gray", (128,))

    def test_bg_target_remap_anchors(self):
        # board bg BGR (20, 20, 25) (= RGB 25,20,20) -> target white
        t = _transform(bg_target=(255, 255, 255), bg_levels=np.array([20.0, 20.0, 25.0]))
        assert t.apply("rgb", (0.0, 0.0, 0.0)) == ("rgb", (255, 255, 255))  # dark -> white
        assert t.apply("rgb", (1.0, 1.0, 1.0)) == ("rgb", (0, 0, 0))  # white -> black
        # the board background lands exactly on the target
        assert t.apply("rgb", (25 / 255, 20 / 255, 20 / 255)) == ("rgb", (255, 255, 255))

    def test_bg_target_remap_emits_rgb(self):
        t = _transform(bg_target=(255, 255, 255), bg_levels=np.array([20.0, 20.0, 25.0]))
        # CMYK black (k=1) is dark -> lands on the white target
        space, comps = t.apply("cmyk", (0.0, 0.0, 0.0, 1.0))
        assert space == "rgb"  # per-channel scales differ -> DeviceRGB output
        assert comps == (255, 255, 255)


class TestBoardBgLevels:
    def test_p25(self):
        region = np.zeros((4, 4, 3), dtype=np.uint8)
        region[:, :, 0] = 20  # B
        region[:, :, 1] = 20  # G
        region[:, :, 2] = 25  # R
        np.testing.assert_array_equal(vectorops.board_bg_levels(region), [20.0, 20.0, 25.0])

    def test_clamped_to_220(self):
        region = np.full((4, 4, 3), 250, dtype=np.uint8)
        np.testing.assert_array_equal(vectorops.board_bg_levels(region), [220.0, 220.0, 220.0])


def test_aa_band_px():
    assert vectorops.aa_band_px(72) == 4
    assert vectorops.aa_band_px(150) == 6
    assert vectorops.aa_band_px(300) == 10


# ---------------------------------------------------------------------------
# geometry decision
# ---------------------------------------------------------------------------


class TestDecide:
    def _d(self, bbox_tl, comps_q=(30, 30, 30), space="rgb", tol=2.0):
        return vectorops._decide(bbox_tl, space, comps_q, BOARD, PAGE, tol)

    def test_outside(self):
        assert self._d((500.0, 600.0, 560.0, 700.0)) == "keep"
        assert self._d((10.0, 600.0, 80.0, 700.0)) == "keep"  # top margin

    def test_inside(self):
        assert self._d((200.0, 200.0, 300.0, 300.0)) == "invert"

    def test_straddles_edge(self):
        assert self._d((400.0, 200.0, 500.0, 300.0)) == "invert"

    def test_tolerance(self):
        # 1.5 pt outside the board (tol 2) still counts as "at the edge"
        assert self._d((448.5, 200.0, 520.0, 300.0)) == "invert"
        # 3 pt outside: clearly margin content
        assert self._d((453.0, 200.0, 560.0, 300.0)) == "keep"

    def test_fullpage_white_plate(self):
        assert self._d((0.0, 0.0, 595.0, 842.0), comps_q=(255, 255, 255)) == "keep"
        assert self._d((0.0, 0.0, 595.0, 842.0), comps_q=(240, 240, 240)) == "keep"

    def test_fullpage_dark_is_board(self):
        # a full-bleed dark fill cannot be a plate -> the board itself
        assert self._d((0.0, 0.0, 595.0, 842.0), comps_q=(30, 30, 30)) == "invert"
        # just below the near-white threshold: not a plate
        assert self._d((0.0, 0.0, 595.0, 842.0), comps_q=(199, 199, 199)) == "invert"

    def test_gray_plate(self):
        assert self._d((0.0, 0.0, 595.0, 842.0), comps_q=(250,), space="gray") == "keep"

    def test_cmyk_plate(self):
        # white in CMYK = (0,0,0,0)
        assert self._d((0.0, 0.0, 595.0, 842.0), comps_q=(0, 0, 0, 0), space="cmyk") == "keep"

    def test_none_bbox(self):
        assert self._d(None) == "keep"


# ---------------------------------------------------------------------------
# stream rewriter
# ---------------------------------------------------------------------------


class TestStreamRewriter:
    def test_inside_fill_inserts_inversion(self):
        out = rewrite(b"0.1 0.1 0.1 rg 200 300 100 100 re f")
        # the original operand is never modified ...
        assert b"0.1 0.1 0.1 rg 200 300 100 100 re" in out
        # ... an explicit inverted colour is inserted before the fill
        assert out.count(b"rg") == 2
        assert out.index(_INV_01) > out.index(b"100 100 re")
        assert out.rstrip().endswith(b"f")

    def test_outside_fill_kept(self):
        data = b"0.9 0.9 0.9 rg 500 700 50 50 re f"
        assert rewrite(data) == data  # margin content untouched, byte-for-byte

    def test_shared_operand_inside_then_outside(self):
        """One colour set for two paints (inside then outside): inversion is
        inserted for the first, the original re-inserted for the second."""
        data = b"0.1 0.1 0.1 rg 200 300 100 100 re f 500 700 50 50 re f"
        out = rewrite(data)
        assert out.count(b"0.1 0.1 0.1 rg") == 2  # original + restore
        first_fill = out.index(b"100 100 re")
        # inversion inserted for the first (inside) fill
        assert out.index(_INV_01) > first_fill
        # the original is restored between the second fill's re and f
        second_re = out.index(b"500 700 50 50 re")
        restore = out.index(b"0.1 0.1 0.1 rg", first_fill)
        assert second_re < restore
        assert out[restore + len(b"0.1 0.1 0.1 rg") :].lstrip()[:1] == b"f"

    def test_shared_operand_outside_then_inside(self):
        """The dangerous order: a keep paint comes *before* the invert paint
        and shares the colour operand.  The early paint must stay intact."""
        data = b"0.1 0.1 0.1 rg 500 700 50 50 re f 200 300 100 100 re f"
        out = rewrite(data)
        # the outside paint is untouched (no insertion between its re and f)
        assert b"0.1 0.1 0.1 rg 500 700 50 50 re f" in out
        # the inside paint gets its own inserted inversion
        assert _INV_01 in out
        assert out.count(b"0.1 0.1 0.1 rg") == 1

    def test_q_q_state_restore(self):
        data = (
            b"q 0.1 0.1 0.1 rg 200 300 100 100 re f Q "
            b"q 0.1 0.1 0.1 rg 500 700 50 50 re f Q"
        )
        out = rewrite(data)
        # second (outside) fill keeps the original value byte-for-byte
        assert b"0.1 0.1 0.1 rg 500 700 50 50 re f" in out
        # first (inside) fill has an insertion between its re and f
        assert b"0.1 0.1 0.1 rg 200 300 100 100 re f" not in out
        assert out.count(b"0.1 0.1 0.1 rg") == 2

    def test_cm_transform(self):
        # local rect (0,0,0.6,0.6) scaled x200 and moved to (200, 300):
        # page coords x 200..320, y(bottom) 300..420 -> inside the board
        out = rewrite(b"q 200 0 0 200 200 300 cm 0.1 0.1 0.1 rg 0 0 0.6 0.6 re f Q")
        assert _INV_01 in out  # inverted
        # same local rect moved outside the board (top margin)
        out2 = rewrite(b"q 200 0 0 200 200 700 cm 0.1 0.1 0.1 rg 0 0 0.6 0.6 re f Q")
        assert out2.count(b"rg") == 1  # kept, no insertion

    def test_fullpage_plate_kept(self):
        out = rewrite(b"0.99 0.99 0.99 rg 0 0 595 842 re f")
        assert out == b"0.99 0.99 0.99 rg 0 0 595 842 re f"

    def test_default_color_insertion_before_string(self):
        """Text without an explicit colour (PDF default black) inside the
        board gets an explicit inverted colour inserted *before the string
        operand* — between string and show operator would break MuPDF's text
        extraction."""
        out = rewrite(b"BT /F1 12 Tf 1 0 0 1 250 450 Tm (hello) Tj ET")
        assert b"1 1 1 rg" in out
        assert out.index(b"1 1 1 rg") < out.index(b"(hello)") < out.index(b"Tj")

    def test_text_outside_kept(self):
        data = b"BT /F1 12 Tf 1 0 0 1 520 750 Tm (side note) Tj ET"
        assert rewrite(data) == data

    def test_rotated_text_raises(self):
        with pytest.raises(VectorUnsupported, match="rotated/skewed text"):
            rewrite(b"BT /F1 12 Tf 0.7071 0.7071 -0.7071 0.7071 300 400 Tm (x) Tj ET")

    def test_gs_raises(self):
        with pytest.raises(VectorUnsupported, match="ExtGState"):
            rewrite(b"/GS0 gs")

    def test_sh_raises(self):
        with pytest.raises(VectorUnsupported, match="shading"):
            rewrite(b"100 100 100 100 re W n /Sh0 sh")

    def test_scn_raises(self):
        with pytest.raises(VectorUnsupported, match="scn/SCN"):
            rewrite(b"0.5 0.5 0.5 0 scn")

    def test_cs_non_device_raises(self):
        with pytest.raises(VectorUnsupported, match="unsupported colour space"):
            rewrite(b"/ICCSpace cs")
        with pytest.raises(VectorUnsupported, match="unsupported colour space"):
            rewrite(b"/CS0 CS")

    def test_cs_device_gray_switch(self):
        out = rewrite(b"0.1 g 200 300 100 100 re f")
        assert out != b"0.1 g 200 300 100 100 re f"
        assert b" g" in out and b" rg" not in out  # gray stays gray
        out2 = rewrite(b"0.1 0.1 0.1 rg 200 300 100 100 re f")
        assert b" rg" in out2

    def test_keep_color_in_stream(self):
        data = b"1 0 0 rg 200 300 100 100 re f"
        out = rewrite(data, keep_colors={"red"})
        assert out == data  # red stays red

    def test_stroke_color(self):
        out = rewrite(b"0.1 0.1 0.1 RG 200 300 m 300 300 l S")
        assert b"0.1 0.1 0.1 RG 200 300 m 300 300 l" in out  # original untouched
        assert _INV_01 in out  # inverted stroke colour inserted before S
        assert out.index(_INV_01) > out.index(b"300 300 l")

    def test_unknown_do_raises(self):
        with pytest.raises(VectorUnsupported, match="unknown XObject"):
            vectorops._StreamRewriter(None, b"/Nope Do", _transform(), BOARD, PAGE, 2.0, res={})

    def test_image_do_outside_board_ok(self):
        """An image XObject fully outside the board is tolerated (kept)."""
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # image xobject at the top margin (top-left 500..560 / 20..80)
        ix = doc.get_new_xref()
        doc.update_object(
            ix,
            "<< /Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceRGB "
            "/BitsPerComponent 8 /Length 0 >>",
        )
        doc.update_stream(ix, b"\x00" * 48)
        doc.xref_set_key(page.xref, "Resources", f"<< /XObject << /Im0 {ix} 0 R >> >>")
        res = {"Im0": ix}
        data = b"q 40 0 0 40 500 20 cm /Im0 Do Q"  # bottom-origin y=20 -> top 762..802
        rw = vectorops._StreamRewriter(doc, data, _transform(), BOARD, PAGE, 2.0, res=res)
        assert rw.result() == data  # untouched

    def test_image_do_inside_board_raises(self):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        ix = doc.get_new_xref()
        doc.update_object(
            ix,
            "<< /Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceRGB "
            "/BitsPerComponent 8 /Length 0 >>",
        )
        doc.update_stream(ix, b"\x00" * 48)
        doc.xref_set_key(page.xref, "Resources", f"<< /XObject << /Im0 {ix} 0 R >> >>")
        res = {"Im0": ix}
        # image at board centre (bottom-origin y ~ 350..390)
        data = b"q 40 0 0 40 250 350 cm /Im0 Do Q"
        with pytest.raises(VectorUnsupported, match="image XObject inside/near board"):
            vectorops._StreamRewriter(doc, data, _transform(), BOARD, PAGE, 2.0, res=res)


# ---------------------------------------------------------------------------
# page/XObject-tree rewrite (render-level)
# ---------------------------------------------------------------------------


def _make_form_board_doc(nested: bool = False, matrix=None):
    """A4 page: white full-page plate + board content in a Form XObject.

    The board (top-left 150,150 300x400) is a dark rect + white line; with
    *nested* the dark content sits in a second Form referenced from the first
    one; with *matrix* the inner form uses a scaling /Matrix.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y0, y1 = 842 - 550, 842 - 150  # bottom-origin board edges

    if nested:
        inner_x = doc.get_new_xref()
        inner_stream = (
            b"0.08 0.08 0.10 rg 150 292 300 400 re f\n"
            b"1 1 1 RG 1.5 w 200 500 m 400 500 l S"
        )
        doc.update_object(
            inner_x,
            "<< /Type /XObject /Subtype /Form /BBox [150 292 450 692] "
            "/Resources << >> /Length 0 >>",
        )
        doc.update_stream(inner_x, inner_stream)
        outer_stream = b"1 0 0 1 0 0 cm /Fm1 Do"
        outer_bbox = "150 292 450 692"
    elif matrix:
        # local rect (125,200,50,50) under /Matrix [2 0 0 2 0 0] lands at
        # page x 250..350, y(bottom) 400..500 -> inside the board
        inner_x = doc.get_new_xref()
        doc.update_object(
            inner_x,
            "<< /Type /XObject /Subtype /Form /BBox [100 150 225 275] "
            "/Matrix [2 0 0 2 0 0] /Resources << >> /Length 0 >>",
        )
        doc.update_stream(inner_x, b"0.1 0.1 0.1 rg 125 200 50 50 re f")
        outer_stream = b"1 0 0 1 0 0 cm /Fm1 Do"
        outer_bbox = "150 292 450 692"
    else:
        inner_x = None
        outer_stream = (
            b"0.08 0.08 0.10 rg 150 292 300 400 re f\n"
            b"1 1 1 RG 1.5 w 200 500 m 400 500 l S"
        )
        outer_bbox = "150 292 450 692"

    inner_res = f"/XObject << /Fm1 {inner_x} 0 R >>" if inner_x else ""
    fxref = doc.get_new_xref()
    doc.update_object(
        fxref,
        f"<< /Type /XObject /Subtype /Form /BBox [{outer_bbox}] "
        f"/Resources << {inner_res} >> /Length 0 >>",
    )
    doc.update_stream(fxref, outer_stream)
    page_stream = b"0.99 0.99 0.99 rg 0 0 595 842 re f\nq 1 0 0 1 0 0 cm /Fm0 Do Q"
    cxref = doc.get_new_xref()
    doc.update_object(cxref, "<< /Length 0 >>")
    doc.update_stream(cxref, page_stream)
    page.set_contents(cxref)
    doc.xref_set_key(page.xref, "Resources", f"<< /XObject << /Fm0 {fxref} 0 R >> >>")
    return doc, page, fxref, inner_x


def _apply(doc, page, results):
    for target, xref, data in results:
        if target == "page":
            nx = doc.get_new_xref()
            doc.update_object(nx, "<< /Length 0 >>")
            doc.update_stream(nx, data)
            page.set_contents(nx)
        else:
            doc.update_stream(xref, data)


def _render(doc, page):
    pix = page.get_pixmap(dpi=72)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


class TestRewritePageTree:
    def _rewrite(self, doc, page, **kw):
        results = vectorops.rewrite_page_tree(
            doc, page, _transform(**kw), BOARD, PAGE, 2.0
        )
        _apply(doc, page, results)
        return results

    def test_flat_form_board_inverted_plate_kept(self):
        doc, page, fxref, _ = _make_form_board_doc()
        results = self._rewrite(doc, page)
        assert any(t == "xref" and x == fxref for t, x, _ in results)
        img = _render(doc, page)
        # board interior (top-left 160..440 x 160..540) becomes light
        assert img[160:540, 160:440].reshape(-1, 3).mean() > 180
        # margin stays the (kept) white plate
        assert img[10:50, 10:50].reshape(-1, 3).mean() > 245

    def test_nested_form(self):
        doc, page, _, inner_x = _make_form_board_doc(nested=True)
        results = self._rewrite(doc, page)
        assert any(t == "xref" and x == inner_x for t, x, _ in results)
        img = _render(doc, page)
        assert img[160:540, 160:440].reshape(-1, 3).mean() > 180
        assert img[10:50, 10:50].reshape(-1, 3).mean() > 245

    def test_matrix_scaled_form(self):
        doc, page, _, inner_x = _make_form_board_doc(matrix=True)
        self._rewrite(doc, page)
        img = _render(doc, page)
        # scaled rect at page x 250..350, top y 342..442 -> inverted (light)
        assert img[350:430, 260:340].reshape(-1, 3).mean() > 180
        # board area outside the scaled rect still shows the plate? No: the
        # form only contains that rect; the rest is the white page plate
        assert img[10:50, 10:50].reshape(-1, 3).mean() > 245

    def test_unsupported_inside_form_raises_and_leaves_doc(self):
        """A ``sh`` deep in the XObject tree must abort the whole rewrite
        with *nothing* written back (self-healing, ADR 0008 D2)."""
        doc, page, fxref, _ = _make_form_board_doc()
        sx = doc.get_new_xref()
        doc.update_object(
            sx,
            "<< /Type /Shading /ShadingType 2 /ColorSpace /DeviceRGB "
            "/Coords [200 300 300 400] /Function << /FunctionType 2 /Domain [0 1] "
            "/C0 [1 1 1] /C1 [0 0 0] /BitsPerSample 8 /Matrix [1 0 0 1 0 0] >> "
            "/Extend [true true] >>",
        )
        doc.update_stream(fxref, doc.xref_stream(fxref) + b"\n100 100 100 100 re W n /Sh0 sh")
        doc.xref_set_key(fxref, "Resources", f"<< /Shading << /Sh0 {sx} 0 R >> >>")
        before = _render(doc, page)
        with pytest.raises(VectorUnsupported, match="shading"):
            vectorops.rewrite_page_tree(doc, page, _transform(), BOARD, PAGE, 2.0)
        # the render is unchanged: nothing was written back (the pipeline
        # falls back to the raster path on the exception)
        np.testing.assert_array_equal(_render(doc, page), before)
