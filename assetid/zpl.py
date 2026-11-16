"""ZPL for RFID label printer-encoders.

One label is one ``^XA ... ^XZ`` block: ``^RFW,H`` writes the 24-hex GIAI-96
EPC into the EPC bank; the visible face carries the organisation, the
inventory number, an optional description, a Code128 with the alias (no
printer-generated text) and the alias as plain text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .errors import NotGiai96

__all__ = ["DOTS_PER_MM", "build_zpl", "build_zpl_batch", "sanitize_zpl_text"]

#: 203 dpi printers have 8 dots per millimetre.
DOTS_PER_MM = 8

_EPC_RE = re.compile(r"^[0-9A-Fa-f]{24}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_zpl_text(text: str | None) -> str:
    """Make ``text`` safe inside ``^FD...^FS``.

    ``^`` and ``~`` (ZPL command and control prefixes) become spaces, control
    characters are dropped and so is every non-ASCII character: losing accents
    is intentional, for compatibility with the printer's default code page.
    """
    if not text:
        return ""
    cleaned = text.replace("^", " ").replace("~", " ")
    cleaned = _CONTROL_RE.sub("", cleaned)
    cleaned = cleaned.encode("ascii", "ignore").decode("ascii")
    return cleaned.strip()


def _dots(value_mm: float) -> int:
    return int(round(value_mm * DOTS_PER_MM))


def _code128_module_dots(data: str, available_dots: int) -> int:
    """``^BY`` module width: 2 dots when the alias fits, else 1 (conservative estimate)."""
    modules = 11 * (len(data) + 2) + 13  # start, data, check, stop; no Code C compression
    return 2 if modules * 2 <= available_dots else 1


def build_zpl(
    label: Any,
    org_name: str | None = None,
    w_mm: float = 50,
    h_mm: float = 30,
    *,
    description: str | None = None,
) -> str:
    """Return the ZPL block for one label (RFID encode plus printed face).

    ``label`` needs ``epc``, ``alias`` and ``inventory_number`` attributes; the
    EPC must be exactly 24 hex characters (:class:`NotGiai96` otherwise).
    """
    epc = str(getattr(label, "epc", "") or "")
    if not _EPC_RE.match(epc):
        raise NotGiai96(f"EPC must be 24 hex characters, got {epc!r}")
    if w_mm <= 0 or h_mm <= 0:
        raise ValueError("label size must be positive")
    alias = sanitize_zpl_text(str(label.alias))
    number = sanitize_zpl_text(str(label.inventory_number))
    org = sanitize_zpl_text(org_name)
    desc = sanitize_zpl_text(description or getattr(label, "description", None))

    width, height = _dots(w_mm), _dots(h_mm)
    margin = _dots(2)
    usable = width - 2 * margin
    scale = h_mm / 30.0
    font_small = max(14, _dots(2.5 * scale))
    font_big = max(24, _dots(5.5 * scale))
    bar_height = max(24, _dots(10 * scale))

    lines = [
        "^XA",
        f"^PW{width}",
        f"^LL{height}",
        "^LH0,0",
        f"^RFW,H^FD{epc.upper()}^FS",
    ]
    cursor = margin
    if org:
        lines.append(f"^FO{margin},{cursor}^A0N,{font_small},{font_small}^FD{org}^FS")
        cursor += font_small + _dots(0.5)
    lines.append(f"^FO{margin},{cursor}^A0N,{font_big},{font_big}^FD{number}^FS")
    cursor += font_big + _dots(0.5)
    if desc:
        lines.append(f"^FO{margin},{cursor}^A0N,{font_small},{font_small}^FD{desc}^FS")
        cursor += font_small + _dots(0.5)
    module = _code128_module_dots(alias, usable)
    lines.append(f"^FO{margin},{cursor}^BY{module}^BCN,{bar_height},N,N,N^FD{alias}^FS")
    cursor += bar_height + _dots(0.5)
    lines.append(f"^FO{margin},{cursor}^A0N,{font_small},{font_small}^FD{alias}^FS")
    lines.append("^XZ")
    return "\n".join(lines)


def build_zpl_batch(
    labels: Iterable[Any],
    org_name: str | None = None,
    w_mm: float = 50,
    h_mm: float = 30,
) -> str:
    """Concatenate one ZPL block per label."""
    return "\n".join(build_zpl(label, org_name, w_mm, h_mm) for label in labels)
