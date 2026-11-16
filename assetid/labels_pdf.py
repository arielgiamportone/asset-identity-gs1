"""Vector PDF rendering of labels: A4 adhesive sheets and single thermal labels.

Each label cell shows the organisation name, the inventory number, optional
description and category, a Code128 with the alias (bottom-left), a QR with
the GS1 Digital Link (right, wide cells only) and an optional logo (top-right).
When a label has no identity yet (incomplete namespace) the cell falls back to
*basic mode*: both codes carry the inventory number.
"""

from __future__ import annotations

import base64
import binascii
import io
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

__all__ = [
    "DEFAULT_PRESET",
    "SHEET_PRESETS",
    "LabelFace",
    "SheetPreset",
    "decode_logo",
    "render_sheet",
    "render_single",
]


@dataclass(frozen=True, slots=True)
class SheetPreset:
    """Geometry of an adhesive A4 sheet, in millimetres, first row at the top."""

    name: str
    columns: int
    rows: int
    cell_width: float
    cell_height: float
    margin_left: float
    margin_top: float
    pitch_x: float
    pitch_y: float

    @property
    def per_page(self) -> int:
        return self.columns * self.rows

    def cell_origin(self, index: int) -> tuple[float, float]:
        """Top-left corner (mm, from the top-left of the page) of cell ``index``."""
        row, column = divmod(index, self.columns)
        return self.margin_left + column * self.pitch_x, self.margin_top + row * self.pitch_y


#: Approximations of common manufacturer templates; calibrate for your stock.
SHEET_PRESETS: dict[str, SheetPreset] = {
    "a4-21": SheetPreset("a4-21", 3, 7, 63.5, 38.1, 7.0, 15.1, 66.0, 38.1),
    "a4-65": SheetPreset("a4-65", 5, 13, 38.1, 21.2, 4.75, 10.7, 40.6, 21.2),
    "a4-14": SheetPreset("a4-14", 2, 7, 99.1, 38.1, 4.65, 15.1, 101.6, 38.1),
}
DEFAULT_PRESET = "a4-21"

_PAD_MM = 1.5
_HEADER_PT = 5.5
_HEADER_MAX_CHARS = 44
_HEADER_MAX_CHARS_WITH_LOGO = 32
_NUMBER_PT = 12.0
_NUMBER_PT_SHORT = 9.0
_SHORT_CELL_MM = 30.0
_BARCODE_MM = 7.0
_BARCODE_MM_SHORT = 5.0
_MODULE_MAX_MM = 0.40
_MODULE_MIN_MM = 0.10
_QR_MIN_WIDTH_MM = 60.0
_QR_MAX_SIDE_MM = 15.0
_LOGO_MIN_CELL_MM = (50.0, 20.0)
_LOGO_MAX_MM = (14.0, 7.0)
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


@dataclass(frozen=True, slots=True)
class LabelFace:
    """What gets printed on one label. Identity fields are optional (basic mode)."""

    inventory_number: str
    alias: str | None = None
    gs1_link: str | None = None
    epc: str | None = None
    description: str | None = None
    category: str | None = None

    @classmethod
    def from_label(
        cls, label: Any, *, description: str | None = None, category: str | None = None
    ) -> LabelFace:
        """Build a face from any object with the identity attributes (e.g. a registry label)."""
        return cls(
            inventory_number=str(label.inventory_number),
            alias=getattr(label, "alias", None),
            gs1_link=getattr(label, "gs1_link", None),
            epc=getattr(label, "epc", None),
            description=description or getattr(label, "description", None),
            category=category or getattr(label, "category", None),
        )


def _as_face(item: Any) -> LabelFace:
    return item if isinstance(item, LabelFace) else LabelFace.from_label(item)


def decode_logo(logo: str | bytes | None) -> ImageReader | None:
    """Turn a base64 string, a data-URI or raw image bytes into an image reader.

    Anything that is not a decodable image yields ``None``; the caller then
    simply renders without a logo.
    """
    if not logo:
        return None
    try:
        if isinstance(logo, str):
            payload = logo.split(",", 1)[1] if logo.startswith("data:") else logo
            data = base64.b64decode(payload.strip(), validate=True)
        else:
            data = bytes(logo)
        reader = ImageReader(io.BytesIO(data))
        reader.getSize()
        return reader
    except (binascii.Error, ValueError, OSError, IndexError, TypeError):
        return None


def _latin(text: str) -> str:
    """Keep the text printable with the built-in Type 1 fonts (WinAnsi)."""
    return text.encode("cp1252", "replace").decode("cp1252")


def _fit(text: str, font: str, size: float, max_width: float) -> str:
    text = _latin(text)
    if stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "…"
    while text and stringWidth(text + ellipsis, font, size) > max_width:
        text = text[:-1]
    return text + ellipsis if text else ""


