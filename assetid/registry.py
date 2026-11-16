"""Issuing registry: namespaces per tenant, labels, reservations and audit.

Persistence is a small SQLite schema (in-memory by default) created
idempotently. Every query that touches a tenant's identifiers filters by
tenant; asset keys and aliases are globally unique, and ``(block, serial)``
is unique as a safety net on top of the by-construction guarantee.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from os import PathLike

from .errors import DuplicateAlias, NamespaceCollision, NamespaceIncomplete
from .identity import (
    AssetIdentity,
    CodeKind,
    Namespace,
    derive_identity,
    normalize_inventory_number,
    parse_any,
)
from .lifecycle import LabelState, check_transition

__all__ = [
    "RESERVED_OWNER_PREFIX",
    "AuditEvent",
    "DuplicateAlias",
    "EventKind",
    "Label",
    "LabelRegistry",
    "NamespaceRegistry",
    "Store",
    "reserved_owner_key",
]

#: Owner-key prefix of labels reserved before their asset exists.
RESERVED_OWNER_PREFIX = "RESERVED:"


class EventKind(StrEnum):
    LABEL_ISSUED = "LABEL_ISSUED"
    LABEL_STATE_CHANGED = "LABEL_STATE_CHANGED"
    LABEL_SCAN_MISMATCH = "LABEL_SCAN_MISMATCH"
    NAMESPACE_ASSIGNED = "NAMESPACE_ASSIGNED"


def reserved_owner_key(tenant_id: str, inventory_number: str) -> str:
    """Sentinel owner key of a reserved identity (tenant-scoped)."""
    return f"{RESERVED_OWNER_PREFIX}{tenant_id}:{inventory_number}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True, slots=True)
class Label:
    """A label row: one asset (or reservation sentinel), one identity, one state."""

    id: int
    owner_key: str
    tenant_id: str
    inventory_number: str
    block: int
    serial: int
    asset_reference: str
    giai: str
    alias: str
    epc: str
    gs1_link: str
    state: LabelState
    issued_at: str
    printed_at: str | None
    placed_at: str | None
    retired_at: str | None
    issued_by: str | None
    reprint_count: int

    @property
    def is_reserved(self) -> bool:
        return self.owner_key.startswith(RESERVED_OWNER_PREFIX)

    @property
    def asset_id(self) -> str | None:
        """The asset key, or ``None`` while the label is only reserved."""
        return None if self.is_reserved else self.owner_key

    @property
    def identity(self) -> AssetIdentity:
        return AssetIdentity(
            block=self.block,
            serial=self.serial,
            asset_reference=self.asset_reference,
            inventory_number=self.inventory_number,
            giai=self.giai,
            alias=self.alias,
            epc=self.epc,
            gs1_link=self.gs1_link,
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: int
    at: str
    kind: EventKind
    tenant_id: str | None
    owner_key: str | None
    detail: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS namespaces (
    tenant_id       TEXT PRIMARY KEY,
    company_prefix  TEXT NOT NULL,
    block           INTEGER NOT NULL UNIQUE,
    tenant_code     TEXT NOT NULL UNIQUE,
    resolver_domain TEXT NOT NULL,
    scheme          TEXT NOT NULL DEFAULT 'https',
    strict          INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    assigned_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_key        TEXT NOT NULL UNIQUE,
    tenant_id        TEXT NOT NULL,
    inventory_number TEXT NOT NULL,
    block            INTEGER NOT NULL,
    serial           INTEGER NOT NULL,
    asset_reference  TEXT NOT NULL,
    giai             TEXT NOT NULL UNIQUE,
    alias            TEXT NOT NULL UNIQUE,
    epc              TEXT NOT NULL UNIQUE,
    gs1_link         TEXT NOT NULL,
    state            TEXT NOT NULL,
    issued_at        TEXT NOT NULL,
    printed_at       TEXT,
    placed_at        TEXT,
    retired_at       TEXT,
    issued_by        TEXT,
    reprint_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (block, serial)
);
CREATE INDEX IF NOT EXISTS labels_tenant ON labels (tenant_id);
CREATE TABLE IF NOT EXISTS audit_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    tenant_id TEXT,
    owner_key TEXT,
    detail    TEXT NOT NULL DEFAULT ''
);
"""

#: Columns added after the first schema; applied with a tolerant ALTER so that
#: databases created by an older version keep working.
_COLUMN_UPGRADES: tuple[tuple[str, str, str], ...] = (
    ("labels", "issued_by", "TEXT"),
    ("labels", "reprint_count", "INTEGER NOT NULL DEFAULT 0"),
    ("namespaces", "strict", "INTEGER NOT NULL DEFAULT 0"),
)


