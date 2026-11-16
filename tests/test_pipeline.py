"""End-to-end pipeline tests (synthetic PDFs, the 8 mandatory scenarios).

Scenarios (task section 8):
1. white page + black smartboard rectangle
2. white page + dark-gray smartboard rectangle
3. white page + rectangle at different positions
4. multi-page PDF
5. PDF without a recognizable smartboard area
6. pixels outside the detected area remain unchanged
7. white text appears dark after inversion
8. PDF page size remains unchanged
plus: vector boards (like inputs/test.pdf), ambiguity, input immutability,
guards against overwriting the input.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from smartboard_invert import process_pdf
from smartboard_invert.processing import SmartboardError, fitz, pdf_to_images

import synth
from synth import A4_W, A4_H, DPI, board_image, changed_bbox, make_pdf, outside_mask, PX_PER_PT


def process(tmp_path, pages, crop=False, **kwargs):
    """Run ``process_pdf`` on a synthetic document.

    ``crop=False`` is pinned as the test-suite default (ADR 0006 made crop
    the production default, but most of the suite validates the
    page-faithful behaviour); crop tests pass ``crop=True`` explicitly.
    """
    src = tmp_path / "in.pdf"
    truths = make_pdf(src, pages)
    dst = tmp_path / "out.pdf"
    result = process_pdf(src, dst, dpi=DPI, crop=crop, **kwargs)
    return src, dst, truths, result


def renders(src: Path, dst: Path):
    return pdf_to_images(src, dpi=DPI), pdf_to_images(dst, dpi=DPI)


def page_sizes_equal(src: Path, dst: Path) -> bool:
    a, b = fitz.open(str(src)), fitz.open(str(dst))
    try:
        if a.page_count != b.page_count:
            return False
        return all(a[i].rect == b[i].rect for i in range(a.page_count))
    finally:
        a.close()
        b.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- 1. white page + black smartboard rectangle ---------------------------


def test_black_board(tmp_path):
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert page.detected, page.message
    assert page.method == "image-replace"
    assert page.confidence >= 0.5
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]
    # outside the ground-truth board: pixel identical
    mask = outside_mask(gt, a[0].shape[:2], inflate=8)
    assert cv2.absdiff(a[0], b[0])[mask].max() == 0
    # inside: strongly inverted
    inside = ~mask
    assert cv2.absdiff(a[0], b[0])[inside].mean() > 50
    # changed pixels stay inside the ground-truth rectangle (no crop/move)
    cb = changed_bbox(a[0], b[0])
    assert cb is not None
    assert cb[0] >= gt[0] - 10 and cb[1] >= gt[1] - 10
    assert cb[2] <= gt[2] + 10 and cb[3] <= gt[3] + 10


# --- 2. white page + dark-gray smartboard rectangle ------------------------


def test_dark_gray_board(tmp_path):
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (60, 60, 60)}]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert page.detected, page.message
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]
    # sample a text-free strip (top 6% of the board) to check the background
    h = int(gt[3]) - int(gt[1])
    strip = np.s_[int(gt[1]) + 2 : int(gt[1]) + max(8, h // 16), int(gt[0]) : int(gt[2])]
    g_in = cv2.cvtColor(a[0], cv2.COLOR_BGR2GRAY)[strip]
    g_out = cv2.cvtColor(b[0], cv2.COLOR_BGR2GRAY)[strip]
    assert g_in.mean() < 100
    assert g_out.mean() > 180
    assert abs(g_out.mean() + g_in.mean() - 255) < 25  # ≈ 255 − v


# --- 3. rectangle at different positions -----------------------------------


@pytest.mark.parametrize(
    "rect",
    [
        (60, 60, 200, 300),  # top-left
        (200, 296, 200, 250),  # center
        (350, 480, 190, 280),  # bottom-right
    ],
)
def test_board_different_positions(tmp_path, rect):
    pages = [{"kind": "image", "rect": rect, "bg": (15, 15, 15)}]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert page.detected, page.message
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]
    mask = outside_mask(gt, a[0].shape[:2], inflate=8)
    assert cv2.absdiff(a[0], b[0])[mask].max() == 0
    cb = changed_bbox(a[0], b[0])
    assert cb is not None
    assert cb[0] >= gt[0] - 10 and cb[1] >= gt[1] - 10
    assert cb[2] <= gt[2] + 10 and cb[3] <= gt[3] + 10


# --- 4. multi-page PDF ------------------------------------------------------


def test_multipage_mixed(tmp_path):
    pages = [
        {"kind": "image", "rect": (100, 100, 250, 500), "bg": (0, 0, 0)},
        {"kind": "vector", "rect": (300, 100, 200, 500), "bg": (40, 40, 45)},
        {"kind": "blank", "marks": [(100, 100, 20, 40), (200, 400, 20, 40)]},
    ]
    src, dst, truths, result = process(tmp_path, pages)
    assert len(result.pages) == 3
    assert result.pages[0].detected and result.pages[0].method == "image-replace"
    assert result.pages[1].detected and result.pages[1].method == "rerasterize"
    assert not result.pages[2].detected
    assert result.pages[2].method == "copy"
    a, b = renders(src, dst)
    assert len(a) == len(b) == 3
    # page 3 (no board) is pixel-identical (lossless copy)
    assert cv2.absdiff(a[2], b[2]).max() == 0
    # page 1: outside unchanged
    gt = truths[0]["rect_px"]
    mask = outside_mask(gt, a[0].shape[:2], inflate=8)
    assert cv2.absdiff(a[0], b[0])[mask].max() == 0
    # page 2 (vector): outside nearly unchanged, inside inverted
    gt2 = truths[1]["rect_px"]
    diff2 = cv2.absdiff(a[1], b[1])
    mask2 = outside_mask(gt2, a[1].shape[:2], inflate=8)
    assert diff2[mask2].mean() < 0.5
    assert diff2[~mask2].mean() > 30
    # page sizes all preserved
    assert page_sizes_equal(src, dst)


# --- 5. PDF without a recognizable smartboard area --------------------------


def test_no_board_page_unchanged(tmp_path, caplog):
    pages = [
        {"kind": "blank", "marks": [(100, 100, 20, 40), (200, 400, 20, 40), (300, 600, 20, 40)]}
    ]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert not page.detected
    assert page.method == "copy"
    a, b = renders(src, dst)
    assert cv2.absdiff(a[0], b[0]).max() == 0  # pixel-identical output page
    with caplog.at_level("WARNING", logger="smartboard_invert.pdfpipeline"):
        assert any("no unambiguous" in r.message.lower() for r in caplog.records)
    assert dst.is_file()


def test_two_boards_ambiguous_unchanged(tmp_path):
    """Two large dark rectangles on ONE page → not unambiguous → unchanged."""
    pages = [
        {
            "kind": "image",
            "multi": True,
            "rect": [(60, 100, 180, 600), (330, 100, 180, 600)],
            "bg": (0, 0, 0),
            "text": False,
        }
    ]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert not page.detected
    assert page.method == "copy"
    a, b = renders(src, dst)
    assert cv2.absdiff(a[0], b[0]).max() == 0


# --- 6. pixels outside the detected area remain unchanged -------------------


def test_outside_detected_area_unchanged(tmp_path):
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (20, 20, 25)}]
    src, dst, truths, result = process(tmp_path, pages)
    assert result.pages[0].detected
    rect_px = result.pages[0].rect_px  # the *detected* rect, not the ground truth
    a, b = renders(src, dst)
    mask = outside_mask(rect_px, a[0].shape[:2])
    diff = cv2.absdiff(a[0], b[0])
    assert diff[mask].max() == 0


# --- 7. white text appears dark after inversion -----------------------------


def test_white_text_becomes_dark(tmp_path):
    pages = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (10, 10, 10), "text": True, "seed": 0}
    ]
    src, dst, truths, result = process(tmp_path, pages)
    assert result.pages[0].detected
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]
    inside = outside_mask(gt, a[0].shape[:2], inflate=-5)  # strictly inside
    inside = ~inside
    # white pixels of the original (text) inside the board
    white_in = inside & (cv2.cvtColor(a[0], cv2.COLOR_BGR2GRAY) > 245)
    assert white_in.sum() > 500, "fixture must contain white text"
    out_gray = cv2.cvtColor(b[0], cv2.COLOR_BGR2GRAY)
    assert out_gray[white_in].max() < 40  # white text is now dark


# --- 8. PDF page size remains unchanged -------------------------------------


def test_page_size_preserved(tmp_path):
    pages = [
        {"kind": "image", "rect": (100, 100, 250, 500), "bg": (0, 0, 0)},
        {"kind": "vector", "rect": (300, 100, 200, 500), "bg": (40, 40, 45)},
        {"kind": "blank", "marks": []},
    ]
    src, dst, truths, result = process(tmp_path, pages)
    doc_in, doc_out = fitz.open(str(src)), fitz.open(str(dst))
    try:
        assert doc_in.page_count == doc_out.page_count == 3
        for i in range(3):
            assert doc_in[i].rect == doc_out[i].rect == fitz.Rect(0, 0, A4_W, A4_H)
            assert doc_in[i].mediabox == doc_out[i].mediabox
    finally:
        doc_in.close()
        doc_out.close()


# --- additional scenarios ----------------------------------------------------


def test_vector_board_like_sample(tmp_path):
    """Vector-drawn board (like inputs/test.pdf) via the rerasterize path."""
    pages = [{"kind": "vector", "rect": (147, 10, 299, 822), "bg": (19, 21, 25)}]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert page.detected, page.message
    assert page.method == "rerasterize"
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]
    diff = cv2.absdiff(a[0], b[0])
    mask = outside_mask(gt, a[0].shape[:2], inflate=8)
    assert diff[mask].max() <= 8  # reraster tolerance (ADR 0001 D3)
    assert diff[~mask].mean() > 50
    g_in = cv2.cvtColor(a[0], cv2.COLOR_BGR2GRAY)
    g_out = cv2.cvtColor(b[0], cv2.COLOR_BGR2GRAY)
    box = np.s_[int(gt[1]) : int(gt[3]), int(gt[0]) : int(gt[2])]
    assert g_in[box].mean() < 80
    assert g_out[box].mean() > 180


def test_board_with_white_border_keeps_border(tmp_path):
    """A white border inside the board image stays white after inversion."""
    pages = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (15, 15, 15), "border": 20, "text": False}
    ]
    src, dst, truths, result = process(tmp_path, pages)
    assert result.pages[0].detected
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]
    # the ring between the image bbox and the dark area is the white border
    x0 = int(150 * synth.PX_PER_PT)
    y0 = int(150 * synth.PX_PER_PT)
    x1 = int((150 + 300) * synth.PX_PER_PT)
    y1 = int((150 + 550) * synth.PX_PER_PT)
    border_mask = outside_mask(gt, a[0].shape[:2]) & (
        (np.indices(a[0].shape[:2])[1][:, None] < x1)
    )
    # simpler: check the top border strip (above the dark area, inside the image)
    strip = b[0][y0 + 2 : int(gt[1]) - 2, x0 + 50 : x1 - 50]
    assert strip.shape[0] > 0
    assert cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).mean() > 240  # still white


def test_input_file_not_modified(tmp_path):
    src = tmp_path / "in.pdf"
    make_pdf(src, [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}])
    before = sha256(src)
    dst = tmp_path / "out.pdf"
    process_pdf(src, dst, dpi=DPI)  # first run
    process_pdf(src, dst, dpi=DPI)  # second run over the same input
    assert sha256(src) == before  # input untouched after both runs


def test_output_must_differ_from_input(tmp_path):
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
    src = tmp_path / "in.pdf"
    make_pdf(src, pages)
    before = sha256(src)
    with pytest.raises(SmartboardError, match="differ"):
        process_pdf(src, src)
    assert sha256(src) == before


def test_corrupt_input_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(SmartboardError):
        process_pdf(bad, tmp_path / "out.pdf")


def test_bad_dpi_raises(tmp_path):
    pages = [{"kind": "blank", "marks": []}]
    src = tmp_path / "in.pdf"
    make_pdf(src, pages)
    with pytest.raises(SmartboardError, match="dpi"):
        process_pdf(src, tmp_path / "out.pdf", dpi=5)


def test_debug_images_written(tmp_path):
    pages = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
        {"kind": "blank", "marks": [(100, 100, 20, 40)]},
    ]
    src = tmp_path / "in.pdf"
    make_pdf(src, pages)
    debug_dir = tmp_path / "outputs" / "debug"
    result = process_pdf(src, tmp_path / "outputs" / "in.pdf", dpi=DPI, debug_dir=debug_dir)
    files = sorted(debug_dir.glob("*_debug.png"))
    assert len(files) == 2
    img = cv2.imread(str(files[0]))
    assert img is not None
    assert img.shape[2] == 3
    # composite must be wider than a single panel (3 panels + separators)
    single = synth.page_render(src)
    assert img.shape[1] > 2 * single.shape[1]


def test_rotated_image_placement_uses_fallback(tmp_path):
    """A non-axis-aligned image (rotate=90) cannot be replaced in place →
    the rerasterize fallback must be used, page size/position preserved."""
    import cv2

    from smartboard_invert.processing import fitz

    src = tmp_path / "rot.pdf"
    doc = fitz.open()
    page = doc.new_page(width=A4_W, height=A4_H)
    img = synth.board_image(600, 1100, bg=(15, 15, 15), text=True, seed=0)
    ok, png = cv2.imencode(".png", img)
    page.insert_image(fitz.Rect(150, 200, 450, 500), stream=png.tobytes(), rotate=90)
    doc.save(str(src))
    doc.close()

    result = process_pdf(src, tmp_path / "out.pdf", dpi=DPI, crop=False)
    page_res = result.pages[0]
    assert page_res.detected
    assert page_res.method == "rerasterize"
    # outside the detected rect: unchanged
    a, b = renders(src, tmp_path / "out.pdf")
    mask = outside_mask(page_res.rect_px, a[0].shape[:2], inflate=8)
    assert cv2.absdiff(a[0], b[0])[mask].max() <= 8
    assert cv2.absdiff(a[0], b[0])[~mask].mean() > 50
    assert page_sizes_equal(src, tmp_path / "out.pdf")


def test_progress_callback(tmp_path):
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}] * 3
    src = tmp_path / "in.pdf"
    make_pdf(src, pages)
    calls = []
    process_pdf(
        src,
        tmp_path / "out.pdf",
        dpi=DPI,
        progress=lambda n, total: calls.append((n, total)),
    )
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_page_error_is_reraised_and_doc_closed(tmp_path, monkeypatch):
    """A page-level error must propagate (and not leave a corrupt output)."""
    import smartboard_invert.pdfpipeline as pipeline

    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
    src = tmp_path / "in.pdf"
    make_pdf(src, pages)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "_process_page", boom)
    with pytest.raises(RuntimeError, match="boom"):
        process_pdf(src, tmp_path / "out.pdf", dpi=DPI)
    assert not (tmp_path / "out.pdf").exists()


def test_rotated_page_copied_unchanged(tmp_path, caplog):
    """A page with /Rotate != 0 is a documented fail-safe (A-11): copied
    unchanged with a warning (no risky pixel mapping on rotated pages)."""
    import cv2

    from smartboard_invert.processing import fitz

    src = tmp_path / "rot_page.pdf"
    doc = fitz.open()
    page = doc.new_page(width=A4_W, height=A4_H)
    img = synth.board_image(600, 1100, bg=(15, 15, 15), text=False)
    ok, png = cv2.imencode(".png", img)
    page.insert_image(fitz.Rect(150, 200, 450, 500), stream=png.tobytes())
    page.set_rotation(90)
    doc.save(str(src))
    doc.close()

    with caplog.at_level("WARNING", logger="smartboard_invert.pdfpipeline"):
        result = process_pdf(src, tmp_path / "out.pdf", dpi=DPI)
    page_res = result.pages[0]
    assert not page_res.detected
    assert page_res.method == "copy"
    assert any("rotation" in r.message.lower() for r in caplog.records)
    a, b = renders(src, tmp_path / "out.pdf")
    assert cv2.absdiff(a[0], b[0]).max() == 0  # pixel-identical copy


def test_thin_white_border_not_inverted_full_coverage(tmp_path):
    """An image that is >95% dark with a thin (~2%) white inner border:
    the full-coverage native detection must not drag the border into the
    inversion – the border stays white (inversion follows the page-level
    rectangle, ADR 0001)."""
    pages = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (15, 15, 15), "border": 4, "text": False}
    ]
    src, dst, truths, result = process(tmp_path, pages)
    page = result.pages[0]
    assert page.detected, page.message
    assert page.method == "image-replace"
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]  # dark area (border already excluded)
    # the border strip above the dark area (inside the image bbox) stays white
    img_x0 = int(150 * synth.PX_PER_PT)
    img_y0 = int(150 * synth.PX_PER_PT)
    strip = b[0][img_y0 + 1 : int(gt[1]) - 1, img_x0 + 40 : img_x0 + 560]
    assert strip.shape[0] > 0
    assert cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY).mean() > 240
    # outside the detected rect: unchanged; inside: inverted
    mask = outside_mask(page.rect_px, a[0].shape[:2])
    assert cv2.absdiff(a[0], b[0])[mask].max() == 0
    assert cv2.absdiff(a[0], b[0])[~mask].mean() > 50


def test_image_replace_failure_falls_back_to_rerasterize(tmp_path, monkeypatch):
    """If the image replacement fails (decode/replace error), the page must
    fall back to re-rasterization with unchanged outside pixels and preserved
    page size."""
    import smartboard_invert.pdfpipeline as pipeline

    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
    src = tmp_path / "in.pdf"
    truths = make_pdf(src, pages)
    monkeypatch.setattr(pipeline, "_try_image_replace", lambda *a, **k: False)
    result = process_pdf(src, tmp_path / "out.pdf", dpi=DPI, crop=False)
    page_res = result.pages[0]
    assert page_res.detected
    assert page_res.method == "rerasterize"
    a, b = renders(src, tmp_path / "out.pdf")
    gt = truths[0]["rect_px"]
    mask = outside_mask(gt, a[0].shape[:2], inflate=8)
    assert cv2.absdiff(a[0], b[0])[mask].max() <= 8
    assert cv2.absdiff(a[0], b[0])[~mask].mean() > 30
    assert page_sizes_equal(src, tmp_path / "out.pdf")


def test_invert_disabled_copies_page(tmp_path):
    """With the transformation disabled the detected page is copied as-is."""
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
    src, dst, truths, result = process(tmp_path, pages, invert=False)
    page = result.pages[0]
    assert page.detected
    assert page.method == "copy"
    a, b = renders(src, dst)
    assert cv2.absdiff(a[0], b[0]).max() == 0


# --- crop post-stage (ADR 0003) ----------------------------------------------


def assert_crop_matches_faithful(
    crop_img: np.ndarray,
    faith_img: np.ndarray,
    rect_px,
    out_w: float = None,
    out_h: float = None,
) -> None:
    """Compare one cropped page render with the rect slice of the faithful
    (crop=False) render of the same page at the same dpi (ADR 0003, D1/D5).

    * The render shape must equal the cropped page size in points at ``DPI``
      (±1 px for MuPDF's MediaBox rounding).
    * The 2-px-eroded inner area must be pixel-identical (max diff 0).
    * The full area may only differ in the ≤1-px boundary resampling phase:
      mean diff < 0.5 and < 1 % of the pixels differing.
    """
    if out_w is not None and out_h is not None:
        exp_h = round(out_h * DPI / 72)
        exp_w = round(out_w * DPI / 72)
        assert crop_img.shape[0] == pytest.approx(exp_h, abs=1), (
            f"crop render height {crop_img.shape[0]} != expected {exp_h} (±1 px)"
        )
        assert crop_img.shape[1] == pytest.approx(exp_w, abs=1), (
            f"crop render width {crop_img.shape[1]} != expected {exp_w} (±1 px)"
        )
    x0, y0 = int(rect_px[0]), int(rect_px[1])
    h, w = crop_img.shape[:2]
    slice_img = faith_img[y0 : y0 + h, x0 : x0 + w]
    assert slice_img.shape == crop_img.shape, (
        f"faithful slice shape {slice_img.shape} != crop render shape {crop_img.shape}"
    )
    diff = cv2.absdiff(crop_img, slice_img)
    inner_max = int(diff[2:-2, 2:-2].max())
    assert inner_max == 0, f"eroded 2px inner must be pixel-identical (max diff {inner_max})"
    mean = float(diff.mean())
    assert mean < 0.5, f"full-region mean diff {mean} >= 0.5"
    frac = float((diff.max(axis=2) > 0).mean())
    assert frac < 0.01, f"{frac:.4%} of the pixels differ (>= 1 %)"


class TestCropGeometry:
    """crop=True: board pages are re-wrapped to the board rect, pages without
    a board stay full; page count and order are preserved (ADR 0003, D1/D3)."""

    PAGES = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
        {"kind": "vector", "rect": (300, 100, 200, 500), "bg": (40, 40, 45)},
        {"kind": "blank", "marks": []},
    ]

    @pytest.fixture
    def run(self, tmp_path):
        src, dst, truths, result = process(tmp_path, self.PAGES, crop=True)
        return src, dst, truths, result

    def test_page_count_and_order_preserved(self, run):
        src, dst, truths, result = run
        assert len(result.pages) == 3
        doc = fitz.open(str(dst))
        try:
            assert doc.page_count == 3
        finally:
            doc.close()
        imgs = pdf_to_images(dst, dpi=DPI)
        assert len(imgs) == 3
        # The order is pinned by per-page size + content: page 0 = inverted
        # image board, page 1 = inverted vector board, page 2 = untouched
        # blank page (still white).
        gray = [cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) for im in imgs]
        assert gray[0].mean() > 100  # dark board inverted -> mostly light
        assert gray[1].mean() > 100  # dark vector board inverted -> mostly light
        assert gray[2].mean() > 245  # blank page: still white

    def test_output_rects_match_board_rects(self, run):
        src, dst, truths, result = run
        doc = fitz.open(str(dst))
        try:
            r0, r1, r2 = (doc[i].rect for i in range(3))
        finally:
            doc.close()
        # page 0: image board (150,150,300,550) -> (0,0,300,550) ±0.5 pt
        assert r0.x0 == pytest.approx(0, abs=0.5)
        assert r0.y0 == pytest.approx(0, abs=0.5)
        assert r0.width == pytest.approx(300, abs=0.5)
        assert r0.height == pytest.approx(550, abs=0.5)
        # page 1: vector board 200x500 (position irrelevant after the crop)
        assert r1.x0 == pytest.approx(0, abs=0.5)
        assert r1.y0 == pytest.approx(0, abs=0.5)
        assert r1.width == pytest.approx(200, abs=0.5)
        assert r1.height == pytest.approx(500, abs=0.5)
        # page 2: no board -> full A4, unchanged
        assert r2 == fitz.Rect(0, 0, A4_W, A4_H)
        # and exactly the *detected* rect (floats passed through, no rounding)
        for i, rect in enumerate((r0, r1)):
            pr = result.pages[i]
            assert rect.width == pytest.approx(pr.rect_pt[2] - pr.rect_pt[0], abs=0.5)
            assert rect.height == pytest.approx(pr.rect_pt[3] - pr.rect_pt[1], abs=0.5)

    def test_cropped_flags(self, run):
        src, dst, truths, result = run
        assert [p.cropped for p in result.pages] == [True, True, False]

    def test_summary_reports_cropped_pages(self, run):
        src, dst, truths, result = run
        s = result.summary()
        assert "cropped to board rect" in s
        assert "2 cropped" in s


class TestCropPixelEquivalence:
    """The crop render of a board page must match the rect slice of a
    SEPARATE faithful (crop=False) run on the same input (ADR 0003, D1:
    vector-exact re-wrap, no re-rasterization).  Covers all three output
    methods: image-replace, rerasterize, copy (detected, untransformed)."""

    PAGES = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
        {"kind": "vector", "rect": (300, 100, 200, 500), "bg": (40, 40, 45)},
        {"kind": "blank", "marks": []},
    ]

    @pytest.fixture
    def runs(self, tmp_path):
        src = tmp_path / "in.pdf"
        truths = make_pdf(src, self.PAGES)
        dst_crop = tmp_path / "crop.pdf"
        dst_faith = tmp_path / "faithful.pdf"
        res_crop = process_pdf(src, dst_crop, dpi=DPI, crop=True)
        res_faith = process_pdf(src, dst_faith, dpi=DPI, crop=False)
        return src, dst_crop, dst_faith, truths, res_crop, res_faith

    @pytest.mark.parametrize(
        "page_index, method",
        [(0, "image-replace"), (1, "rerasterize")],
        ids=["image-replace", "rerasterize"],
    )
    def test_crop_render_matches_faithful_slice(self, runs, page_index, method):
        src, dst_crop, dst_faith, truths, res_crop, _ = runs
        pr = res_crop.pages[page_index]
        assert pr.detected and pr.cropped
        assert pr.method == method
        crop_imgs = pdf_to_images(dst_crop, dpi=DPI)
        faith_imgs = pdf_to_images(dst_faith, dpi=DPI)
        doc = fitz.open(str(dst_crop))
        try:
            out_rect = doc[page_index].rect
        finally:
            doc.close()
        assert_crop_matches_faithful(
            crop_imgs[page_index],
            faith_imgs[page_index],
            pr.rect_px,
            out_w=out_rect.width,
            out_h=out_rect.height,
        )

    def test_crop_render_copy_method_matches_faithful(self, tmp_path):
        """Third method: detected but untransformed page (invert off) ->
        'copy'; it is still cropped and still pixel-equivalent."""
        pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
        src = tmp_path / "in.pdf"
        make_pdf(src, pages)
        no_transform = dict(invert=False)
        res_crop = process_pdf(src, tmp_path / "crop.pdf", dpi=DPI, crop=True, **no_transform)
        process_pdf(src, tmp_path / "faithful.pdf", dpi=DPI, crop=False, **no_transform)
        pr = res_crop.pages[0]
        assert pr.detected and pr.method == "copy" and pr.cropped
        crop_imgs = pdf_to_images(tmp_path / "crop.pdf", dpi=DPI)
        faith_imgs = pdf_to_images(tmp_path / "faithful.pdf", dpi=DPI)
        doc = fitz.open(str(tmp_path / "crop.pdf"))
        try:
            out_rect = doc[0].rect
        finally:
            doc.close()
        assert_crop_matches_faithful(
            crop_imgs[0],
            faith_imgs[0],
            pr.rect_px,
            out_w=out_rect.width,
            out_h=out_rect.height,
        )


class TestCropRotation:
    """Mixed doc: the /Rotate=90 page (A-11: detection never runs on rotated
    pages) stays full and pixel-identical; the board page is cropped
    (ADR 0003, D1)."""

    @pytest.fixture
    def mixed(self, tmp_path):
        src = tmp_path / "rot_mixed.pdf"
        doc = fitz.open()
        # page 0: board image + /Rotate 90 (same fixture as
        # test_rotated_page_copied_unchanged)
        page = doc.new_page(width=A4_W, height=A4_H)
        img = synth.board_image(600, 1100, bg=(15, 15, 15), text=False)
        ok, png = cv2.imencode(".png", img)
        assert ok
        page.insert_image(fitz.Rect(150, 200, 450, 500), stream=png.tobytes())
        page.set_rotation(90)
        # page 1: image board (150, 150, 300, 550)
        page = doc.new_page(width=A4_W, height=A4_H)
        img = synth.board_image(600, 1100, bg=(0, 0, 0), text=True, seed=0)
        ok, png = cv2.imencode(".png", img)
        assert ok
        page.insert_image(fitz.Rect(150, 150, 450, 700), stream=png.tobytes())
        doc.save(str(src))
        doc.close()
        res_crop = process_pdf(src, tmp_path / "crop.pdf", dpi=DPI, crop=True)
        process_pdf(src, tmp_path / "faithful.pdf", dpi=DPI, crop=False)
        return src, tmp_path / "crop.pdf", tmp_path / "faithful.pdf", res_crop

    def test_rotated_page_copied_full_and_pixel_identical(self, mixed):
        src, dst_crop, _, res_crop = mixed
        p0 = res_crop.pages[0]
        assert p0.detected is False
        assert p0.cropped is False
        doc = fitz.open(str(dst_crop))
        try:
            r0 = doc[0].rect
            rot0 = doc[0].rotation
        finally:
            doc.close()
        # full A4 in the visual (rotated) orientation, /Rotate preserved
        assert rot0 == 90
        assert r0.width == pytest.approx(A4_H, abs=0.5)  # 842
        assert r0.height == pytest.approx(A4_W, abs=0.5)  # 595
        a = pdf_to_images(src, dpi=DPI)
        b = pdf_to_images(dst_crop, dpi=DPI)
        assert cv2.absdiff(a[0], b[0]).max() == 0  # pixel-identical to input

    def test_board_page_cropped_and_pixel_equivalent(self, mixed):
        src, dst_crop, dst_faith, res_crop = mixed
        p1 = res_crop.pages[1]
        assert p1.detected is True
        assert p1.cropped is True
        crop_imgs = pdf_to_images(dst_crop, dpi=DPI)
        faith_imgs = pdf_to_images(dst_faith, dpi=DPI)
        doc = fitz.open(str(dst_crop))
        try:
            r1 = doc[1].rect
        finally:
            doc.close()
        assert r1.width == pytest.approx(300, abs=0.5)
        assert r1.height == pytest.approx(550, abs=0.5)
        assert_crop_matches_faithful(
            crop_imgs[1], faith_imgs[1], p1.rect_px, out_w=r1.width, out_h=r1.height
        )


class TestCropNoBoard:
    def test_blank_doc_stays_page_faithful(self, tmp_path, caplog):
        """No board on any page: output is the page-faithful document
        (never an empty file) + a summary warning (ADR 0003, D1)."""
        pages = [{"kind": "blank", "marks": [(100, 100, 20, 40), (200, 400, 20, 40)]}]
        src = tmp_path / "in.pdf"
        make_pdf(src, pages)
        dst = tmp_path / "out.pdf"
        with caplog.at_level("WARNING", logger="smartboard_invert.pdfpipeline"):
            result = process_pdf(src, dst, dpi=DPI, crop=True)
        assert len(result.pages) == 1
        assert result.pages[0].detected is False
        assert result.pages[0].cropped is False
        doc = fitz.open(str(dst))
        try:
            assert doc.page_count == 1
            r = doc[0].rect
        finally:
            doc.close()
        assert r.width == pytest.approx(A4_W, abs=0.5)
        assert r.height == pytest.approx(A4_H, abs=0.5)
        a = pdf_to_images(src, dpi=DPI)
        b = pdf_to_images(dst, dpi=DPI)
        assert cv2.absdiff(a[0], b[0]).max() == 0  # pixel-identical output page
        assert any("no page has a detected board" in r.message for r in caplog.records)
        assert dst.is_file() and dst.stat().st_size > 0

    def test_mixed_doc_warns_per_no_board_page(self, tmp_path, caplog):
        """Each no-board page of a mixed doc gets its own 'copied in full'
        warning; the board page is cropped (ADR 0003, D1)."""
        pages = [
            {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
            {"kind": "blank", "marks": [(100, 100, 20, 40)]},
        ]
        src = tmp_path / "in.pdf"
        make_pdf(src, pages)
        with caplog.at_level("WARNING", logger="smartboard_invert.pdfpipeline"):
            result = process_pdf(src, tmp_path / "out.pdf", dpi=DPI, crop=True)
        assert result.pages[0].cropped is True
        assert result.pages[1].cropped is False
        full = [r for r in caplog.records if "copied in full" in r.message]
        assert len(full) == 1
        assert "Page 2" in full[0].message


class TestCropRegression:
    def test_default_run_matches_explicit_crop(self, tmp_path):
        """ADR 0006: crop is the production default – the default run must be
        pixel-identical to an explicit crop=True run, and an explicit
        crop=False run must keep the page-faithful sizes (ADR 0003, D5)."""
        pages = [
            {"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)},
            {"kind": "vector", "rect": (300, 100, 200, 500), "bg": (40, 40, 45)},
            {"kind": "blank", "marks": [(100, 100, 20, 40)]},
        ]
        src = tmp_path / "in.pdf"
        make_pdf(src, pages)
        process_pdf(src, tmp_path / "default.pdf", dpi=DPI)  # crop default (on)
        process_pdf(src, tmp_path / "crop.pdf", dpi=DPI, crop=True)
        process_pdf(src, tmp_path / "faithful.pdf", dpi=DPI, crop=False)
        d = pdf_to_images(tmp_path / "default.pdf", dpi=DPI)
        c = pdf_to_images(tmp_path / "crop.pdf", dpi=DPI)
        a, f = renders(src, tmp_path / "faithful.pdf")
        assert len(d) == len(c) == len(f) == 3
        # default run == explicit crop run, pixel-identical
        for i in range(3):
            assert d[i].shape == c[i].shape
            assert cv2.absdiff(d[i], c[i]).max() == 0
        # board pages: crop shrinks the page, faithful run keeps the input size
        assert f[0].shape == a[0].shape
        assert d[0].shape[:2] != f[0].shape[:2]
        # no-board page: identical across all runs
        assert d[2].shape == f[2].shape
        assert cv2.absdiff(d[2], f[2]).max() == 0


class TestCropOffsetPageBox:
    """ADR 0007, D1: pages whose MediaBox/CropBox does not start at (0,0)
    (common for phone/app PDF exports) must crop to exactly the same content
    as the faithful render slice.  The former ``show_pdf_page(clip=…)``
    approach mis-clipped such pages (user report v0.7.1: thin frame, large
    white area, a document strip in the middle)."""

    def _offset_pdf(self, tmp_path: Path, offset=(100, 100), use_cropbox=True) -> Path:
        """A4-sized page whose visible box starts at *offset* instead of
        (0,0); the board image sits at page coords (150,150)-(450,550)."""
        import cv2

        src = tmp_path / "in.pdf"
        doc = fitz.open()
        page = doc.new_page(width=A4_W, height=A4_H)
        img = synth.board_image(600, 1200, bg=(20, 20, 25), text=True, seed=1)
        ok, png = cv2.imencode(".png", img)
        page.insert_image(fitz.Rect(150, 150, 450, 550), stream=png.tobytes())
        xref = page.xref
        box = f"[{offset[0]} {offset[1]} {offset[0] + A4_W:.0f} {offset[1] + A4_H:.0f}]"
        doc.xref_set_key(xref, "MediaBox", box)
        doc.xref_set_key(xref, "CropBox", box if use_cropbox else "null")
        doc.save(str(src))
        doc.close()
        return src

    @pytest.mark.parametrize(
        "use_cropbox", [True, False], ids=["offset-cropbox", "offset-mediabox-only"]
    )
    def test_cropped_matches_faithful_slice(self, tmp_path, use_cropbox):
        src = self._offset_pdf(tmp_path, use_cropbox=use_cropbox)
        res_crop = process_pdf(src, tmp_path / "crop.pdf", dpi=DPI, crop=True)
        process_pdf(src, tmp_path / "faith.pdf", dpi=DPI, crop=False)
        pr = res_crop.pages[0]
        assert pr.detected and pr.cropped
        crop_imgs = pdf_to_images(tmp_path / "crop.pdf", dpi=DPI)
        faith_imgs = pdf_to_images(tmp_path / "faith.pdf", dpi=DPI)
        doc = fitz.open(str(tmp_path / "crop.pdf"))
        try:
            out_rect = doc[0].rect
        finally:
            doc.close()
        assert_crop_matches_faithful(
            crop_imgs[0],
            faith_imgs[0],
            pr.rect_px,
            out_w=out_rect.width,
            out_h=out_rect.height,
        )
        # page size == the board rect, independent of the page origin
        assert out_rect.width == pytest.approx(
            pr.rect_pt[2] - pr.rect_pt[0], abs=0.5
        )
        assert out_rect.height == pytest.approx(
            pr.rect_pt[3] - pr.rect_pt[1], abs=0.5
        )


class TestCropDefensiveRotationMath:
    """ADR 0003, D2 (defensive branch): ``rect * page.derotation_matrix`` maps
    a visual-space rect back into the unrotated page space.

    The ADR's r=90 formula/value was corrected on 2026-11-15 (the original
    draft confounded x and y, yielding a 350x350 square for a 200x350 rect –
    geometrically impossible).  The values asserted here match the corrected
    ADR (D2) and were independently verified against PyMuPDF's
    ``derotation_matrix`` and the ADR's own documentation example
    ("unrotiert (0,0) -> visual (842,0)").
    """

    @pytest.mark.parametrize(
        ("rotation", "expected"),
        [
            (90, (50.0, 542.0, 400.0, 742.0)),
            (180, (295.0, 442.0, 495.0, 792.0)),
            (270, (195.0, 100.0, 545.0, 300.0)),
        ],
    )
    def test_derotation_matrix_maps_visual_to_unrotated(self, tmp_path, rotation, expected):
        src = tmp_path / f"rot_{rotation}.pdf"
        doc = fitz.open()
        page = doc.new_page(width=A4_W, height=A4_H)
        page.set_rotation(rotation)
        doc.save(str(src))
        doc.close()
        doc = fitz.open(str(src))
        try:
            u = fitz.Rect(100, 50, 300, 400) * doc[0].derotation_matrix
        finally:
            doc.close()
        for got, exp in zip((u.x0, u.y0, u.x1, u.y1), expected):
            assert got == pytest.approx(exp, abs=1e-6)

# --- Phase 3: bg_target + keep_colors (ADR 0002, P3-FR-9/10) ------------------


class TestProcessPdfPhase3Validation:
    """process_pdf validates bg_target / keep_colors (P3-FR-9/10) before any
    page processing."""

    @pytest.fixture()
    def blank_pdf(self, tmp_path):
        src = tmp_path / "in.pdf"
        make_pdf(src, [{"kind": "blank", "marks": []}])
        return src

    def test_unknown_keep_color_raises(self, blank_pdf, tmp_path):
        with pytest.raises(SmartboardError, match="unknown color"):
            process_pdf(blank_pdf, tmp_path / "o.pdf", keep_colors={"red", "magenta"})

    @pytest.mark.parametrize(
        "bg_target",
        [
            (255, 255),  # not 3 channels
            (255, 255, 256),  # > 255
            (255, 255, -1),  # < 0
            "255,255,255",  # string is not a sequence of ints
            (True, 0, 0),  # bool is not an int channel
        ],
    )
    def test_invalid_bg_target_raises(self, blank_pdf, tmp_path, bg_target):
        with pytest.raises(SmartboardError, match="bg_target"):
            process_pdf(blank_pdf, tmp_path / "o.pdf", bg_target=bg_target)

    def test_list_bg_target_accepted_and_normalized(self, blank_pdf, tmp_path):
        """A 3-element list is accepted (normalized to a tuple) – no error."""
        dst = tmp_path / "o.pdf"
        result = process_pdf(blank_pdf, dst, dpi=DPI, bg_target=[10, 20, 30])
        assert dst.is_file()
        assert len(result.pages) == 1


#: Image-kind board 300x550 pt at the default scale 2.0 -> 600x1100 px image.
NATIVE_W, NATIVE_H = 600, 1100
#: Markers as ((x, y, w, h) in image px, BGR colour); both inside the board.
RED_MARK = ((100, 400, 80, 60), (20, 20, 220))  # BGR: red marker
GREEN_MARK = ((350, 700, 80, 60), (20, 200, 20))  # BGR: green marker


def _phase3_pages():
    """Dark-gray board (~35,30,30 BGR) with white chalk text and red/green
    marker rectangles (synth ground truth: rect_px/rect_pt of the board)."""
    return [
        {
            "kind": "image",
            "rect": (150, 150, 300, 550),
            "bg": (35, 30, 30),
            "text": True,
            "seed": 0,
            "marks": [RED_MARK, GREEN_MARK],
        }
    ]


def _marker_render_box(mark, rect_pt):
    """Render-pixel box (at DPI) of a marker drawn in native image pixels."""
    (mx, my, mw, mh), _color = mark
    sx = (rect_pt[2] - rect_pt[0]) * PX_PER_PT / NATIVE_W
    sy = (rect_pt[3] - rect_pt[1]) * PX_PER_PT / NATIVE_H
    x0 = rect_pt[0] * PX_PER_PT + mx * sx
    y0 = rect_pt[1] * PX_PER_PT + my * sy
    return x0, y0, x0 + mw * sx, y0 + mh * sy


def test_phase3_remap_to_white_keeps_markers(tmp_path):
    """P3-FR-9/10 E2E: board remapped onto pure white, chalk dark, red/green
    markers keep their original colour."""
    src, dst, truths, result = process(
        tmp_path, _phase3_pages(), bg_target=(255, 255, 255), keep_colors={"red", "green"}
    )
    page = result.pages[0]
    assert page.detected, page.message
    assert page.method == "image-replace"
    a, b = renders(src, dst)
    gt = truths[0]["rect_px"]

    # (1) board background -> target white (tolerance +/-10 for resampling)
    strip = b[0][int(gt[1]) + 10 : int(gt[1]) + 60, int(gt[0]) + 50 : int(gt[2]) - 50]
    assert strip.shape[0] > 0
    for c in range(3):
        assert abs(float(strip[..., c].mean()) - 255.0) <= 10

    # (2) white chalk text -> dark
    inside = ~outside_mask(gt, a[0].shape[:2], inflate=-5)
    white_in = inside & (cv2.cvtColor(a[0], cv2.COLOR_BGR2GRAY) > 245)
    assert white_in.sum() > 500, "fixture must contain white text"
    assert cv2.cvtColor(b[0], cv2.COLOR_BGR2GRAY)[white_in].max() < 80

    # (3) markers keep their original colour: inner pixels strict (+/-5),
    #     whole mark tolerant to resampling at the edges (mean <= 15)
    rect_pt = truths[0]["rect_pt"]
    for mark in (RED_MARK, GREEN_MARK):
        x0, y0, x1, y1 = _marker_render_box(mark, rect_pt)
        color = np.asarray(mark[1], dtype=np.int16)
        inner = b[0][
            int(y0 + 0.25 * (y1 - y0)) : int(y1 - 0.25 * (y1 - y0)),
            int(x0 + 0.25 * (x1 - x0)) : int(x1 - 0.25 * (x1 - x0)),
        ]
        whole = b[0][int(y0) : int(y1), int(x0) : int(x1)]
        assert np.abs(inner.astype(np.int16) - color).max() <= 5
        assert np.abs(whole.astype(np.int16) - color).mean() <= 15


def test_phase3_default_complement_transforms_markers(tmp_path):
    """Same input with v0.4.1 parameters (bg_target=None, keep_colors empty):
    the markers are NOT kept -> bitwise_not(original).  Proves the effect of
    the Phase 3 flags (they change the result)."""
    src, dst, truths, result = process(
        tmp_path, _phase3_pages(), bg_target=None, keep_colors=frozenset()
    )
    page = result.pages[0]
    assert page.detected, page.message
    a, b = renders(src, dst)
    rect_pt = truths[0]["rect_pt"]
    for mark in (RED_MARK, GREEN_MARK):
        x0, y0, x1, y1 = _marker_render_box(mark, rect_pt)
        inner = b[0][
            int(y0 + 0.25 * (y1 - y0)) : int(y1 - 0.25 * (y1 - y0)),
            int(x0 + 0.25 * (x1 - x0)) : int(x1 - 0.25 * (x1 - x0)),
        ]
        expected = np.bitwise_not(np.asarray(mark[1], dtype=np.uint8)).astype(np.int16)
        assert np.abs(inner.astype(np.int16) - expected).max() <= 5


def test_phase3_bit_exact_v041_regression(tmp_path):
    """P3-D-1 regression: with the v0.4.1 parameters (bg_target=None,
    keep_colors=frozenset()) the in-region transformation must stay
    bit-identical to v0.4.1.  Code inspection: the legacy path in
    ``processing.invert_or_remap`` is exactly ``np.bitwise_not(region)`` on
    uint8 (== 255 - v, no float round-trip).

    Verified at the most accessible point – the board image XObject of the
    image-replace output is bit-wise ``np.bitwise_not`` of the embedded
    original image (a possible <= 2 px border ring stays untouched because
    the conservative page-rect -> image-rect mapping clips boundary rows).
    A second run with the same v0.4.1 parameters renders pixel-identical
    pages (determinism; the only bytes that differ between the raw PDF files
    are the random /ID trailer, not the content).
    """
    pages = [
        {"kind": "image", "rect": (150, 150, 300, 550), "bg": (20, 20, 25), "text": True, "seed": 0}
    ]
    native = board_image(NATIVE_W, NATIVE_H, bg=(20, 20, 25), text=True, seed=0)
    src, dst, truths, result = process(tmp_path, pages, bg_target=None, keep_colors=frozenset())
    page = result.pages[0]
    assert page.detected, page.message
    assert page.method == "image-replace"
    # built-in verification (ADR 0001 D3): nothing outside the detected rect
    assert page.verification.get("outside_max_diff") == 0

    doc = fitz.open(str(dst))
    try:
        infos = doc[0].get_image_info(xrefs=True)
        assert len(infos) == 1
        info = doc.extract_image(int(infos[0]["xref"]))
    finally:
        doc.close()
    out_img = cv2.imdecode(np.frombuffer(info["image"], np.uint8), cv2.IMREAD_COLOR)
    assert out_img is not None and out_img.shape == native.shape

    # interior: bit-exact legacy transformation
    assert np.array_equal(out_img[2:-2, 2:-2], np.bitwise_not(native)[2:-2, 2:-2])
    # every NOT transformed pixel (== original; 255 - v has no fixed point)
    # must lie in the <= 2 px border ring
    untouched = (out_img == native).all(axis=2)
    ring = np.ones(native.shape[:2], dtype=bool)
    ring[2:-2, 2:-2] = False
    assert not (untouched & ~ring).any()

    # determinism: a second run with the v0.4.1 parameters renders
    # pixel-identical pages
    dst2 = tmp_path / "out2.pdf"
    process_pdf(
        src, dst2, dpi=DPI, crop=False, bg_target=None, keep_colors=frozenset()
    )
    assert np.array_equal(pdf_to_images(dst, dpi=DPI)[0], pdf_to_images(dst2, dpi=DPI)[0])


# --- Phase 3: keep_hex (ADR 0004, P3-FR-11) --------------------------------


class TestKeepHexPipeline:
    """P3-FR-11 / ADR 0004: explicit hex specs through process_pdf – the
    union with keep_colors, the precedence, the bit-identical regression for
    the empty default, and the validation before any file work."""

    BLUE_MARK = ((100, 400, 80, 60), (255, 0, 0))  # BGR: pure blue (RGB 0000FF)
    BLUE_AXIS = (((0, 0, 1), (0, 0, 255)),)

    def _pages(self):
        """Dark-gray board with white chalk text and a pure-blue marker."""
        return [
            {
                "kind": "image",
                "rect": (150, 150, 300, 550),
                "bg": (35, 30, 30),
                "text": True,
                "seed": 0,
                "marks": [self.BLUE_MARK],
            }
        ]

    def _inner_box(self, dst, rect_pt):
        """Render-pixel box (quarter inset) of the blue mark on the output."""
        x0, y0, x1, y1 = _marker_render_box(self.BLUE_MARK, rect_pt)
        a = pdf_to_images(dst, dpi=DPI)[0]
        return a[
            int(y0 + 0.25 * (y1 - y0)) : int(y1 - 0.25 * (y1 - y0)),
            int(x0 + 0.25 * (x1 - x0)) : int(x1 - 0.25 * (x1 - x0)),
        ]

    def test_blue_mark_preserved_by_hex_range(self, tmp_path):
        """E2E: the pure-blue marker keeps its original colour when the blue
        axis range is kept; the board background is still transformed."""
        src, dst, truths, result = process(
            tmp_path,
            self._pages(),
            keep_colors=frozenset(),
            keep_segments=self.BLUE_AXIS,
        )
        page = result.pages[0]
        assert page.detected, page.message
        assert page.method == "image-replace"
        # built-in verification: nothing outside the detected rect changed
        assert page.verification.get("outside_max_diff") == 0

        inner = self._inner_box(dst, truths[0]["rect_pt"])
        color = np.asarray(self.BLUE_MARK[1], dtype=np.int16)
        assert np.abs(inner.astype(np.int16) - color).max() <= 5

    def test_blue_mark_transformed_without_keep_hex(self, tmp_path):
        """Same input, empty keep_segments: the blue marker is inverted
        (complement of RGB 0000FF is RGB FFFF00 – the blue channel drops)."""
        src, dst, truths, result = process(
            tmp_path, self._pages(), keep_colors=frozenset(), keep_segments=()
        )
        assert result.pages[0].detected, result.pages[0].message
        inner = self._inner_box(dst, truths[0]["rect_pt"])
        # BGR channel 0 = blue: after the strict complement it is ~0,
        # channels 1/2 (green/red) are ~255
        assert float(inner[..., 0].mean()) < 30
        assert float(inner[..., 1].mean()) > 200
        assert float(inner[..., 2].mean()) > 200

    def test_union_with_keep_colors(self, tmp_path):
        """Hex exclusions union with the name-based ones (independent
        effects on different pixels)."""
        red_mark = ((350, 700, 80, 60), (20, 20, 220))  # BGR: red marker
        pages = self._pages()
        pages[0]["marks"] = [self.BLUE_MARK, red_mark]
        src, dst, truths, result = process(
            tmp_path,
            pages,
            keep_colors=frozenset({"red"}),
            keep_segments=self.BLUE_AXIS,
        )
        assert result.pages[0].detected, result.pages[0].message
        a = pdf_to_images(dst, dpi=DPI)[0]
        rect_pt = truths[0]["rect_pt"]
        for mark, expected_bgr in (
            (self.BLUE_MARK, np.asarray(self.BLUE_MARK[1], dtype=np.int16)),
            (red_mark, np.asarray(red_mark[1], dtype=np.int16)),
        ):
            x0, y0, x1, y1 = _marker_render_box(mark, rect_pt)
            inner = a[
                int(y0 + 0.25 * (y1 - y0)) : int(y1 - 0.25 * (y1 - y0)),
                int(x0 + 0.25 * (x1 - x0)) : int(x1 - 0.25 * (x1 - x0)),
            ]
            assert np.abs(inner.astype(np.int16) - expected_bgr).max() <= 5

    def test_empty_keep_segments_bit_identical_to_v050(self, tmp_path):
        """ADR 0004 D3 regression: keep_segments=() must produce exactly the
        v0.5.0 output (empty = no hex exclusion at all)."""
        src = tmp_path / "in.pdf"
        make_pdf(src, self._pages())
        dst1 = tmp_path / "out1.pdf"
        dst2 = tmp_path / "out2.pdf"
        process_pdf(src, dst1, dpi=DPI, keep_colors=frozenset())
        process_pdf(src, dst2, dpi=DPI, keep_colors=frozenset(), keep_segments=())
        assert np.array_equal(pdf_to_images(dst1, dpi=DPI)[0], pdf_to_images(dst2, dpi=DPI)[0])

    @pytest.mark.parametrize(
        "keep_segments",
        [
            None,
            42,
            "000001-0000FF",  # the CLI string is not a tuple of segments
            (((256, 0, 0), (0, 0, 0)),),
            (((True, 0, 0), (0, 0, 0)),),
            (((255, 0), (255, 0, 0)),),
        ],
    )
    def test_invalid_keep_segments_raise_before_any_file_work(
        self, tmp_path, keep_segments
    ):
        src = tmp_path / "in.pdf"
        make_pdf(src, [{"kind": "blank", "marks": []}])
        dst = tmp_path / "out.pdf"
        with pytest.raises(SmartboardError):
            process_pdf(src, dst, dpi=DPI, keep_segments=keep_segments)
        assert not dst.exists(), "validation must happen before any output"
