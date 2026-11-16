"""Spec cases 1, 3, 4, 5, 6, 10 and the parse_any classifier."""

from __future__ import annotations

import pytest

from assetid import (
    ALIAS_PREFIX,
    AssetIdentity,
    CodeKind,
    InvalidCharacter,
    Namespace,
    OutOfRange,
    build_alias,
    build_asset_reference,
    build_giai,
    build_gs1_link,
    derive_identity,
    giai_from_gs1_link,
    normalize_inventory_number,
    parse_alias,
    parse_any,
    split_asset_reference,
    split_giai,
)
from assetid.identity import STRICT_BLOCK_MIN

CP = "9520012"
DOMAIN = "verify.example.org"


def make_namespace(block: int = 14, code: str = "NOR", **extra: object) -> Namespace:
    return Namespace(CP, block, code, DOMAIN, **extra)  # type: ignore[arg-type]


# -- case 1 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("MOB-0042", "MOB0042"), ("r-7", "R7"), ("  eqp / 0001 ", "EQP0001"), ("Ñ-12", "12")],
)
def test_normalize_inventory_number(raw: str, expected: str) -> None:
    assert normalize_inventory_number(raw) == expected


def test_normalize_rejects_empty_result() -> None:
    with pytest.raises(InvalidCharacter):
        normalize_inventory_number("---")


# -- case 3 ------------------------------------------------------------------


def test_asset_reference_round_trip() -> None:
    assert build_asset_reference(14, 42) == "001400000042"
    assert split_asset_reference("001400000042") == (14, 42)
    assert build_asset_reference(0, 0) == "0" * 12
    assert build_asset_reference(9999, 99_999_999) == "999999999999"


@pytest.mark.parametrize(("block", "serial"), [(99999, 1), (-1, 1), (1, 10**9), (1, -1)])
def test_asset_reference_out_of_range(block: int, serial: int) -> None:
    with pytest.raises(OutOfRange):
        build_asset_reference(block, serial)


@pytest.mark.parametrize("bad", ["12345678901", "1234567890123"])
def test_split_asset_reference_length(bad: str) -> None:
    with pytest.raises(OutOfRange):
        split_asset_reference(bad)


def test_split_asset_reference_characters() -> None:
    with pytest.raises(InvalidCharacter):
        split_asset_reference("00140000004A")


# -- case 4 ------------------------------------------------------------------


def test_alias_build_and_parse() -> None:
    alias = build_alias("ABC", "MOB-0042")
    assert alias == f"{ALIAS_PREFIX}-ABC-MOB0042-3"
    parts = parse_alias(alias)
    assert parts.tenant_code == "ABC"
    assert parts.inventory_number == "MOB0042"
    assert parts.check == "3"
    assert parts.check_ok
    assert parts.body == "ABC-MOB0042"


def test_alias_tampered_check_is_reported_not_raised() -> None:
    alias = build_alias("ABC", "MOB-0042")
    tampered = alias[:-1] + ("4" if alias[-1] != "4" else "5")
    assert parse_alias(tampered).check_ok is False
    # a changed body with the old check is also detected
    assert parse_alias(alias.replace("MOB0042", "MOB0043")).check_ok is False


@pytest.mark.parametrize("bad", ["ABC-MOB0042-3", "XYZ-ABC-MOB0042-3", "", "AID-", "AID-ABC"])
def test_alias_without_prefix_or_structure_raises(bad: str) -> None:
    with pytest.raises(InvalidCharacter):
        parse_alias(bad)


def test_alias_rejects_bad_tenant_code() -> None:
    with pytest.raises(InvalidCharacter):
        build_alias("A-B", "MOB-1")
    with pytest.raises(InvalidCharacter):
        build_alias("abc", "MOB-1")


# -- case 5 ------------------------------------------------------------------


def test_giai_validation() -> None:
    assert build_giai(CP, "001400000042") == CP + "001400000042"
    with pytest.raises(InvalidCharacter):
        build_giai("95A0012", "001400000042")
    with pytest.raises(OutOfRange):
        build_giai("9" * 19, "001400000042")  # 31 characters
    assert len(build_giai("9" * 18, "001400000042")) == 30


def test_split_giai_uses_configured_prefix_length() -> None:
    giai = build_giai(CP, "001400000042")
    assert split_giai(giai, len(CP)) == (CP, "001400000042")
    with pytest.raises(OutOfRange):
        split_giai(giai, len(CP) + 1)


