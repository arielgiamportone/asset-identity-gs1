"""Exception hierarchy of the library."""

from __future__ import annotations

__all__ = [
    "AssetIdError",
    "IllegalTransition",
    "InvalidCharacter",
    "NamespaceCollision",
    "NamespaceIncomplete",
    "NotGiai96",
    "OutOfRange",
]


class AssetIdError(Exception):
    """Base class for every error raised by :mod:`assetid`."""


class InvalidCharacter(AssetIdError, ValueError):
    """A string contains a character outside the allowed alphabet or shape."""


class OutOfRange(AssetIdError, ValueError):
    """A numeric component is outside the range the identifier can encode."""


class NotGiai96(AssetIdError, ValueError):
    """A string is not a GIAI-96 EPC (wrong length, header or partition)."""


class NamespaceCollision(AssetIdError):
    """Another tenant already owns the block (or tenant code) being assigned."""


class NamespaceIncomplete(AssetIdError):
    """The tenant has no complete namespace, so identities cannot be issued."""


class IllegalTransition(AssetIdError):
    """A label state change is not allowed by the lifecycle table."""
