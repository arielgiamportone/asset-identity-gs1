"""The lifecycle table itself."""

from __future__ import annotations

import pytest

from assetid import IllegalTransition
from assetid.lifecycle import ALLOWED_TRANSITIONS, LabelState, can_transition, check_transition

S = LabelState


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (S.ISSUED, S.PRINTED, True),
        (S.ISSUED, S.PLACED, False),
        (S.ISSUED, S.RETIRED, True),
        (S.PRINTED, S.PRINTED, True),
        (S.PRINTED, S.PLACED, True),
        (S.PRINTED, S.RETIRED, True),
        (S.PLACED, S.PRINTED, True),
        (S.PLACED, S.PLACED, True),
        (S.PLACED, S.RETIRED, True),
        (S.RETIRED, S.PRINTED, False),
        (S.RETIRED, S.PLACED, False),
        (S.RETIRED, S.RETIRED, True),
        (S.PRINTED, S.ISSUED, False),
    ],
)
def test_transition_table(current: S, target: S, allowed: bool) -> None:
    assert can_transition(current, target) is allowed
    if allowed:
        check_transition(current, target)
    else:
        with pytest.raises(IllegalTransition):
            check_transition(current, target)


def test_every_state_has_a_row() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(LabelState)
