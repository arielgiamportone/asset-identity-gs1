"""Identity model: namespace, the four equivalent forms and pure conversions.

An asset identity is derived from ``(company prefix, block, serial)`` and the
human inventory number:

- **GIAI** ``company_prefix ‖ asset_reference`` (GS1 AI 8004);
- **alias** ``AID-<TENANT_CODE>-<NORMALISED_NUMBER>-<check>`` for barcodes and people;
- **EPC** GIAI-96 hex for UHF RFID chips;
- **GS1 Digital Link** ``https://<domain>/8004/<GIAI>`` for QR codes.

Alias and GIAI are *not* arithmetically related; the registry links them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from .checkchar import compute_check_char, verify_check_char
from .epc import decode_giai96, encode_giai96
from .errors import InvalidCharacter, NotGiai96, OutOfRange

__all__ = [
    "ALIAS_PREFIX",
    "ASSET_REFERENCE_DIGITS",
    "BLOCK_DIGITS",
    "GIAI_AI",
    "GIAI_MAX_LENGTH",
    "SERIAL_DIGITS",
    "AliasParts",
    "AssetIdentity",
    "CodeKind",
    "Namespace",
    "ParsedCode",
    "build_alias",
    "build_asset_reference",
    "build_giai",
    "build_gs1_link",
    "derive_identity",
    "giai_from_gs1_link",
    "normalize_inventory_number",
    "parse_alias",
    "parse_any",
    "split_asset_reference",
    "split_giai",
]

#: Fixed three-letter prefix of every alias produced by this library.
ALIAS_PREFIX = "AID"
#: GS1 Application Identifier of the GIAI.
GIAI_AI = "8004"
#: Maximum GIAI length (AI 8004 is up to 30 characters).
GIAI_MAX_LENGTH = 30
BLOCK_DIGITS = 4
SERIAL_DIGITS = 8
ASSET_REFERENCE_DIGITS = BLOCK_DIGITS + SERIAL_DIGITS
BLOCK_MAX = 10**BLOCK_DIGITS - 1
SERIAL_MAX = 10**SERIAL_DIGITS - 1
#: Smallest block whose padded form has no leading zero (strict TDS conformance).
STRICT_BLOCK_MIN = 10 ** (BLOCK_DIGITS - 1)

_TENANT_CODE_RE = re.compile(r"^[A-Z0-9]{1,8}$")
_DOMAIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?$")
_LINK_RE = re.compile(r"/" + GIAI_AI + r"/([^/?#]+)")


def _require_digits(value: str, what: str) -> None:
    if not value or not value.isascii() or not value.isdigit():
        raise InvalidCharacter(f"{what} must be ASCII digits, got {value!r}")


# --------------------------------------------------------------------------- #
# Namespace
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Namespace:
    """The per-tenant configuration assigned once by the namespace authority.

    ``strict=True`` additionally requires ``block >= 1000`` so that the asset
    reference never starts with a zero, which keeps the EPC decodable by
    strict third-party GIAI-96 decoders.
    """

    company_prefix: str
    block: int
    tenant_code: str
    resolver_domain: str
    scheme: str = "https"
    strict: bool = False

    def __post_init__(self) -> None:
        _require_digits(self.company_prefix, "company prefix")
        if not 6 <= len(self.company_prefix) <= 12:
            raise OutOfRange("company prefix must have 6 to 12 digits")
        if not isinstance(self.block, int) or not 0 <= self.block <= BLOCK_MAX:
            raise OutOfRange(f"block must be an integer 0..{BLOCK_MAX}, got {self.block!r}")
        if self.strict and self.block < STRICT_BLOCK_MIN:
            raise OutOfRange(f"strict namespaces need block >= {STRICT_BLOCK_MIN}")
        if not _TENANT_CODE_RE.match(self.tenant_code):
            raise InvalidCharacter(
                f"tenant code must be 1..8 characters A-Z0-9, got {self.tenant_code!r}"
            )
        if not _DOMAIN_RE.match(self.resolver_domain):
            raise InvalidCharacter(
                f"resolver domain must be a bare host, got {self.resolver_domain!r}"
            )
        if self.scheme not in ("https", "http"):
            raise InvalidCharacter(f"scheme must be https or http, got {self.scheme!r}")


# --------------------------------------------------------------------------- #
# Pure building blocks
# --------------------------------------------------------------------------- #


def normalize_inventory_number(text: str) -> str:
    """Upper-case ``text`` and keep only ASCII letters and digits.

    >>> normalize_inventory_number("MOB-0042"), normalize_inventory_number("r-7")
    ('MOB0042', 'R7')
    """
    normalized = "".join(c for c in text.upper() if c.isascii() and c.isalnum())
    if not normalized:
        raise InvalidCharacter(f"inventory number {text!r} has no alphanumeric characters")
    return normalized


def build_asset_reference(block: int, serial: int) -> str:
    """Return the 12-digit individual asset reference ``block(4) ‖ serial(8)``."""
    if not isinstance(block, int) or not 0 <= block <= BLOCK_MAX:
        raise OutOfRange(f"block must be 0..{BLOCK_MAX}, got {block!r}")
    if not isinstance(serial, int) or not 0 <= serial <= SERIAL_MAX:
        raise OutOfRange(f"serial must be 0..{SERIAL_MAX}, got {serial!r}")
    return f"{block:0{BLOCK_DIGITS}d}{serial:0{SERIAL_DIGITS}d}"


def split_asset_reference(reference: str) -> tuple[int, int]:
    """Inverse of :func:`build_asset_reference`."""
    _require_digits(reference, "asset reference")
    if len(reference) != ASSET_REFERENCE_DIGITS:
        raise OutOfRange(
            f"asset reference must have {ASSET_REFERENCE_DIGITS} digits, got {len(reference)}"
        )
    return int(reference[:BLOCK_DIGITS]), int(reference[BLOCK_DIGITS:])


def build_giai(company_prefix: str, asset_reference: str) -> str:
    """Return ``company_prefix ‖ asset_reference`` after validating both."""
    _require_digits(company_prefix, "company prefix")
    _require_digits(asset_reference, "asset reference")
    giai = company_prefix + asset_reference
    if len(giai) > GIAI_MAX_LENGTH:
        raise OutOfRange(f"GIAI has {len(giai)} characters; the maximum is {GIAI_MAX_LENGTH}")
    return giai


def split_giai(giai: str, company_prefix_length: int) -> tuple[str, str]:
    """Split a GIAI into ``(company_prefix, asset_reference)``.

    The company prefix length is configuration, not something the GIAI
    carries; the remaining digits must be the 12-digit asset reference.
    """
    _require_digits(giai, "GIAI")
    prefix, reference = giai[:company_prefix_length], giai[company_prefix_length:]
    if len(prefix) != company_prefix_length or len(reference) != ASSET_REFERENCE_DIGITS:
        raise OutOfRange(
            f"GIAI {giai!r} does not match a {company_prefix_length}-digit prefix "
            f"plus a {ASSET_REFERENCE_DIGITS}-digit reference"
        )
    return prefix, reference


def build_gs1_link(resolver_domain: str, giai: str, scheme: str = "https") -> str:
    """Return the GS1 Digital Link URI ``<scheme>://<domain>/8004/<giai>``."""
    domain = resolver_domain.strip().rstrip("/")
    if not _DOMAIN_RE.match(domain):
        raise InvalidCharacter(f"resolver domain must be a bare host, got {resolver_domain!r}")
    if scheme not in ("https", "http"):
        raise InvalidCharacter(f"scheme must be https or http, got {scheme!r}")
    _require_digits(giai, "GIAI")
    return f"{scheme}://{domain}/{GIAI_AI}/{giai}"