class Store:
    """SQLite connection plus schema management and the audit log."""

    def __init__(
        self,
        path: str | PathLike[str] = ":memory:",
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.clock = clock or _utc_now
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        for table, column, declaration in _COLUMN_UPGRADES:
            self._ensure_column(table, column, declaration)

    def _ensure_column(self, table: str, column: str, declaration: str) -> None:
        present = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def now(self) -> str:
        return self.clock()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialise writers with ``BEGIN IMMEDIATE``; rolls back on error."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def record_event(
        self,
        kind: EventKind,
        tenant_id: str | None,
        owner_key: str | None,
        detail: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO audit_events (at, kind, tenant_id, owner_key, detail) VALUES (?,?,?,?,?)",
            (self.now(), str(kind), tenant_id, owner_key, detail),
        )

    def events(
        self, *, owner_key: str | None = None, kind: EventKind | None = None
    ) -> list[AuditEvent]:
        sql = "SELECT * FROM audit_events WHERE 1=1"
        params: list[object] = []
        if owner_key is not None:
            sql += " AND owner_key = ?"
            params.append(owner_key)
        if kind is not None:
            sql += " AND kind = ?"
            params.append(str(kind))
        rows = self.conn.execute(sql + " ORDER BY id", params).fetchall()
        return [
            AuditEvent(
                id=r["id"],
                at=r["at"],
                kind=EventKind(r["kind"]),
                tenant_id=r["tenant_id"],
                owner_key=r["owner_key"],
                detail=r["detail"],
            )
            for r in rows
        ]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class NamespaceRegistry:
    """The namespace authority's side: one block and code per tenant, once."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def assign(self, tenant_id: str, namespace: Namespace) -> Namespace:
        """Assign (or re-save) ``namespace`` to ``tenant_id``.

        Raises :class:`NamespaceCollision` when another tenant already holds
        the block or the tenant code. Re-saving the same tenant updates its
        row instead of duplicating it.
        """
        conn = self.store.conn
        with self.store.transaction():
            clash = conn.execute(
                "SELECT tenant_id FROM namespaces WHERE (block = ? OR tenant_code = ?) "
                "AND tenant_id <> ?",
                (namespace.block, namespace.tenant_code, tenant_id),
            ).fetchone()
            if clash:
                raise NamespaceCollision(
                    f"block {namespace.block} or code {namespace.tenant_code!r} already "
                    f"belongs to tenant {clash['tenant_id']!r}"
                )
            conn.execute(
                "INSERT INTO namespaces (tenant_id, company_prefix, block, tenant_code, "
                "resolver_domain, scheme, strict, enabled, assigned_at) "
                "VALUES (?,?,?,?,?,?,?,1,?) "
                "ON CONFLICT(tenant_id) DO UPDATE SET company_prefix=excluded.company_prefix, "
                "block=excluded.block, tenant_code=excluded.tenant_code, "
                "resolver_domain=excluded.resolver_domain, scheme=excluded.scheme, "
                "strict=excluded.strict, enabled=1, assigned_at=excluded.assigned_at",
                (
                    tenant_id,
                    namespace.company_prefix,
                    namespace.block,
                    namespace.tenant_code,
                    namespace.resolver_domain,
                    namespace.scheme,
                    int(namespace.strict),
                    self.store.now(),
                ),
            )
            self.store.record_event(
                EventKind.NAMESPACE_ASSIGNED,
                tenant_id,
                None,
                f"block={namespace.block} code={namespace.tenant_code}",
            )
        return namespace

    def set_enabled(self, tenant_id: str, enabled: bool) -> None:
        """Disable (or re-enable) issuing for a tenant without losing its block."""
        self.store.conn.execute(
            "UPDATE namespaces SET enabled = ? WHERE tenant_id = ?", (int(enabled), tenant_id)
        )

    def get(self, tenant_id: str) -> Namespace | None:
        """Return the tenant's enabled namespace, or ``None``."""
        row = self.store.conn.execute(
            "SELECT * FROM namespaces WHERE tenant_id = ? AND enabled = 1", (tenant_id,)
        ).fetchone()
        if row is None:
            return None
        return Namespace(
            company_prefix=row["company_prefix"],
            block=row["block"],
            tenant_code=row["tenant_code"],
            resolver_domain=row["resolver_domain"],
            scheme=row["scheme"],
            strict=bool(row["strict"]),
        )

    def require(self, tenant_id: str) -> Namespace:
        namespace = self.get(tenant_id)
        if namespace is None:
            raise NamespaceIncomplete(
                f"tenant {tenant_id!r} has no enabled namespace; issuing is disabled"
            )
        return namespace

    def tenants(self) -> list[str]:
        rows = self.store.conn.execute("SELECT tenant_id FROM namespaces ORDER BY block")
        return [r["tenant_id"] for r in rows]


