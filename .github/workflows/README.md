# GitHub Actions Workflows

This directory is intentionally sparse.

## Lint / type-check

Canonical path is local: `make pre-commit` (runs `ruff` + `mypy` + `pytest`).
Ruff config lives in `pyproject.toml` under `[tool.ruff]`; mypy config under
`[tool.mypy]`. There is no CI lint workflow — ruff is the project's lint tool.

If you want CI to enforce ruff on push, groom a story with the PM; the
previously-present `pylint.yml` workflow was removed (US-186, 2026-04-18)
because its defaults checked `snake_case` while the project uses `camelCase`,
its Python matrix (3.8/3.9/3.10) predated the 3.11+ requirement, and it did
not install the project's actual dependencies — producing a failing email on
every push without adding coverage beyond what ruff already provides.
