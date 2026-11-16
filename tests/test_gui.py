"""GUI tests: the "Auf Board zuschneiden (Rand entfernen)" checkbox
(ADR 0003, D4) and the "Zusätzliche Hex-Farben" entry (ADR 0004, D1/D4) –
the controls exist, have the documented defaults, and are passed through to
``process_pdf(crop=...)`` / ``process_pdf(keep_segments=...)``.

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


class TestKeepHexEntry:
    """ADR 0004, D1/D4: the "Zusätzliche Hex-Farben" entry – exists, defaults
    to empty, is validated in the main thread *before* the worker starts (on
    error: dialog, controls stay enabled, no worker), and is passed through
    to ``process_pdf(keep_segments=...)``."""

    def test_entry_exists_and_defaults_empty(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        assert hasattr(app, "keep_hex_entry")
        assert app.keep_hex_entry.get() == ""

    def test_parse_keep_hex_valid(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        app.keep_hex_entry.insert(0, "FF0000, 00FF00, 000001-0000FF")
        assert app._parse_keep_hex() == (
            ((255, 0, 0), (255, 0, 0)),
            ((0, 255, 0), (0, 255, 0)),
            ((0, 0, 1), (0, 0, 255)),
        )

    def test_parse_keep_hex_empty_is_empty_tuple(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        assert app._parse_keep_hex() == ()

    def test_parse_keep_hex_invalid_shows_dialog_and_returns_none(
        self, tk_root, monkeypatch
    ):
        app = gui.SmartboardGUI(tk_root)
        app.keep_hex_entry.insert(0, "zzz")
        errors = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: errors.append((t, m))
        )
        assert app._parse_keep_hex() is None
        assert errors, "an error dialog must be shown"
        assert "keep-hex" in errors[0][1]

    def test_invalid_hex_aborts_before_worker(self, tk_root, monkeypatch):
        """An invalid entry must stop the run before the controls are
        disabled and before any worker thread is started."""
        app = gui.SmartboardGUI(tk_root)
        calls = []
        monkeypatch.setattr(gui, "process_pdf", lambda *a, **k: calls.append(1))
        monkeypatch.setattr(gui.messagebox, "showerror", lambda t, m: None)
        app.keep_hex_entry.insert(0, "zzz")
        app.input_path.delete(0, "end")
        app.input_path.insert(0, "/nonexistent/in.pdf")
        app.output_path.delete(0, "end")
        app.output_path.insert(0, "/nonexistent/out.pdf")
        before = {t for t in threading.enumerate()}
        app.start_processing()
        assert not calls, "process_pdf must not be called on invalid input"
        assert {t for t in threading.enumerate()} == before, (
            "no worker thread may start when the hex entry is invalid"
        )

    def test_keep_hex_reaches_process_pdf(self, tk_root, monkeypatch):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, "/nonexistent/in.pdf")
        app.output_path.delete(0, "end")
        app.output_path.insert(0, "/nonexistent/out.pdf")
        app.keep_hex_entry.insert(0, "000001-0000FF")
        before = {t for t in threading.enumerate()}
        app.start_processing()
        for t in threading.enumerate():
            if t not in before:
                t.join(timeout=15)
                assert not t.is_alive(), "processing worker did not finish"
        assert calls, "process_pdf was not called"
        assert calls[0][1]["keep_segments"] == (((0, 0, 1), (0, 0, 255)),)

    def test_empty_entry_reaches_process_pdf_as_empty_tuple(
        self, tk_root, monkeypatch
    ):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, "/nonexistent/in.pdf")
        app.output_path.delete(0, "end")
        app.output_path.insert(0, "/nonexistent/out.pdf")
        before = {t for t in threading.enumerate()}
        app.start_processing()
        for t in threading.enumerate():
            if t not in before:
                t.join(timeout=15)
                assert not t.is_alive(), "processing worker did not finish"
        assert calls, "process_pdf was not called"
        assert calls[0][1]["keep_segments"] == ()
