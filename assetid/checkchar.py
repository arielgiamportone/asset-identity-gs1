"""Mod-43 check character, identical to the optional Code 39 check digit."""

from __future__ import annotations

from .errors import InvalidCharacter

__all__ = ["MOD43_ALPHABET", "compute_check_char", "verify_check_char"]

#: The 43 Code 39 symbols in value order (0..42).
MOD43_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%"

_VALUE_OF = {symbol: value for value, symbol in enumerate(MOD43_ALPHABET)}


def compute_check_char(body: str) -> str:
    """Return the mod-43 check character of ``body``.

    Every character of ``body`` must belong to :data:`MOD43_ALPHABET`; the
    check character is the symbol whose value equals the sum of the body values
    modulo 43. An empty body is allowed and yields ``"0"``.

    >>> compute_check_char("ABC-MOB0042")
    '3'
    """
    total = 0
    for char in body:
        try:
            total += _VALUE_OF[char]
        except KeyError:
            raise InvalidCharacter(
                f"character {char!r} is outside the mod-43 alphabet {MOD43_ALPHABET!r}"
            ) from None
    return MOD43_ALPHABET[total % 43]


def verify_check_char(body: str, check: str) -> bool:
    """Return whether ``check`` is the mod-43 check character of ``body``.

    Unlike :func:`compute_check_char`, a body with foreign characters simply
    fails verification instead of raising.
    """
    try:
        return compute_check_char(body) == check
    except InvalidCharacter:
        return False
