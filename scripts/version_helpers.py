################################################################################
# File Name: version_helpers.py
# Purpose/Description: US-241 deploy versioning + release record helpers.
#                      Single source of truth for the SemVer-shaped V<M>.<m>.<p>
#                      version string and the {version, releasedAt, gitHash,
#                      description} release record shape that deploy-pi.sh and
#                      deploy-server.sh write to .deploy-version on each tier.
#                      Doubles as a CLI (compose-record subcommand) so the
#                      bash deploy scripts can shell out to one place rather
#                      than duplicating JSON-composition logic in heredocs.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation (Sprint 19 US-241)
# ================================================================================
################################################################################

"""Release versioning + deploy record helpers (US-241, B-047 US-A).

Public API:
    parseVersion(s) -> (major, minor, patch)
    bumpVersion(version, kind) -> str
    validateRelease(record) -> bool
    readDeployVersion(path) -> dict | None
    composeReleaseRecord(versionFile, gitHash, releasedAt=None) -> dict

CLI:
    python scripts/version_helpers.py compose-record \\
        --version-file deploy/RELEASE_VERSION \\
        --git-hash <short-hash> \\
        [--released-at <ISO-8601-Z>]

Versioning scheme (CIO directive 2026-04-29): SemVer-shaped V<major>.<minor>.<patch>.
Starting version is V0.18.0 (post-Sprint-18, pre-stable). PM bumps the version
in deploy/RELEASE_VERSION at sprint close; the deploy scripts NEVER bump it
themselves -- they only read + stamp the current value into .deploy-version on
each tier with a fresh UTC timestamp + git-hash.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "parseVersion",
    "bumpVersion",
    "validateRelease",
    "readDeployVersion",
    "composeReleaseRecord",
    "DESCRIPTION_MAX_LEN",
    "RELEASE_RECORD_KEYS",
]

DESCRIPTION_MAX_LEN = 400
RELEASE_RECORD_KEYS = ("version", "releasedAt", "gitHash", "description")

_VERSION_RE = re.compile(r"^V(\d+)\.(\d+)\.(\d+)$")
_RELEASED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ---- Parsing + bumping ---------------------------------------------------

def parseVersion(s: str) -> tuple[int, int, int]:
    """Parse a V<major>.<minor>.<patch> string into a numeric triple.

    Args:
        s: Version string. Must start with capital V (e.g., 'V0.18.0').

    Returns:
        (major, minor, patch) integers.

    Raises:
        ValueError: If the string is not the canonical SemVer-shaped form.
    """
    if not isinstance(s, str):
        raise ValueError(f"version must be a string, got {type(s).__name__}")
    if s.startswith("v") and not s.startswith("V"):
        raise ValueError(f"version must start with capital V, got {s!r}")
    match = _VERSION_RE.match(s)
    if not match:
        raise ValueError(
            f"invalid version {s!r}; expected V<major>.<minor>.<patch> with "
            f"non-negative integers (e.g., V0.18.0)"
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def bumpVersion(version: str, kind: str) -> str:
    """Bump a version string by one increment.

    Args:
        version: Current version string (e.g., 'V0.18.0').
        kind: One of 'major', 'minor', 'patch'.
            - major: increments major, resets minor + patch to 0.
            - minor: increments minor, resets patch to 0.
            - patch: increments patch.

    Returns:
        Bumped version string (e.g., 'V0.19.0').

    Raises:
        ValueError: If version is invalid or kind is unknown.
    """
    major, minor, patch = parseVersion(version)
    if kind == "major":
        return f"V{major + 1}.0.0"
    if kind == "minor":
        return f"V{major}.{minor + 1}.0"
    if kind == "patch":
        return f"V{major}.{minor}.{patch + 1}"
    raise ValueError(
        f"unknown bump kind {kind!r}; expected one of 'major', 'minor', 'patch'"
    )


# ---- Release record validation ------------------------------------------

def validateRelease(record: Any) -> bool:
    """Validate a release record's shape.

    Required keys: version, releasedAt, gitHash, description.
        - version: V<M>.<m>.<p> string (parseVersion-compatible).
        - releasedAt: UTC ISO-8601 with 'T' separator + 'Z' suffix
          (e.g., '2026-04-30T14:32:00Z').
        - gitHash: non-empty string.
        - description: string with len <= DESCRIPTION_MAX_LEN (400).

    Args:
        record: Candidate record (anything; must be dict-like).

    Returns:
        True iff every key is present + every value matches the rules above.
    """
    if not isinstance(record, dict):
        return False
    for key in RELEASE_RECORD_KEYS:
        if key not in record:
            return False

    version = record["version"]
    if not isinstance(version, str):
        return False
    try:
        parseVersion(version)
    except ValueError:
        return False

    releasedAt = record["releasedAt"]
    if not isinstance(releasedAt, str) or not _RELEASED_AT_RE.match(releasedAt):
        return False

    gitHash = record["gitHash"]
    if not isinstance(gitHash, str) or not gitHash:
        return False

    description = record["description"]
    if not isinstance(description, str) or len(description) > DESCRIPTION_MAX_LEN:
        return False

    return True


# ---- File IO + composition -----------------------------------------------

def readDeployVersion(path: str | Path) -> dict | None:
    """Read a tier's .deploy-version file.

    Args:
        path: Path to the .deploy-version file.

    Returns:
        Parsed record if the file exists, parses as JSON, AND passes
        validateRelease. Returns None otherwise (missing file, malformed JSON,
        invalid shape) -- B-047 US-B/C consume this and need to fall back
        gracefully when no valid record is present.
    """
    p = Path(path)
    if not p.is_file():
        return None
    try:
        record = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not validateRelease(record):
        return None
    return record


def composeReleaseRecord(
    versionFile: str | Path,
    gitHash: str,
    releasedAt: str | None = None,
) -> dict:
    """Compose a release record for a deploy run.

    Args:
        versionFile: Path to deploy/RELEASE_VERSION (JSON with {version, description}).
        gitHash: short git hash for the deployed tree (caller runs
            `git rev-parse --short HEAD`).
        releasedAt: Optional UTC ISO-8601-Z timestamp. If None, uses now (UTC).

    Returns:
        Validated record {version, releasedAt, gitHash, description}.

    Raises:
        FileNotFoundError: versionFile does not exist.
        ValueError: versionFile has bad shape, version invalid, or description too long.
    """
    p = Path(versionFile)
    if not p.is_file():
        raise FileNotFoundError(f"version file not found: {p}")
    data = json.loads(p.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{p}: top-level must be a JSON object")
    if "version" not in data or "description" not in data:
        raise ValueError(
            f"{p}: must contain 'version' and 'description' keys; got {list(data)}"
        )
    version = data["version"]
    parseVersion(version)  # Raises ValueError if invalid.

    description = data["description"]
    if not isinstance(description, str):
        raise ValueError(f"{p}: description must be a string")
    if len(description) > DESCRIPTION_MAX_LEN:
        raise ValueError(
            f"{p}: description exceeds {DESCRIPTION_MAX_LEN} chars "
            f"(got {len(description)})"
        )

    if releasedAt is None:
        releasedAt = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "version": version,
        "releasedAt": releasedAt,
        "gitHash": gitHash,
        "description": description,
    }
    if not validateRelease(record):
        raise ValueError(f"composed record failed validation: {record}")
    return record


# ---- CLI -----------------------------------------------------------------

def _resolveGitHashFallback() -> str:
    """Best-effort short-hash for the local repo; returns 'unknown' on failure.

    Used only by the CLI when --git-hash is omitted (defensive for callers
    who forget the flag); production deploy scripts always pass --git-hash
    explicitly.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _runComposeRecord(args: argparse.Namespace) -> int:
    record = composeReleaseRecord(
        args.version_file,
        gitHash=args.git_hash or _resolveGitHashFallback(),
        releasedAt=args.released_at,
    )
    print(json.dumps(record))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="US-241 release-versioning helpers (CLI for deploy scripts)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    compose = sub.add_parser(
        "compose-record",
        help="Compose a {version, releasedAt, gitHash, description} JSON record.",
    )
    compose.add_argument("--version-file", required=True, help="Path to deploy/RELEASE_VERSION")
    compose.add_argument("--git-hash", default="", help="Short git hash; falls back to local repo")
    compose.add_argument("--released-at", default=None, help="UTC ISO-8601-Z; default now")

    args = parser.parse_args(argv)
    if args.cmd == "compose-record":
        return _runComposeRecord(args)
    parser.error(f"unknown subcommand: {args.cmd}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
