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
    Open images safely for PDF: fix EXIF orientation, ensure RGB or L.
    Return list of PIL.Image objects.
    """
    opened = []
    for p in paths:
        img = Image.open(p)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        opened.append(img)
    return opened


def ensure_unique_path(path: str) -> str:
    """
    If 'path' exists, append ' (2)', ' (3)', ... before extension.
    """
    base, ext = os.path.splitext(path)
    if not os.path.exists(path):
        return path
    i = 2
    while True:
        candidate = f"{base} ({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


class JPG2PDFApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Merge JPGs to Single PDF (Batch by Subfolder)")

        # State
        self.folder_var = StringVar(value="")
        self.output_var = StringVar(value="")  # kept but unused in batch mode
        self.sort_var = StringVar(value="Natural (img2 < img10)")
        self.resolution_var = StringVar(value="300")  # DPI for PDF metadata
        self.include_top_folder = BooleanVar(value=True)  # also process the chosen folder itself

        # UI
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(root)
        frm.pack(fill="both", expand=True, **pad)

        # Folder picker
        row = 0
        ttk.Label(frm, text="Top-level folder:").grid(row=row, column=0, sticky="w")
        folder_entry = ttk.Entry(frm, textvariable=self.folder_var, width=54)
        folder_entry.grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Select Folder", command=self.on_pick_folder).grid(row=row, column=2)

        # Output file (disabled/ignored in batch mode)
        row += 1
        ttk.Label(frm, text="Output PDF (ignored in batch mode):").grid(row=row, column=0, sticky="w")
        out_entry = ttk.Entry(frm, textvariable=self.output_var, width=54, state="disabled")
        out_entry.grid(row=row, column=1, sticky="we", **pad)
        ttk.Button(frm, text="Browse…", state="disabled").grid(row=row, column=2)

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

        # Include top folder toggle
        row += 1
        ttk.Checkbutton(frm, text="Also create a PDF in the top folder if it has JPGs",
                        variable=self.include_top_folder).grid(row=row, column=0, columnspan=3, sticky="w", **pad)

        # Progress bar
        row += 1
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="we", **pad)

        # Status
        row += 1
        self.status = ttk.Label(frm, text="Select a top-level folder to begin.")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w")

        # Action buttons
        row += 1
        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="e", **pad)
        ttk.Button(btn_frame, text="Batch Merge (one PDF per folder)", command=self.on_batch_merge).pack(side="right", padx=6)
        ttk.Button(btn_frame, text="Quit", command=root.quit).pack(side="right")

        frm.columnconfigure(1, weight=1)

    def on_pick_folder(self):
        folder = filedialog.askdirectory(title="Select top-level folder")
        if folder:
            self.folder_var.set(folder)
            self.update_folder_stats()

    def update_folder_stats(self):
        folder = self.folder_var.get()
        if not folder or not os.path.isdir(folder):
            self.status.config(text="No folder selected.")
            return

        # Count how many subfolders (and optionally top folder) have JPGs
        count_folders = 0
        count_imgs_total = 0

        if self.include_top_folder.get():
            imgs = find_jpgs(folder)
            if imgs:
                count_folders += 1
                count_imgs_total += len(imgs)

        for dirpath, dirnames, filenames in os.walk(folder):
            if dirpath == folder:
                continue  # skip top here; handled above according to toggle
            imgs = find_jpgs(dirpath)
            if imgs:
                count_folders += 1
                count_imgs_total += len(imgs)

        self.status.config(text=f"Found {count_imgs_total} image(s) across {count_folders} folder(s).")

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

    def folders_with_images(self, top: str):
        """
        Yield (dirpath, [image_paths]) for each folder that contains JPGs.
        Respects include_top_folder toggle.
        """
        if self.include_top_folder.get():
            imgs = find_jpgs(top)
            if imgs:
                yield top, imgs

        for dirpath, dirnames, filenames in os.walk(top):
            if dirpath == top:
                continue  # top handled above (or skipped)
            imgs = find_jpgs(dirpath)
            if imgs:
                yield dirpath, imgs

    def write_pdf_for_folder(self, folder: str, img_paths, dpi: float):
        # Sort images according to UI choice
        img_paths = self.sort_paths(img_paths)

        # Load images
        opened = load_images_for_pdf(img_paths)
        try:
            first = opened[0]
            if first.mode not in ("RGB", "L"):
                first = first.convert("RGB")
            rest = []
            for im in opened[1:]:
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                rest.append(im)

            # Output path: <folder>/<basename>_merged.pdf (unique)
            base = os.path.basename(os.path.normpath(folder)) or "merged"
            out_pdf = os.path.join(folder, f"{base}_merged.pdf")
            out_pdf = ensure_unique_path(out_pdf)

            first.save(out_pdf, "PDF", save_all=True, append_images=rest, resolution=dpi)
            return out_pdf
        finally:
            # Always close images
            for im in opened:
                try:
                    im.close()
                except:
                    pass

    def on_batch_merge(self):
        folder = self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please select a valid top-level folder.")
            return

        # Parse DPI
        try:
            dpi = float(self.resolution_var.get())
        except ValueError:
            dpi = 300.0

        # Gather all target folders
        targets = list(self.folders_with_images(folder))
        if not targets:
            messagebox.showwarning("No images", "No .jpg/.jpeg files found in the top folder or subfolders.")
            return

        # Progress across folders
        self.progress["value"] = 0
        self.progress["maximum"] = len(targets)

        made = 0
        errors = []

        for idx, (dirpath, img_paths) in enumerate(targets, start=1):
            rel = os.path.relpath(dirpath, folder)
            if rel == ".":
                rel_display = "(top folder)"
            else:
                rel_display = rel

            try:
                self.status.config(text=f"Processing {idx}/{len(targets)}: {rel_display} ({len(img_paths)} image(s))…")
                self.root.update_idletasks()

                out_pdf = self.write_pdf_for_folder(dirpath, img_paths, dpi)
                made += 1
                self.status.config(text=f"Created: {out_pdf}")
            except Exception as e:
                errors.append((dirpath, str(e), traceback.format_exc()))
                self.status.config(text=f"Failed in {rel_display}: {e}")

            self.progress["value"] = idx
            self.root.update_idletasks()

        # Summary
        if errors:
            msg = [f"Created {made} PDF(s). {len(errors)} folder(s) failed:\n"]
            for d, err, _tb in errors:
                msg.append(f"- {d}\n  {err}")
            messagebox.showwarning("Completed with errors", "\n".join(msg))
        else:
            messagebox.showinfo("Success", f"Created {made} PDF(s) across {len(targets)} folder(s).")
        self.status.config(text="Done.")
        self.progress["value"] = 0


def main():
    root = Tk()
    # Optional: nicer default scaling on HiDPI (Windows)
    try:
        if sys.platform.startswith("win"):
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = JPG2PDFApp(root)
    root.minsize(660, 300)
    root.mainloop()


if __name__ == "__main__":
    main()