def giai_from_gs1_link(url: str) -> str:
    """Extract the GIAI from a Digital Link: what follows ``/8004/`` up to ``/`` or ``?``."""
    match = _LINK_RE.search(url)
    if not match:
        raise InvalidCharacter(f"no /{GIAI_AI}/ segment in {url!r}")
    giai = match.group(1)
    _require_digits(giai, "GIAI")
    return giai


def build_alias(tenant_code: str, inventory_number: str) -> str:
    """Return ``AID-<tenant_code>-<normalised number>-<mod-43 check>``."""
    if not _TENANT_CODE_RE.match(tenant_code):
        raise InvalidCharacter(f"tenant code must be 1..8 characters A-Z0-9, got {tenant_code!r}")
    body = f"{tenant_code}-{normalize_inventory_number(inventory_number)}"
    return f"{ALIAS_PREFIX}-{body}-{compute_check_char(body)}"


@dataclass(frozen=True, slots=True)
class AliasParts:
    """Result of :func:`parse_alias`; ``check_ok`` is recomputed, never trusted."""

    tenant_code: str
    inventory_number: str
    check: str
    check_ok: bool

    @property
    def body(self) -> str:
        return f"{self.tenant_code}-{self.inventory_number}"


def parse_alias(text: str) -> AliasParts:
    """Parse an alias produced by :func:`build_alias`.

    The prefix is mandatory (``InvalidCharacter`` otherwise). The *last* hyphen
    separates the check character and the *first* hyphen of the remainder
    separates tenant code and inventory number. A wrong check character does
    not raise; it is reported through ``check_ok``.
    """
    value = text.strip()
    head = ALIAS_PREFIX + "-"
    if not value.startswith(head):
        raise InvalidCharacter(f"alias must start with {head!r}, got {text!r}")
    rest = value[len(head) :]
    body, sep, check = rest.rpartition("-")
    if not sep or not body:
        raise InvalidCharacter(f"alias {text!r} has no check character")
    tenant_code, sep, number = body.partition("-")
    if not sep or not tenant_code or not number:
        raise InvalidCharacter(f"alias {text!r} has no tenant code / number split")
    return AliasParts(
        tenant_code=tenant_code,
        inventory_number=number,
        check=check,
        check_ok=len(check) == 1 and verify_check_char(body, check),
    )


