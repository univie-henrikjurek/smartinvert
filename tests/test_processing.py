"""Tests for smartboard_invert.processing (render, invert_region, enhance)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from smartboard_invert import processing
from smartboard_invert.processing import fitz

from tests.synth import board_image

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "test.pdf"

# A4 @150dpi render size
W, H = 1240, 1755


def make_page(board_rect, bg=(20, 20, 25), white_holes=True):
    img = np.full((H, W, 3), 255, dtype=np.uint8)
    x0, y0, x1, y1 = board_rect
    img[y0:y1, x0:x1] = bg
    if white_holes:
        for i in range(6):
            yy = y0 + int((y1 - y0) * (0.15 + 0.12 * i))
            cv2.rectangle(img, (x0 + 40, yy), (x1 - 40, yy + 18), (255, 255, 255), -1)
    return img


class TestPdfToImages:
    def test_returns_bgr_uint8(self):
        imgs = processing.pdf_to_images(FIXTURE_PDF, dpi=100)
        assert len(imgs) >= 1
        for img in imgs:
            assert isinstance(img, np.ndarray)
            assert img.dtype == np.uint8
            assert img.ndim == 3 and img.shape[2] == 3

    def test_missing_file(self, tmp_path):
        with pytest.raises(processing.SmartboardError, match="not found"):
            processing.pdf_to_images(tmp_path / "nope.pdf")

    def test_corrupt_file(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"this is not a pdf")
        with pytest.raises(processing.SmartboardError, match="Unable to open"):
            processing.pdf_to_images(bad)


class TestInvertRegion:
    def test_strict_255_minus_v_inside(self):
        img = np.full((100, 100, 3), (10, 20, 30), dtype=np.uint8)
        img[10:20, 30:40] = (200, 100, 50)
        out = processing.invert_region(img, (30, 10, 40, 20))
        expected = np.bitwise_not(img[10:20, 30:40])
        assert np.array_equal(out[10:20, 30:40], expected)
        assert np.array_equal(out[10:20, 30:40], 255 - img[10:20, 30:40])

    def test_outside_pixel_identical(self):
        img = make_page((300, 200, 940, 1550))
        out = processing.invert_region(img, (300, 200, 940, 1550))
        outside = np.ones((H, W), dtype=bool)
        outside[200:1550, 300:940] = False
        assert np.array_equal(out[outside], img[outside])
        # changed pixels are exactly the rectangle
        changed = (out != img).any(axis=2)
        assert changed.shape == (H, W)
        assert np.array_equal(changed, ~outside)

    def test_clamps_to_image_bounds(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        out = processing.invert_region(img, (-10, -10, 60, 60))
        assert np.array_equal(out, np.bitwise_not(img))
        # fully outside → unchanged
        out2 = processing.invert_region(img, (200, 200, 300, 300))
        assert np.array_equal(out2, img)

    def test_pad(self):
        img = np.full((40, 40, 3), (100, 100, 100), dtype=np.uint8)
        out = processing.invert_region(img, (10, 10, 20, 20), pad=2)
        # the padded region (8,8)-(22,22) is inverted
        assert np.array_equal(out[8:22, 8:22], np.bitwise_not(img[8:22, 8:22]))
        # everything outside the padded region is untouched
        outside = np.ones((40, 40), dtype=bool)
        outside[8:22, 8:22] = False
        assert np.array_equal(out[outside], img[outside])

    def test_rejects_bad_input(self):
        with pytest.raises(processing.SmartboardError):
            processing.invert_region(np.zeros((10, 10), dtype=np.uint8), (0, 0, 5, 5))
        with pytest.raises(processing.SmartboardError):
            processing.invert_region(np.zeros((10, 10, 4), dtype=np.uint8), (0, 0, 5, 5))


class TestEnhanceImage:
    def test_no_board_returns_unchanged(self, caplog):
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        for i in range(5):
            x = 200 + i * 120
            cv2.rectangle(img, (x, 300), (x + 30, 360), (0, 0, 0), -1)
        with caplog.at_level("WARNING", logger="smartboard_invert.processing"):
            out, det = processing.enhance_image_ex(img)
        assert not det.found
        assert np.array_equal(out, img)
        assert any("no unambiguous" in r.message.lower() for r in caplog.records)

    def test_inverts_only_detected_region(self):
        rect = (300, 200, 940, 1550)
        img = make_page(rect, bg=(15, 15, 15))
        out, det = processing.enhance_image_ex(img)
        assert det.found, det.message
        x0, y0, x1, y1 = det.rect
        assert np.array_equal(out[y0:y1, x0:x1], np.bitwise_not(img[y0:y1, x0:x1]))
        outside = np.ones((H, W), dtype=bool)
        outside[y0:y1, x0:x1] = False
        assert np.array_equal(out[outside], img[outside])

    def test_white_text_becomes_dark(self):
        rect = (300, 200, 940, 1550)
        img = make_page(rect, bg=(10, 10, 10), white_holes=True)
        out, det = processing.enhance_image_ex(img)
        assert det.found
        # the white bars (row 1: y0 + 0.15*(h)) must now be dark
        yy = rect[1] + int((rect[3] - rect[1]) * 0.15)
        bar_in = img[yy + 2 : yy + 16, rect[0] + 60 : rect[2] - 60]
        bar_out = out[yy + 2 : yy + 16, rect[0] + 60 : rect[2] - 60]
        assert bar_in.mean() > 240  # was white
        assert bar_out.mean() < 30  # now dark

    def test_invert_false_keeps_dark_board_dark(self):
        rect = (300, 200, 940, 1550)
        img = make_page(rect, bg=(15, 15, 15))
        out, det = processing.enhance_image_ex(img, invert=False, apply_clahe=True)
        assert det.found
        cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        g_in = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[cy, cx]
        g_out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[cy, cx]
        assert g_in < 60
        assert g_out < 128  # CLAHE only, no inversion

    def test_plain_wrapper_matches_ex(self):
        img = make_page((300, 200, 940, 1550))
        assert np.array_equal(processing.enhance_image(img), processing.enhance_image_ex(img)[0])

    def test_rejects_bad_input(self):
        with pytest.raises(processing.SmartboardError):
            processing.enhance_image(np.zeros((10, 10), dtype=np.uint8))


class TestImagesToPdf:
    def test_creates_pdf_with_image_sized_pages(self, tmp_path):
        img = np.full((100, 200, 3), 255, dtype=np.uint8)
        out = tmp_path / "out.pdf"
        processing.images_to_pdf([img], out)
        assert out.is_file()
        doc = fitz.open(str(out))
        try:
            assert doc.page_count == 1
            assert doc[0].rect == fitz.Rect(0, 0, 200, 100)
        finally:
            doc.close()

    def test_empty_list_raises(self, tmp_path):
        with pytest.raises(processing.SmartboardError):
            processing.images_to_pdf([], tmp_path / "x.pdf")

    def test_bad_image_raises(self, tmp_path):
        with pytest.raises(processing.SmartboardError):
            processing.images_to_pdf([np.zeros((10, 10), dtype=np.uint8)], tmp_path / "x.pdf")
