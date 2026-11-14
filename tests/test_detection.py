"""Unit tests for the smartboard region detection (synthetic images only).

Covers the mandatory fail-safe behaviour:
* black / dark-gray boards are detected,
* boards at different positions are detected,
* single glyphs / small drawings never trigger the detection,
* ambiguous (two large dark regions) situations are refused,
* a page without a white background is refused,
* in page mode a "full page" detection is impossible,
* in image mode a board covering the whole image is accepted.
"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
import pytest

from smartboard_invert.detection import detect_smartboard_region

# A4 rendered at 150 dpi (same geometry the pipeline uses).
W, H = 1240, 1755


def make_page(board_rect: Tuple[int, int, int, int], bg=(20, 20, 25), white_holes: bool = True) -> np.ndarray:
    """White page with a dark rectangular board (plus white 'text' bars)."""
    img = np.full((H, W, 3), 255, dtype=np.uint8)
    x0, y0, x1, y1 = board_rect
    img[y0:y1, x0:x1] = bg
    if white_holes:
        for i in range(6):
            yy = y0 + int((y1 - y0) * (0.15 + 0.12 * i))
            cv2.rectangle(img, (x0 + 40, yy), (x1 - 40, yy + 18), (255, 255, 255), -1)
    return img


def assert_rect_close(rect: Tuple[int, int, int, int], expected: Tuple[int, int, int, int], tol: int = 10) -> None:
    assert rect is not None
    for got, exp in zip(rect, expected):
        assert abs(got - exp) <= tol, f"rect {rect} not within {tol}px of {expected}"


class TestDetectionHappyPath:
    def test_black_board_center(self):
        rect = (300, 200, 940, 1550)
        res = detect_smartboard_region(make_page(rect, bg=(10, 10, 10)))
        assert res.found, res.message
        assert_rect_close(res.rect, rect)
        assert res.confidence >= 0.6
        assert res.threshold > 0
        assert res.background_level > 240

    def test_dark_gray_board(self):
        rect = (300, 200, 940, 1550)
        res = detect_smartboard_region(make_page(rect, bg=(60, 60, 60)))
        assert res.found, res.message
        assert_rect_close(res.rect, rect)
        assert res.confidence >= 0.6

    def test_medium_gray_board(self):
        rect = (300, 200, 940, 1550)
        res = detect_smartboard_region(make_page(rect, bg=(128, 128, 128)))
        assert res.found, res.message
        assert_rect_close(res.rect, rect)

    def test_board_top_left(self):
        rect = (60, 80, 500, 700)
        res = detect_smartboard_region(make_page(rect, bg=(30, 30, 30)))
        assert res.found, res.message
        assert_rect_close(res.rect, rect)

    def test_board_bottom_right(self):
        rect = (700, 900, 1180, 1680)
        res = detect_smartboard_region(make_page(rect, bg=(30, 30, 30)))
        assert res.found, res.message
        assert_rect_close(res.rect, rect)

    def test_white_text_holes_do_not_disturb(self):
        rect = (300, 200, 940, 1550)
        res = detect_smartboard_region(make_page(rect, bg=(15, 15, 15), white_holes=True))
        assert res.found, res.message
        assert_rect_close(res.rect, rect, tol=12)
        # the filled board must be (nearly) rectangular
        assert res.candidates[0]["extent"] >= 0.85


class TestDetectionFailSafe:
    def test_small_glyphs_only(self):
        """A few small dark marks (like characters) must NOT be detected."""
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        for i in range(6):
            x = 200 + i * 120
            cv2.rectangle(img, (x, 300), (x + 30, 360), (0, 0, 0), -1)
        res = detect_smartboard_region(img)
        assert not res.found
        assert res.rect is None
        assert res.confidence == 0.0

    def test_one_large_glyph(self):
        """Even a single large dark drawing (non-rectangular) is refused."""
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        cv2.circle(img, (620, 800), 300, (0, 0, 0), -1)  # big circle: extent pi/4
        res = detect_smartboard_region(img)
        assert not res.found

    def test_two_large_boards_ambiguous(self):
        """Two dark regions of comparable size → not unambiguous → refused."""
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        img[200:1500, 100:550] = (10, 10, 10)
        img[200:1500, 700:1150] = (10, 10, 10)
        res = detect_smartboard_region(img)
        assert not res.found
        assert res.rect is None

    def test_full_page_dark_refused_in_page_mode(self):
        """A completely dark image has no white margin → must be refused in
        page mode (the whole white page must never be inverted)."""
        img = np.full((H, W, 3), (30, 30, 30), dtype=np.uint8)
        res = detect_smartboard_region(img)
        assert not res.found
        assert "background" in res.message.lower() or "no" in res.message.lower()

    def test_full_bleed_board_touching_edge_refused(self):
        """A dark rectangle touching the page edge is rejected (margin gate)."""
        img = np.full((H, W, 3), 255, dtype=np.uint8)
        img[:, 60:1180] = (20, 20, 20)  # touches top and bottom edge
        res = detect_smartboard_region(img)
        assert not res.found

    def test_page_background_not_light(self):
        """Pages whose background is not light are refused outright."""
        img = np.full((H, W, 3), (80, 80, 80), dtype=np.uint8)
        img[200:1500, 300:940] = (10, 10, 10)
        res = detect_smartboard_region(img)
        assert not res.found
        assert "background" in res.message.lower()

    def test_light_gray_board_not_deutlich_dunkler(self):
        """A board only marginally darker than white (200 vs 255) is not
        'deutlich dunkler' → refused with default settings."""
        rect = (300, 200, 940, 1550)
        res = detect_smartboard_region(make_page(rect, bg=(200, 200, 200), white_holes=False))
        assert not res.found

    def test_invalid_inputs(self):
        assert not detect_smartboard_region(None).found  # type: ignore[arg-type]
        assert not detect_smartboard_region(np.zeros((10, 10), np.uint8)).found
        assert not detect_smartboard_region(np.zeros((10, 10, 3, 3), np.uint8)).found
        assert not detect_smartboard_region(np.zeros((100, 100), dtype=np.float32)).found


class TestImageMode:
    def test_whole_image_dark_is_the_board(self):
        """allow_full_coverage: a dark image (the board IS the image) is
        accepted over its whole extent."""
        img = np.full((900, 600, 3), (30, 30, 35), dtype=np.uint8)
        res = detect_smartboard_region(img, allow_full_coverage=True)
        assert res.found, res.message
        assert_rect_close(res.rect, (0, 0, 600, 900), tol=2)

    def test_whole_image_dark_with_sparse_text(self):
        img = np.full((900, 600, 3), (25, 25, 30), dtype=np.uint8)
        cv2.rectangle(img, (100, 200), (500, 230), (255, 255, 255), -1)
        res = detect_smartboard_region(img, allow_full_coverage=True)
        assert res.found, res.message
        assert_rect_close(res.rect, (0, 0, 600, 900), tol=4)

    def test_board_inside_border_in_image_mode(self):
        """Dark board with a white border: the rect is the dark area inside."""
        from tests.synth import board_image

        img = board_image(600, 900, bg=(20, 20, 25), text=False, border=25)
        res = detect_smartboard_region(img, allow_full_coverage=True)
        assert res.found, res.message
        assert_rect_close(res.rect, (25, 25, 575, 875), tol=8)

    def test_image_mode_still_refuses_light_image(self):
        """A light image with only small dark marks is refused even in image
        mode (there is no dark board inside)."""
        img = np.full((900, 600, 3), 255, dtype=np.uint8)
        cv2.rectangle(img, (100, 100), (130, 160), (0, 0, 0), -1)
        res = detect_smartboard_region(img, allow_full_coverage=True)
        assert not res.found
