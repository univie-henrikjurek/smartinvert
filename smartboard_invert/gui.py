"""Very small Tkinter based GUI for the Smartboard Inversion tool.

The GUI mirrors the CLI options but presents them in a graphical form:

* File chooser for the input PDF (or a folder: all ``*.pdf`` files in it
  are processed into the chosen output folder, like the CLI batch —
  ADR 0007, D2).
* A fixed internal rendering DPI (the pipeline default of 150) — the DPI
  slider was removed in v0.8.0 (ADR 0009): with vector-preserving
  inversion the output quality no longer depends on the processing DPI,
  and for raster content the default is sufficient.  The CLI ``--dpi`` is
  unaffected.
* Options: "Auf Board zuschneiden" (crop, on by default) and the
  *Target background* combobox (complement or pure white) stay directly
  visible.  The advanced options (ADR 0011, D1) live in a collapsible
  section (collapsed by default): the *Invert colours* checkbox, four
  *Markerfarben erhalten* checkboxes (Rot/Grün/Blau/Gelb — default
  Rot+Grün, i.e. today's ``keep_colors={red, green}``) and the
  *Zusätzliche Hex-Farben* entry (explicit hex colours / ranges such as
  ``FF0000, 00FF00, 000001-0000FF`` left un-inverted, ADR 0004).
* A *Preview* button that shows the first page before/after processing.
* A *Run* button that processes the entire document and displays a progress
  bar.  On success a "Done" dialog (own ``Toplevel``) offers the button
  "Speicherordner öffnen", which opens the file manager at the output
  (ADR 0011, D3), so beginners can find their result.

All heavy work runs in a background thread so the UI stays responsive.
"""

import json
import logging
import queue
import threading
from pathlib import Path
from tkinter import (
    Tk,
    Frame,
    Label,
    Entry,
    Button,
    Checkbutton,
    IntVar,
    StringVar,
    Toplevel,
    TclError,
    filedialog,
    messagebox,
    ttk,
)

from PIL import Image, ImageTk
import cv2
import numpy as np

from . import processing
from .cli import _plan_jobs, parse_keep_hex
from .diagnostics import diagnose_pdf
from .pdfpipeline import process_pdf
from .processing import SmartboardError
from .reveal import reveal_output

logger = logging.getLogger(__name__)

#: Choices for the target-background combobox (index 0 = strict complement,
#: index 1 = pure white).
BG_TARGET_CHOICES = ("Complement (255 − v)", "Reinweiß (255,255,255)")

#: (widget attribute, CLI colour name) pairs for the "Markerfarben
#: erhalten" checkboxes (ADR 0011, D1 — replaces the fixed
#: keep_colors={red, green} of ADR 0005 D2).  Defaults: red + green
#: checked (= the historical default behaviour).
MARKER_COLOUR_VARS = (
    ("keep_red_var", "Rot", "red"),
    ("keep_green_var", "Grün", "green"),
    ("keep_blue_var", "Blau", "blue"),
    ("keep_yellow_var", "Gelb", "yellow"),
)


