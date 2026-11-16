"""Spec case 21: PDF rendering never produces an invalid document."""

from __future__ import annotations

import re
import warnings

import pytest

from assetid import (
    SHEET_PRESETS,
    LabelFace,
    LabelRegistry,
    Namespace,
    NamespaceRegistry,
    Store,
    render_sheet,
    render_single,
)
from assetid.labels_pdf import decode_logo
from assetid.synthetic import (
    demo_logo_base64,
    demo_logo_data_uri,
    demo_logo_png,
    generate_assets,
    generate_tenants,
)

ORG = "Ayuntamiento de Peñas Blancas – Área de Patrimonio"


def page_count(pdf: bytes) -> int:
    assert re.search(rb"/Type\s*/Pages", pdf), "no /Pages object"
    match = re.search(rb"/Count\s+(\d+)", pdf)
    assert match, "no page count"
    return int(match.group(1))


def assert_valid_pdf(pdf: bytes) -> None:
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert page_count(pdf) >= 1


@pytest.fixture
def issued() -> list:
    tenant = generate_tenants(1, seed=4)[0]
    store = Store()
    NamespaceRegistry(store).assign(
        tenant.tenant_id,
        Namespace(tenant.company_prefix, tenant.block, tenant.tenant_code, tenant.resolver_domain),
    )
    registry = LabelRegistry(store)
    assets = generate_assets(45, seed=4)
    return [
        LabelFace.from_label(
            registry.issue(tenant.tenant_id, a.asset_id, a.inventory_number),
            description=a.description,
            category=a.category,
        )
        for a in assets
    ]


@pytest.mark.parametrize("preset", sorted(SHEET_PRESETS))
def test_sheet_for_every_preset(issued: list, preset: str) -> None:
    pdf = render_sheet(issued, ORG, preset=preset)
    assert_valid_pdf(pdf)
    per_page = SHEET_PRESETS[preset].per_page
    assert page_count(pdf) == -(-len(issued) // per_page)


def test_sheet_with_offset_spills_to_next_page(issued: list) -> None:
    one = render_sheet(issued[:1], ORG, start_offset=20)
    assert page_count(one) == 1
    two = render_sheet(issued[:2], ORG, start_offset=20)
    assert page_count(two) == 2
    wrapped = render_sheet(issued[:1], ORG, start_offset=21)  # wraps to a fresh sheet
    assert page_count(wrapped) == 1
    with pytest.raises(ValueError):
        render_sheet(issued, ORG, start_offset=-1)
    with pytest.raises(ValueError):
        render_sheet(issued, ORG, preset="letter-30")


def test_empty_batch_is_a_valid_pdf_with_a_warning() -> None:
    with pytest.warns(UserWarning):
        pdf = render_sheet([], ORG, compress=False)
    assert_valid_pdf(pdf)
    assert b"empty batch" in pdf


def test_accents_and_symbols_render(issued: list) -> None:
    face = LabelFace("MOB-0042", alias=issued[0].alias, description="Óleo «Amanecer» — ñ/ç/€")
    pdf = render_single(face, "Área Económica Ñandú", compress=False)
    assert_valid_pdf(pdf)
    assert b"MOB-0042" in pdf
    sheet = render_sheet([face], "Área Económica Ñandú", compress=False)
    assert_valid_pdf(sheet)


def test_single_label_default_and_custom_sizes(issued: list) -> None:
    pdf = render_single(issued[0], ORG, compress=False)
    assert_valid_pdf(pdf)
    assert re.search(rb"/MediaBox \[ ?0 0 180(\.\d+)? 108", pdf)  # 63.5 x 38.1 mm in points
    small = render_single(issued[0], ORG, w_mm=38.1, h_mm=21.2)
    assert_valid_pdf(small)
    with pytest.raises(ValueError):
        render_single(issued[0], ORG, w_mm=0)


@pytest.mark.parametrize(
    "logo",
    [
        demo_logo_base64(),
        demo_logo_data_uri(),
        demo_logo_png(),
        "not base64 !!",
        "data:image/png;base64,QUJD",
        b"\x00\x01",
        None,
        "",
    ],
)
def test_logo_valid_invalid_data_uri_or_absent(issued: list, logo: object) -> None:
    assert_valid_pdf(render_sheet(issued[:3], ORG, logo=logo))  # type: ignore[arg-type]
    assert_valid_pdf(render_single(issued[0], ORG, logo=logo))  # type: ignore[arg-type]


def test_decode_logo() -> None:
    assert decode_logo(demo_logo_base64()) is not None
    assert decode_logo(demo_logo_data_uri()) is not None
    assert decode_logo(demo_logo_png()) is not None
    assert decode_logo("///") is None
    assert decode_logo("data:image/png;base64,") is None
    assert decode_logo(None) is None


def test_basic_mode_without_identity() -> None:
    faces = [LabelFace("EQP-0001"), LabelFace("EQP-0002", description="Proyector")]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        pdf = render_sheet(faces, ORG, compress=False)
    assert_valid_pdf(pdf)
    assert b"EQP-0001" in pdf


def test_long_texts_are_truncated_not_overflowing(issued: list) -> None:
    face = LabelFace("X" * 80, alias=issued[0].alias, description="y" * 300, category="z" * 100)
    pdf = render_sheet([face], "O" * 200, preset="a4-65", compress=False)
    assert_valid_pdf(pdf)
    assert b"O" * 45 not in pdf  # header limited to 44 characters


def test_face_from_label_keeps_identity(issued: list) -> None:
    face = issued[0]
    assert face.alias and face.gs1_link and face.epc
    assert LabelFace.from_label(face) == face
