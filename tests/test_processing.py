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


# --- Phase 3: invert_or_remap / color_mask / keep-colour priority (ADR 0002) ---


class TestInvertOrRemap:
    """Phase 3 (ADR 0002, D1 / P3-FR-9): the in-region pixel operation."""

    def test_flat_region_lands_exactly_on_target(self):
        """Anchor: v = B_c (p25 of the channel) -> exactly T_c."""
        region = np.full((64, 64, 3), 30, dtype=np.uint8)
        out = processing.invert_or_remap(region, bg_target=(255, 255, 255))
        assert np.array_equal(out, np.full_like(region, 255))

    def test_white_pixel_maps_to_black(self):
        """Anchor: v = 255 -> 0 (white stays black)."""
        region = np.full((64, 64, 3), 30, dtype=np.uint8)
        region[32, 32] = 255
        out = processing.invert_or_remap(region, bg_target=(255, 255, 255))
        assert np.array_equal(out[32, 32], (0, 0, 0))
        assert np.array_equal(out[0, 0], (255, 255, 255))  # anchor stays exact

    def test_monotone_decreasing(self):
        """v = 30 < 100 < 200 < 255  =>  v' strictly decreasing.

        p25 stays 30 (the other values are < 0.1 % of the pixels), so with
        T = 255: v' = 255 * (255 - v) / (255 - 30) -> 255, 176, 62, 0.
        """
        region = np.full((64, 64, 3), 30, dtype=np.uint8)
        region[1, 1], region[2, 2], region[3, 3] = 100, 200, 255
        out = processing.invert_or_remap(region, bg_target=(255, 255, 255))
        values = [int(out[0, 0, 0]), int(out[1, 1, 0]), int(out[2, 2, 0]), int(out[3, 3, 0])]
        assert values == [255, 176, 62, 0]
        assert values == sorted(values, reverse=True)

    def test_bg_target_none_is_bit_identical_to_bitwise_not(self):
        """The legacy path (bg_target=None) must stay bit-identical to the
        v0.4.1 np.bitwise_not – no float round-trip (P3-D-1)."""
        rng = np.random.default_rng(7)
        region = rng.integers(0, 256, size=(97, 63, 3), dtype=np.uint8)
        out = processing.invert_or_remap(region)
        assert out.shape == region.shape and out.dtype == np.uint8
        assert np.array_equal(out, np.bitwise_not(region))

    def test_mixed_half_dark_half_white(self):
        """Half 30 (-> target 255) and half 255 (-> 0); p25 = 30."""
        region = np.full((64, 64, 3), 30, dtype=np.uint8)
        region[:, 32:] = 255
        out = processing.invert_or_remap(region, bg_target=(255, 255, 255))
        assert (out[:, :32] == 255).all()
        assert (out[:, 32:] == 0).all()

    def test_p25_above_220_is_clamped(self):
        """p25 = 250 > 220 -> B_c is clamped to 220 (denominator >= 35, no
        division explosion): v = 250 -> 255 * 5 / (255 - 220) = 36.43 -> 36
        (round-half-up), v = 255 -> 0."""
        region = np.full((64, 64, 3), 250, dtype=np.uint8)
        region[:10, :10] = 255  # < 25 % of the pixels, p25 stays 250
        out = processing.invert_or_remap(region, bg_target=(255, 255, 255))
        assert np.array_equal(out[20, 20], (36, 36, 36))
        assert np.array_equal(out[0, 0], (0, 0, 0))

    def test_non_square_target_has_per_channel_scale(self):
        """bg_target is user-facing RGB (internally BGR); each channel uses
        its own T_c.  The anchor pixel (v = B_c = 30) lands exactly on the
        target colour in every channel."""
        region = np.full((8, 8, 3), 30, dtype=np.uint8)
        out = processing.invert_or_remap(region, bg_target=(255, 250, 240))
        # (R, G, B) = (255, 250, 240)  <=>  BGR (240, 250, 255)
        assert (out == np.array((240, 250, 255), dtype=np.uint8)).all()


