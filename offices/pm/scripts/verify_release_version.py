#!/usr/bin/env python3
"""
verify_release_version.py -- Sprint-close Phase 6 validator.

Validates deploy/RELEASE_VERSION against the field-cap constraints the
deploy pipeline enforces. Prevents mid-deploy halts from oversize
fields (TD-040 description-cap pattern + TD-048-class theme-cap pattern;
both have caused mid-deploy halts in prior sprint closes).

Caps validated:
  version: matches r'^V\\d+\\.\\d+\\.\\d+$' (SemVer per feedback_pm_semver_convention.md)
  theme: <= 50 chars
  description: <= 400 chars

Usage:
  python offices/pm/scripts/verify_release_version.py             # default deploy/RELEASE_VERSION
  python offices/pm/scripts/verify_release_version.py --path <override>

Exit code: 0 on all checks pass; 1 on cap violation (caller should fix
file before deploy); 2 on file/parse error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RELEASE_PATH = REPO_ROOT / "deploy" / "RELEASE_VERSION"

VERSION_PATTERN = re.compile(r"^V\d+\.\d+\.\d+$")
THEME_CAP = 50
DESCRIPTION_CAP = 400


def verifyReleaseVersion(path: Path) -> list[str]:
    """Return list of error strings; empty list = all checks pass."""
    if not path.exists():
        return [f"file not found: {path}"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    errors: list[str] = []

    version = data.get("version", "")
    if not VERSION_PATTERN.match(version):
        errors.append(f"version {version!r} does not match SemVer pattern V<major>.<minor>.<patch>")

    theme = data.get("theme", "")
    if len(theme) > THEME_CAP:
        errors.append(f"theme exceeds {THEME_CAP} chars (got {len(theme)}): {theme!r}")

    description = data.get("description", "")
    if len(description) > DESCRIPTION_CAP:
        errors.append(f"description exceeds {DESCRIPTION_CAP} chars (got {len(description)})")

    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--path", default=str(DEFAULT_RELEASE_PATH), help="RELEASE_VERSION path override")
    args = parser.parse_args(argv)

    errors = verifyReleaseVersion(Path(args.path))

    if errors:
        print(f"FAIL ({len(errors)} error(s)):", file=sys.stderr)
        for err in errors:
            print(f"  ERROR: {err}", file=sys.stderr)
        if errors[0].startswith("file not found") or errors[0].startswith("invalid JSON"):
            return 2
        return 1

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    print(f"OK {data['version']}")
    print(f"  theme:       {len(data['theme'])} / {THEME_CAP} chars")
    print(f"  description: {len(data['description'])} / {DESCRIPTION_CAP} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
