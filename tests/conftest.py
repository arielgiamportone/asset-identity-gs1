"""Shared fixtures built from the synthetic generators."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from assetid import Namespace
from assetid.registry import LabelRegistry, NamespaceRegistry, Store
from assetid.synthetic import SyntheticTenant, generate_tenants


def namespace_of(tenant: SyntheticTenant) -> Namespace:
    return Namespace(
        tenant.company_prefix, tenant.block, tenant.tenant_code, tenant.resolver_domain
    )


@pytest.fixture
def tenants() -> list[SyntheticTenant]:
    return generate_tenants(3, seed=11)


@pytest.fixture
def store() -> Iterator[Store]:
    ticks = iter(range(1, 100_000))
    with Store(clock=lambda: f"2026-01-01T00:00:{next(ticks):02d}+00:00") as s:
        yield s


@pytest.fixture
def namespaces(store: Store, tenants: list[SyntheticTenant]) -> NamespaceRegistry:
    registry = NamespaceRegistry(store)
    for tenant in tenants:
        registry.assign(tenant.tenant_id, namespace_of(tenant))
    return registry


@pytest.fixture
def labels(store: Store, namespaces: NamespaceRegistry) -> LabelRegistry:
    return LabelRegistry(store, namespaces)