# -- case 6 ------------------------------------------------------------------


def test_gs1_link_and_inverse() -> None:
    giai = build_giai(CP, "001400000042")
    link = build_gs1_link("d", giai)
    assert link == f"https://d/8004/{giai}"
    assert giai_from_gs1_link(link) == giai
    assert giai_from_gs1_link(link + "?linkType=gs1:pip") == giai
    assert giai_from_gs1_link(link + "/21/extra") == giai
    assert build_gs1_link("d/", giai, scheme="http") == f"http://d/8004/{giai}"


def test_gs1_link_rejects_bad_inputs() -> None:
    with pytest.raises(InvalidCharacter):
        build_gs1_link("https://d", "952001000000000001")
    with pytest.raises(InvalidCharacter):
        build_gs1_link("d", "12A")
    with pytest.raises(InvalidCharacter):
        giai_from_gs1_link("https://d/01/09520012345678")


# -- namespace and derived identity -----------------------------------------


def test_namespace_validates_ranges() -> None:
    ns = make_namespace()
    assert ns.scheme == "https"
    with pytest.raises(OutOfRange):
        make_namespace(block=10_000)
    with pytest.raises(InvalidCharacter):
        make_namespace(code="no-r")
    with pytest.raises(InvalidCharacter):
        Namespace("95A0012", 1, "NOR", DOMAIN)
    with pytest.raises(OutOfRange):
        Namespace("95200", 1, "NOR", DOMAIN)
    with pytest.raises(InvalidCharacter):
        Namespace(CP, 1, "NOR", "https://verify.example.org/")
    with pytest.raises(InvalidCharacter):
        Namespace(CP, 1, "NOR", DOMAIN, scheme="ftp")


def test_namespace_strict_mode_requires_block_without_leading_zero() -> None:
    assert make_namespace(block=STRICT_BLOCK_MIN, strict=True).strict
    with pytest.raises(OutOfRange):
        make_namespace(block=14, strict=True)


def test_namespace_is_immutable() -> None:
    ns = make_namespace()
    with pytest.raises(AttributeError):
        ns.block = 15  # type: ignore[misc]


def test_derive_identity_has_four_consistent_forms() -> None:
    identity = derive_identity(make_namespace(), 42, "MOB-0042")
    assert isinstance(identity, AssetIdentity)
    assert identity.asset_reference == "001400000042"
    assert identity.giai == CP + "001400000042"
    assert identity.alias == "AID-NOR-MOB0042-" + identity.alias[-1]
    assert parse_alias(identity.alias).check_ok
    assert identity.gs1_link == f"https://{DOMAIN}/8004/{identity.giai}"
    assert len(identity.epc) == 24
    assert parse_any(identity.epc).payload == identity.epc
    assert giai_from_gs1_link(identity.gs1_link) == identity.giai


# -- case 10 -----------------------------------------------------------------


def test_same_serial_in_two_blocks_gives_distinct_forms() -> None:
    a = derive_identity(make_namespace(block=14, code="NOR"), 7, "MOB-0001")
    b = derive_identity(make_namespace(block=15, code="SUR"), 7, "MOB-0001")
    assert a.giai != b.giai
    assert a.epc != b.epc
    assert a.alias != b.alias
    assert a.gs1_link != b.gs1_link


# -- parse_any ---------------------------------------------------------------


def test_parse_any_classifies_each_form() -> None:
    identity = derive_identity(make_namespace(), 42, "MOB-0042")
    assert parse_any(identity.alias).kind is CodeKind.ALIAS
    assert parse_any(identity.alias.lower()).payload == identity.alias
    assert parse_any(" " + identity.giai + " ").payload == identity.giai
    assert parse_any(identity.giai).kind is CodeKind.GIAI
    assert parse_any(identity.epc.lower()).payload == identity.epc
    assert parse_any(identity.epc).kind is CodeKind.EPC
    link = parse_any(identity.gs1_link)
    assert link.kind is CodeKind.GS1_LINK and link.payload == identity.giai


@pytest.mark.parametrize("text", ["", "   ", "hello", "https://example.org/01/123", "12345"])
def test_parse_any_unknown(text: str) -> None:
    assert parse_any(text).kind is CodeKind.UNKNOWN
