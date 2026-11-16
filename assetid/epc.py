"""GIAI-96 EPC encoding and decoding (EPC Tag Data Standard).

Layout of the 96 bits: header (8) ‖ filter (3) ‖ partition (3) ‖ company
prefix (40..20) ‖ individual asset reference (42..62). The partition value
tells how the 82 bits left after the fixed fields are split between the
company prefix and the asset reference.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import NotGiai96, OutOfRange

__all__ = [
    "GIAI96_HEADER",
    "Giai96Parts",
    "PARTITIONS",
    "decode_giai96",
    "encode_giai96",
    "giai_from_giai96",
    "partition_for_prefix",
]

#: EPC header byte for the GIAI-96 scheme.
GIAI96_HEADER = 0x34

#: Partition table: value -> (prefix bits, prefix digits, reference bits, max reference digits).
PARTITIONS: dict[int, tuple[int, int, int, int]] = {
    0: (40, 12, 42, 13),
    1: (37, 11, 45, 14),
    2: (34, 10, 48, 15),
    3: (30, 9, 52, 16),
    4: (27, 8, 55, 17),
    5: (24, 7, 58, 18),
    6: (20, 6, 62, 19),
}

_HEX_DIGITS = 24
_FILTER_MAX = 7


@dataclass(frozen=True, slots=True)
class Giai96Parts:
    """Fields decoded from a GIAI-96 EPC.

    ``company_prefix`` is zero-padded to the digits of its partition and
    ``asset_reference`` to the partition maximum, so that round-trips through
    this library preserve leading zeros. ``block`` and ``serial`` read the
    library's 12-digit reference layout (4 + 8) from the tail of the reference.
    """

    header: int
    filter_value: int
    partition: int
    company_prefix: str
    asset_reference: str

    @property
    def reference_12(self) -> str:
        """The last 12 digits of the asset reference (block ‖ serial)."""
        return self.asset_reference[-12:].rjust(12, "0")

    @property
    def block(self) -> int:
        return int(self.reference_12[:4])

    @property
    def serial(self) -> int:
        return int(self.reference_12[4:])

    @property
    def giai(self) -> str:
        """GIAI as this library builds it: company prefix ‖ 12-digit reference."""
        return self.company_prefix + self.reference_12


def partition_for_prefix(company_prefix: str) -> int:
    """Return the GIAI-96 partition value for a 6..12 digit company prefix."""
    if not company_prefix.isdigit() or not company_prefix.isascii():
        raise OutOfRange(f"company prefix must be numeric, got {company_prefix!r}")
    if not 6 <= len(company_prefix) <= 12:
        raise OutOfRange(f"company prefix must have 6 to 12 digits, got {len(company_prefix)}")
    return 12 - len(company_prefix)


def encode_giai96(company_prefix: str, asset_reference: str, filter_value: int = 0) -> str:
    """Encode a GIAI-96 EPC and return it as 24 upper-case hex characters.

    ``asset_reference`` must be numeric, no longer than the partition allows,
    and its value must fit in the reference bits. Leading zeros are accepted
    (the library pads references to 12 digits) but a strict third-party
    decoder will drop them; see :func:`decode_giai96`.
    """
    partition = partition_for_prefix(company_prefix)
    prefix_bits, _, reference_bits, max_digits = PARTITIONS[partition]
    if not 0 <= filter_value <= _FILTER_MAX:
        raise OutOfRange(f"filter value must be 0..{_FILTER_MAX}, got {filter_value}")
    if not asset_reference.isdigit() or not asset_reference.isascii():
        raise OutOfRange(f"asset reference must be numeric, got {asset_reference!r}")
    if not 1 <= len(asset_reference) <= max_digits:
        raise OutOfRange(
            f"asset reference has {len(asset_reference)} digits; partition {partition} "
            f"allows at most {max_digits}"
        )
    reference = int(asset_reference)
    if reference >= 1 << reference_bits:
        raise OutOfRange(f"asset reference {asset_reference} does not fit in {reference_bits} bits")
    value = GIAI96_HEADER << 88
    value |= filter_value << 85
    value |= partition << 82
    value |= int(company_prefix) << reference_bits
    value |= reference
    return f"{value:0{_HEX_DIGITS}X}"


def decode_giai96(epc_hex: str) -> Giai96Parts:
    """Decode 24 hex characters into :class:`Giai96Parts`.

    Raises :class:`NotGiai96` when the string is not 24 hex characters, the
    header is not ``0x34`` or the partition is above 6.
    """
    text = epc_hex.strip()
    if len(text) != _HEX_DIGITS or not all(c in "0123456789abcdefABCDEF" for c in text):
        raise NotGiai96(f"expected {_HEX_DIGITS} hex characters, got {epc_hex!r}")
    value = int(text, 16)
    header = value >> 88
    if header != GIAI96_HEADER:
        raise NotGiai96(f"header 0x{header:02X} is not GIAI-96 (0x{GIAI96_HEADER:02X})")
    filter_value = (value >> 85) & 0b111
    partition = (value >> 82) & 0b111
    if partition not in PARTITIONS:
        raise NotGiai96(f"partition {partition} is reserved")
    prefix_bits, prefix_digits, reference_bits, max_digits = PARTITIONS[partition]
    prefix = (value >> reference_bits) & ((1 << prefix_bits) - 1)
    reference = value & ((1 << reference_bits) - 1)
    return Giai96Parts(
        header=header,
        filter_value=filter_value,
        partition=partition,
        company_prefix=f"{prefix:0{prefix_digits}d}",
        asset_reference=f"{reference:0{max_digits}d}",
    )


def giai_from_giai96(epc_hex: str) -> str:
    """Shortcut: decode an EPC and return the library-form GIAI."""
    return decode_giai96(epc_hex).giai
