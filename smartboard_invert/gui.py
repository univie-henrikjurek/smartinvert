"""Very small Tkinter based GUI for the Smartboard Inversion tool.

The GUI mirrors the CLI options but presents them in a graphical form:

* File chooser for the input PDF.
* DPI slider (50‑300).
* Checkboxes for *Invert*, *CLAHE* and *Noise cleaning*.
* A *Preview* button that shows the first page before/after processing.
* A *Run* button that processes the entire document and displays a progress bar.

All heavy work runs in a background thread so the UI stays responsive.
"""

import json
import logging
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


class SmartboardGUI:
    def __init__(self, master: Tk):
        self.master = master
        master.title("Smartboard PDF Inverter")
        master.geometry("600x500")
        self.create_widgets()

    def create_widgets(self):
        # ---------- File selection ----------
        file_frame = Frame(self.master)
        file_frame.pack(fill="x", padx=10, pady=5)
        Label(file_frame, text="Input PDF:").pack(side="left")
        self.input_path = Entry(file_frame, width=50)
        self.input_path.pack(side="left", padx=5)
        Button(file_frame, text="Browse", command=self.browse_file).pack(side="left")

        # ---------- Options ----------
        opts_frame = Frame(self.master)
        opts_frame.pack(fill="x", padx=10, pady=5)
        # DPI slider
        Label(opts_frame, text="DPI:").grid(row=0, column=0, sticky="w")
        self.dpi_var = DoubleVar(value=150)
        self.dpi_slider = ttk.Scale(opts_frame, from_=50, to=300, orient="horizontal", variable=self.dpi_var)
        self.dpi_slider.grid(row=0, column=1, sticky="ew", padx=5)
        opts_frame.columnconfigure(1, weight=1)
        # Checkboxes
        self.invert_var = IntVar(value=1)
        Checkbutton(opts_frame, text="Invert colours", variable=self.invert_var).grid(row=1, column=0, columnspan=2, sticky="w")
        self.clahe_var = IntVar(value=0)
        Checkbutton(opts_frame, text="Apply CLAHE (legacy)", variable=self.clahe_var).grid(row=2, column=0, columnspan=2, sticky="w")
        self.clean_var = IntVar(value=0)
        Checkbutton(opts_frame, text="Noise cleaning (legacy)", variable=self.clean_var).grid(row=3, column=0, columnspan=2, sticky="w")

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

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.input_path.delete(0, "end")
            self.input_path.insert(0, path)

    def preview(self):
        pdf_path = self.input_path.get().strip()
        if not pdf_path:
            messagebox.showwarning("Missing file", "Please select an input PDF first.")
            return
        try:
            images = processing.pdf_to_images(pdf_path, dpi=int(self.dpi_var.get()))
            if not images:
                raise SmartboardError("No pages rendered")
            first = images[0]
            processed, det = processing.enhance_image_ex(
                first,
                invert=bool(self.invert_var.get()),
                apply_clahe=bool(self.clahe_var.get()),
                clean=bool(self.clean_var.get()),
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
        if not pdf_path:
            messagebox.showwarning("Missing file", "Please select an input PDF first.")
            return
        out_path = Path(pdf_path).with_name(Path(pdf_path).stem + "_inverted.pdf")
        # Read the Tk variables in the main thread (Tk thread-safety) and hand
        # plain values to the worker.
        options = {
            "dpi": int(self.dpi_var.get()),
            "invert": bool(self.invert_var.get()),
            "clahe": bool(self.clahe_var.get()),
            "clean": bool(self.clean_var.get()),
        }
        # Disable controls while processing.
        for child in self.master.winfo_children():
            child.configure(state="disabled")
        threading.Thread(
            target=self._process_worker, args=(pdf_path, out_path, options), daemon=True
        ).start()

    def _process_worker(self, pdf_path: str, out_path: Path, options: dict):
        def on_progress(n: int, total: int):
            def _update():
                self.progress["maximum"] = total
                self.progress["value"] = n

            self.master.after(0, _update)

        try:
            result = process_pdf(
                pdf_path,
                out_path,
                dpi=options["dpi"],
                invert=options["invert"],
                apply_clahe=options["clahe"],
                clean=options["clean"],
                progress=on_progress,
            )
            self.master.after(
                0, lambda: messagebox.showinfo("Done", f"Saved to {out_path}\n{result.summary()}")
            )
        except SmartboardError as e:
            self.master.after(0, lambda: messagebox.showerror("Error", str(e)))
        except Exception as e:
            logger.exception("Unexpected error during processing")
            self.master.after(0, lambda: messagebox.showerror("Error", f"Unexpected error: {e}"))
        finally:
            # Re‑enable UI components.
            self.master.after(0, self._reset_ui)

    def _reset_ui(self):
        for child in self.master.winfo_children():
            child.configure(state="normal")
        self.progress['value'] = 0


def main():
    root = Tk()
    app = SmartboardGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
