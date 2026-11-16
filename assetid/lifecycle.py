"""Label lifecycle: ``ISSUED -> PRINTED -> PLACED -> RETIRED``.

Allowed transitions (rows: from, columns: to)::

    from \\ to   PRINTED            PLACED            RETIRED
    ISSUED      yes                no (manual)       yes
    PRINTED     yes (reprint)      yes               yes
    PLACED      yes (reprint)      yes (idempotent)  yes
    RETIRED     no                 no                yes

A label only reaches ``PLACED`` from ``ISSUED`` through a field scan
(:meth:`assetid.registry.LabelRegistry.mark_placed_from_field`), which
proves it was printed and stuck.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import IllegalTransition

__all__ = ["ALLOWED_TRANSITIONS", "LabelState", "can_transition", "check_transition"]


class LabelState(StrEnum):
    ISSUED = "ISSUED"
    PRINTED = "PRINTED"
    PLACED = "PLACED"
    RETIRED = "RETIRED"


ALLOWED_TRANSITIONS: dict[LabelState, frozenset[LabelState]] = {
    LabelState.ISSUED: frozenset({LabelState.PRINTED, LabelState.RETIRED}),
    LabelState.PRINTED: frozenset({LabelState.PRINTED, LabelState.PLACED, LabelState.RETIRED}),
    LabelState.PLACED: frozenset({LabelState.PRINTED, LabelState.PLACED, LabelState.RETIRED}),
    LabelState.RETIRED: frozenset({LabelState.RETIRED}),
}


def can_transition(current: LabelState, target: LabelState) -> bool:
    """Return whether ``current -> target`` is in the lifecycle table."""
    return target in ALLOWED_TRANSITIONS[LabelState(current)]


def check_transition(current: LabelState, target: LabelState) -> None:
    """Raise :class:`IllegalTransition` unless ``current -> target`` is allowed."""
    if not can_transition(current, target):
        raise IllegalTransition(f"label cannot go from {current} to {target}")