class SmartboardGUI:
    def __init__(self, master: Tk):
        self.master = master
        master.title("Smartboard PDF Inverter")
        master.geometry("660x700")
        self.create_widgets()
        # Thread-safe event queue: worker threads must never touch Tk
        # widgets directly (tkinter is not thread-safe); they enqueue
        # callbacks that the main loop executes (see _poll_events).
        self._events: "queue.Queue" = queue.Queue()
        master.after(100, self._poll_events)

    def create_widgets(self):
        # ---------- File/folder selection ----------
        file_frame = Frame(self.master)
        file_frame.pack(fill="x", padx=10, pady=5)
        Label(file_frame, text="Input:").pack(side="left")
        self.input_path = Entry(file_frame, width=44)
        self.input_path.pack(side="left", padx=5)
        Button(file_frame, text="PDF…", command=self.browse_file).pack(side="left")
        Button(file_frame, text="Folder…", command=self.browse_folder).pack(side="left")

        out_frame = Frame(self.master)
        out_frame.pack(fill="x", padx=10, pady=5)
        Label(out_frame, text="Output (optional):").pack(side="left")
        self.output_path = Entry(out_frame, width=44)
        self.output_path.pack(side="left", padx=5)
        self.output_path.insert(0, "")
        Button(out_frame, text="Browse…", command=self.browse_output).pack(side="left")
        Label(
            self.master,
            text="(empty: PDF → <name>_inverted.pdf next to the input; folder → an output folder is required)",
        ).pack(anchor="w", padx=12)

        # ---------- Options ----------
        # ADR 0009: no DPI control — the GUI processes at the pipeline
        # default (150 dpi); the CLI --dpi remains for power users.
        # ADR 0011, D1: only the everyday options stay directly visible;
        # the advanced options (invert / marker colours / hex entry) live
        # in a collapsible section, collapsed by default.
        opts_frame = Frame(self.master)
        opts_frame.pack(fill="x", padx=10, pady=5)
        # crop is ON by default (ADR 0006, v0.7.1): the page should contain
        # only the visible board area
        self.crop_var = IntVar(value=1)
        Checkbutton(opts_frame, text="Auf Board zuschneiden (Rand entfernen)", variable=self.crop_var).grid(row=0, column=0, columnspan=2, sticky="w")
        # Target background (v0.5.0)
        Label(opts_frame, text="Zielhintergrund:").grid(row=1, column=0, sticky="w")
        self.bg_var = StringVar(value=BG_TARGET_CHOICES[0])
        # readonly by design; _reset_ui() restores the state after the
        # generic enable/disable walk of _set_controls_state()
        self.bg_combo = ttk.Combobox(
            opts_frame,
            textvariable=self.bg_var,
            values=BG_TARGET_CHOICES,
            state="readonly",
            width=28,
        )
        self.bg_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=5)

        # ---------- Advanced options (ADR 0011, D1) ----------
        # Collapsed by default so the beginner view stays minimal.  The
        # toggle button is walked by _set_controls_state() like every other
        # control (disabled while a run is in progress).
        self.advanced_btn = Button(
            self.master,
            text="▸ Erweiterte Optionen",
            command=self._toggle_advanced,
        )
        self.advanced_btn.pack(anchor="w", padx=12, pady=(0, 2))
        # Not packed initially = hidden.  Toggling only maps/unmaps the
        # frame, so expanding never resets an option's state.
        self.advanced_frame = Frame(self.master)
        self.invert_var = IntVar(value=1)
        Checkbutton(
            self.advanced_frame, text="Invert colours", variable=self.invert_var
        ).grid(row=0, column=0, columnspan=4, sticky="w")
        Label(
            self.advanced_frame, text="Markerfarben erhalten:"
        ).grid(row=1, column=0, columnspan=4, sticky="w")
        for col, (attr, label, _cli_name) in enumerate(MARKER_COLOUR_VARS):
            default_on = _cli_name in ("red", "green")  # historical default
            setattr(self, attr, IntVar(value=1 if default_on else 0))
            Checkbutton(
                self.advanced_frame, text=label, variable=getattr(self, attr)
            ).grid(row=2, column=col, sticky="w", padx=(0, 14) if col < 3 else 0)
        # Explicit hex colours / ranges left un-inverted (ADR 0004); empty =
        # off.  Parsed in the main thread before the worker starts (see
        # _parse_keep_hex); the field is intentionally NOT cleared after a run.
        # It stays a writable Entry — architecture prep for the later
        # colour-picker idea (ADR 0011, D4).
        Label(self.advanced_frame, text="Zusätzliche Hex-Farben:").grid(
            row=3, column=0, sticky="w"
        )
        self.keep_hex_entry = Entry(self.advanced_frame, width=44)
        self.keep_hex_entry.grid(row=3, column=1, columnspan=3, sticky="w", padx=5)
        Label(
            self.advanced_frame,
            text="(z.B. FF0000, 00FF00, 000001-0000FF — leer = aus)",
        ).grid(row=4, column=0, columnspan=4, sticky="w")

        # ---------- Preview ----------
        preview_frame = Frame(self.master)
        preview_frame.pack(fill="both", expand=True, padx=10, pady=5)
        Button(preview_frame, text="Preview first page", command=self.preview).pack(pady=5)
        self.preview_canvas = ttk.Label(preview_frame)
        self.preview_canvas.pack(expand=True)

        # ---------- Run & Progress ----------
        run_frame = Frame(self.master)
        run_frame.pack(fill="x", padx=10, pady=5)
        Button(run_frame, text="Run", command=self.start_processing).pack(side="left")
        self.progress = ttk.Progressbar(run_frame, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", expand=True, side="left", padx=5)

    def _transform_options(self) -> dict:
        """Current transformation options (target background + kept colours).

        Read in the calling (main) thread and handed over as plain values –
        the same rule the thread-safe event queue is built on.

        ``keep_colors`` is the set of checked "Markerfarben erhalten"
        checkboxes (ADR 0011, D1 — replaces the fixed ``{red, green}`` of
        ADR 0005 D2); the defaults (Rot+Grün checked) reproduce the
        historical behaviour exactly.
        """
        keep = {
            cli_name
            for attr, _label, cli_name in MARKER_COLOUR_VARS
            if getattr(self, attr).get()
        }
        return {
            "bg_target": None if self.bg_var.get() == BG_TARGET_CHOICES[0] else (255, 255, 255),
            "keep_colors": frozenset(keep),
        }

    def _toggle_advanced(self) -> None:
        """Show/hide the advanced options frame (ADR 0011, D1).

        The frame is only mapped/unmapped — its widgets keep their state,
        so expanding the section never resets an option.
        """
        if self.advanced_frame.winfo_manager():
            self.advanced_frame.pack_forget()
            self.advanced_btn.configure(text="▸ Erweiterte Optionen")
        else:
            self.advanced_frame.pack(
                fill="x", padx=10, pady=(0, 5), after=self.advanced_btn
            )
            self.advanced_btn.configure(text="▾ Erweiterte Optionen")
        self._adjust_window_height()

    def _adjust_window_height(self) -> None:
        """Grow the fixed-geometry window to fit the (advanced) content."""
        self.master.update_idletasks()
        height = max(700, self.master.winfo_reqheight())
        self.master.geometry(f"660x{height}")

    def _parse_keep_hex(self):
        """Parse the hex-keep entry (main thread, single choke point).

        Returns the parsed segments (empty tuple = feature off), or ``None``
        when the entry is invalid — in which case an error dialog is shown
        and the caller must abort *before* disabling controls or starting
        the worker.
        """
        try:
            return parse_keep_hex(self.keep_hex_entry.get())
        except SmartboardError as e:
            messagebox.showerror("Ungültige Hex-Farben", str(e))
            return None

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.input_path.delete(0, "end")
            self.input_path.insert(0, path)

    def browse_folder(self):
        path = filedialog.askdirectory(title="Select a folder containing PDFs")
        if path:
            self.input_path.delete(0, "end")
            self.input_path.insert(0, path)

    def browse_output(self):
        if Path(self.input_path.get().strip()).is_dir():
            path = filedialog.askdirectory(title="Select the output folder")
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")]
            )
        if path:
            self.output_path.delete(0, "end")
            self.output_path.insert(0, path)

    def _resolve_input(self):
        """Return the input path (str) or None with a warning shown."""
        pdf_path = self.input_path.get().strip()
        if not pdf_path:
            messagebox.showwarning("Missing file", "Please select an input PDF or folder first.")
            return None
        p = Path(pdf_path)
        if p.is_dir():
            pdfs = sorted(p.glob("*.pdf"))
            if not pdfs:
                messagebox.showwarning("No PDFs", f"No .pdf files found in:\n{p}")
                return None
            # Preview the first PDF of the folder.
            return str(pdfs[0])
        return pdf_path

    def preview(self):
        pdf_path = self._resolve_input()
        if pdf_path is None:
            return
        try:
            # Validate the hex-keep entry in the main thread BEFORE the
            # (potentially slow) render — fail fast like start_processing.
            keep_segments = self._parse_keep_hex()
            if keep_segments is None:
                return
            # ADR 0009: fixed internal DPI (pdf_to_images default = 150)
            images = processing.pdf_to_images(pdf_path)
            if not images:
                raise SmartboardError("No pages rendered")
            first = images[0]
            transform_options = self._transform_options()
            processed, det = processing.enhance_image_ex(
                first,
                invert=bool(self.invert_var.get()),
                bg_target=transform_options["bg_target"],
                keep_colors=transform_options["keep_colors"],
                keep_segments=keep_segments,
            )
            if not det.found:
                logger.warning("No smartboard region on first page: %s", det.message)
            # Convert both to PIL for display side‑by‑side.
            orig_pil = Image.fromarray(cv2.cvtColor(first, cv2.COLOR_BGR2RGB))
            proc_pil = Image.fromarray(cv2.cvtColor(processed, cv2.COLOR_BGR2RGB))
            # Resize to fit the canvas while keeping aspect ratio.
            max_h = 250
            scale = max_h / max(orig_pil.height, proc_pil.height)
            new_w = int(orig_pil.width * scale)
            new_h = int(orig_pil.height * scale)
            orig_pil = orig_pil.resize((new_w, new_h), Image.LANCZOS)
            proc_pil = proc_pil.resize((new_w, new_h), Image.LANCZOS)
            # Combine side‑by‑side.
            combined = Image.new("RGB", (new_w * 2 + 10, new_h), "white")
            combined.paste(orig_pil, (0, 0))
            combined.paste(proc_pil, (new_w + 10, 0))
            tk_img = ImageTk.PhotoImage(combined)
            self.preview_canvas.configure(image=tk_img)
            self.preview_canvas.image = tk_img  # keep reference
        except SmartboardError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            logger.exception("Unexpected error during preview")
            messagebox.showerror("Error", f"Unexpected error: {e}")

    def start_processing(self):
        pdf_path = self.input_path.get().strip()
        out_field = self.output_path.get().strip()
        if not pdf_path:
            messagebox.showwarning("Missing file", "Please select an input PDF or folder first.")
            return
        # Folder input needs an output folder (checked here, main thread,
        # before any worker starts); the raw fields are handed to the worker,
        # which plans the jobs with the same helper as the CLI (ADR 0007, D2).
        if Path(pdf_path).is_dir() and not out_field:
            messagebox.showwarning(
                "Missing output",
                "For folder input please specify an output folder.",
            )
            return
        # Validate the hex-keep entry first (main thread): on an error the
        # dialog is shown and the run is aborted WITHOUT disabling controls.
        keep_segments = self._parse_keep_hex()
        if keep_segments is None:
            return
        # ADR 0011, D2: pre-check a single-file input for file-level
        # problems (password-protected / damaged / no pages / missing)
        # BEFORE anything else runs — fail-fast with a clear dialog, no
        # worker.  Folder inputs are clarified per file in the worker loop
        # instead (the batch keeps going, like the CLI).
        if not Path(pdf_path).is_dir():
            problem = diagnose_pdf(pdf_path)
            if problem is not None:
                messagebox.showerror("Cannot process", problem)
                return
        # Read the Tk variables in the main thread (Tk thread-safety) and hand
        # plain values to the worker.
        # ADR 0009: no "dpi" here — process_pdf's default (150) applies.
        options = {
            "invert": bool(self.invert_var.get()),
            "crop": bool(self.crop_var.get()),
            "keep_segments": keep_segments,
            **self._transform_options(),
        }
        # Disable controls while processing.
        self._set_controls_state("disabled")
        threading.Thread(
            target=self._process_worker,
            args=(pdf_path, out_field, options),
            daemon=True,
        ).start()

    def _poll_events(self) -> None:
        """Main-loop pump that executes UI events queued by worker threads.

        tkinter widgets may only be touched from the main thread; calling
        ``widget.after(ms, func)`` from a worker thread already fails
        (callback registration happens in the calling thread).  The queue
        keeps all Tk interaction in the main loop.
        """
        try:
            while True:
                event = self._events.get_nowait()
                try:
                    event()
                except Exception:
                    logger.exception("error while processing a UI event")
        except queue.Empty:
            pass
        self.master.after(100, self._poll_events)

    def _process_worker(self, pdf_path: str, out_field: str, options: dict):
        def on_progress(n, total):
            # Thread-safe: the Tk update runs on the main thread.
            self._events.put(
                lambda n=n, total=total: self.progress.configure(maximum=total, value=n)
            )

        def dialog(title: str, message: str, error: bool = False):
            # The message MUST be bound eagerly (default arguments): the
            # lambda runs later in the main thread, where any `except ... as
            # e` variable is already unbound (PEP 3110) — ADR 0007, D3.
            fn = messagebox.showerror if error else messagebox.showinfo
            self._events.put(lambda t=title, m=message, f=fn: f(t, m))

        try:
            try:
                jobs = _plan_jobs(
                    Path(pdf_path), Path(out_field) if out_field else None
                )
            except SmartboardError as e:
                dialog("Error", str(e), error=True)
                return

            total = len(jobs)
            failures: list = []
            results = []
            last_result = None
            for idx, (src, dst) in enumerate(jobs):
                try:
                    last_result = process_pdf(
                        src,
                        dst,
                        invert=options["invert"],
                        crop=options["crop"],
                        bg_target=options.get("bg_target"),
                        keep_colors=options.get("keep_colors", frozenset()),
                        keep_segments=options.get("keep_segments", ()),
                        # Page-level progress for the single-file case;
                        # file-level (below) for batches.
                        progress=on_progress if total == 1 else None,
                    )
                    results.append(last_result)
                except SmartboardError as e:
                    logger.error("Failed to process %s: %s", src, e)
                    # ADR 0011, D2: file-level problems get the clear
                    # user-facing message instead of the raw pipeline error.
                    failures.append(f"{src.name}: {diagnose_pdf(src) or e}")
                except Exception:  # a bad file must not kill the batch
                    logger.exception("Unexpected error while processing %s", src)
                    failures.append(
                        f"{src.name}: "
                        f"{diagnose_pdf(src) or 'unexpected error (see log)'}"
                    )
                if total > 1:
                    on_progress(idx + 1, total)

            # ADR 0011, D2 / P10-FR-6: extra Done-dialog line when no board
            # was detected on any page — the output is just a copy.
            def no_board_line() -> str:
                pages = [page for res in results for page in res.pages]
                if pages and not any(page.detected for page in pages):
                    return (
                        "\n\nNo smartboard region detected on any page — "
                        "the output is an unchanged copy of the input."
                    )
                return ""

            if failures:
                detail = "\n".join(failures[:5])
                more = (
                    f"\n… and {len(failures) - 5} more" if len(failures) > 5 else ""
                )
                dialog(
                    "Some files failed",
                    f"{len(failures)} of {total} file(s) failed:\n{detail}{more}",
                    error=True,
                )
            elif total == 1:
                message = (
                    f"Saved to {jobs[0][1]}\n{last_result.summary()}{no_board_line()}"
                )
                # ADR 0011, D3: the success dialog is an own Toplevel with
                # the "Speicherordner öffnen" button (messagebox cannot
                # carry extra buttons).  Single file -> the file manager
                # marks the output file.
                target = jobs[0][1]
                self._events.put(
                    lambda m=message, t=target: self._show_done_dialog(m, t)
                )
            else:
                message = (
                    f"Saved {total} file(s) to {jobs[0][1].parent}{no_board_line()}"
                )
                # Batch success -> open the output folder (ADR 0011, D3).
                target = jobs[0][1].parent
                self._events.put(
                    lambda m=message, t=target: self._show_done_dialog(m, t)
                )
        finally:
            # Re‑enable UI components (executed on the main thread).
            self._events.put(self._reset_ui)

    def _show_done_dialog(self, message: str, reveal_target: "Path | str") -> None:
        """The success dialog (ADR 0011, D3).

        Own ``Toplevel`` (instead of ``messagebox.showinfo``, which cannot
        carry extra buttons): the message plus the German
        "Speicherordner öffnen" button (explicit user request) that opens
        the file manager at the output, and "OK".

        Runs in the main thread (the worker queues it like every other UI
        event).  Modal while open (``grab_set``) so the main window cannot
        be operated underneath; "Speicherordner öffnen" keeps the dialog
        open (the file manager opens alongside it), "OK" closes it.
        """
        win = Toplevel(self.master)
        win.title("Done")
        win.transient(self.master)
        Label(win, text=message, justify="left", padx=20).pack(pady=(20, 10))
        buttons = Frame(win)
        buttons.pack(pady=(0, 15))
        Button(
            buttons,
            text="Speicherordner öffnen",
            # reveal_output() is non-blocking (Popen) and never raises
            # (missing opener -> log warning, ADR 0011, D3).
            command=lambda: (reveal_output(reveal_target), win.focus_set()),
        ).pack(side="left", padx=5)
        Button(buttons, text="OK", command=win.destroy).pack(side="left", padx=5)
        win.grab_set()
        win.focus_set()

    def _set_controls_state(self, state: str) -> None:
        """Set the state ('normal'/'disabled') of every interactive widget.

        The widget tree is walked recursively: the direct children of the
        top-level window are Frames (which do not support the ``-state``
        option and therefore raised ``TclError``); the actual controls
        (buttons, entries, checkboxes, slider) live inside them.  Widgets
        without a ``-state`` option (Frame, Label, ...) are skipped.
        """

        def _walk(widget) -> None:
            for child in widget.winfo_children():
                try:
                    child.configure(state=state)
                except TclError:
                    pass
                _walk(child)

        _walk(self.master)

    def _reset_ui(self):
        self._set_controls_state("normal")
        # _set_controls_state() sets every -state widget to "normal", which
        # would make the target-background combobox editable – restore it.
        self.bg_combo.configure(state="readonly")
        self.progress['value'] = 0


def main():
    root = Tk()
    app = SmartboardGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
