# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-16

First clean-room release.

### Added

- **Identity model** (`assetid.identity`, `assetid.checkchar`, `assetid.epc`):
  validated immutable `Namespace`, inventory-number normalisation, 12-digit
  asset reference (block ‖ serial), GIAI (AI 8004), GS1 Digital Link, alias
  with mod-43 check character, GIAI-96 EPC encode/decode with the TDS
  partition table, `derive_identity` and the `parse_any` classifier.
- **Registry** (`assetid.registry`, `assetid.lifecycle`): SQLite store with
  idempotent schema and tolerant migrations, namespace assignment with
  collision detection, idempotent issuing with per-tenant serials,
  reservations under a sentinel owner, binding of reservations, lifecycle
  `ISSUED → PRINTED → PLACED → RETIRED`, reprints, field closure, resolution
  of any scanned form and crossed-label detection, audit events.
- **Rendering** (`assetid.labels_pdf`, `assetid.zpl`): vector PDF sheets for
  three A4 presets with start offset, single thermal labels, Code128 + QR +
  optional logo, basic mode without identity; ZPL blocks with `^RFW` EPC
  write and sanitised text for RFID printer-encoders.
- **Synthetic data** (`assetid.synthetic`): deterministic tenants, assets and
  a generated logo; `examples/demo.py` end-to-end run.
- Project skeleton: packaging metadata, MIT license, CI (pytest on Python
  3.11 and 3.12, ruff, gitleaks), bilingual case-study README and the
  anti-leak test over tree and history.
