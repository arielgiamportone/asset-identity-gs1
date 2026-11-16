"""Deterministic synthetic data for tests, examples and demos.

Everything here is generated: there are no real inventories, organisations,
GS1 company prefixes or logos. Company prefixes start with ``952``, the GS1
prefix reserved for demonstrations and examples, so they can never collide with
a licensed prefix.
"""

from __future__ import annotations

import base64
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "CATEGORIES",
    "SyntheticAsset",
    "SyntheticTenant",
    "demo_company_prefix",
    "demo_logo_base64",
    "demo_logo_data_uri",
    "demo_logo_png",
    "generate_assets",
    "generate_tenants",
]

#: GS1 prefix reserved for demonstrations and examples.
DEMO_PREFIX_HEAD = "952"

#: Asset categories with their inventory-number prefix and sample descriptions.
CATEGORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "furniture": (
        "MOB",
        (
            "Silla giratoria de oficina",
            "Mesa de reuniones de roble",
            "Estantería metálica de 5 baldas",
            "Archivador de cuatro cajones",
            "Sillón de recepción tapizado",
        ),
    ),
    "equipment": (
        "EQP",
        (
            "Ordenador portátil 14''",
            "Proyector de techo",
            "Impresora multifunción",
            "Cámara de vigilancia exterior",
            "Desfibrilador semiautomático",
        ),
    ),
    "artwork": (
        "ART",
        (
            "Óleo sobre lienzo «Amanecer»",
            "Escultura en bronce",
            "Grabado numerado 12/50",
            "Acuarela enmarcada",
        ),
    ),
    "building": (
        "EDF",
        (
            "Edificio de oficinas municipales",
            "Nave de almacén",
            "Centro cívico de barrio",
        ),
    ),
    "vehicle": (
        "VEH",
        (
            "Furgón de mantenimiento",
            "Vehículo eléctrico de reparto",
            "Barredora urbana",
        ),
    ),
}

_TENANT_CODES: tuple[str, ...] = (
    "NOR",
    "SUR",
    "EST",
    "OES",
    "CEN",
    "ALT",
    "BAJ",
    "RIO",
    "MAR",
    "SOL",
    "LUN",
    "VAL",
    "PIC",
    "VEG",
    "COS",
    "BOS",
    "LAG",
    "PRA",
)

_TOWNS: tuple[str, ...] = (
    "Villanueva del Prado",
    "Puerto Sereno",
    "Alcoba de la Sierra",
    "Monteclaro",
    "Riofrío del Valle",
    "Santa Marta de Lomas",
    "Castroviejo",
    "Fuente Alta",
    "Lagunilla de Arriba",
    "Peñas Blancas",
    "Valdelosmolinos",
    "Torrecilla del Pinar",
    "Benavides de Campos",
    "Cerro Hermoso",
    "Olivar de la Reina",
    "Pozo Salado",
    "Navalquemada",
    "Arroyo de las Fuentes",
)


@dataclass(frozen=True, slots=True)
class SyntheticTenant:
    """A tenant as assigned by a (synthetic) namespace authority."""

    tenant_id: str
    tenant_code: str
    block: int
    company_prefix: str
    resolver_domain: str
    org_name: str


@dataclass(frozen=True, slots=True)
class SyntheticAsset:
    """An inventory asset as a tenant would register it."""

    asset_id: str
    inventory_number: str
    description: str
    category: str


def demo_company_prefix(length: int = 7, seed: int | None = 0) -> str:
    """Return a numeric GS1-looking prefix of ``length`` digits starting with ``952``.

    ``length`` must be between 6 and 12 (the GS1 Company Prefix range). The
    remaining digits come from ``random.Random(seed)``, so the result is
    reproducible for a given seed.
    """
    if not 6 <= length <= 12:
        raise ValueError("company prefix length must be between 6 and 12 digits")
    rng = random.Random(seed)
    tail = "".join(str(rng.randrange(10)) for _ in range(length - len(DEMO_PREFIX_HEAD)))
    return DEMO_PREFIX_HEAD + tail


