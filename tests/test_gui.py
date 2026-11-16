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
from pathlib import Path

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


def _dummy_pdf(tmp_path: Path) -> Path:
    """A file that exists (the stubbed process_pdf never reads its bytes,
    but the worker's job planning — like the CLI's — requires the input
    to exist)."""
    p = tmp_path / "in.pdf"
    p.write_bytes(b"%PDF-1.4 dummy")
    return p


def _run_start(app) -> None:
    """Call start_processing and wait for the worker thread to finish."""
    before = {t for t in threading.enumerate()}
    app.start_processing()
    for t in threading.enumerate():
        if t not in before:
            t.join(timeout=15)
            assert not t.is_alive(), "processing worker did not finish"


class TestCropCheckbox:
    def test_crop_var_exists_and_defaults_on(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        assert hasattr(app, "crop_var")
        assert app.crop_var.get() == 1  # ADR 0006: crop is the default

    def _start_with_crop(self, app, monkeypatch, crop_value, tmp_path):
        """Start a run with a stubbed process_pdf; return (args, kwargs) of
        the recorded call."""
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        app.crop_var.set(crop_value)
        _run_start(app)
        assert calls, "process_pdf was not called"
        return calls[0]

    def test_crop_checked_reaches_process_pdf(self, tk_root, monkeypatch, tmp_path):
        app = gui.SmartboardGUI(tk_root)
        _args, kwargs = self._start_with_crop(app, monkeypatch, 1, tmp_path)
        assert kwargs["crop"] is True

    def test_crop_default_reaches_process_pdf_as_true(self, tk_root, monkeypatch, tmp_path):
        """ADR 0006: the (on-by-default) checkbox must reach process_pdf as
        crop=True."""
        app = gui.SmartboardGUI(tk_root)
        _args, kwargs = self._start_with_crop(app, monkeypatch, app.crop_var.get(), tmp_path)
        assert kwargs["crop"] is True


class TestSimplifiedOptions:
    """ADR 0005, D1/D2: the legacy CLAHE / noise-cleaning checkboxes and the
    redundant red/green checkboxes are gone from the GUI; ``keep_colors``
    is fixed to the documented default {red, green}."""

    def test_removed_controls_do_not_exist(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        for attr in ("clahe_var", "clean_var", "keep_red_var", "keep_green_var"):
            assert not hasattr(app, attr), f"{attr} must be removed (ADR 0005)"

    def test_remaining_controls_exist(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        for attr in ("invert_var", "crop_var", "bg_var", "keep_hex_entry"):
            assert hasattr(app, attr), f"{attr} must still exist"

    def test_keep_colors_reaches_process_pdf_as_red_green(
        self, tk_root, monkeypatch, tmp_path
    ):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        _run_start(app)
        assert calls, "process_pdf was not called"
        assert calls[0][1]["keep_colors"] == frozenset({"red", "green"})


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

    def test_keep_hex_reaches_process_pdf(self, tk_root, monkeypatch, tmp_path):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        app.keep_hex_entry.insert(0, "000001-0000FF")
        _run_start(app)
        assert calls, "process_pdf was not called"
        assert calls[0][1]["keep_segments"] == (((0, 0, 1), (0, 0, 255)),)

    def test_empty_entry_reaches_process_pdf_as_empty_tuple(
        self, tk_root, monkeypatch, tmp_path
    ):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        _run_start(app)
        assert calls, "process_pdf was not called"
        assert calls[0][1]["keep_segments"] == ()


class TestFolderBatch:
    """ADR 0007, D2/D3: folder input is batch-processed with the CLI's
    ``_plan_jobs`` semantics, and the worker's error dialogs are robust
    (no NameError from a late-bound ``except ... as e`` variable — PEP 3110)."""

    def _make_folder(self, tmp_path: Path, names=("a.pdf", "b.pdf")) -> Path:
        ind = tmp_path / "inputs"
        ind.mkdir()
        for n in names:
            (ind / n).write_bytes(b"%PDF-1.4 dummy")
        return ind

    def _fill(self, app, in_text: str, out_text: str = "") -> None:
        app.input_path.delete(0, "end")
        app.input_path.insert(0, in_text)
        app.output_path.delete(0, "end")
        app.output_path.insert(0, out_text)

    def test_folder_batch_processes_each_pdf_into_output_folder(
        self, tk_root, monkeypatch, tmp_path
    ):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args[0], args[1]))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        ind = self._make_folder(tmp_path)
        outd = tmp_path / "outputs"
        self._fill(app, str(ind), str(outd))
        _run_start(app)
        assert calls == [
            (ind / "a.pdf", outd / "a.pdf"),
            (ind / "b.pdf", outd / "b.pdf"),
        ]

    def test_folder_without_output_folder_warns_without_worker(
        self, tk_root, monkeypatch, tmp_path
    ):
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showwarning", lambda t, m: shown.append((t, m))
        )
        calls = []
        monkeypatch.setattr(
            gui, "process_pdf", lambda *a, **k: calls.append(a)
        )
        app = gui.SmartboardGUI(tk_root)
        self._fill(app, str(self._make_folder(tmp_path)))
        _run_start(app)
        assert shown, "a warning dialog must be shown"
        assert not calls, "no worker may start without an output folder"

    def test_worker_error_dialog_is_shown_without_nameerror(
        self, tk_root, monkeypatch, tmp_path
    ):
        """The user's v0.7.1 crash: the error dialog itself raised NameError
        (the lambda ran after the except block unbound `e`)."""
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )

        def boom(*a, **k):
            raise gui.SmartboardError("boom-input")

        monkeypatch.setattr(gui, "process_pdf", boom)
        app = gui.SmartboardGUI(tk_root)
        self._fill(app, str(_dummy_pdf(tmp_path)), str(tmp_path / "out.pdf"))
        _run_start(app)
        app._poll_events()  # pump the queued dialog lambda (main thread)
        assert shown, "an error dialog must be shown"
        assert "boom-input" in shown[-1][1]
