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
from synth import A4_W, A4_H, DPI, changed_bbox, make_pdf, outside_mask


def process(tmp_path, pages, **kwargs):
    src = tmp_path / "in.pdf"
    truths = make_pdf(src, pages)
    dst = tmp_path / "out.pdf"
    result = process_pdf(src, dst, dpi=DPI, **kwargs)
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

    result = process_pdf(src, tmp_path / "out.pdf", dpi=DPI)
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
    result = process_pdf(src, tmp_path / "out.pdf", dpi=DPI)
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
    """With every transformation disabled the detected page is copied as-is."""
    pages = [{"kind": "image", "rect": (150, 150, 300, 550), "bg": (0, 0, 0)}]
    src, dst, truths, result = process(tmp_path, pages, invert=False, apply_clahe=False, clean=False)
    page = result.pages[0]
    assert page.detected
    assert page.method == "copy"
    a, b = renders(src, dst)
    assert cv2.absdiff(a[0], b[0]).max() == 0
