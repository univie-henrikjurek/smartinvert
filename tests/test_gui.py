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
from smartboard_invert.pdfpipeline import PageResult, ProcessResult  # noqa: E402


@pytest.fixture
def tk_root():
    from tkinter import TclError, Tk

    try:
        root = Tk()
    except TclError as e:
        pytest.skip(f"no X display available: {e}")
    yield root
    root.destroy()
    # Deterministically finalize the (now unreachable) app objects of this
    # test HERE, in the main thread.  The app and its event queue form a
    # reference cycle, so without this the cyclic GC would collect them at
    # an arbitrary later allocation point — possibly in a WORKER thread of
    # a later test.  There, the tkinter Variable.__del__ finalizers would
    # call into the dead Tcl interpreter from the wrong thread (RuntimeError
    # / Tcl lock contention with a concurrent main-thread GC = the test
    # suite's mysterious "processing worker did not finish" hangs).
    import gc

    gc.collect()


def _dummy_pdf(tmp_path: Path) -> Path:
    """A REAL minimal 1-page PDF (fitz-generated).

    The ADR 0011, D2 pre-check runs the real ``diagnose_pdf`` on the input
    in ``start_processing`` — a fake ``%PDF-1.4 dummy`` header would fail
    the pre-check ("not a valid PDF") and abort every worker test.  The
    stubbed ``process_pdf`` never reads the bytes, but the input must be a
    valid PDF and must exist (job planning requirement).
    """
    p = tmp_path / "in.pdf"
    if not p.exists():
        import fitz

        doc = fitz.open()
        doc.new_page()
        doc.save(str(p))
        doc.close()
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
        # ADR 0005: the legacy CLAHE / noise-cleaning checkboxes are gone.
        # (The former keep_red_var/keep_green_var pair is back again — in
        # extended form — in the advanced section; ADR 0011 D1 supersedes
        # ADR 0005 D2 on that point.)
        for attr in ("clahe_var", "clean_var"):
            assert not hasattr(app, attr), f"{attr} must be removed (ADR 0005)"
        # ADR 0009: the DPI slider (and its variable / readout label) is
        # gone from the GUI (ADR 0011 D1 keeps it out of the advanced
        # section as well)
        for attr in ("dpi_var", "dpi_slider", "dpi_value"):
            assert not hasattr(app, attr), f"{attr} must be removed (ADR 0009)"

    def test_remaining_controls_exist(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        for attr in (
            "invert_var",
            "crop_var",
            "bg_var",
            "keep_hex_entry",
            # ADR 0011 D1: advanced section + marker-colour checkboxes
            "advanced_btn",
            "advanced_frame",
            "keep_red_var",
            "keep_green_var",
            "keep_blue_var",
            "keep_yellow_var",
        ):
            assert hasattr(app, attr), f"{attr} must still exist"

    def test_no_dpi_reaches_process_pdf(self, tk_root, monkeypatch, tmp_path):
        """ADR 0009: the GUI must not pass a dpi at all — the pipeline
        default (150) applies."""
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
        assert "dpi" not in calls[0][1], "GUI must not pass a DPI (ADR 0009)"

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


class TestAdvancedOptionsSection:
    """ADR 0011, D1: the advanced options (invert + marker colours + hex
    entry) live in a section that is collapsed by default; the four
    marker-colour checkboxes replace the fixed {red, green} default."""

    def test_advanced_section_hidden_by_default(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        assert app.advanced_frame.winfo_manager() == "", (
            "the advanced section must be collapsed by default"
        )
        assert "▸" in app.advanced_btn.cget("text")

    def test_toggle_shows_and_hides_advanced_section(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        app._toggle_advanced()
        assert app.advanced_frame.winfo_manager() == "pack"
        assert "▾" in app.advanced_btn.cget("text")
        app._toggle_advanced()
        assert app.advanced_frame.winfo_manager() == ""
        assert "▸" in app.advanced_btn.cget("text")

    def test_marker_colour_defaults_are_red_green(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        assert app.keep_red_var.get() == 1
        assert app.keep_green_var.get() == 1
        assert app.keep_blue_var.get() == 0
        assert app.keep_yellow_var.get() == 0
        # defaults reproduce the historical fixed behaviour exactly
        assert app._transform_options()["keep_colors"] == frozenset({"red", "green"})

    def test_marker_colours_reach_process_pdf(self, tk_root, monkeypatch, tmp_path):
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append((args, kwargs))
            from smartboard_invert.pdfpipeline import ProcessResult

            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app._toggle_advanced()
        app.keep_red_var.set(0)  # keep green + blue only
        app.keep_blue_var.set(1)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        _run_start(app)
        assert calls, "process_pdf was not called"
        assert calls[0][1]["keep_colors"] == frozenset({"green", "blue"})

    def test_all_marker_colours_off_means_empty_set(self, tk_root):
        app = gui.SmartboardGUI(tk_root)
        app._toggle_advanced()
        for var in (
            app.keep_red_var,
            app.keep_green_var,
            app.keep_blue_var,
            app.keep_yellow_var,
        ):
            var.set(0)
        assert app._transform_options()["keep_colors"] == frozenset()


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


class TestPrecheck:
    """ADR 0011, D2: a file-level problem of a single-file input
    (password-protected / damaged / empty / missing) is caught in the main
    thread BEFORE the controls are disabled and BEFORE any worker starts
    (fail-fast with a clear dialog)."""

    def test_corrupt_input_shows_clear_dialog_and_aborts(
        self, tk_root, monkeypatch, tmp_path
    ):
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )
        calls = []
        monkeypatch.setattr(gui, "process_pdf", lambda *a, **k: calls.append(1))
        app = gui.SmartboardGUI(tk_root)
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"this is not a pdf")
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(bad))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        before = {t for t in threading.enumerate()}
        app.start_processing()
        assert not calls, "process_pdf must not be called on a damaged input"
        assert {t for t in threading.enumerate()} == before, (
            "no worker thread may start when the pre-check fails"
        )
        assert shown, "an error dialog must be shown"
        assert "not a valid pdf" in shown[0][1].lower()
        # the run was aborted BEFORE disabling the controls
        assert str(app.advanced_btn.cget("state")) in ("normal", "")

    def test_encrypted_input_shows_password_dialog_and_aborts(
        self, tk_root, monkeypatch, tmp_path
    ):
        import synth

        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )
        calls = []
        monkeypatch.setattr(gui, "process_pdf", lambda *a, **k: calls.append(1))
        app = gui.SmartboardGUI(tk_root)
        secret = synth.make_encrypted_pdf(tmp_path / "secret.pdf")
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(secret))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        app.start_processing()
        assert not calls
        assert shown and "password-protected" in shown[0][1].lower()

    def test_missing_input_shows_not_found_dialog_and_aborts(
        self, tk_root, monkeypatch, tmp_path
    ):
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )
        calls = []
        monkeypatch.setattr(gui, "process_pdf", lambda *a, **k: calls.append(1))
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(tmp_path / "nope.pdf"))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        app.start_processing()
        assert not calls
        assert shown and "not found" in shown[0][1].lower()

    def test_valid_input_passes_precheck_and_starts_worker(
        self, tk_root, monkeypatch, tmp_path
    ):
        """A valid PDF must NOT be stopped by the pre-check (no dialog)."""
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )
        calls = []

        def fake_process_pdf(*args, **kwargs):
            calls.append(1)
            return ProcessResult(input_path=args[0], output_path=args[1])

        monkeypatch.setattr(gui, "process_pdf", fake_process_pdf)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        _run_start(app)
        assert calls, "process_pdf must be called for a valid input"
        assert not shown, "no error dialog may be shown for a valid input"


