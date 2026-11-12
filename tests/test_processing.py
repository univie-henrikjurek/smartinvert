import os
from pathlib import Path

import pytest
import numpy as np

from smartboard_invert import processing

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "test.pdf"
OUTPUT_PDF = Path(__file__).parent / "output_test.pdf"

@pytest.fixture(scope="module")
def rendered_images():
    imgs = processing.pdf_to_images(FIXTURE_PDF, dpi=150)
    assert isinstance(imgs, list) and len(imgs) > 0
    for img in imgs:
        assert isinstance(img, np.ndarray)
        assert img.ndim == 3 and img.shape[2] == 3
    return imgs

def test_enhance_image_identity(rendered_images):
    img = rendered_images[0]
    out = processing.enhance_image(img, invert=False, apply_clahe=False, clean=False)
    # Without any operation the output should be a binary version of the grayscale image.
    # We simply verify shape equality and dtype.
    assert out.shape == img.shape
    assert out.dtype == img.dtype

def test_full_pipeline(rendered_images):
    processed = [processing.enhance_image(i) for i in rendered_images]
    # Ensure processing returns list of same length
    assert len(processed) == len(rendered_images)
    # Write to PDF
    processing.images_to_pdf(processed, OUTPUT_PDF)
    assert OUTPUT_PDF.is_file()
    # Clean up
    OUTPUT_PDF.unlink()

def test_cli_execution(tmp_path, monkeypatch):
    # Run the CLI via subprocess using the virtual environment interpreter.
    import subprocess, sys
    cmd = [sys.executable, "-m", "smartboard_invert.cli", "--input", str(FIXTURE_PDF)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # Expected output file location
    out_path = FIXTURE_PDF.with_name(FIXTURE_PDF.stem + "_inverted.pdf")
    assert out_path.is_file()
    # Clean up
    out_path.unlink()
