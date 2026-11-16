"""End-to-end demo on synthetic data: namespace, issuing, sheets, ZPL, scans.

Run ``python examples/demo.py [output_dir]``. It writes a label sheet PDF, a
single thermal label PDF and a ZPL batch, then prints a short report. Nothing
here is real: tenants, assets, prefixes and the logo are generated.
"""

from __future__ import annotations

import sys
from pathlib import Path

from assetid import (
    LabelFace,
    LabelRegistry,
    Namespace,
    NamespaceRegistry,
    Store,
    build_zpl_batch,
    render_sheet,
    render_single,
)
from assetid.synthetic import demo_logo_data_uri, generate_assets, generate_tenants


def main(output_dir: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    store = Store(out / "labels.sqlite")
    namespaces = NamespaceRegistry(store)
    registry = LabelRegistry(store, namespaces)

    tenants = generate_tenants(2, seed=1)
    for tenant in tenants:
        namespaces.assign(
            tenant.tenant_id,
            Namespace(
                tenant.company_prefix, tenant.block, tenant.tenant_code, tenant.resolver_domain
            ),
        )

    site = tenants[0]
    assets = generate_assets(30, seed=1)
    faces = [
        LabelFace.from_label(
            registry.issue(site.tenant_id, asset.asset_id, asset.inventory_number, by="demo"),
            description=asset.description,
            category=asset.category,
        )
        for asset in assets
    ]
    reserved = registry.reserve(site.tenant_id, 3, prefix="M", by="demo")

    (out / "sheet-a4-21.pdf").write_bytes(
        render_sheet(faces, site.org_name, preset="a4-21", logo=demo_logo_data_uri())
    )
    (out / "single.pdf").write_bytes(render_single(faces[0], site.org_name))
    (out / "batch.zpl").write_text(build_zpl_batch(faces[:5], site.org_name), encoding="ascii")

    first = faces[0]
    print(f"tenant {site.tenant_id} ({site.tenant_code}, block {site.block})")
    print(f"  GIAI          {first.gs1_link and first.gs1_link.rsplit('/', 1)[-1]}")
    print(f"  alias         {first.alias}")
    print(f"  EPC           {first.epc}")
    print(f"  Digital Link  {first.gs1_link}")
    print(f"  reserved      {[r.inventory_number for r in reserved]}")
    scanned = registry.resolve_scanned(first.alias)
    verdict = registry.verify_scan(assets[1].asset_id, first.alias)
    print(
        f"  scan {first.alias} -> {scanned.asset_id if scanned else None}; "
        f"verifying {assets[1].asset_id} against it -> {verdict}"
    )
    print(f"written to {out}/")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "examples/output")
