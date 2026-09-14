################################################################################
# File Name: test_shared_runtime_dir_preserve.py
# Purpose/Description: US-737 guard. systemd does NOT ref-count a RuntimeDirectory
#                      shared between units (measured by Atlas on systemd 257.13,
#                      2026-09-13): any sharer WITHOUT RuntimeDirectoryPreserve=yes
#                      deletes /run/eclipse-obd on its own stop, for every other
#                      sharer and for powerwatch's power-source.json.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-13    | Rex          | Initial implementation (Sprint 85 US-737)
# ================================================================================
################################################################################

"""Every unit sharing RuntimeDirectory=eclipse-obd must preserve it on stop.

The defect: eclipse-obd.service was the one sharer without
``RuntimeDirectoryPreserve=yes``. Stopping it alone removed /run/eclipse-obd,
and powerwatch's A-26 power-source publish then failed with EPERM. The prose
in seven places said systemd ref-counts the shared dir. It does not, and that
claim is why nobody added the line. So the guard pins both halves: the
directive on every sharer, and the absence of the false claim.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
SHARED_RUNTIME_DIR = "eclipse-obd"

# Units known to share the dir on this tree. Recorded independently of the
# scan so a broken glob or parser cannot pass on an empty sharer set.
KNOWN_SHARERS = frozenset(
    {"eclipse-obd.service", "eclipse-states-http.service", "eclipse-boot-state.service"}
)

# Where the false "systemd ref-counts it" claim lived (US-737 lists the sites).
CLAIM_SCAN_ROOTS = (DEPLOY_DIR, REPO_ROOT / "src")
CLAIM_SCAN_FILES = (REPO_ROOT / "specs" / "architecture.md",)
REF_COUNT_CLAIM_RE = re.compile(r"ref-?count", re.IGNORECASE)
# The corrections state the negation ("systemd does NOT ref-count it") on the
# same line, deliberately, so a grep for the term lands on the correction.
NEGATION_RE = re.compile(r"\bnot\b", re.IGNORECASE)


def _assertsRefCount(line: str) -> bool:
    """True when a line affirms the ref-count claim rather than denying it."""
    return bool(REF_COUNT_CLAIM_RE.search(line)) and not NEGATION_RE.search(line)


def _directives(unitPath: Path) -> dict[str, list[str]]:
    """Return non-comment ``Key=value`` directives of a unit, keyed by name."""
    found: dict[str, list[str]] = {}
    for line in unitPath.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        found.setdefault(key.strip(), []).append(value.strip())
    return found


def _sharersOfEclipseObdRuntimeDir() -> dict[str, dict[str, list[str]]]:
    sharers = {}
    for unitPath in sorted(DEPLOY_DIR.glob("*.service")):
        directives = _directives(unitPath)
        names = " ".join(directives.get("RuntimeDirectory", [])).split()
        if SHARED_RUNTIME_DIR in names:
            sharers[unitPath.name] = directives
    return sharers


def test_sharerScan_findsEveryKnownSharer():
    """
    Given: the deploy/ unit files
    When: scanned for RuntimeDirectory=eclipse-obd
    Then: every known sharer is found -- a scan that finds nothing proves nothing
    """
    assert KNOWN_SHARERS <= set(_sharersOfEclipseObdRuntimeDir())


def test_everySharerOfEclipseObdRuntimeDir_declaresPreserveYes():
    """
    Given: systemd removes a RuntimeDirectory when ANY declaring unit stops
    When: each sharer's RuntimeDirectoryPreserve is read
    Then: it is exactly "yes" -- one sharer without it deletes the dir for all
    """
    missing = {
        name: directives.get("RuntimeDirectoryPreserve")
        for name, directives in _sharersOfEclipseObdRuntimeDir().items()
        if directives.get("RuntimeDirectoryPreserve") != ["yes"]
    }
    assert not missing, (
        f"sharers of RuntimeDirectory={SHARED_RUNTIME_DIR} without "
        f"RuntimeDirectoryPreserve=yes (stopping any one deletes the dir): {missing}"
    )


def test_eclipseObdService_declaresPreserveYes():
    """
    Given: eclipse-obd.service, the sharer that stops on every deploy and restart
    When: its directives are read
    Then: RuntimeDirectoryPreserve=yes is present (the measured US-737 reproducer)
    """
    directives = _directives(DEPLOY_DIR / "eclipse-obd.service")
    assert directives.get("RuntimeDirectory") == [SHARED_RUNTIME_DIR]
    assert directives.get("RuntimeDirectoryPreserve") == ["yes"]


def test_refCountClaimPredicate_matchesTheRetiredWording():
    """
    Given: the phrasings the retired claim used
    When: the claim predicate is applied
    Then: each matches -- so a zero from the scan below is a real zero -- and
          the same-line correction does not
    """
    retired = (
        "#     1. RuntimeDirectory=eclipse-obd here (shared name -> systemd ref-counts it;",
        "# Shared ref-counted runtime dir (C-5). Creates /run/eclipse-obd owned by User=.",
        "ref-count never hits zero while it is up",
        "systemd refcounts the dir",
    )
    for phrase in retired:
        assert _assertsRefCount(phrase), phrase
    assert not _assertsRefCount("# systemd does NOT ref-count a RuntimeDirectory shared")
    assert not _assertsRefCount("**Sharing the name does NOT make systemd ref-count it**")


def test_noRefCountClaimSurvives_inDeploySrcOrArchitecture():
    """
    Given: systemd does not ref-count a shared RuntimeDirectory
    When: deploy/, src/ and specs/architecture.md are searched for the claim
    Then: zero hits -- a reader of US-394 must not find the old assurance
    """
    candidates = [p for root in CLAIM_SCAN_ROOTS for p in root.rglob("*") if p.is_file()]
    candidates += [p for p in CLAIM_SCAN_FILES]
    assert len(candidates) > 100, f"claim scan saw only {len(candidates)} files"

    hits = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineNo, line in enumerate(text.splitlines(), start=1):
            if _assertsRefCount(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{lineNo}: {line.strip()}")
    assert not hits, "retired 'systemd ref-counts RuntimeDirectory' claim survives:\n" + "\n".join(
        hits
    )
