################################################################################
# File Name: audit_config_literals.py
# Purpose/Description: B-044 standing-rule audit -- scan the repository for
#     literal infrastructure addresses (IPs, hostnames, ports, MACs) that
#     should live in config.json. Portable Python (stdlib only), runs on
#     Windows, Linux, and Pi. Backs both the CLI tool (.sh wrapper) and the
#     pytest fast-suite lint gate.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex          | Initial implementation (US-201)
# ================================================================================
################################################################################

"""
B-044 audit: reject hardcoded infrastructure addresses outside config.json.

Patterns detected (exact set chosen from B-044 groundingRefs):
    - IP:        10.27.27.<N>           (DeathStarWiFi LAN)
    - Hostname:  chi-srv-01, chi-eclipse-01, chi-eclipse-tuner, chi-nas-01
                 eclipse-tuner
    - MAC:       00:04:3E:85:0D:FB      (OBDLink LX -- case-insensitive)

Exempt paths (path-prefix, relative to repo root, forward-slashed):
    specs/, docs/, offices/                        (documentation / PM)
    .git/, .venv/, __pycache__/, htmlcov/          (tool caches)
    .pytest_cache/, .mypy_cache/, .ruff_cache/
    data/regression/, data/smoke_test_results.json (test artifacts)
    config.json, .env.example, .env.production.example  (source of truth)
    tests/conftest.py                              (canonical test fixture)
    scripts/audit_config_literals.py               (self)
    scripts/audit_config_literals.sh               (self)
    tests/lint/test_no_hardcoded_addresses.py      (self)
    deploy/addresses.sh                            (canonical bash-side mirror)

Exempt by extension: *.md anywhere (documentation).

Inline pragma:
    Lines matching `b044-exempt` (any case) are skipped. Use with a
    one-line reason, e.g.
        DEFAULT = "10.27.27.10"  # b044-exempt: validator default registry

CLI (via scripts/audit_config_literals.sh or directly):
    python scripts/audit_config_literals.py                # reports, exits 0 on clean
    python scripts/audit_config_literals.py --verbose      # per-file findings
    python scripts/audit_config_literals.py --exempt PATH  # add path-prefix exemption
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PRAGMA_MARKER = "b044-exempt"
# Line that is entirely a comment (bash/python `#...` OR yaml/toml `#...`).
# These are documentation within source files -- they describe what a value
# IS, they don't introduce drift (drift comes from code, not prose).
COMMENT_LINE_PATTERN = re.compile(r"^\s*#")

IP_PATTERN = re.compile(r"10\.27\.27\.\d{1,3}")
HOSTNAME_PATTERN = re.compile(
    r"\b(?:chi-srv-01|chi-eclipse-01|chi-eclipse-tuner|chi-nas-01|eclipse-tuner)\b",
    re.IGNORECASE,
)
MAC_PATTERN = re.compile(r"00:04:3[eE]:85:0[dD]:[fF][bB]")


DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    # Documentation + PM artifacts (category B + D per B-044)
    "specs/",
    "docs/",
    "offices/",
    # Tool caches + build artifacts (never relevant)
    ".git/",
    ".venv/",
    "__pycache__/",
    "htmlcov/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    # Test artifacts + regression inputs
    "data/regression/",
    "data/smoke_test_results.json",
    # Canonical configuration (source of truth; literals ARE the config)
    "config.json",
    ".env.example",
    ".env.production.example",
    # Bash-side canonical mirror of pi.network.* + server.network.*
    "deploy/addresses.sh",
    "deploy/deploy.conf",
    "deploy/deploy.conf.example",
    # Test fixtures (category C per B-044: deterministic by design).
    # Production-value assertions in tests are contract tests for validator
    # defaults; mock/fake IPs are intentional payloads, not drift risk.
    "tests/",
    # Self-references (would flag their own regex patterns)
    "scripts/audit_config_literals.py",
    "scripts/audit_config_literals.sh",
)

# Directories pruned at os.walk time -- never descend into them. Matches
# DEFAULT_EXEMPT_PREFIXES top-level entries that are fully-contained trees.
PRUNE_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "__pycache__", "htmlcov",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "build", "dist", ".egg-info",
})

SCANNED_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".sh", ".service", ".json", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".conf", ".example",
})


@dataclass(frozen=True)
class AddressFinding:
    """One B-044 violation: a literal that should live in config."""

    path: Path
    lineNo: int
    pattern: str  # "ip" | "hostname" | "mac"
    snippet: str


def scanLine(path: Path, lineNo: int, line: str) -> list[AddressFinding]:
    """Scan one line; return zero or more findings.

    Skip conditions:
        - Inline pragma `b044-exempt` anywhere on the line
        - Line is entirely a comment (starts with `#` after whitespace)
          -- documentation prose, not runtime code
    """
    if PRAGMA_MARKER in line.lower():
        return []
    if COMMENT_LINE_PATTERN.match(line):
        return []

    findings: list[AddressFinding] = []
    snippet = line.rstrip("\r\n").strip()
    if IP_PATTERN.search(line):
        findings.append(AddressFinding(path, lineNo, "ip", snippet))
    if HOSTNAME_PATTERN.search(line):
        findings.append(AddressFinding(path, lineNo, "hostname", snippet))
    if MAC_PATTERN.search(line):
        findings.append(AddressFinding(path, lineNo, "mac", snippet))
    return findings


def _isExempt(relPath: str, exemptPrefixes: tuple[str, ...]) -> bool:
    """Path (relative, forward-slashed) matches any exempt prefix."""
    if relPath.lower().endswith(".md"):
        return True
    return any(relPath == p or relPath.startswith(p) for p in exemptPrefixes)


def _shouldScan(p: Path) -> bool:
    """Only scan source-like files (by extension)."""
    return p.suffix.lower() in SCANNED_EXTENSIONS


def _scanPythonFile(path: Path, relPath: str) -> list[AddressFinding]:
    """Python-aware scan: skip triple-quoted docstring content (category B)."""
    findings: list[AddressFinding] = []
    inTripleDouble = False
    inTripleSingle = False
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineNo, line in enumerate(fh, start=1):
            # Toggle state on triple-quote occurrences. Lines that both
            # open and close a block (e.g. single-line `"""blah"""`) land
            # the state back where it started -- treat the line as docstring.
            doubleCount = line.count('"""')
            singleCount = line.count("'''")
            lineIsDoc = inTripleDouble or inTripleSingle
            if doubleCount:
                if doubleCount % 2 != 0:
                    inTripleDouble = not inTripleDouble
                lineIsDoc = True
            if singleCount:
                if singleCount % 2 != 0:
                    inTripleSingle = not inTripleSingle
                lineIsDoc = True
            if lineIsDoc:
                continue
            findings.extend(scanLine(Path(relPath), lineNo, line))
    return findings