class TestValidateBgTarget:
    """Phase 3 review fix: ``bg_target`` is validated centrally in the
    public API (``invert_or_remap`` / :func:`validate_bg_target`), not only
    in ``process_pdf`` — bad values must raise SmartboardError, never
    silently produce wrong pixels or leak a raw TypeError/ValueError."""

    def test_none_passes_through(self):
        assert processing.validate_bg_target(None) is None

    def test_tuple_passes_through(self):
        assert processing.validate_bg_target((255, 255, 255)) == (255, 255, 255)

    def test_list_is_normalised_to_tuple(self):
        assert processing.validate_bg_target([10, 20, 30]) == (10, 20, 30)

    @pytest.mark.parametrize(
        "value",
        [
            (300, 0, 0),    # out of range
            (0, -5, 128),   # negative
            (255, 255),     # too short
            (255, 255, 255, 10),  # too long
            (True, 0, 0),   # bool rejected
            ("255", 0, 0),  # non-int
            (255.0, 0, 0),  # float rejected (strict ints)
            "255,255,255",  # raw string (parser's job, not this one)
            255,            # scalar, not a 3-sequence
        ],
    )
    def test_invalid_raises(self, value):
        with pytest.raises(processing.SmartboardError):
            processing.validate_bg_target(value)

    def test_invert_or_remap_rejects_bad_bg_target(self):
        region = np.full((8, 8, 3), 30, dtype=np.uint8)
        with pytest.raises(processing.SmartboardError):
            processing.invert_or_remap(region, bg_target=(300, -5, 128))
        with pytest.raises(processing.SmartboardError):
            processing.invert_or_remap(region, bg_target=(255, 255, 300))
        # valid list input is accepted end-to-end
        out = processing.invert_or_remap(region, bg_target=[255, 255, 255])
        assert (out == 255).all()


class TestColorMask:
    """Phase 3 (ADR 0002, D2): marker-colour masks (BGR, int16)."""

    @staticmethod
    def flat(color):
        return np.full((64, 64, 3), color, dtype=np.uint8)

    @pytest.mark.parametrize(
        ("color", "name"),
        [
            ((0, 0, 255), "red"),  # BGR
            ((0, 255, 0), "green"),
            ((255, 0, 0), "blue"),
            ((0, 255, 255), "yellow"),
        ],
    )
    def test_pure_colour_fully_masked(self, color, name):
        mask = processing.color_mask(self.flat(color), {name})
        assert mask.shape == (64, 64)
        assert mask.dtype == bool
        assert mask.all()

    def test_white_never_masked(self):
        img = self.flat((255, 255, 255))
        for color in sorted(processing.KEEPABLE_COLORS):
            assert not processing.color_mask(img, {color}).any()

    def test_gray_never_masked(self):
        img = self.flat((200, 200, 200))  # chalk gray: R == G == B
        assert not processing.color_mask(img, set(processing.KEEPABLE_COLORS)).any()

    def test_dark_noise_below_r_min_not_masked(self):
        """Reddish flicker with R < 80 must never count, even if "dominant"."""
        img = self.flat((60, 5, 10))  # BGR = RGB(10, 5, 60): R = 10 < 80
        assert not processing.color_mask(img, set(processing.KEEPABLE_COLORS)).any()

    def test_red_above_r_min_masked(self):
        img = self.flat((15, 20, 90))  # BGR = RGB(90, 20, 15): R = 90 >= 80, dominant
        assert processing.color_mask(img, {"red"}).all()

    def test_delta_boundary_is_strict_greater(self):
        """r == g + 40 must NOT match (strict '>'), r == g + 41 must."""
        edge = self.flat((10, 81, 121))  # RGB(121, 81, 10): r == g + 40
        assert not processing.color_mask(edge, {"red"}).any()
        over = self.flat((10, 81, 122))  # RGB(122, 81, 10): r == g + 41
        assert processing.color_mask(over, {"red"}).all()

    def test_yellow_is_not_red_or_green(self):
        img = self.flat((0, 255, 255))  # BGR yellow: R == G == 255 > B + 40
        assert not processing.color_mask(img, {"red"}).any()
        assert not processing.color_mask(img, {"green"}).any()
        assert processing.color_mask(img, {"yellow"}).all()

    def test_unknown_color_raises(self):
        img = self.flat((0, 0, 255))
        with pytest.raises(processing.SmartboardError, match="unknown color"):
            processing.color_mask(img, {"magenta"})
        with pytest.raises(processing.SmartboardError):
            processing.color_mask(img, {"red", "magenta"})

    def test_rejects_bad_array(self):
        with pytest.raises(processing.SmartboardError):
            processing.color_mask(np.zeros((10, 10), dtype=np.uint8), {"red"})  # 2-D
        with pytest.raises(processing.SmartboardError):
            processing.color_mask(np.zeros((10, 10, 3), dtype=np.float32), {"red"})  # float
        with pytest.raises(processing.SmartboardError):
            processing.color_mask(np.zeros((10, 10, 4), dtype=np.uint8), {"red"})  # 4 channels
        with pytest.raises(processing.SmartboardError):
            processing.color_mask(None, {"red"})

    def test_empty_color_set_is_all_false(self):
        img = self.flat((0, 0, 255))
        assert not processing.color_mask(img, frozenset()).any()


