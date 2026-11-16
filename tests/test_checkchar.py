"""Spec cases 2 and 4 (check character side)."""

from __future__ import annotations

import pytest

from assetid import InvalidCharacter, compute_check_char
from assetid.checkchar import MOD43_ALPHABET, verify_check_char


def test_alphabet_has_43_symbols_in_code39_order() -> None:
    assert len(MOD43_ALPHABET) == 43
    assert MOD43_ALPHABET.startswith("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    assert MOD43_ALPHABET.endswith("-. $/+%")


def test_spec_worked_example() -> None:
    # 10+11+12+36+22+24+11+0+0+4+2 = 132 ; 132 mod 43 = 3
    assert compute_check_char("ABC-MOB0042") == "3"


@pytest.mark.parametrize("body", ["ABC-MOB0042", "NOR-EQP0001", "", "-. $/+%", "Z" * 50])
def test_check_char_is_deterministic_and_in_alphabet(body: str) -> None:
    first = compute_check_char(body)
    assert first == compute_check_char(body)
    assert len(first) == 1 and first in MOD43_ALPHABET


def test_check_char_matches_brute_force() -> None:
    body = "NOR-ART0007"
    total = sum(MOD43_ALPHABET.index(c) for c in body)
    assert compute_check_char(body) == MOD43_ALPHABET[total % 43]


@pytest.mark.parametrize("body", ["café", "abc", "ABC_1", "ABC*1"])
def test_foreign_character_raises(body: str) -> None:
    with pytest.raises(InvalidCharacter):
        compute_check_char(body)


def test_verify_never_raises() -> None:
    assert verify_check_char("ABC-MOB0042", "3")
    assert not verify_check_char("ABC-MOB0042", "4")
    assert not verify_check_char("café", "0")