class TestWorkerFailureDiagnosis:
    """ADR 0011, D2: in the worker loop (folder input), a failed file gets
    the clear diagnosis message in the failure list."""

    def test_corrupt_file_failure_uses_diagnosis_message(
        self, tk_root, monkeypatch, tmp_path
    ):
        """process_pdf raises a raw pipeline error for a damaged file; the
        'Some files failed' dialog must carry the user-facing diagnosis
        instead."""
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )
        ind = tmp_path / "inputs"
        ind.mkdir()
        (ind / "broken.pdf").write_bytes(b"this is not a pdf")
        (ind / "good.pdf").write_bytes(b"%PDF-1.4 dummy")  # never read (stub)

        def fake(src, dst, **kw):
            if Path(src).name == "broken.pdf":
                raise gui.SmartboardError("raw pipeline error")
            return ProcessResult(input_path=src, output_path=dst)

        monkeypatch.setattr(gui, "process_pdf", fake)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(ind))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "outputs"))
        _run_start(app)
        app._poll_events()
        assert shown, "the failure dialog must be shown"
        message = shown[-1][1]
        assert "not a valid pdf" in message.lower(), (
            "the clear diagnosis must replace the raw error"
        )
        assert "raw pipeline error" not in message

    def test_undetermined_failure_keeps_generic_message(
        self, tk_root, monkeypatch, tmp_path
    ):
        """If diagnose_pdf finds no file-level problem (valid input), the
        failure line falls back to the generic 'unexpected error (see log)'
        wording for non-SmartboardError exceptions."""
        shown = []
        monkeypatch.setattr(
            gui.messagebox, "showerror", lambda t, m: shown.append((t, m))
        )
        ind = tmp_path / "inputs"
        ind.mkdir()
        import fitz

        good = ind / "good.pdf"  # a VALID pdf -> diagnose_pdf finds nothing
        doc = fitz.open()
        doc.new_page()
        doc.save(str(good))
        doc.close()

        def fake(src, dst, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(gui, "process_pdf", fake)
        app = gui.SmartboardGUI(tk_root)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(ind))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "outputs"))
        _run_start(app)
        app._poll_events()
        assert shown
        assert "unexpected error (see log)" in shown[-1][1]