def _row_to_label(row: sqlite3.Row) -> Label:
    return Label(
        id=row["id"],
        owner_key=row["owner_key"],
        tenant_id=row["tenant_id"],
        inventory_number=row["inventory_number"],
        block=row["block"],
        serial=row["serial"],
        asset_reference=row["asset_reference"],
        giai=row["giai"],
        alias=row["alias"],
        epc=row["epc"],
        gs1_link=row["gs1_link"],
        state=LabelState(row["state"]),
        issued_at=row["issued_at"],
        printed_at=row["printed_at"],
        placed_at=row["placed_at"],
        retired_at=row["retired_at"],
        issued_by=row["issued_by"],
        reprint_count=row["reprint_count"],
    )


_STATE_STAMP = {
    LabelState.PRINTED: "printed_at",
    LabelState.PLACED: "placed_at",
    LabelState.RETIRED: "retired_at",
}


class LabelRegistry:
    """The local operator's side: issue, reserve, print, place, retire, resolve."""

    def __init__(self, store: Store, namespaces: NamespaceRegistry | None = None) -> None:
        self.store = store
        self.namespaces = namespaces or NamespaceRegistry(store)

    # -- lookups ------------------------------------------------------------

    def get(self, asset_id: str) -> Label | None:
        """Return the label of ``asset_id`` (an owner key), or ``None``."""
        row = self.store.conn.execute(
            "SELECT * FROM labels WHERE owner_key = ?", (asset_id,)
        ).fetchone()
        return _row_to_label(row) if row else None

    def labels(self, tenant_id: str, *, include_reserved: bool = True) -> list[Label]:
        rows = self.store.conn.execute(
            "SELECT * FROM labels WHERE tenant_id = ? ORDER BY serial", (tenant_id,)
        ).fetchall()
        labels = [_row_to_label(r) for r in rows]
        if not include_reserved:
            labels = [label for label in labels if not label.is_reserved]
        return labels

    def _by_column(self, column: str, value: str) -> Label | None:
        row = self.store.conn.execute(
            f"SELECT * FROM labels WHERE {column} = ?", (value,)
        ).fetchone()
        return _row_to_label(row) if row else None

    def _next_serial(self, tenant_id: str) -> int:
        row = self.store.conn.execute(
            "SELECT COALESCE(MAX(serial), 0) AS top FROM labels WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()
        return int(row["top"]) + 1

    def _find_reserved(self, tenant_id: str, inventory_number: str) -> Label | None:
        wanted = normalize_inventory_number(inventory_number)
        rows = self.store.conn.execute(
            "SELECT * FROM labels WHERE tenant_id = ? AND owner_key LIKE ?",
            (tenant_id, RESERVED_OWNER_PREFIX + "%"),
        ).fetchall()
        for row in rows:
            if normalize_inventory_number(row["inventory_number"]) == wanted:
                return _row_to_label(row)
        return None

    # -- issuing ------------------------------------------------------------

    def _insert(
        self,
        owner_key: str,
        tenant_id: str,
        inventory_number: str,
        identity: AssetIdentity,
        state: LabelState,
        by: str | None,
    ) -> Label:
        now = self.store.now()
        try:
            cursor = self.store.conn.execute(
                "INSERT INTO labels (owner_key, tenant_id, inventory_number, block, serial, "
                "asset_reference, giai, alias, epc, gs1_link, state, issued_at, printed_at, "
                "placed_at, issued_by, reprint_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
                (
                    owner_key,
                    tenant_id,
                    inventory_number,
                    identity.block,
                    identity.serial,
                    identity.asset_reference,
                    identity.giai,
                    identity.alias,
                    identity.epc,
                    identity.gs1_link,
                    str(state),
                    now,
                    now if state in (LabelState.PRINTED, LabelState.PLACED) else None,
                    now if state is LabelState.PLACED else None,
                    by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "alias" in str(exc):
                raise DuplicateAlias(
                    f"alias {identity.alias!r} is already issued to another asset"
                ) from exc
            raise
        self.store.record_event(
            EventKind.LABEL_ISSUED, tenant_id, owner_key, f"serial={identity.serial}"
        )
        row = self.store.conn.execute(
            "SELECT * FROM labels WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_label(row)

    def issue(
        self, tenant_id: str, asset_id: str, inventory_number: str, by: str | None = None
    ) -> Label:
        """Issue the identity of ``asset_id`` (idempotent).

        If the asset already has a label it is returned unchanged. If the
        inventory number was reserved beforehand the reservation is bound to
        the asset instead of minting a new serial. Otherwise the next serial of
        the tenant is taken inside a write transaction and the four forms are
        derived. Raises :class:`NamespaceIncomplete` when the tenant has no
        enabled namespace and :class:`DuplicateAlias` when another asset of the
        tenant already carries the same (normalised) inventory number.
        """
        existing = self.get(asset_id)
        if existing is not None:
            return existing
        namespace = self.namespaces.require(tenant_id)
        with self.store.transaction():
            reserved = self._find_reserved(tenant_id, inventory_number)
            if reserved is not None:
                return self._bind(reserved, asset_id)
            serial = self._next_serial(tenant_id)
            identity = derive_identity(namespace, serial, inventory_number.strip())
            return self._insert(
                asset_id, tenant_id, inventory_number.strip(), identity, LabelState.ISSUED, by
            )

    # -- reservations -------------------------------------------------------

    _NUMBER_RE_CACHE: dict[str, re.Pattern[str]] = {}

    @classmethod
    def _number_pattern(cls, prefix: str) -> re.Pattern[str]:
        pattern = cls._NUMBER_RE_CACHE.get(prefix)
        if pattern is None:
            pattern = re.compile(r"^" + re.escape(prefix.upper()) + r"-?(\d+)$")
            cls._NUMBER_RE_CACHE[prefix] = pattern
        return pattern

    def next_inventory_number(
        self, tenant_id: str, prefix: str = "M", existing_numbers: Iterable[str] = ()
    ) -> str:
        """Return ``<prefix>-NNNN`` after the highest number seen for the prefix.

        The maximum is taken over the tenant's labels (reserved ones included)
        and over ``existing_numbers``, the caller's list of assets that may not
        carry a label yet.
        """
        pattern = self._number_pattern(prefix)
        top = 0
        rows = self.store.conn.execute(
            "SELECT inventory_number FROM labels WHERE tenant_id = ?", (tenant_id,)
        ).fetchall()
        candidates = [r["inventory_number"] for r in rows]
        candidates.extend(existing_numbers)
        for number in candidates:
            match = pattern.match(number.strip().upper())
            if match:
                top = max(top, int(match.group(1)))
        return f"{prefix}-{top + 1:04d}"

    def reserve(
        self,
        tenant_id: str,
        count: int,
        prefix: str = "M",
        by: str | None = None,
        existing_numbers: Iterable[str] = (),
    ) -> list[Label]:
        """Reserve ``count`` identities before the assets exist.

        Each reservation gets the next ``<prefix>-NNNN`` number, consumes a
        serial and is stored under a sentinel owner key, so it inflates no
        asset counts. Every call reserves new numbers.
        """
        if count < 0:
            raise ValueError("count must be non-negative")
        namespace = self.namespaces.require(tenant_id)
        existing = list(existing_numbers)
        reserved: list[Label] = []
        with self.store.transaction():
            for _ in range(count):
                number = self.next_inventory_number(tenant_id, prefix, existing)
                serial = self._next_serial(tenant_id)
                identity = derive_identity(namespace, serial, number)
                reserved.append(
                    self._insert(
                        reserved_owner_key(tenant_id, number),
                        tenant_id,
                        number,
                        identity,
                        LabelState.ISSUED,
                        by,
                    )
                )
        return reserved

    def _bind(self, reserved: Label, asset_id: str) -> Label:
        now = self.store.now()
        self.store.conn.execute(
            "UPDATE labels SET owner_key = ?, state = ?, printed_at = COALESCE(printed_at, ?), "
            "placed_at = ? WHERE id = ?",
            (asset_id, str(LabelState.PLACED), now, now, reserved.id),
        )
        self.store.record_event(
            EventKind.LABEL_STATE_CHANGED,
            reserved.tenant_id,
            asset_id,
            f"bound reserved {reserved.inventory_number} -> PLACED",
        )
        label = self.get(asset_id)
        assert label is not None
        return label

    def bind_reserved(self, tenant_id: str, inventory_number: str, asset_id: str) -> Label | None:
        """Bind the reservation carrying ``inventory_number`` to ``asset_id``.

        The label becomes ``PLACED`` (it is already stuck on the asset). If the
        asset already has a label it is returned and nothing changes; if no
        reservation matches, ``None`` is returned.
        """
        existing = self.get(asset_id)
        if existing is not None:
            return existing
        with self.store.transaction():
            reserved = self._find_reserved(tenant_id, inventory_number)
            if reserved is None:
                return None
            return self._bind(reserved, asset_id)

    # -- lifecycle ----------------------------------------------------------

    def _require(self, asset_id: str) -> Label:
        label = self.get(asset_id)
        if label is None:
            raise KeyError(asset_id)
        return label

    def _set_state(self, label: Label, state: LabelState, reason: str) -> Label:
        stamp = _STATE_STAMP[state]
        self.store.conn.execute(
            f"UPDATE labels SET state = ?, {stamp} = ? WHERE id = ?",
            (str(state), self.store.now(), label.id),
        )
        self.store.record_event(
            EventKind.LABEL_STATE_CHANGED,
            label.tenant_id,
            label.owner_key,
            f"{label.state} -> {state} ({reason})",
        )
        refreshed = self.get(label.owner_key)
        assert refreshed is not None
        return refreshed

    def mark(self, asset_id: str, state: LabelState | str) -> Label:
        """Move the label of ``asset_id`` to ``state`` following the lifecycle table."""
        target = LabelState(state)
        label = self._require(asset_id)
        check_transition(label.state, target)
        with self.store.transaction():
            return self._set_state(label, target, "manual")

    def retire(self, asset_id: str) -> Label:
        """Retire the label (the asset was written off)."""
        return self.mark(asset_id, LabelState.RETIRED)

    def reprint(self, asset_id: str) -> Label:
        """Count a reprint; unless retired, the label becomes ``PRINTED`` with a fresh stamp."""
        label = self._require(asset_id)
        with self.store.transaction():
            self.store.conn.execute(
                "UPDATE labels SET reprint_count = reprint_count + 1 WHERE id = ?", (label.id,)
            )
            if label.state is LabelState.RETIRED:
                refreshed = self.get(asset_id)
                assert refreshed is not None
                return refreshed
            return self._set_state(label, LabelState.PRINTED, "reprint")

    def mark_placed_from_field(self, asset_id: str) -> Label | None:
        """Close the loop from a field verification that located the asset.

        ``ISSUED`` labels pass through ``PRINTED`` automatically (the scan
        proves printing and sticking). ``PLACED``/``RETIRED`` labels are left
        untouched; ``None`` when the asset has no label.
        """
        label = self.get(asset_id)
        if label is None:
            return None
        if label.state in (LabelState.PLACED, LabelState.RETIRED):
            return label
        with self.store.transaction():
            if label.state is LabelState.ISSUED:
                label = self._set_state(label, LabelState.PRINTED, "field scan")
            return self._set_state(label, LabelState.PLACED, "field scan")

    # -- scanning -----------------------------------------------------------

    def resolve_scanned(self, text: str | None) -> Label | None:
        """Resolve any scanned value (alias, GIAI, EPC or Digital Link) to its label."""
        parsed = parse_any(text or "")
        if parsed.kind is CodeKind.ALIAS:
            return self._by_column("alias", parsed.payload)
        if parsed.kind in (CodeKind.GIAI, CodeKind.GS1_LINK):
            return self._by_column("giai", parsed.payload)
        if parsed.kind is CodeKind.EPC:
            return self._by_column("epc", parsed.payload) or self._by_column("giai", parsed.payload)
        return None

    def verify_scan(self, asset_id: str, text: str | None) -> bool | None:
        """Check a field scan against the asset being verified.

        ``True`` when the scanned code resolves to ``asset_id``; ``False`` when
        it resolves to another asset or to nothing (a crossed label, recorded
        as ``LABEL_SCAN_MISMATCH``); ``None`` when nothing was scanned.
        """
        if text is None or not text.strip():
            return None
        label = self.resolve_scanned(text)
        if label is not None and label.owner_key == asset_id:
            return True
        found = label.owner_key if label is not None else "nothing"
        self.store.record_event(
            EventKind.LABEL_SCAN_MISMATCH,
            label.tenant_id if label is not None else None,
            asset_id,
            f"scanned {text.strip()!r} resolved to {found}",
        )
        return False
