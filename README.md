# asset-identity-gs1

**GS1 identity for the physical assets of an inventory: one identity, four equivalent forms, uniqueness without a server.**

[Versión en español](README.es.md) · `pip install asset-identity-gs1` (import `assetid`) · MIT · CI on Python 3.11 and 3.12

```python
from assetid import Namespace, derive_identity

ns = Namespace("9520012", block=1000, tenant_code="NOR", resolver_domain="verify.example.org")
identity = derive_identity(ns, serial=42, inventory_number="MOB-0042")

identity.giai      # '9520012100000000042'                      GS1 key (AI 8004)
identity.alias     # 'AID-NOR-MOB0042-1'                        barcode + humans, mod-43 check
identity.epc       # '3416450E300000174876E82A'               GIAI-96 for UHF RFID chips
identity.gs1_link  # 'https://verify.example.org/8004/9520012100000000042'   QR payload
```

This repository is a **clean-room case study**: it was rebuilt from a written
specification, without access to the original code, and every byte of data in
it is synthetic. See [Attribution](#attribution).

---

## The problem

Public and private organisations keep an inventory of physical assets
(buildings, furniture, equipment, artworks) that has to be **labelled** and then
**recognised in the field** with a laser scanner, a phone camera or a UHF RFID
reader. Three things make this harder than printing a barcode:

1. **Many sites, many tenants.** Each site labels on its own schedule, often
   offline and on its own premises. Two sites must never produce the same code.
2. **Three readers, one identity.** A barcode gun reads text, a phone reads a
   URL, an RFID reader returns 96 bits. They must all resolve to the same asset.
3. **The label outlives the data model.** Inventory numbers get renumbered,
   assets get re-registered, labels get printed before the asset exists in the
   system. The identity must survive all of that.

## Constraints

- **Interoperable**: the canonical key is a GS1 GIAI (AI 8004), so any GS1-aware
  system can read it; the RFID form follows the EPC Tag Data Standard.
- **No runtime coordination**: a tenant must be able to issue and print with the
  central authority unreachable.
- **Cheap tags**: the RFID form has to fit 96-bit EPC memory (GIAI-96), which
  rules out alphanumeric asset references.
- **Field-friendly**: the printed alias needs a visible check character, so a
  mistyped number is caught before it reaches the database.
- **Pure Python**, minimal dependencies (reportlab, Pillow), SQLite persistence.

## Architecture

```
            namespace authority (once per tenant)
            ─────────────────────────────────────
            company prefix · block · tenant code · resolver domain
                               │
                               ▼
   ┌──────────────── identity (pure functions) ─────────────────┐
   │  (prefix, block, serial) ──► asset reference (12 digits)   │
   │                          ──► GIAI = prefix ‖ reference     │
   │                          ──► EPC  = GIAI-96 (96 bits)      │
   │                          ──► GS1 Digital Link /8004/<GIAI> │
   │  (tenant code, inventory number) ──► alias + mod-43 check  │
   └────────────────────────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────── registry (SQLite) ─────────────────────────┐
   │ NamespaceRegistry  assign / collision / enable             │
   │ LabelRegistry      issue · reserve · bind · mark · reprint │
   │                    field closure · resolve any scan        │
   │ lifecycle          ISSUED → PRINTED → PLACED → RETIRED     │
   └────────────────────────────────────────────────────────────┘
                               │
                               ▼
   ┌──────────────── rendering ─────────────────────────────────┐
   │ labels_pdf   A4 sheets (21/65/14 per page), single labels, │
   │              Code128 + QR + logo, vector PDF               │
   │ zpl          ^RFW EPC write + printed face for RFID        │
   │              printer-encoders                              │
   └────────────────────────────────────────────────────────────┘
```

| Module | Responsibility |
|---|---|
| `assetid.identity` | `Namespace`, normalisation, asset reference, GIAI, Digital Link, alias, `derive_identity`, `parse_any` |
| `assetid.checkchar` | mod-43 check character (the Code 39 algorithm) |
| `assetid.epc` | GIAI-96 encode/decode with the TDS partition table |
| `assetid.lifecycle` | state machine and transition table |
| `assetid.registry` | `Store` (SQLite), `NamespaceRegistry`, `LabelRegistry`, audit events |
| `assetid.labels_pdf` | sheet presets, `render_sheet`, `render_single`, `LabelFace` |
| `assetid.zpl` | `build_zpl`, `build_zpl_batch`, text sanitising |
| `assetid.synthetic` | deterministic generators for tenants, assets and a logo |

### Uniqueness by construction

The 12-digit asset reference is `block(4) ‖ serial(8)`. A central authority
hands each tenant **one block, once**; afterwards the tenant increments its own
serial locally. Different blocks give different GIAIs and EPCs even when two
tenants reach the same serial, exactly like MAC address prefixes or GS1 company
prefixes. The authority only checks collisions at assignment time
(`NamespaceCollision`, HTTP 409 in an API); nothing is checked at print time.

### Two numbers, one registry

The **serial** feeds the GIAI and the EPC and never changes. The **inventory
number** feeds the alias (`AID-<TENANT>-<NUMBER>-<check>`) because that is what
people recognise. They are linked by the registry, not by arithmetic, so a
renumbering never invalidates a chip.

### Labels before assets

A site can reserve a batch of identities (`M-0001`, `M-0002`, …) before the
assets exist. Each reservation consumes a serial and lives under a sentinel
owner (`RESERVED:<tenant>:<number>`), so it never inflates asset counts. When
the asset is finally registered with that number, the reservation is bound to
it and the label is already `PLACED`.

## Decisions and discarded alternatives

| Decision | Discarded | Why |
|---|---|---|
| **GIAI** as canonical key | SGTIN | A patrimonial asset is an individual item with no product GTIN; GIAI is the GS1 key for own assets and its long reference leaves room to partition tenants |
| **Namespace partition** | Central registry queried at print time | Sites print offline and on-premise; partition gives uniqueness by construction and a cloud verifier becomes an add-on |
| **Numeric, fixed-width reference** | GIAI-202 (alphanumeric) | Fits 96-bit chips and packs block + serial |
| **Code128** | Code 39 | Denser (fits 63 mm cells), lower case and symbols, built-in checksum |
| **Visible mod-43** check | mod-10 | The alias is alphanumeric; mod-43 covers letters and the hyphen |
| Alias from the **inventory number**, GIAI from the **serial** | One single number | Operators recognise their number; the serial survives renumbering; the registry links both |
| QR = **GS1 Digital Link** | QR with the alias | One payload that is both a verification URL and a GS1 key |
| Reservation with **sentinel owner** | Empty placeholder assets | No fake assets in the indicators; registration inherits the code already stuck on |
| reportlab for **Code128 and QR** | python-barcode + qrcode | One vector backend, no raster step, fewer dependencies |

Everything the specification left open is logged, with the alternatives, in
[`docs/DECISIONES.md`](docs/DECISIONES.md) (Spanish).

## What was measured and how to reproduce it

Measured on one run of the included synthetic generators (CPython 3.13, one
core, no tuning). Figures are indicative, not benchmarks.

| Operation | Result |
|---|---|
| GIAI-96 encode + decode round trip | ~270 000 / s |
| Alias build with check character | ~720 000 / s |
| `LabelRegistry.issue` (SQLite in memory / on disk) | ~2 100 / s · ~540 / s |
| `resolve_scanned` by Digital Link | ~70 000 / s |
| Render 210 labels (10 sheets of 21) with QR and logo | ~4.4 s, 264 KiB |
| Render 210 labels (65 per sheet, no QR) | ~0.07 s |
| ZPL batch of 210 labels | ~1 ms |

The QR encoder dominates sheet rendering (about 20 ms per code); batches of a
few hundred labels are fine, tens of thousands are not interactive.

Reproduce:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                      # 148 tests, including the anti-leak scan
ruff check . && ruff format --check .
python examples/demo.py     # writes examples/output/{sheet-a4-21.pdf,single.pdf,batch.zpl,labels.sqlite}
```

The test suite maps one to one to the specification's 23 test cases
(`tests/test_identity.py`, `test_epc.py`, `test_registry.py`,
`test_labels_pdf.py`, `test_zpl.py`, `test_no_leaks.py`).

## Usage sketch

```python
from assetid import LabelFace, LabelRegistry, LabelState, Namespace, NamespaceRegistry, Store
from assetid import build_zpl_batch, render_sheet

store = Store("labels.sqlite")                       # ":memory:" by default
NamespaceRegistry(store).assign("site-north", Namespace("9520012", 1000, "NOR", "verify.example.org"))
registry = LabelRegistry(store)

label = registry.issue("site-north", asset_id="asset-17", inventory_number="MOB-0042", by="clerk")
registry.reprint("asset-17")                         # PRINTED, reprint_count == 1
registry.mark_placed_from_field("asset-17")          # PLACED (ISSUED passes through PRINTED)
registry.verify_scan("asset-17", "AID-NOR-MOB0042-1")   # True / False (crossed label) / None (no read)

reserved = registry.reserve("site-north", 3)         # M-0001..M-0003 under a sentinel owner
registry.bind_reserved("site-north", "M-0002", "asset-18")

pdf = render_sheet([LabelFace.from_label(label, description="Office chair")], "City of Example")
zpl = build_zpl_batch([label], org_name="City of Example")
```

## Known limits

- **Strict TDS decoders.** GS1's GIAI-96 rules say the asset reference must not
  start with zero. With a block below 1000 the padded reference does
  (`0014…`), so a strict third-party decoder returns fewer digits. This library
  pads on decode; for full conformance assign blocks ≥ 1000 or use
  `Namespace(strict=True)`.
- **Filter values** other than 0 are accepted but their meaning for GIAI-96 is
  not defined here.
- **Sheet geometry** approximates common manufacturer templates; calibrate the
  presets (or pass `outlines=True`) before a production run.
- **No PNG output**, no GIAI-202, no GS1-128/DataMatrix, no public resolver
  behind the Digital Link, no reader drivers, no web UI (all out of scope).
- **Single-writer SQLite.** Issuing is serialised with `BEGIN IMMEDIATE`; it is
  meant for one site's database, not a shared multi-process service.
- **ZPL module width** drops to one dot (0.125 mm at 203 dpi) when a 17-character
  alias does not fit the default 50 mm label; use wider stock or 300 dpi.

## How it was built

Three-phase clean-room process: (1) a specification was written from the
original system without code; (2) this repository was implemented in a fresh
session from the specification and the public standards only, with an
AI coding assistant driving the implementation under review; (3) an
independent review compares both before publication. The anti-leak test in
`tests/test_no_leaks.py` keeps a sealed list of terms that must never appear in
the tree or the history.

## Attribution

Patterns developed during my work at Intervalor Data and published with
permission. Independent (clean-room) implementation with synthetic data; it
contains no code or data from the company or its clients.

## License

MIT, see [LICENSE](LICENSE).
