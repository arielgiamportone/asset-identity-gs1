"""Spec cases 11-20: namespaces, issuing, reservations, lifecycle and scans."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from assetid import (
    IllegalTransition,
    Namespace,
    NamespaceCollision,
    NamespaceIncomplete,
    parse_alias,
)
from assetid.lifecycle import LabelState
from assetid.registry import (
    RESERVED_OWNER_PREFIX,
    DuplicateAlias,
    EventKind,
    LabelRegistry,
    NamespaceRegistry,
    Store,
    reserved_owner_key,
)
from assetid.synthetic import SyntheticTenant, generate_assets

# -- case 11: namespace collisions -------------------------------------------


def test_block_used_by_another_tenant_is_rejected(
    namespaces: NamespaceRegistry, tenants: list[SyntheticTenant]
) -> None:
    other = tenants[0]
    clash = Namespace(other.company_prefix, other.block, "NEW", other.resolver_domain)
    with pytest.raises(NamespaceCollision):
        namespaces.assign("tenant-999", clash)
    code_clash = Namespace(other.company_prefix, 4321, other.tenant_code, other.resolver_domain)
    with pytest.raises(NamespaceCollision):
        namespaces.assign("tenant-999", code_clash)
    assert "tenant-999" not in namespaces.tenants()


def test_resaving_own_namespace_updates_without_duplicating(
    store: Store, namespaces: NamespaceRegistry, tenants: list[SyntheticTenant]
) -> None:
    mine = tenants[0]
    before = store.conn.execute("SELECT COUNT(*) FROM namespaces").fetchone()[0]
    updated = Namespace(mine.company_prefix, mine.block, mine.tenant_code, "new.example.org")
    namespaces.assign(mine.tenant_id, updated)
    after = store.conn.execute("SELECT COUNT(*) FROM namespaces").fetchone()[0]
    assert before == after
    assert namespaces.get(mine.tenant_id) == updated
    events = store.events(kind=EventKind.NAMESPACE_ASSIGNED)
    assert [e.tenant_id for e in events].count(mine.tenant_id) == 2


# -- case 12: idempotent issuing ---------------------------------------------


def test_issue_is_idempotent_and_serials_are_consecutive(
    labels: LabelRegistry, tenants: list[SyntheticTenant], store: Store
) -> None:
    tenant = tenants[0]
    first = labels.issue(tenant.tenant_id, "asset-1", "MOB-0042", by="clerk")
    again = labels.issue(tenant.tenant_id, "asset-1", "MOB-0042", by="someone-else")
    assert first == again
    assert first.serial == 1 and first.state is LabelState.ISSUED
    assert first.issued_by == "clerk" and first.reprint_count == 0
    assert first.block == tenant.block
    assert parse_alias(first.alias).check_ok
    assert first.identity.giai == first.giai
    second = labels.issue(tenant.tenant_id, "asset-2", "MOB-0043")
    assert second.serial == 2
    assert len(labels.labels(tenant.tenant_id)) == 2
    assert store.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 2
    issued = store.events(kind=EventKind.LABEL_ISSUED)
    assert [e.owner_key for e in issued] == ["asset-1", "asset-2"]


def test_serials_are_per_tenant_and_identities_differ(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    a = labels.issue(tenants[0].tenant_id, "asset-a", "EQP-0001")
    b = labels.issue(tenants[1].tenant_id, "asset-b", "EQP-0001")
    assert a.serial == b.serial == 1
    assert a.giai != b.giai and a.epc != b.epc and a.alias != b.alias


def test_duplicate_inventory_number_in_tenant_is_rejected(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    labels.issue(tenants[0].tenant_id, "asset-1", "MOB-0042")
    with pytest.raises(DuplicateAlias):
        labels.issue(tenants[0].tenant_id, "asset-2", "mob 0042")
    assert labels.get("asset-2") is None


# -- case 13: incomplete namespace -------------------------------------------


def test_issue_without_namespace_fails(store: Store) -> None:
    registry = LabelRegistry(store)
    with pytest.raises(NamespaceIncomplete):
        registry.issue("tenant-x", "asset-1", "MOB-0001")
    with pytest.raises(NamespaceIncomplete):
        registry.reserve("tenant-x", 1)


def test_disabled_namespace_blocks_issuing(
    labels: LabelRegistry, namespaces: NamespaceRegistry, tenants: list[SyntheticTenant]
) -> None:
    namespaces.set_enabled(tenants[0].tenant_id, False)
    assert namespaces.get(tenants[0].tenant_id) is None
    with pytest.raises(NamespaceIncomplete):
        labels.issue(tenants[0].tenant_id, "asset-1", "MOB-0001")
    namespaces.set_enabled(tenants[0].tenant_id, True)
    assert labels.issue(tenants[0].tenant_id, "asset-1", "MOB-0001").serial == 1


# -- case 14: manual transitions ---------------------------------------------


def test_manual_placed_from_issued_is_illegal_but_retire_is_allowed(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    tenant_id = tenants[0].tenant_id
    labels.issue(tenant_id, "asset-1", "MOB-0001")
    with pytest.raises(IllegalTransition):
        labels.mark("asset-1", LabelState.PLACED)
    retired = labels.mark("asset-1", "RETIRED")
    assert retired.state is LabelState.RETIRED and retired.retired_at is not None
    with pytest.raises(IllegalTransition):
        labels.mark("asset-1", LabelState.PRINTED)
    with pytest.raises(KeyError):
        labels.mark("ghost", LabelState.PRINTED)


def test_retire_helper_and_state_events(
    labels: LabelRegistry, tenants: list[SyntheticTenant], store: Store
) -> None:
    tenant_id = tenants[0].tenant_id
    labels.issue(tenant_id, "asset-1", "MOB-0001")
    labels.mark("asset-1", LabelState.PRINTED)
    labels.mark("asset-1", LabelState.PLACED)
    assert labels.retire("asset-1").state is LabelState.RETIRED
    kinds = [
        e.detail for e in store.events(owner_key="asset-1", kind=EventKind.LABEL_STATE_CHANGED)
    ]
    assert kinds == [
        "ISSUED -> PRINTED (manual)",
        "PRINTED -> PLACED (manual)",
        "PLACED -> RETIRED (manual)",
    ]


# -- case 15: reprints -------------------------------------------------------


def test_reprint_twice(labels: LabelRegistry, tenants: list[SyntheticTenant]) -> None:
    tenant_id = tenants[0].tenant_id
    issued = labels.issue(tenant_id, "asset-1", "MOB-0001")
    labels.reprint("asset-1")
    label = labels.reprint("asset-1")
    assert label.reprint_count == 2
    assert label.state is LabelState.PRINTED
    assert label.printed_at is not None and label.printed_at > issued.issued_at
    assert label.serial == issued.serial and label.giai == issued.giai


def test_reprint_of_retired_label_only_counts(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    labels.issue(tenants[0].tenant_id, "asset-1", "MOB-0001")
    labels.retire("asset-1")
    label = labels.reprint("asset-1")
    assert label.reprint_count == 1 and label.state is LabelState.RETIRED
    assert label.printed_at is None


# -- case 16: resolving scans ------------------------------------------------


def test_resolve_by_every_form(labels: LabelRegistry, tenants: list[SyntheticTenant]) -> None:
    label = labels.issue(tenants[0].tenant_id, "asset-1", "MOB-0001")
    assert labels.resolve_scanned(label.alias) == label
    assert labels.resolve_scanned(label.alias.lower()) == label
    assert labels.resolve_scanned(label.giai) == label
    assert labels.resolve_scanned(label.epc) == label
    assert labels.resolve_scanned(label.gs1_link) == label
    assert labels.resolve_scanned(label.gs1_link + "?linkType=all") == label
    assert labels.resolve_scanned("") is None
    assert labels.resolve_scanned(None) is None
    assert labels.resolve_scanned("AID-NOR-NOPE-0") is None
    assert labels.resolve_scanned("952001000000000001") is None
    assert labels.resolve_scanned("garbage") is None


# -- case 17: field closure --------------------------------------------------


def test_mark_placed_from_field(labels: LabelRegistry, tenants: list[SyntheticTenant]) -> None:
    tenant_id = tenants[0].tenant_id
    labels.issue(tenant_id, "asset-1", "MOB-0001")
    placed = labels.mark_placed_from_field("asset-1")
    assert placed is not None
    assert placed.state is LabelState.PLACED
    assert placed.printed_at is not None and placed.placed_at is not None
    again = labels.mark_placed_from_field("asset-1")
    assert again == placed  # no-op, same stamps
    assert labels.mark_placed_from_field("ghost") is None
    labels.issue(tenant_id, "asset-2", "MOB-0002")
    labels.mark("asset-2", LabelState.PRINTED)
    assert labels.mark_placed_from_field("asset-2").state is LabelState.PLACED  # type: ignore[union-attr]
    labels.retire("asset-2")
    assert labels.mark_placed_from_field("asset-2").state is LabelState.RETIRED  # type: ignore[union-attr]


# -- case 18: crossed labels -------------------------------------------------


def test_verify_scan_detects_crossed_label(
    labels: LabelRegistry, tenants: list[SyntheticTenant], store: Store
) -> None:
    tenant_id = tenants[0].tenant_id
    one = labels.issue(tenant_id, "asset-1", "MOB-0001")
    two = labels.issue(tenant_id, "asset-2", "MOB-0002")
    assert labels.verify_scan("asset-1", one.alias) is True
    assert labels.verify_scan("asset-1", one.gs1_link) is True
    assert labels.verify_scan("asset-1", two.alias) is False
    assert labels.verify_scan("asset-1", "AID-XXX-UNKNOWN-0") is False
    assert labels.verify_scan("asset-1", "") is None
    assert labels.verify_scan("asset-1", None) is None
    mismatches = store.events(kind=EventKind.LABEL_SCAN_MISMATCH)
    assert len(mismatches) == 2
    assert mismatches[0].owner_key == "asset-1" and "asset-2" in mismatches[0].detail


# -- cases 19 and 20: reservations -------------------------------------------


def test_reserve_three_then_next_number(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    tenant_id = tenants[0].tenant_id
    reserved = labels.reserve(tenant_id, 3)
    assert [r.inventory_number for r in reserved] == ["M-0001", "M-0002", "M-0003"]
    assert [r.serial for r in reserved] == [1, 2, 3]
    assert all(r.is_reserved and r.asset_id is None for r in reserved)
    assert reserved[0].owner_key == reserved_owner_key(tenant_id, "M-0001")
    assert reserved[0].owner_key.startswith(RESERVED_OWNER_PREFIX)
    assert all(r.state is LabelState.ISSUED for r in reserved)
    assert labels.next_inventory_number(tenant_id) == "M-0004"
    assert labels.labels(tenant_id, include_reserved=False) == []
    # each call reserves new numbers
    assert [r.inventory_number for r in labels.reserve(tenant_id, 1)] == ["M-0004"]


def test_next_number_counts_existing_assets_and_other_prefixes(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    tenant_id = tenants[0].tenant_id
    assert labels.next_inventory_number(tenant_id, "M", ["M-0010", "m-0012", "X-0099"]) == "M-0013"
    labels.issue(tenant_id, "asset-1", "EQP-0005")
    assert labels.next_inventory_number(tenant_id, "EQP") == "EQP-0006"
    assert labels.next_inventory_number(tenant_id, "M") == "M-0001"
    # reservations are tenant-scoped
    labels.reserve(tenants[1].tenant_id, 2)
    assert labels.next_inventory_number(tenant_id, "M") == "M-0001"


def test_bind_reserved_to_real_asset(
    labels: LabelRegistry, tenants: list[SyntheticTenant], store: Store
) -> None:
    tenant_id = tenants[0].tenant_id
    reserved = labels.reserve(tenant_id, 3)
    bound = labels.bind_reserved(tenant_id, "M-0002", "asset-7")
    assert bound is not None
    assert bound.owner_key == "asset-7" and bound.asset_id == "asset-7"
    assert bound.state is LabelState.PLACED
    assert bound.printed_at is not None and bound.placed_at is not None
    assert bound.giai == reserved[1].giai and bound.serial == reserved[1].serial
    assert labels.get(reserved_owner_key(tenant_id, "M-0002")) is None
    remaining = [r.inventory_number for r in labels.labels(tenant_id) if r.is_reserved]
    assert remaining == ["M-0001", "M-0003"]
    assert store.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 3
    # binding again for the same asset returns the existing label, nothing new
    assert labels.bind_reserved(tenant_id, "M-0001", "asset-7") == bound
    assert [r.inventory_number for r in labels.labels(tenant_id) if r.is_reserved] == remaining
    # unknown number -> None
    assert labels.bind_reserved(tenant_id, "M-0099", "asset-8") is None


def test_issue_with_reserved_number_binds_instead_of_minting(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    tenant_id = tenants[0].tenant_id
    reserved = labels.reserve(tenant_id, 1)[0]
    label = labels.issue(tenant_id, "asset-9", "m 0001")
    assert label.serial == reserved.serial and label.owner_key == "asset-9"
    assert label.state is LabelState.PLACED
    assert labels.next_inventory_number(tenant_id) == "M-0002"


# -- persistence --------------------------------------------------------------


def test_store_on_disk_is_idempotent_and_upgrades_old_schema(tmp_path: Path) -> None:
    path = tmp_path / "labels.sqlite"
    with Store(path) as first:
        NamespaceRegistry(first).assign("t1", Namespace("952001", 1000, "NOR", "v.example.org"))
        LabelRegistry(first).issue("t1", "asset-1", "MOB-0001")
    with Store(path) as second:  # CREATE IF NOT EXISTS keeps the data
        assert LabelRegistry(second).get("asset-1") is not None
    # simulate a database from before `reprint_count` and `strict` existed
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE labels_old AS SELECT * FROM labels")
    raw.execute("ALTER TABLE labels DROP COLUMN reprint_count")
    raw.execute("ALTER TABLE namespaces DROP COLUMN strict")
    raw.commit()
    raw.close()
    with Store(path) as third:
        columns = {r[1] for r in third.conn.execute("PRAGMA table_info(labels)")}
        assert "reprint_count" in columns
        registry = LabelRegistry(third)
        assert registry.reprint("asset-1").reprint_count == 1
        assert NamespaceRegistry(third).get("t1").strict is False  # type: ignore[union-attr]


def test_transaction_rolls_back_on_error(store: Store) -> None:
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.record_event(EventKind.LABEL_ISSUED, "t", "x", "boom")
            raise RuntimeError("boom")
    assert store.events() == []


def test_bulk_issue_from_synthetic_assets(
    labels: LabelRegistry, tenants: list[SyntheticTenant]
) -> None:
    tenant_id = tenants[2].tenant_id
    assets = generate_assets(50, seed=3, messy=True)
    issued = [labels.issue(tenant_id, a.asset_id, a.inventory_number) for a in assets]
    assert [label.serial for label in issued] == list(range(1, 51))
    assert len({label.alias for label in issued}) == 50
    assert len({label.epc for label in issued}) == 50
    assert all(labels.resolve_scanned(label.epc) == label for label in issued)
