"""A tiny PDF writer: text, lines, boxes and JPEG pictures, nothing else.

Written so the project needs no PDF library. It makes one or more A4 pages
with the standard Helvetica fonts, which every PDF reader has. Text is
Latin-1 only (other characters become "?"), so use "Rs." rather than a
rupee sign.
"""

import re

A4 = (595, 842)           # points
ENDSTREAM = b"\nendstream"
FONTS = {"regular": "Helvetica", "bold": "Helvetica-Bold",
         "mono": "Courier"}


class PdfError(ValueError):
    """The picture or text cannot be put in a PDF."""


def jpeg_info(data):
    """``(width, height, components)`` of a baseline/progressive JPEG."""

    if data[:2] != b"\xff\xd8":
        raise PdfError("not a JPEG picture")

    pos = 2

    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue

        marker = data[pos + 1]

        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            pos += 1 if marker == 0xFF else 2
            continue

        length = int.from_bytes(data[pos + 2:pos + 4], "big")

        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[pos + 5:pos + 7], "big")
            width = int.from_bytes(data[pos + 7:pos + 9], "big")

            return width, height, data[pos + 9]

        pos += 2 + length

    raise PdfError("could not read the JPEG size")


def _escape(text):
    text = str(text).encode("latin-1", "replace").decode("latin-1")

    return (text.replace("\\", "\\\\").replace("(", "\\(")
            .replace(")", "\\)"))


class Page:
    def __init__(self):
        self.ops = []
        self.images = []                 # (name, data, width, height, comps)

    def text(self, x, y, text, size=10, font="regular", gray=0.0):
        self.ops.append(
            f"BT {gray:.2f} g /{font} {size} Tf {x:.1f} {y:.1f} Td "
            f"({_escape(text)}) Tj ET")

    def line(self, x1, y1, x2, y2, width=0.8, gray=0.0):
        self.ops.append(f"{gray:.2f} G {width} w {x1:.1f} {y1:.1f} m "
                        f"{x2:.1f} {y2:.1f} l S")

    def rect(self, x, y, w, h, width=0.8, gray=0.0, fill=None):
        if fill is not None:
            self.ops.append(f"{fill:.2f} g {x:.1f} {y:.1f} {w:.1f} "
                            f"{h:.1f} re f")

        self.ops.append(f"{gray:.2f} G {width} w {x:.1f} {y:.1f} "
                        f"{w:.1f} {h:.1f} re S")

    def jpeg(self, data, x, y, max_w, max_h):
        """Place a JPEG inside the box, keeping its shape. Returns its size."""

        width, height, comps = jpeg_info(data)

        if comps not in (1, 3):
            raise PdfError("only grey or RGB JPEG pictures are supported")

        scale = min(max_w / width, max_h / height)
        w, h = width * scale, height * scale
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, data, width, height, comps))
        self.ops.append(f"q {w:.1f} 0 0 {h:.1f} {x:.1f} {y:.1f} cm "
                        f"/{name} Do Q")

        return w, h


class Document:
    def __init__(self, title="", author=""):
        self.title = title
        self.author = author
        self.pages = []

    def add_page(self):
        page = Page()
        self.pages.append(page)

        return page

    def render(self):
        objects = []                       # bytes bodies, 1-based ids

        def add(body):
            objects.append(body if isinstance(body, bytes) else body.encode("latin-1"))

            return len(objects)

        catalog = add(b"")                 # filled in once pages exist
        pages_id = add(b"")
        font_ids = {key: add(f"<< /Type /Font /Subtype /Type1 /BaseFont "
                             f"/{name} /Encoding /WinAnsiEncoding >>")
                    for key, name in FONTS.items()}
        fonts = " ".join(f"/{k} {i} 0 R" for k, i in font_ids.items())
        page_ids = []

        for page in self.pages:
            xobjects = []

            for name, data, width, height, comps in page.images:
                space = "/DeviceRGB" if comps == 3 else "/DeviceGray"
                head = (f"<< /Type /XObject /Subtype /Image /Width {width} "
                        f"/Height {height} /ColorSpace {space} "
                        f"/BitsPerComponent 8 /Filter /DCTDecode "
                        f"/Length {len(data)} >>\nstream\n").encode("latin-1")
                image_id = add(head + data + ENDSTREAM)
                xobjects.append(f"/{name} {image_id} 0 R")

            content = "\n".join(page.ops).encode("latin-1")
            content_id = add(
                f"<< /Length {len(content)} >>\nstream\n".encode("latin-1")
                + content + b"\nendstream")
            resources = f"/Font << {fonts} >>"

            if xobjects:
                resources += f" /XObject << {' '.join(xobjects)} >>"

            page_ids.append(add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox "
                f"[0 0 {A4[0]} {A4[1]}] /Resources << {resources} >> "
                f"/Contents {content_id} 0 R >>"))

        kids = " ".join(f"{i} 0 R" for i in page_ids)
        objects[pages_id - 1] = (
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"
        ).encode("latin-1")
        objects[catalog - 1] = (
            f"<< /Type /Catalog /Pages {pages_id} 0 R >>").encode("latin-1")
        info = add(f"<< /Title ({_escape(self.title)}) "
                   f"/Author ({_escape(self.author)}) "
                   f"/Producer (Traffic Agent) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []

        for number, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

        start = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode()
        out += b"0000000000 65535 f \n"

        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()

        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R "
                f"/Info {info} 0 R >>\nstartxref\n{start}\n%%EOF\n").encode()

        return bytes(out)