class TestKeepColorsPriority:
    """Phase 3 (ADR 0002, D1/D2 / P3-FR-10): kept marker pixels take
    precedence over both complement and remap; the exclusion mask is
    computed on the *original* (pre-processing) image and applied last."""

    @staticmethod
    def board_with_red_block():
        # gray board with an 8x8 red marker (RGB 255,0,0 == BGR (0,0,255))
        img = np.full((64, 64, 3), (80, 80, 80), dtype=np.uint8)
        img[28:36, 28:36] = (0, 0, 255)
        return img

    def test_kept_red_beats_remap(self):
        img = self.board_with_red_block()
        out = processing.invert_or_remap(img, bg_target=(255, 255, 255), keep_colors={"red"})
        # the red marker keeps its original values (RGB 255,0,0)
        assert (out[28:36, 28:36] == np.array((0, 0, 255), dtype=np.uint8)).all()
        # the gray background (p25 = 80) lands exactly on the target
        assert (out[0, 0] == 255).all()

    def test_kept_red_beats_complement(self):
        img = self.board_with_red_block()
        out = processing.invert_or_remap(img, bg_target=None, keep_colors={"red"})
        red = np.zeros((64, 64), dtype=bool)
        red[28:36, 28:36] = True
        assert (out[red] == img[red]).all()  # kept pixels == original
        assert (out[~red] == np.bitwise_not(img[~red])).all()  # rest: strict 255 - v

    def test_exclusion_mask_uses_original_not_region(self):
        """The exclusion is computed on `original`, not on the transformed
        region: even if the marker pixels are altered in the region (as by
        pre-processing), the original marker positions keep their original
        values."""
        original = np.full((16, 16, 3), (80, 80, 80), dtype=np.uint8)
        original[6:10, 6:10] = (0, 0, 255)  # red in the original
        region = original.copy()
        region[6:10, 6:10] = (10, 10, 10)  # "pre-processed" away in region
        out = processing.invert_or_remap(
            region, original, bg_target=(255, 255, 255), keep_colors={"red"}
        )
        assert (out[6:10, 6:10] == np.array((0, 0, 255), dtype=np.uint8)).all()

    def test_original_shape_mismatch_raises(self):
        region = np.zeros((8, 8, 3), dtype=np.uint8)
        with pytest.raises(processing.SmartboardError, match="original"):
            processing.invert_or_remap(region, np.zeros((4, 4, 3), dtype=np.uint8))

    def test_rejects_bad_input(self):
        with pytest.raises(processing.SmartboardError):
            processing.invert_or_remap(np.zeros((10, 10), dtype=np.uint8))
        with pytest.raises(processing.SmartboardError):
            processing.invert_or_remap(np.zeros((10, 10, 4), dtype=np.uint8))
        with pytest.raises(processing.SmartboardError):
            processing.invert_or_remap(np.zeros((10, 10, 3), dtype=np.float32))
        with pytest.raises(processing.SmartboardError):
            processing.invert_or_remap(None)
