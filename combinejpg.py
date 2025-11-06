import os
import re
import sys
import traceback
from datetime import datetime
from tkinter import Tk, StringVar, BooleanVar, filedialog, messagebox
from tkinter import ttk

from PIL import Image, ImageOps  # pip install pillow


def natural_key(s: str):
    """
    Natural sort key: 'img2.jpg' < 'img10.jpg'
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', s)]


def find_jpgs(folder: str):
    """
    Return list of absolute paths to .jpg/.jpeg files (non-recursive).
    """
    exts = {".jpg", ".jpeg"}
    items = []
    for name in os.listdir(folder):
        ext = os.path.splitext(name)[1].lower()
        if ext in exts:
            items.append(os.path.join(folder, name))
    return items


def load_images_for_pdf(paths):
    """
    Open images safely for PDF: fix EXIF orientation, ensure RGB.
    Return list of PIL.Image objects (first image + rest list).
    """
    opened = []
    for p in paths:
        img = Image.open(p)
        # Respect EXIF orientation & convert to RGB (PDF requires RGB or L)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        opened.append(img)
    return opened


class JPG2PDFApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Merge JPGs to Single PDF")

        # State
        self.folder_var = StringVar(value="")
        self.output_var = StringVar(value="")
        self.sort_var = StringVar(value="Natural (img2 < img10)")
        self.resolution_var = StringVar(value="300")  # DPI for PDF metadata
        self.include_subfolders = BooleanVar(value=False)  # kept for future use (currently non-recursive)

        # UI
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True, **pad)

        # Folder picker
        row = 0
        ttk.Label(frm, text="Source folder (JPG/JPEG):").grid(row=row, column=0, sticky="w")
        folder_entry = ttk.Entry(frm, textvariable=self.folder_var, width=54)
        folder_entry.grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Select Folder", command=self.on_pick_folder).grid(row=row, column=2)

        # Output file
        row += 1
        ttk.Label(frm, text="Output PDF:").grid(row=row, column=0, sticky="w")
        out_entry = ttk.Entry(frm, textvariable=self.output_var, width=54)
        out_entry.grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Browse…", command=self.on_pick_output).grid(row=row, column=2)

        # Sort & DPI
        row += 1
        ttk.Label(frm, text="Sort order:").grid(row=row, column=0, sticky="w")
        sort_combo = ttk.Combobox(frm, textvariable=self.sort_var, state="readonly",
                                  values=[
                                      "Natural (img2 < img10)",
                                      "Filename A → Z",
                                      "Filename Z → A",
                                      "Modified time (oldest → newest)",
                                      "Modified time (newest → oldest)"
                                  ])
        sort_combo.grid(row=row, column=1, sticky="we", **pad)
        sort_combo.current(0)

        row += 1
        ttk.Label(frm, text="PDF Resolution (DPI):").grid(row=row, column=0, sticky="w")
        dpi_entry = ttk.Entry(frm, textvariable=self.resolution_var, width=10)
        dpi_entry.grid(row=row, column=1, sticky="w", **pad)

        # Progress bar
        row += 1
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="we", **pad)

        # Status
        row += 1
        self.status = ttk.Label(frm, text="Select a folder to begin.")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w")

        # Action buttons
        row += 1
        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="e", **pad)
        ttk.Button(btn_frame, text="Merge to PDF", command=self.on_merge).pack(side="right", padx=6)
        ttk.Button(btn_frame, text="Quit", command=root.quit).pack(side="right")

        frm.columnconfigure(1, weight=1)

    def on_pick_folder(self):
        folder = filedialog.askdirectory(title="Select folder with JPG/JPEG images")
        if folder:
            self.folder_var.set(folder)
            # Suggest output path
            base = os.path.basename(os.path.normpath(folder)) or "merged"
            default_pdf = os.path.join(folder, f"{base}_merged.pdf")
            if not self.output_var.get():
                self.output_var.set(default_pdf)
            self.update_file_count()

    def update_file_count(self):
        folder = self.folder_var.get()
        if not folder or not os.path.isdir(folder):
            self.status.config(text="No folder selected.")
            return
        files = find_jpgs(folder)
        self.status.config(text=f"Found {len(files)} JPG/JPEG file(s) in the folder.")

    def on_pick_output(self):
        initial = self.output_var.get() or "merged.pdf"
        path = filedialog.asksaveasfilename(
            title="Save merged PDF as…",
            defaultextension=".pdf",
            initialfile=os.path.basename(initial),
            initialdir=os.path.dirname(initial) if initial else None,
            filetypes=[("PDF files", "*.pdf")]
        )
        if path:
            self.output_var.set(path)

    def sort_paths(self, paths):
        mode = self.sort_var.get()
        if mode.startswith("Natural"):
            return sorted(paths, key=lambda p: natural_key(os.path.basename(p)))
        elif mode.startswith("Filename A"):
            return sorted(paths, key=lambda p: os.path.basename(p).lower())
        elif mode.startswith("Filename Z"):
            return sorted(paths, key=lambda p: os.path.basename(p).lower(), reverse=True)
        elif mode.startswith("Modified time (oldest"):
            return sorted(paths, key=lambda p: os.path.getmtime(p))
        elif mode.startswith("Modified time (newest"):
            return sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True)
        else:
            return paths

    def on_merge(self):
        folder = self.folder_var.get().strip()
        out_pdf = self.output_var.get().strip()

        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please select a valid folder.")
            return

        files = find_jpgs(folder)
        if not files:
            messagebox.showwarning("No images", "No .jpg/.jpeg files found in the selected folder.")
            return

        files = self.sort_paths(files)

        if not out_pdf:
            messagebox.showerror("Error", "Please specify an output PDF path.")
            return

        # Ensure output directory exists
        out_dir = os.path.dirname(out_pdf) or folder
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create output directory:\n{e}")
                return

        # Parse DPI
        try:
            dpi = float(self.resolution_var.get())
        except ValueError:
            dpi = 300.0

        # Merge
        try:
            self.progress["value"] = 0
            self.progress["maximum"] = len(files)
            self.status.config(text="Opening images…")

            opened = []
            for idx, p in enumerate(files, start=1):
                opened.append(ImageOps.exif_transpose(Image.open(p)))
                self.progress["value"] = idx
                self.status.config(text=f"Loaded {idx}/{len(files)}: {os.path.basename(p)}")
                self.root.update_idletasks()

            # Convert to RGB as needed
            first = opened[0]
            if first.mode not in ("RGB", "L"):
                first = first.convert("RGB")
            rest = []
            for img in opened[1:]:
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                rest.append(img)

            self.status.config(text="Writing PDF…")
            # Pillow uses the first image's size as the page size for all pages
            first.save(out_pdf, "PDF", save_all=True, append_images=rest, resolution=dpi)

            # Close images
            for im in opened:
                try:
                    im.close()
                except:
                    pass

            self.status.config(text=f"Done: {out_pdf}")
            messagebox.showinfo("Success", f"Merged {len(files)} image(s) into:\n{out_pdf}")

        except Exception as e:
            tb = traceback.format_exc()
            messagebox.showerror("Merge failed", f"{e}\n\nDetails:\n{tb}")
            self.status.config(text="Failed.")
        finally:
            self.progress["value"] = 0

def main():
    root = Tk()
    # Optional: nicer default scaling on HiDPI
    try:
        if sys.platform.startswith("win"):
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = JPG2PDFApp(root)
    root.minsize(620, 260)
    root.mainloop()


if __name__ == "__main__":
    main()
