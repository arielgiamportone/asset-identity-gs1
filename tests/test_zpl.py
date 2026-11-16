"""Spec case 22: ZPL for RFID printer-encoders."""

from __future__ import annotations

import pytest

from assetid import (
    LabelFace,
    NotGiai96,
    build_zpl,
    build_zpl_batch,
    derive_identity,
    sanitize_zpl_text,
)
from assetid.identity import Namespace

NS = Namespace("952001", 1000, "NOR", "verify.example.org")


def face(serial: int, number: str, **extra: str) -> LabelFace:
    identity = derive_identity(NS, serial, number)
    return LabelFace(
        number, alias=identity.alias, gs1_link=identity.gs1_link, epc=identity.epc, **extra
    )


def test_block_contains_rfid_write_barcode_alias_and_number() -> None:
    label = face(1, "MOB-0042", description="Silla giratoria")
    zpl = build_zpl(label, org_name="Ayuntamiento de Monteclaro")
    assert zpl.startswith("^XA\n^PW400\n^LL240\n^LH0,0\n")
    assert zpl.endswith("^XZ")
    assert f"^RFW,H^FD{label.epc}^FS" in zpl
    assert f"^BCN,80,N,N,N^FD{label.alias}^FS" in zpl
    assert "^BY" in zpl
    assert "^FDMOB-0042^FS" in zpl
    assert "^FDAyuntamiento de Monteclaro^FS" in zpl
    assert "^FDSilla giratoria^FS" in zpl
    assert zpl.count("^XA") == zpl.count("^XZ") == 1


def test_epc_must_be_24_hex() -> None:
    for bad in ("", "1234", "G" * 24, "34" * 13):
        with pytest.raises(NotGiai96):
            build_zpl(LabelFace("MOB-1", alias="AID-NOR-MOB1-0", epc=bad))
    with pytest.raises(NotGiai96):
        build_zpl(LabelFace("MOB-1", alias="AID-NOR-MOB1-0"))  # no EPC at all


def test_text_is_sanitised_against_injection_and_non_ascii() -> None:
    label = face(2, "MOB-0043", description="Mesa^XZ~JA de reuniones ñ")
    zpl = build_zpl(label, org_name="Ayuntamiento de Peñas Blancas ^FS")
    assert zpl.count("^XZ") == 1 and "~JA" not in zpl
    assert "^FDMesa XZ JA de reuniones^FS" in zpl
    assert "^FDAyuntamiento de Peas Blancas  FS^FS" in zpl
    assert zpl.isascii()


def test_sanitize_helper() -> None:
    assert sanitize_zpl_text("a^b~c") == "a b c"
    assert sanitize_zpl_text("cañón\x00\x1f") == "can"
    assert sanitize_zpl_text(None) == ""
    assert sanitize_zpl_text("  spaced  ") == "spaced"


def test_batch_of_two_has_two_blocks() -> None:
    batch = build_zpl_batch([face(1, "MOB-0001"), face(2, "MOB-0002")], org_name="Org")
    assert batch.count("^XA") == 2 and batch.count("^XZ") == 2
    assert batch.count("^RFW,H^FD") == 2
    assert build_zpl_batch([]) == ""


def test_custom_size_scales_geometry_and_module() -> None:
    label = face(3, "MOB-0003")
    wide = build_zpl(label, w_mm=100, h_mm=50)
    assert "^PW800\n^LL400" in wide
    assert "^BY2^BCN" in wide  # the alias fits at two dots per module
    narrow = build_zpl(label, w_mm=50, h_mm=30)
    assert "^BY1^BCN" in narrow  # falls back to one dot per module
    with pytest.raises(ValueError):
        build_zpl(label, w_mm=0)
