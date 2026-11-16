"""Anti-leak guard: no forbidden term may appear in the tree or the git history.

This repository is a clean-room reimplementation. The specification it was built
from carries a list of terms (client names, internal identifiers, fixtures,
paths) that must never surface in the public repository. That list is itself
sensitive, so it is stored here obfuscated (base64 of a JSON array) and this
file is excluded from the scan. On failure the offending term and location are
reported so the author can fix the file *and* rewrite the commit.

Each entry is [term, flags] where flags may contain:

- c: match case-sensitively (default is case-insensitive);
- o: open end, i.e. no word boundary required after the term.

Word boundaries are alphanumeric only, so foo_term is still a hit for
term (underscores do not hide an identifier), while xterm is not.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

_SEALED_TERMS = (
    "W1siSW50ZXJ2YWxvciIsICIiXSwgWyJJbnRlcnZhbG9yIENvbnN1bHRpbmcgR3JvdXAiLCAiIl0sIFsiaW50"
    "ZXJ2YWxvci5lcyIsICIiXSwgWyJpbnRlcnZhbG9yc29mdCIsICIiXSwgWyJBWVVOREFUQSIsICIiXSwgWyJJ"
    "TlZBWVVOVCIsICIiXSwgWyJJTlRFUkRBVEEiLCAiIl0sIFsiQXNzZXREYXRhIiwgIiJdLCBbIkFzc2V0Vmlz"
    "aW9uIiwgIiJdLCBbIkludkRhdGEiLCAiIl0sIFsiS0FUSEFSU0lEIiwgIiJdLCBbIkRhdGFTdGFyIiwgIiJd"
    "LCBbImdldHBsdWdnZWQiLCAiIl0sIFsiTWVnYXNpc3RlbWFzIiwgIiJdLCBbIk1hbnNpcyIsICIiXSwgWyJB"
    "RU5BIiwgIiJdLCBbIkVVSVBPIiwgIiJdLCBbIkJhcmFqYXMiLCAiIl0sIFsiTUFEIDY5LzIzIiwgIiJdLCBb"
    "Ik1BRC0xMTIiLCAiIl0sIFsiU2FuIEJhcnRvbG9tw6kiLCAiIl0sIFsiVGlyYWphbmEiLCAiIl0sIFsiRmly"
    "Z2FzIiwgIiJdLCBbIlphbXVkaW8iLCAiIl0sIFsiU2FndW50byIsICIiXSwgWyJPbGFiZXJyaWEiLCAiIl0s"
    "IFsiQnJ1Z2Fyb2xhcyIsICIiXSwgWyJBaXphcm5hemFiYWwiLCAiIl0sIFsiTWV0cm8gZGUgTWFkcmlkIiwg"
    "IiJdLCBbIkRpcHV0YWNpw7NuIGRlIFNvcmlhIiwgIiJdLCBbIkFnw6huY2lhIGRlIFJlc2lkdXMiLCAiIl0s"
    "IFsiQXJpZWwgR2lhbXBvcnRlIiwgIiJdLCBbIkM6XFxVc2VycyIsICIiXSwgWyJPbmVEcml2ZSAtIEludGVy"
    "dmFsb3IiLCAiIl0sIFsiQVlVTkRBVEEgVGFnIiwgIiJdLCBbInZlcmlmaWNhLmludGVydmFsb3JkYXRhLmNv"
    "bSIsICIiXSwgWyJpbnRlcnZhbG9yZGF0YS5jb20iLCAiIl0sIFsic2FuX2JhcnRvbG9tZSIsICIiXSwgWyJz"
    "YW5fYmFydG9sb21lX3RpcmFqYW5hIiwgIiJdLCBbInNhbl9iYXJ0b2xvbWVfZGVfdGlyYWphbmEiLCAiIl0s"
    "IFsiZmlyZ2FzIiwgIiJdLCBbInNidCIsICIiXSwgWyJTYW4gQmFydG9sb23DqSBkZSBUaXJhamFuYSIsICIi"
    "XSwgWyJTYW4gQWd1c3TDrW4gZGUgR3VhZGFsaXgiLCAiIl0sIFsiR3JhbiBDYW5hcmlhIiwgIiJdLCBbIkJp"
    "emthaWEiLCAiIl0sIFsiQ2HDsWFkYSBkZWwgUsOtbyIsICIiXSwgWyJDYXNhIENvbnNpc3RvcmlhbCIsICIi"
    "XSwgWyJTYWRkbGUgUG90IElWIiwgIiJdLCBbInBsaWVnbyAxNi8yMDI1IiwgIiJdLCBbImNvbnRyYXRvIDE2"
    "LzIwMjUiLCAiIl0sIFsiY2zDoXVzdWxhcyBPY3RhdmEiLCAiIl0sIFsiY2zDoXVzdWxhIE5vdmVuYSIsICIi"
    "XSwgWyJjbMOhdXN1bGEgRMOpY2ltYSIsICIiXSwgWyJPY3RhdmEvTm92ZW5hL0TDqWNpbWEiLCAiIl0sIFsi"
    "QXJpZWwiLCAiIl0sIFsiR2lhbXBvcnRvbmUiLCAiIl0sIFsiR2lhbXBvcnRlIiwgIiJdLCBbIk51cmlhIiwg"
    "IiJdLCBbIsOTbGl2ZXIiLCAiIl0sIFsiUmHDumwiLCAiIl0sIFsiQ0VSLTAwMDIiLCAiIl0sIFsiQ0VSMDAw"
    "MiIsICIiXSwgWyJSLTA0MTkiLCAiIl0sIFsiTS0wMDA3IiwgIiJdLCBbIldPLTE2NjI5IiwgIiJdLCBbIlZF"
    "UklGX0lOViIsICIiXSwgWyJWRVJJRl9JTlZfQ0FNUE8iLCAiIl0sIFsiQUxUQV9NVUVCTEUiLCAiIl0sIFsi"
    "ZXRpcXVldGFfZXNjYW5lYWRhIiwgIiJdLCBbImNvZGlnb19lc2NhbmVhZG8iLCAiIl0sIFsibnVtX3Jlc2Vy"
    "dmFkbyIsICIiXSwgWyJSRVNFUlZBOiIsICIiXSwgWyJleGVjdXRvcklkIiwgIiJdLCBbIm9mZmljZUlkIiwg"
    "IiJdLCBbImlkZW50aWRhZC5weSIsICIiXSwgWyJyZWdpc3Ryby5weSIsICIiXSwgWyJyZW5kZXIucHkiLCAi"
    "Il0sIFsicmZpZC5weSIsICIiXSwgWyJldGlxdWV0YXNfZW1pdGlkYXMiLCAiIl0sIFsiY29uZmlndXJhY2lv"
    "bl9ldGlxdWV0YXMiLCAiIl0sIFsiYmllbmVzX2lubXVlYmxlcyIsICIiXSwgWyJtdW5pY2lwaW9faWQiLCAi"
    "Il0sIFsiYmllbl9pZCIsICIiXSwgWyJudW1faW52ZW50YXJpbyIsICIiXSwgWyJ0ZW5hbnRfYmxvY2siLCAi"
    "Il0sIFsidGVuYW50X2FsaWFzIiwgIiJdLCBbImRvbWluaW9fdmVyaWZpY2FjaW9uIiwgIiJdLCBbImVwY19n"
    "aWFpOTYiLCAiIl0sIFsiZGlnaXRhbF9saW5rIiwgIiJdLCBbImVtaXRpcl9ldGlxdWV0YSIsICIiXSwgWyJy"
    "ZXNvbHZlcl9wb3JfY29kaWdvX2VzY2FuZWFkbyIsICIiXSwgWyJtYXJjYXJfY29sb2NhZGFfZGVzZGVfY2Ft"
    "cG8iLCAiIl0sIFsicmVzZXJ2YXJfZXRpcXVldGFzX211ZWJsZSIsICIiXSwgWyJ2aW5jdWxhcl9yZXNlcnZh"
    "X2FfYmllbiIsICIiXSwgWyJidWlsZF96cGxfcmZpZCIsICIiXSwgWyJQUkVTRVRTX0E0IiwgIiJdLCBbImE0"
    "XzIxIiwgIiJdLCBbImE0XzY1IiwgIiJdLCBbImE0XzE0IiwgIiJdLCBbIk1PRFVMT19FVElRVUVUQVMiLCAi"
    "Il0sIFsiSURFTlRJRklDQUNJT05fQUNUSVZPUyIsICIiXSwgWyJDT05UUk9MX0ZJU0lDTyIsICIiXSwgWyIv"
    "YmFja29mZmljZSIsICIiXSwgWyJDOlxcVXNlcnNcXEFyaWVsIEdpYW1wb3J0ZSIsICIiXSwgWyJEZXNrdG9w"
    "XFxQTFVHIiwgIiJdLCBbIkM6XFxBWVVOREFUQSIsICIiXSwgWyJJTlRFUlZBTCIsICJjIl0sIFsiUExVRyIs"
    "ICJjIl0sIFsiUFBUIiwgImMiXSwgWyJVVEUiLCAiYyJdLCBbIk9EVCIsICJjIl0sIFsiVUREIiwgImMiXSwg"
    "WyJBWVQiLCAiYyJdLCBbIkZJUiIsICJjIl0sIFsiWk1EIiwgImMiXSwgWyJPVDEiLCAiYyJdLCBbIkV2YSIs"
    "ICJjIl0sIFsiTHVpcyIsICJjIl0sIFsiQW5ueSIsICJjIl0sIFsiVmljdG9yaWEiLCAiYyJdLCBbIk1vZGVs"
    "byBBIiwgImMiXSwgWyJEZXBsb3kgQSIsICJjIl0sIFsiRkFTRSA4IiwgImNvIl0sIFsiRkFTRSA5IiwgImNv"
    "Il1d"
)

# Phrases that legitimately contain a listed term (the fixed attribution line).
_SEALED_EXEMPTIONS = "WyJ0cmFiYWpvIGVuIEludGVydmFsb3IgRGF0YSIsICJ3b3JrIGF0IEludGVydmFsb3IgRGF0YSJd"


def _unseal(blob: str) -> list:
    return json.loads(base64.b64decode(blob).decode("utf-8"))


def _compile(term: str, flags: str) -> re.Pattern[str]:
    pattern = re.escape(term)
    if term[0].isalnum():
        pattern = r"(?<![A-Za-z0-9])" + pattern
    if term[-1].isalnum() and "o" not in flags:
        pattern = pattern + r"(?![A-Za-z0-9])"
    re_flags = 0 if "c" in flags else re.IGNORECASE
    return re.compile(pattern, re_flags)


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (term, _compile(term, flags)) for term, flags in _unseal(_SEALED_TERMS)
]
EXEMPTIONS: list[re.Pattern[str]] = [
    re.compile(re.escape(phrase)) for phrase in _unseal(_SEALED_EXEMPTIONS)
]


def _strip_exemptions(text: str) -> str:
    for pattern in EXEMPTIONS:
        text = pattern.sub(" ", text)
    return text


def _find_hits(text: str) -> list[tuple[str, int]]:
    """Return (term, line_number) for every forbidden term found in text."""
    text = _strip_exemptions(text)
    hits: list[tuple[str, int]] = []
    for term, pattern in PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append((term, text.count("\n", 0, match.start()) + 1))
    return hits


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def _tracked_and_untracked_files() -> list[Path]:
    listing = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return [ROOT / name for name in listing.split("\0") if name]


def _is_git_repo() -> bool:
    try:
        return _git("rev-parse", "--is-inside-work-tree").strip() == "true"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def test_terms_list_is_well_formed() -> None:
    assert len(PATTERNS) > 50
    assert all(term for term, _ in PATTERNS)


def test_matcher_respects_boundaries() -> None:
    probe = _compile("alpha", "")
    assert probe.search("x alpha y")
    assert probe.search("x_alpha_y")
    assert not probe.search("xalpha")
    assert not probe.search("alphas")
    assert _compile("Alpha", "c").search("Alpha") and not _compile("Alpha", "c").search("alpha")
    assert _compile("v 8", "o").search("v 8x")


@pytest.mark.skipif(not _is_git_repo(), reason="requires a git checkout")
def test_working_tree_has_no_forbidden_terms() -> None:
    offenders: list[str] = []
    for path in _tracked_and_untracked_files():
        if path == SELF or not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        for term, _ in _find_hits(relative):
            offenders.append(f"{relative} (file name): {term!r}")
        for term, line in _find_hits(_read_text(path)):
            offenders.append(f"{relative}:{line}: {term!r}")
    assert not offenders, "Forbidden terms found:\n" + "\n".join(offenders)


@pytest.mark.skipif(not _is_git_repo(), reason="requires a git checkout")
def test_history_has_no_forbidden_terms() -> None:
    # Commit messages and full patches; author/committer headers are excluded on
    # purpose (the repository owner's account name is not a leak).
    log = _git("log", "-p", "--format=%n--- commit %H%n%B", "--no-color", "--all")
    offenders = [f"history line {line}: {term!r}" for term, line in _find_hits(log)]
    assert not offenders, "Forbidden terms found in git history:\n" + "\n".join(offenders)
