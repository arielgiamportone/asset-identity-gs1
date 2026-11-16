"""Tests for the synthetic data generators."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from assetid import synthetic


def test_company_prefix_is_demo_range_and_deterministic() -> None:
    a = synthetic.demo_company_prefix(7, seed=1)
    b = synthetic.demo_company_prefix(7, seed=1)
    assert a == b
    assert a.startswith("952") and len(a) == 7 and a.isdigit()
    assert synthetic.demo_company_prefix(12, seed=3) != synthetic.demo_company_prefix(12, seed=4)


@pytest.mark.parametrize("length", [5, 13])
def test_company_prefix_rejects_bad_length(length: int) -> None:
    with pytest.raises(ValueError):
        synthetic.demo_company_prefix(length)


def test_tenants_have_unique_blocks_and_codes() -> None:
    tenants = synthetic.generate_tenants(25, seed=7)
    assert len(tenants) == 25
    assert len({t.block for t in tenants}) == 25
    assert len({t.tenant_code for t in tenants}) == 25
    assert len({t.tenant_id for t in tenants}) == 25
    assert all(t.company_prefix == tenants[0].company_prefix for t in tenants)
    assert all(t.tenant_code.isalnum() and t.tenant_code.isupper() for t in tenants)
    assert all(1000 <= t.block <= 9999 for t in tenants)


def test_tenants_are_deterministic_and_configurable() -> None:
    assert synthetic.generate_tenants(3, seed=2) == synthetic.generate_tenants(3, seed=2)
    custom = synthetic.generate_tenants(
        2, seed=0, company_prefix="952000123", resolver_domain="tags.example.net", first_block=14
    )
    assert [t.block for t in custom] == [14, 15]
    assert custom[0].company_prefix == "952000123"
    assert custom[0].resolver_domain == "tags.example.net"


def test_tenants_reject_block_overflow() -> None:
    with pytest.raises(ValueError):
        synthetic.generate_tenants(2, first_block=9999)


def test_assets_are_unique_and_deterministic() -> None:
    assets = synthetic.generate_assets(200, seed=5)
    assert len(assets) == 200
    assert len({a.inventory_number for a in assets}) == 200
    assert len({a.asset_id for a in assets}) == 200
    assert assets == synthetic.generate_assets(200, seed=5)
    assert {a.category for a in assets} <= set(synthetic.CATEGORIES)
    assert any(not a.description.isascii() for a in assets), "accents are part of the fixture"


def test_assets_messy_mode_produces_untidy_numbers() -> None:
    assets = synthetic.generate_assets(60, seed=1, messy=True)
    numbers = [a.inventory_number for a in assets]
    assert any(n != n.strip() for n in numbers)
    assert any(n != n.upper() for n in numbers)
    assert any("/" in n for n in numbers)


def test_assets_category_filter() -> None:
    assets = synthetic.generate_assets(10, categories=["artwork"])
    assert all(a.category == "artwork" for a in assets)
    assert all(a.inventory_number.startswith("ART-") for a in assets)
    with pytest.raises(ValueError):
        synthetic.generate_assets(1, categories=["spaceship"])


def test_logo_is_a_valid_png_in_all_encodings() -> None:
    png = synthetic.demo_logo_png()
    assert png.startswith(b"\x89PNG")
    image = Image.open(io.BytesIO(png))
    assert image.size == (140, 70)
    assert base64.b64decode(synthetic.demo_logo_base64()) == png
    uri = synthetic.demo_logo_data_uri()
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == png
