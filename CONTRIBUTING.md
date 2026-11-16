# Contributing

Thanks for your interest. This repository is a clean-room case study, so a few
ground rules apply on top of the usual ones.

## Ground rules

- **Synthetic data only.** Tests and examples must use the generators in
  `assetid/synthetic.py` (or data built inline). Never commit real inventories,
  real GS1 company prefixes, logos or exports, even "anonymised" ones.
- **No secrets, no internal paths.** CI runs `gitleaks`; anything that looks like a
  token, a corporate e-mail or a local filesystem path will be rejected.
- **Standards first.** When behaviour is not obvious, follow the public standard
  (GS1 General Specifications, EPC Tag Data Standard, GS1 Digital Link, ZPL) and
  note the decision in `docs/DECISIONES.md`.
- **English identifiers.** Code, identifiers and docstrings are in English.
  User-facing docs are bilingual (`README.md` / `README.es.md`).

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

`tests/test_no_leaks.py` scans the working tree **and** the git history for a
list of forbidden terms. If it fails, remove the term from the file *and* rewrite
the offending commit before pushing.

## Pull requests

1. One topic per PR, with tests for every behavioural change.
2. Keep public functions typed and documented.
3. Add an entry under *Unreleased* in `CHANGELOG.md`.
4. CI must be green on Python 3.11 and 3.12.