# --------------------------------------------------------------------------- #
# Derived identity
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    """The four equivalent forms of one asset plus the numbers they derive from."""

    block: int
    serial: int
    asset_reference: str
    inventory_number: str
    giai: str
    alias: str
    epc: str
    gs1_link: str


def derive_identity(namespace: Namespace, serial: int, inventory_number: str) -> AssetIdentity:
    """Derive the four forms from a namespace, a serial and an inventory number."""
    reference = build_asset_reference(namespace.block, serial)
    giai = build_giai(namespace.company_prefix, reference)
    return AssetIdentity(
        block=namespace.block,
        serial=serial,
        asset_reference=reference,
        inventory_number=inventory_number,
        giai=giai,
        alias=build_alias(namespace.tenant_code, inventory_number),
        epc=encode_giai96(namespace.company_prefix, reference),
        gs1_link=build_gs1_link(namespace.resolver_domain, giai, namespace.scheme),
    )


# --------------------------------------------------------------------------- #
# Recognising any scanned code
# --------------------------------------------------------------------------- #


class CodeKind(StrEnum):
    ALIAS = "ALIAS"
    GIAI = "GIAI"
    EPC = "EPC"
    GS1_LINK = "GS1_LINK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ParsedCode:
    """What a scanned string looks like and its normalised payload.

    For ``GS1_LINK`` the payload is the extracted GIAI; for ``EPC`` the upper-
    case hex; for ``ALIAS`` the trimmed alias; for ``UNKNOWN`` the input itself.
    """

    kind: CodeKind
    payload: str
    text: str


def parse_any(text: str) -> ParsedCode:
    """Classify a scanned value as alias, GIAI, GIAI-96 EPC or Digital Link.

    A 24-character all-digit string starting with ``34`` is ambiguous between
    a GIAI and an EPC; it is reported as ``EPC`` (the registry tries both).
    Anything unrecognised yields ``UNKNOWN`` rather than an exception, because
    an unreadable scan is a field finding, not an ingestion error.
    """
    value = (text or "").strip()
    if not value:
        return ParsedCode(CodeKind.UNKNOWN, "", value)
    if value.upper().startswith(ALIAS_PREFIX + "-"):
        return ParsedCode(CodeKind.ALIAS, value.upper(), value)
    lowered = value.lower()
    if lowered.startswith(("http://", "https://")):
        parts = urlsplit(value)
        try:
            giai = giai_from_gs1_link(parts.path)
        except InvalidCharacter:
            return ParsedCode(CodeKind.UNKNOWN, value, value)
        return ParsedCode(CodeKind.GS1_LINK, giai, value)
    if len(value) == 24:
        try:
            decode_giai96(value)
        except NotGiai96:
            pass
        else:
            return ParsedCode(CodeKind.EPC, value.upper(), value)
    if value.isascii() and value.isdigit() and 6 < len(value) <= GIAI_MAX_LENGTH:
        return ParsedCode(CodeKind.GIAI, value, value)
    return ParsedCode(CodeKind.UNKNOWN, value, value)
