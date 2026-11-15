"""Very small Tkinter based GUI for the Smartboard Inversion tool.

The GUI mirrors the CLI options but presents them in a graphical form:

* File chooser for the input PDF.
* DPI slider (50‑300).
* Checkboxes for *Invert*, *CLAHE*, *Noise cleaning* and *Crop to board*.
* *Target background* combobox (complement or pure white) and checkboxes to
  keep the red/green marker colours un-inverted.
* A *Preview* button that shows the first page before/after processing.
* A *Run* button that processes the entire document and displays a progress bar.

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
    DoubleVar,
    StringVar,
    TclError,
    filedialog,
    messagebox,
    ttk,
)

from PIL import Image, ImageTk
import cv2
import numpy as np

from . import processing
from .pdfpipeline import process_pdf
from .processing import SmartboardError

logger = logging.getLogger(__name__)

#: Choices for the target-background combobox (index 0 = strict complement,
#: index 1 = pure white).
BG_TARGET_CHOICES = ("Complement (255 − v)", "Reinweiß (255,255,255)")


class SmartboardGUI:
    def __init__(self, master: Tk):
        self.master = master
        master.title("Smartboard PDF Inverter")
        master.geometry("660x760")
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
        opts_frame = Frame(self.master)
        opts_frame.pack(fill="x", padx=10, pady=5)
        # DPI slider (with a live value readout so the position is never a
        # guess)
        Label(opts_frame, text="DPI:").grid(row=0, column=0, sticky="w")
        self.dpi_var = DoubleVar(value=150)
        self.dpi_value = Label(opts_frame, text="150", width=4, anchor="e")
        self.dpi_slider = ttk.Scale(
            opts_frame,
            from_=50,
            to=300,
            orient="horizontal",
            variable=self.dpi_var,
            command=self._on_dpi_change,
        )
        self.dpi_slider.grid(row=0, column=1, sticky="ew", padx=5)
        self.dpi_value.grid(row=0, column=2, sticky="w", padx=(4, 0))
        opts_frame.columnconfigure(1, weight=1)
        # Checkboxes
        self.invert_var = IntVar(value=1)
        Checkbutton(opts_frame, text="Invert colours", variable=self.invert_var).grid(row=1, column=0, columnspan=2, sticky="w")
        self.clahe_var = IntVar(value=0)
        Checkbutton(opts_frame, text="Apply CLAHE (legacy)", variable=self.clahe_var).grid(row=2, column=0, columnspan=2, sticky="w")
        self.clean_var = IntVar(value=0)
        Checkbutton(opts_frame, text="Noise cleaning (legacy)", variable=self.clean_var).grid(row=3, column=0, columnspan=2, sticky="w")
        self.crop_var = IntVar(value=0)
        Checkbutton(opts_frame, text="Auf Board zuschneiden (Rand entfernen)", variable=self.crop_var).grid(row=4, column=0, columnspan=2, sticky="w")
        # Target background + kept marker colours (v0.5.0)
        Label(opts_frame, text="Zielhintergrund:").grid(row=5, column=0, sticky="w")
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
        self.bg_combo.grid(row=5, column=1, columnspan=2, sticky="w", padx=5)
        self.keep_red_var = IntVar(value=1)
        Checkbutton(opts_frame, text="Rot erhalten", variable=self.keep_red_var).grid(row=6, column=0, columnspan=2, sticky="w")
        self.keep_green_var = IntVar(value=1)
        Checkbutton(opts_frame, text="Grün erhalten", variable=self.keep_green_var).grid(row=7, column=0, columnspan=2, sticky="w")

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

    def _on_dpi_change(self, _value) -> None:
        """Keep the DPI value label in sync with the slider."""
        self.dpi_value.configure(text=str(int(float(self.dpi_var.get()))))

    def _transform_options(self) -> dict:
        """Current transformation options (target background + kept colours).

        Read in the calling (main) thread and handed over as plain values –
        the same rule the thread-safe event queue is built on.
        """
        return {
            "bg_target": None if self.bg_var.get() == BG_TARGET_CHOICES[0] else (255, 255, 255),
            "keep_colors": frozenset(
                name
                for name, var in (("red", self.keep_red_var), ("green", self.keep_green_var))
                if var.get()
            ),
        }

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
            images = processing.pdf_to_images(pdf_path, dpi=int(self.dpi_var.get()))
            if not images:
                raise SmartboardError("No pages rendered")
            first = images[0]
            transform_options = self._transform_options()
            processed, det = processing.enhance_image_ex(
                first,
                invert=bool(self.invert_var.get()),
                apply_clahe=bool(self.clahe_var.get()),
                clean=bool(self.clean_var.get()),
                bg_target=transform_options["bg_target"],
                keep_colors=transform_options["keep_colors"],
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
        in_p = Path(pdf_path)
        if in_p.is_dir():
            if not out_field:
                messagebox.showwarning(
                    "Missing output",
                    "For folder input please specify an output folder.",
                )
                return
            out_path = Path(out_field)
        else:
            # Empty output field keeps the legacy name next to the input.
            out_path = (
                Path(out_field)
                if out_field
                else in_p.with_name(in_p.stem + "_inverted.pdf")
            )
        # Read the Tk variables in the main thread (Tk thread-safety) and hand
        # plain values to the worker.
        options = {
            "dpi": int(self.dpi_var.get()),
            "invert": bool(self.invert_var.get()),
            "clahe": bool(self.clahe_var.get()),
            "clean": bool(self.clean_var.get()),
            "crop": bool(self.crop_var.get()),
            **self._transform_options(),
        }
        # Disable controls while processing.
        self._set_controls_state("disabled")
        threading.Thread(
            target=self._process_worker, args=(pdf_path, out_path, options), daemon=True
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

    def _process_worker(self, pdf_path: str, out_path: Path, options: dict):
        def on_progress(n, total):
            # Thread-safe: the Tk update runs on the main thread.
            self._events.put(
                lambda n=n, total=total: self.progress.configure(maximum=total, value=n)
            )

        try:
            result = process_pdf(
                pdf_path,
                out_path,
                dpi=options["dpi"],
                invert=options["invert"],
                apply_clahe=options["clahe"],
                clean=options["clean"],
                crop=options["crop"],
                bg_target=options.get("bg_target"),
                keep_colors=options.get("keep_colors", frozenset()),
                progress=on_progress,
            )
            self._events.put(
                lambda: messagebox.showinfo("Done", f"Saved to {out_path}\n{result.summary()}")
            )
        except SmartboardError as e:
            self._events.put(lambda: messagebox.showerror("Error", str(e)))
        except Exception as e:
            logger.exception("Unexpected error during processing")
            self._events.put(lambda: messagebox.showerror("Error", f"Unexpected error: {e}"))
        finally:
            # Re‑enable UI components (executed on the main thread).
            self._events.put(self._reset_ui)

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
