import io
import os
import sys
from tkinter import Tk, filedialog, messagebox

# ---- Dependencies ----
try:
    import ebooklib
    from ebooklib import epub, ITEM_DOCUMENT, ITEM_IMAGE
    from bs4 import BeautifulSoup
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from PIL import Image as PILImage
except ImportError:
    sys.stderr.write(
        "Missing packages.\n"
        "Run: pip install ebooklib beautifulsoup4 reportlab pillow\n"
    )
    raise

# ---- Page and style constants (BORDERLESS) ----
PAGE_SIZE = A4
MARGIN = 0 * cm  # borderless
LINE_SPACING = 1.35
DEFAULT_FONT_SIZE = 20
H1_SIZE = 20
H2_SIZE = 20
H3_SIZE = 20
QUOTE_INDENT = 0.0  # no extra indentation on a borderless page
IMAGE_MAX_HEIGHT_RATIO = 0.98  # allow images to nearly fill the page height

# ---- Helpers for Japanese/CJK wrapping ----
def is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or
        0x3400 <= code <= 0x4DBF or
        0x3040 <= code <= 0x309F or
        0x30A0 <= code <= 0x30FF or
        0xFF00 <= code <= 0xFFEF or
        0x3000 <= code <= 0x303F
    )

def tokenize_for_wrap(text: str):
    tokens, buf, last_cjk = [], "", None
    for ch in text:
        if ch == "\u00A0":
            ch = " "
        if ch.isspace():
            if buf:
                tokens.append(buf); buf = ""
            tokens.append(ch); last_cjk = None
            continue
        cjk = is_cjk_char(ch)
        if last_cjk is None:
            buf = ch; last_cjk = cjk
        else:
            if cjk != last_cjk:
                tokens.append(buf); buf = ch; last_cjk = cjk
            else:
                if cjk:
                    tokens.append(buf); buf = ch
                else:
                    buf += ch
    if buf:
        tokens.append(buf)
    return tokens

def str_width(s: str, font_name: str, font_size: float) -> float:
    return pdfmetrics.stringWidth(s, font_name, font_size)

def wrap_cjk_aware(text: str, max_width: float, font_name: str, font_size: float):
    lines = []
    for raw in text.splitlines() or [""]:
        if raw.strip() == "" and raw != "":
            lines.append(""); continue
        tokens = tokenize_for_wrap(raw)
        cur = ""
        for tk in tokens:
            if tk == " ":
                if cur and not cur.endswith(" "):
                    trial = cur + " "
                    if str_width(trial, font_name, font_size) <= max_width:
                        cur = trial
                continue
            add = tk
            if cur == "":
                if str_width(add, font_name, font_size) <= max_width:
                    cur = add
                else:
                    piece = ""
                    for ch in add:
                        if str_width(piece + ch, font_name, font_size) <= max_width:
                            piece += ch
                        else:
                            if piece: lines.append(piece)
                            piece = ch
                    cur = piece
            else:
                trial = cur + add
                if str_width(trial, font_name, font_size) <= max_width:
                    cur = trial
                else:
                    lines.append(cur.rstrip())
                    if str_width(add, font_name, font_size) > max_width:
                        piece = ""
                        for ch in add:
                            if str_width(piece + ch, font_name, font_size) <= max_width:
                                piece += ch
                            else:
                                if piece: lines.append(piece)
                                piece = ch
                        cur = piece
                    else:
                        cur = add
        lines.append(cur.rstrip())
    return lines

# ---- PDF drawing helpers (no footer, no margins) ----
def draw_paragraph(c, text, x, y, right_x, font_name, font_size, indent_left=0):
    leading = font_size * LINE_SPACING
    max_width = right_x - (x + indent_left)
    lines = wrap_cjk_aware(text, max_width, font_name, font_size)
    c.setFont(font_name, font_size)
    for line in lines:
        if y - leading < MARGIN:  # bottom edge
            c.showPage()
            c.setFont(font_name, font_size)
            y = PAGE_SIZE[1] - MARGIN  # top edge
        c.drawString(x + indent_left, y - leading, line)
        y -= leading
    return y