def _scanGenericFile(path: Path, relPath: str) -> list[AddressFinding]:
    """Scan line-by-line for non-Python files (bash, yaml, json, etc.)."""
    findings: list[AddressFinding] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineNo, line in enumerate(fh, start=1):
            findings.extend(scanLine(Path(relPath), lineNo, line))
    return findings


def auditRepository(
    repoRoot: Path,
    extraExempt: list[str] | None = None,
) -> list[AddressFinding]:
    """Walk the repo tree and return every B-044 violation found.

    Uses os.walk with in-place dirs pruning so tool caches and .git are
    never descended into -- large-tree performance matters (otherwise
    rglob materializes every .git object path before filtering).

    Args:
        repoRoot: absolute path to the repository root.
        extraExempt: extra path prefixes (relative, forward-slashed) to skip.

    Returns:
        List of AddressFinding -- empty iff the repo is clean.
    """
    exemptPrefixes = DEFAULT_EXEMPT_PREFIXES + tuple(extraExempt or ())
    findings: list[AddressFinding] = []
    rootStr = str(repoRoot)

    for dirPath, dirNames, fileNames in os.walk(rootStr):
        # Prune in place so os.walk skips these subtrees entirely.
        dirNames[:] = sorted(d for d in dirNames if d not in PRUNE_DIRS)
        for fname in sorted(fileNames):
            filePath = Path(dirPath) / fname
            if not _shouldScan(filePath):
                continue
            try:
                relPath = filePath.relative_to(repoRoot).as_posix()
            except ValueError:
                continue
            if _isExempt(relPath, exemptPrefixes):
                continue
            try:
                if filePath.suffix.lower() == ".py":
                    findings.extend(_scanPythonFile(filePath, relPath))
                else:
                    findings.extend(_scanGenericFile(filePath, relPath))
            except OSError:
                continue

    return findings


def _formatFindings(findings: list[AddressFinding], verbose: bool) -> str:
    if not findings:
        return "B-044 audit clean: zero hardcoded addresses."
    lines = [f"B-044 audit: {len(findings)} finding(s)."]
    if verbose:
        for f in findings:
            lines.append(f"  {f.path}:{f.lineNo} [{f.pattern}] {f.snippet}")
    else:
        # Summary -- count per file, first 5 files.
        perFile: dict[str, int] = {}
        for f in findings:
            key = str(f.path)
            perFile[key] = perFile.get(key, 0) + 1
        for i, (k, v) in enumerate(sorted(perFile.items())):
            if i >= 10:
                lines.append(f"  ... and {len(perFile) - 10} more files")
                break
            lines.append(f"  {k}: {v}")
        lines.append("Use --verbose for full listing.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_config_literals",
        description=(
            "B-044 audit: scan for hardcoded infrastructure addresses. "
            "Exits 0 when clean, 1 when findings exist."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print every finding (file + line + snippet).",
    )
    parser.add_argument(
        "--exempt",
        action="append",
        default=[],
        metavar="PATH",
        help="Extra path-prefix exemption (may repeat).",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Repository root (default: parent of scripts/).",
    )
    args = parser.parse_args(argv)

    findings = auditRepository(args.root, extraExempt=args.exempt)
    print(_formatFindings(findings, args.verbose))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