class TestDoneMessageNoBoard:
    """ADR 0011, D2 / P10-FR-6: when no board was detected on any page, the
    Done message carries the extra 'unchanged copy' line."""

    def _run_with_pages(self, app, monkeypatch, tmp_path, pages):
        def fake(src, dst, **kw):
            res = ProcessResult(input_path=src, output_path=dst)
            res.pages = pages
            return res

        monkeypatch.setattr(gui, "process_pdf", fake)
        app.input_path.delete(0, "end")
        app.input_path.insert(0, str(_dummy_pdf(tmp_path)))
        app.output_path.delete(0, "end")
        app.output_path.insert(0, str(tmp_path / "out.pdf"))
        _run_start(app)

    def test_no_board_line_in_done_message(self, tk_root, monkeypatch, tmp_path):
        shown_info = []
        monkeypatch.setattr(
            gui.messagebox, "showinfo", lambda t, m: shown_info.append((t, m))
        )
        app = gui.SmartboardGUI(tk_root)
        self._run_with_pages(
            app,
            monkeypatch,
            tmp_path,
            [PageResult(page_index=0, detected=False, method="copy")],
        )
        app._poll_events()
        assert shown_info, "the Done dialog must be shown"
        assert "unchanged copy of the input" in shown_info[0][1]

    def test_board_found_no_extra_line(self, tk_root, monkeypatch, tmp_path):
        shown_info = []
        monkeypatch.setattr(
            gui.messagebox, "showinfo", lambda t, m: shown_info.append((t, m))
        )
        app = gui.SmartboardGUI(tk_root)
        self._run_with_pages(
            app,
            monkeypatch,
            tmp_path,
            [PageResult(page_index=0, detected=True, method="image-replace")],
        )
        app._poll_events()
        assert shown_info
        assert "unchanged copy of the input" not in shown_info[0][1]