def draw_image(c, pil_img, x, y, right_x, font_name):
    page_w, page_h = PAGE_SIZE
    max_w = right_x - x
    img_w, img_h = pil_img.size
    scale = min(max_w / img_w, (page_h * IMAGE_MAX_HEIGHT_RATIO) / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale

    if y - draw_h < MARGIN:
        c.showPage()
        y = page_h - MARGIN

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG"); buf.seek(0)
    c.drawImage(ImageReader(buf), x, y - draw_h, width=draw_w, height=draw_h,
                preserveAspectRatio=True, mask="auto")
    y -= draw_h
    return y

# ---- Font picker ----
def pick_font():
    messagebox.showinfo(
        "Select Font",
        "Select a CJK-compatible TTF/OTF font (e.g., NotoSansCJKjp-Regular.otf)."
    )
    font_path = filedialog.askopenfilename(
        title="Choose a font file",
        filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")]
    )
    if not font_path:
        raise RuntimeError("No font selected. CJK text requires a Unicode font.")
    font_name = "UserFont"
    pdfmetrics.registerFont(TTFont(font_name, font_path))
    return font_name, font_path

# ---- EPUB → PDF core (borderless) ----
def convert_epub_to_pdf(epub_path, pdf_path, font_name):
    book = epub.read_epub(epub_path)

    spine_ids = [sid for sid, _ in book.spine]
    id_to_item = {it.id: it for it in book.get_items()}
    href_map = {it.get_name(): it for it in book.get_items()}

    c = canvas.Canvas(pdf_path, pagesize=PAGE_SIZE)
    x_left = MARGIN
    x_right = PAGE_SIZE[0] - MARGIN
    y = PAGE_SIZE[1] - MARGIN  # start at very top

    # Title page (optional)
    try:
        meta = next(iter(book.get_metadata("DC", "title")), None)
        title = meta[0] if meta else None
    except Exception:
        title = None

    if title:
        c.setFont(font_name, 26)
        for line in wrap_cjk_aware(title, x_right - x_left, font_name, 26):
            if y - 30 < MARGIN:
                c.showPage(); c.setFont(font_name, 26)
                y = PAGE_SIZE[1] - MARGIN
            c.drawString(x_left, y - 30, line); y -= 38
        y -= 12  # small gap

    for sid in spine_ids:
        item = id_to_item.get(sid)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")

        # Chapter title
        chapter_title = None
        for tag in ["h1", "h2", "title"]:
            t = soup.find(tag)
            if t and t.get_text(strip=True):
                chapter_title = t.get_text(strip=True); break

        if chapter_title:
            c.setFont(font_name, H1_SIZE)
            for line in wrap_cjk_aware(chapter_title, x_right - x_left, font_name, H1_SIZE):
                if y - (H1_SIZE + 6) < MARGIN:
                    c.showPage(); c.setFont(font_name, H1_SIZE)
                    y = PAGE_SIZE[1] - MARGIN
                c.drawString(x_left, y - (H1_SIZE + 6), line)
                y -= (H1_SIZE + 10)
            y -= 4

        # Content flow
        blocks = soup.find_all(["h1", "h2", "h3", "p", "blockquote", "img", "pre"])
        for b in blocks:
            name = (b.name or "").lower()
            if name in ("p", "pre", "blockquote"):
                text = b.get_text("\n" if name == "pre" else " ", strip=True)
                indent = QUOTE_INDENT if name == "blockquote" else 0.0
                y = draw_paragraph(c, text, x_left, y, x_right, font_name, DEFAULT_FONT_SIZE, indent)
            elif name == "img":
                src = b.get("src")
                if not src:
                    continue
                target = href_map.get(src) or href_map.get(
                    os.path.normpath(os.path.join(os.path.dirname(item.get_name()), src)).replace("\\", "/")
                )
                if target and target.get_type() == ITEM_IMAGE:
                    try:
                        raw = target.get_content()
                        pil = PILImage.open(io.BytesIO(raw)).convert("RGB")
                        y = draw_image(c, pil, x_left, y, x_right, font_name)
                    except Exception:
                        pass
        # tiny gap between chapters
        y -= 4
        if y < MARGIN + 20:
            c.showPage()
            y = PAGE_SIZE[1] - MARGIN

    c.save()

# ---- UI Entry ----
def main():
    root = Tk()
    root.withdraw()

    epub_path = filedialog.askopenfilename(
        title="Select EPUB File",
        filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")]
    )
    if not epub_path:
        messagebox.showinfo("Canceled", "No EPUB selected."); return

    pdf_path = filedialog.asksaveasfilename(
        title="Save PDF As...",
        initialfile=os.path.splitext(os.path.basename(epub_path))[0] + ".pdf",
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")]
    )
    if not pdf_path:
        messagebox.showinfo("Canceled", "No output file selected."); return

    try:
        font_name, font_path = pick_font()
    except Exception as ex:
        messagebox.showerror("Font required", str(ex)); return

    try:
        convert_epub_to_pdf(epub_path, pdf_path, font_name)
        messagebox.showinfo("Done", f"✅ Conversion complete!\nSaved to:\n{pdf_path}\nFont: {font_path}")
    except Exception as ex:
        messagebox.showerror("Error", f"Failed to convert:\n{ex}")

if __name__ == "__main__":
    main()
