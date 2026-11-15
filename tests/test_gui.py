"""GUI tests: the "Auf Board zuschneiden (Rand entfernen)" checkbox
(ADR 0003, D4) – the option exists, defaults to off and is passed through to
``process_pdf(crop=...)``.

Tkinter needs a display.  The whole module is skipped when tkinter is not
installed (headless venvs) or no display can be opened – consistent with the
coverage gate, which excludes gui.py for exactly this reason (pyproject.toml).
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("tkinter")

from smartboard_invert import gui  # noqa: E402


@pytest.fixture
def tk_root():
    from tkinter import TclError, Tk

    try:
        root = Tk()
    except TclError as e:
        pytest.skip(f"no X display available: {e}")
    yield root
    root.destroy()


class TestCropCheckbox:
    def test_crop_var_exists_and_defaults_off(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        assert hasattr(app, "crop_var")
        assert app.crop_var.get() == 0  # default: crop disabled

    def _start_with_crop(self, app, monkeypatch, crop_value):
        """Start a run with a stubbed process_pdf; return (args, kwargs) of
        the recorded call."""
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, "/nonexistent/in.pdf")
        app.output_path.delete(0, "end")
        app.output_path.insert(0, "/nonexistent/out.pdf")
        app.crop_var.set(crop_value)
        before = {t for t in threading.enumerate()}
        app.start_processing()
        for t in threading.enumerate():
            if t not in before:
                t.join(timeout=15)
                assert not t.is_alive(), "processing worker did not finish"
        assert calls, "process_pdf was not called"
        return calls[0]

    def test_crop_checked_reaches_process_pdf(self, tk_root, monkeypatch):
        app = gui.SmartboardGUI(tk_root)
        _args, kwargs = self._start_with_crop(app, monkeypatch, 1)
        assert kwargs["crop"] is True

    def test_crop_default_reaches_process_pdf_as_false(self, tk_root, monkeypatch):
        app = gui.SmartboardGUI(tk_root)
        _args, kwargs = self._start_with_crop(app, monkeypatch, app.crop_var.get())
        assert kwargs["crop"] is False