def _draw_face(
    c: canvas.Canvas,
    face: LabelFace,
    org_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    logo: ImageReader | None,
) -> None:
    """Draw one label whose bottom-left corner is ``(x, y)`` (points)."""
    pad = _PAD_MM * mm
    w_mm, h_mm = width / mm, height / mm
    short = h_mm < _SHORT_CELL_MM
    top = y + height
    inner_w = width - 2 * pad

    # Logo top-right.
    logo_w = 0.0
    if logo is not None and w_mm >= _LOGO_MIN_CELL_MM[0] and h_mm >= _LOGO_MIN_CELL_MM[1]:
        max_w, max_h = _LOGO_MAX_MM[0] * mm, _LOGO_MAX_MM[1] * mm
        iw, ih = logo.getSize()
        scale = min(max_w / iw, max_h / ih)
        lw, lh = iw * scale, ih * scale
        c.drawImage(
            logo,
            x + width - pad - lw,
            top - pad - lh,
            lw,
            lh,
            mask="auto",
            preserveAspectRatio=True,
        )
        logo_w = lw + pad

    # Header.
    limit = _HEADER_MAX_CHARS_WITH_LOGO if logo_w else _HEADER_MAX_CHARS
    header = _fit(org_name[:limit], _FONT_BOLD, _HEADER_PT, inner_w - logo_w)
    cursor = top - pad - _HEADER_PT
    c.setFont(_FONT_BOLD, _HEADER_PT)
    c.drawString(x + pad, cursor, header)

    # Inventory number.
    number_pt = _NUMBER_PT_SHORT if short else _NUMBER_PT
    cursor -= number_pt + 1.5
    c.setFont(_FONT_BOLD, number_pt)
    c.drawString(x + pad, cursor, _fit(face.inventory_number, _FONT_BOLD, number_pt, inner_w))

    # Description and category, tall cells only.
    if not short:
        for text, size in ((face.description, 6.0), (face.category, 5.0)):
            if text:
                cursor -= size + 1.0
                c.setFont(_FONT, size)
                c.drawString(x + pad, cursor, _fit(text, _FONT, size, inner_w))

    # QR on the right for wide cells.
    qr_w = 0.0
    if w_mm >= _QR_MIN_WIDTH_MM:
        side = min(height - 2 * pad, _QR_MAX_SIDE_MM * mm)
        payload = face.gs1_link or face.alias or face.inventory_number
        widget = QrCodeWidget(_latin(payload), barLevel="M")
        x0, y0, x1, y1 = widget.getBounds()
        drawing = Drawing(side, side, transform=[side / (x1 - x0), 0, 0, side / (y1 - y0), 0, 0])
        drawing.add(widget)
        renderPDF.draw(drawing, c, x + width - pad - side, y + pad)
        qr_w = side + pad

    # Code128 bottom-left, module shrunk until it fits beside the QR.
    bar_h = (_BARCODE_MM_SHORT if short else _BARCODE_MM) * mm
    bar_value = _latin(face.alias or face.inventory_number)
    available = inner_w - qr_w
    module = _MODULE_MAX_MM * mm
    barcode = code128.Code128(
        bar_value, barWidth=module, barHeight=bar_h, humanReadable=False, quiet=0
    )
    if barcode.width > available:
        module = max(_MODULE_MIN_MM * mm, module * available / barcode.width)
        barcode = code128.Code128(
            bar_value, barWidth=module, barHeight=bar_h, humanReadable=False, quiet=0
        )
    barcode.drawOn(c, x + pad, y + pad)

    # Alias in small print above the barcode when there is room.
    if face.alias and not short:
        c.setFont(_FONT, 4.5)
        c.drawString(x + pad, y + pad + bar_h + 1.0, _fit(face.alias, _FONT, 4.5, available))


def render_sheet(
    labels: Iterable[Any],
    org_name: str,
    preset: str = DEFAULT_PRESET,
    start_offset: int = 0,
    logo: str | bytes | None = None,
    *,
    outlines: bool = False,
    compress: bool = True,
) -> bytes:
    """Render ``labels`` on A4 adhesive sheets and return the PDF bytes.

    ``start_offset`` skips cells already used on a partially printed sheet (it
    wraps at the sheet size). An empty batch still yields a valid one-page PDF
    carrying a notice, and a :class:`UserWarning` is emitted.
    """
    if preset not in SHEET_PRESETS:
        raise ValueError(f"unknown preset {preset!r}; choose one of {sorted(SHEET_PRESETS)}")
    if start_offset < 0:
        raise ValueError("start_offset must be non-negative")
    geometry = SHEET_PRESETS[preset]
    faces = [_as_face(item) for item in labels]
    logo_reader = decode_logo(logo)
    page_h = A4[1]

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, pageCompression=int(compress))
    c.setTitle(f"Labels {preset}")
    if not faces:
        warnings.warn("render_sheet called with an empty batch", UserWarning, stacklevel=2)
        c.setFont(_FONT, 10)
        c.drawString(20 * mm, page_h - 20 * mm, _latin("No labels to print (empty batch)."))
        c.showPage()
        c.save()
        return buffer.getvalue()

    width, height = geometry.cell_width * mm, geometry.cell_height * mm
    cell = start_offset % geometry.per_page
    for face in faces:
        if cell == geometry.per_page:
            c.showPage()
            cell = 0
        left_mm, top_mm = geometry.cell_origin(cell)
        x = left_mm * mm
        y = page_h - top_mm * mm - height  # convert from top-left to PDF bottom-left origin
        if outlines:
            c.setLineWidth(0.2)
            c.rect(x, y, width, height)
        _draw_face(c, face, org_name, x, y, width, height, logo_reader)
        cell += 1
    c.showPage()
    c.save()
    return buffer.getvalue()


def render_single(
    label: Any,
    org_name: str,
    w_mm: float = 63.5,
    h_mm: float = 38.1,
    logo: str | bytes | None = None,
    *,
    compress: bool = True,
) -> bytes:
    """Render one label on a page of exactly its size (thermal printers)."""
    if w_mm <= 0 or h_mm <= 0:
        raise ValueError("label size must be positive")
    face = _as_face(label)
    width, height = w_mm * mm, h_mm * mm
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height), pageCompression=int(compress))
    c.setTitle(f"Label {face.inventory_number}")
    _draw_face(c, face, org_name, 0.0, 0.0, width, height, decode_logo(logo))
    c.showPage()
    c.save()
    return buffer.getvalue()