def generate_tenants(
    count: int,
    seed: int = 0,
    *,
    company_prefix: str | None = None,
    resolver_domain: str = "verify.example.org",
    first_block: int = 1000,
) -> list[SyntheticTenant]:
    """Generate ``count`` tenants with distinct blocks and tenant codes.

    Blocks are consecutive from ``first_block`` (1000 by default, which keeps the
    EPC asset reference free of leading zeros, see the README on conformance).
    Tenant codes come from a fixed pool of three-letter codes; beyond the pool a
    digit suffix keeps them unique.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    if first_block < 0 or first_block + count - 1 > 9999:
        raise ValueError("blocks must stay within 0..9999")
    rng = random.Random(seed)
    prefix = company_prefix or demo_company_prefix(seed=seed)
    towns = list(_TOWNS)
    rng.shuffle(towns)
    tenants: list[SyntheticTenant] = []
    for i in range(count):
        base = _TENANT_CODES[i % len(_TENANT_CODES)]
        code = base if i < len(_TENANT_CODES) else f"{base[:2]}{i // len(_TENANT_CODES)}"
        town = towns[i % len(towns)]
        tenants.append(
            SyntheticTenant(
                tenant_id=f"tenant-{i + 1:03d}",
                tenant_code=code,
                block=first_block + i,
                company_prefix=prefix,
                resolver_domain=resolver_domain,
                org_name=f"Ayuntamiento de {town}",
            )
        )
    return tenants


def generate_assets(
    count: int,
    seed: int = 0,
    *,
    categories: Sequence[str] | None = None,
    messy: bool = False,
) -> list[SyntheticAsset]:
    """Generate ``count`` assets with unique inventory numbers.

    With ``messy=True`` some inventory numbers come in the untidy forms a real
    import produces (lower case, stray spaces, slashes), which is what the
    normalisation step is for.
    """
    if count < 0:
        raise ValueError("count must be non-negative")
    chosen = tuple(categories or CATEGORIES)
    unknown = [c for c in chosen if c not in CATEGORIES]
    if unknown:
        raise ValueError(f"unknown categories: {unknown}")
    rng = random.Random(seed)
    counters = dict.fromkeys(chosen, 0)
    assets: list[SyntheticAsset] = []
    for i in range(count):
        category = chosen[rng.randrange(len(chosen))]
        prefix, descriptions = CATEGORIES[category]
        counters[category] += 1
        number = f"{prefix}-{counters[category]:04d}"
        if messy:
            style = rng.randrange(4)
            if style == 1:
                number = number.lower()
            elif style == 2:
                number = f" {prefix} {counters[category]:04d} "
            elif style == 3:
                number = number.replace("-", "/")
        assets.append(
            SyntheticAsset(
                asset_id=f"asset-{i + 1:05d}",
                inventory_number=number,
                description=descriptions[rng.randrange(len(descriptions))],
                category=category,
            )
        )
    return assets


def demo_logo_png(seed: int = 0, size: tuple[int, int] = (140, 70)) -> bytes:
    """Return a small generated PNG logo (two coloured blocks and a circle)."""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    colour_a = tuple(rng.randrange(40, 200) for _ in range(3))
    colour_b = tuple(rng.randrange(40, 200) for _ in range(3))
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle((0, 0, w // 2, h), fill=colour_a)
    draw.ellipse((w // 2 + 4, 4, w - 4, h - 4), fill=colour_b)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def demo_logo_base64(seed: int = 0) -> str:
    """Return :func:`demo_logo_png` as a base64 string (no data-URI header)."""
    return base64.b64encode(demo_logo_png(seed)).decode("ascii")


def demo_logo_data_uri(seed: int = 0) -> str:
    """Return :func:`demo_logo_png` as a ``data:image/png;base64,...`` URI."""
    return "data:image/png;base64," + demo_logo_base64(seed)
