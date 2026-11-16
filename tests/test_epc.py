"""Spec cases 7, 8 and 9: GIAI-96 encoding."""

from __future__ import annotations

import pytest

from assetid import NotGiai96, OutOfRange, build_asset_reference, decode_giai96, encode_giai96
from assetid.epc import GIAI96_HEADER, PARTITIONS, giai_from_giai96, partition_for_prefix
from assetid.synthetic import demo_company_prefix

REFERENCE = build_asset_reference(14, 42)  # "001400000042"


@pytest.mark.parametrize("length", [6, 7, 10, 12])
def test_round_trip_for_each_prefix_length(length: int) -> None:
    prefix = demo_company_prefix(length, seed=length)
    epc = encode_giai96(prefix, REFERENCE)
    assert len(epc) == 24 and epc == epc.upper() and int(epc, 16) < 1 << 96
    parts = decode_giai96(epc)
    assert parts.company_prefix == prefix
    assert parts.reference_12 == REFERENCE
    assert (parts.block, parts.serial) == (14, 42)
    assert parts.giai == prefix + REFERENCE
    assert giai_from_giai96(epc) == prefix + REFERENCE
    # The padded reference has the partition's maximum digits.
    assert len(parts.asset_reference) == PARTITIONS[parts.partition][3]


@pytest.mark.parametrize("length", range(6, 13))
def test_header_and_partition(length: int) -> None:
    prefix = demo_company_prefix(length, seed=0)
    epc = encode_giai96(prefix, REFERENCE)
    assert epc.startswith("34")
    parts = decode_giai96(epc)
    assert parts.header == GIAI96_HEADER == 0x34
    assert parts.partition == 12 - length == partition_for_prefix(prefix)
    assert parts.filter_value == 0


def test_partition_table_sums_to_82_bits() -> None:
    for prefix_bits, prefix_digits, reference_bits, reference_digits in PARTITIONS.values():
        assert prefix_bits + reference_bits == 82
        assert prefix_digits + reference_digits == 25
        assert 10**12 < 1 << reference_bits  # a 12-digit reference always fits


def test_filter_value_round_trips_and_is_bounded() -> None:
    epc = encode_giai96("952001", REFERENCE, filter_value=5)
    assert decode_giai96(epc).filter_value == 5
    with pytest.raises(OutOfRange):
        encode_giai96("952001", REFERENCE, filter_value=8)


def test_bit_layout_matches_the_standard() -> None:
    prefix, reference = "9520012", "001400000042"  # partition 5: 24 + 58 bits
    value = int(encode_giai96(prefix, reference), 16)
    assert value >> 88 == 0x34
    assert (value >> 85) & 7 == 0
    assert (value >> 82) & 7 == 5
    assert (value >> 58) & ((1 << 24) - 1) == int(prefix)
    assert value & ((1 << 58) - 1) == int(reference)


@pytest.mark.parametrize("prefix", ["95200", "9520012345678", "95200A"])
def test_bad_prefix_rejected(prefix: str) -> None:
    with pytest.raises(OutOfRange):
        encode_giai96(prefix, REFERENCE)


def test_reference_longer_than_partition_rejected() -> None:
    with pytest.raises(OutOfRange):
        encode_giai96("952001234567", "1" * 14)  # partition 0 allows 13 digits
    with pytest.raises(OutOfRange):
        encode_giai96("952001234567", "9" * 13)  # 13 digits but above 2**42
    with pytest.raises(OutOfRange):
        encode_giai96("952001", "")
    with pytest.raises(OutOfRange):
        encode_giai96("952001", "12A")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "34" * 11,  # 22 chars
        "3" * 24 + "4",  # 25 chars
        "ZZ" + "0" * 22,
        "30" + "0" * 22,  # SGTIN-96 header
        "34" + "1C" + "0" * 20,  # partition 7 (0b111)
    ],
)
def test_decode_rejects_non_giai96(bad: str) -> None:
    with pytest.raises(NotGiai96):
        decode_giai96(bad)


def test_decode_accepts_lower_case_and_whitespace() -> None:
    epc = encode_giai96("952001", REFERENCE)
    assert decode_giai96(" " + epc.lower() + "\n").giai == "952001" + REFERENCE
