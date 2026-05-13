################################################################################
# File Name: test_orphan_cleanup_install.py
# Purpose/Description: US-334 acceptance gate (TD-051).  Static-content
#                      assertions on deploy/orphan-cleanup.service: the unit
#                      must lower its I/O + CPU priority (`IOSchedulingClass=idle`,
#                      `Nice=10`) and order itself `After=eclipse-obd.service`
#                      so the Persistent=true timer's boot-time catch-up DELETE
#                      on data/obd.db does not starve the launching orchestrator's
#                      early `journalctl --list-boots` calls on the Pi 5 SD card
#                      (the root cause behind I-030, around which V0.27.7 US-330
#                      added a race-guard).  Also verifies that deploy-pi.sh's
#                      step_install_orphan_cleanup_unit installs the unit file
#                      verbatim (`install -m 644` from the deploy/ source), so
#                      the new directives reach the installed copy on the next
#                      deploy with no deploy-pi.sh change required.
#
#                      All static assertions in this file FAIL pre-US-334:
#                      orphan-cleanup.service did not contain IOSchedulingClass,
#                      Nice, or After=eclipse-obd.service.
#
#                      Offline-safe: every test is a static file read or a
#                      `bash -n` syntax check -- no network, no SSH.
# Author: Agent2 (Ralph Agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Agent2       | Initial implementation (Sprint 34 US-334 / TD-051)
# ================================================================================
################################################################################

"""Static unit-file + install-path assertions for deploy/orphan-cleanup.service (US-334).

We keep these as plain text-content checks rather than parsing the unit as
INI -- systemd unit files are close to INI but have enough quirks (multiple
``After=`` lines that merge, continuation lines, comments mid-section) that a
full parser would be overkill for the handful of invariants US-334 cares about.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "orphan-cleanup.service"
TIMER_FILE = REPO_ROOT / "deploy" / "orphan-cleanup.timer"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"


def _serviceText() -> str:
    assert SERVICE_FILE.is_file(), f"Service file missing: {SERVICE_FILE}"
    return SERVICE_FILE.read_text(encoding="utf-8")


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


# ----------------------------------------------------------------------------
# Static unit-file content -- offline-safe; FAIL pre-US-334.
# ----------------------------------------------------------------------------

def test_orphanCleanupService_exists():
    assert SERVICE_FILE.is_file()


def test_orphanCleanupService_lowersIoPriorityToIdle():
    """`IOSchedulingClass=idle` in [Service] -- the load-bearing TD-051 throttle.

    Idle I/O class means the catch-up DELETE only runs when nothing else
    needs the SD card, so it yields disk bandwidth to the launching
    orchestrator instead of saturating it (the I-030 contention).
    """
    text = _serviceText()
    assert re.search(r"^IOSchedulingClass=idle\s*$", text, re.MULTILINE), (
        "orphan-cleanup.service is missing `IOSchedulingClass=idle`; the "
        "boot-time catch-up DELETE can still saturate the SD card's I/O "
        "bandwidth and starve the launching orchestrator (TD-051 / I-030)."
    )


def test_orphanCleanupService_lowersCpuPriorityWithNice():
    """`Nice=10` complements the I/O throttle on the CPU side (TD-051)."""
    text = _serviceText()
    match = re.search(r"^Nice=(\d+)\s*$", text, re.MULTILINE)
    assert match is not None, (
        "orphan-cleanup.service is missing a `Nice=` directive; TD-051's "
        "remediation calls for `Nice=10` alongside `IOSchedulingClass=idle`."
    )
    assert int(match.group(1)) >= 10, (
        f"Nice={match.group(1)} is not low-enough priority; expected >= 10 "
        f"so the cleanup yields the CPU to the orchestrator under contention."
    )


def test_orphanCleanupService_orderedAfterEclipseObd():
    """`After=eclipse-obd.service` -- run the catch-up cleanup once the main
    orchestrator has started (TD-051 'cherry on top' of the I/O throttle).

    systemd merges multiple ``After=`` lines, so this is satisfied whether it
    is a standalone line or appended to the existing ``After=network.target``.
    """
    text = _serviceText()
    afterTokens: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^After=(.+)$", line)
        if m:
            afterTokens.update(m.group(1).split())
    assert "eclipse-obd.service" in afterTokens, (
        "orphan-cleanup.service does not order itself After=eclipse-obd.service; "
        "the boot-time catch-up DELETE can run concurrently with the launching "
        "orchestrator's startup I/O (TD-051)."
    )


def test_orphanCleanupService_keepsExistingResourceCaps():
    """The pre-existing MemoryMax/CPUQuota caps from US-322 must survive."""
    text = _serviceText()
    assert "MemoryMax=128M" in text, "US-322 MemoryMax cap was dropped"
    assert "CPUQuota=20%" in text, "US-322 CPUQuota cap was dropped"


def test_orphanCleanupTimer_scheduleUnchanged():
    """doNotTouch: the nightly 03:00 OnCalendar + Persistent=true stay put.

    US-334 throttles the *run*, not *when* it is scheduled.
    """
    text = TIMER_FILE.read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 03:00:00" in text, "orphan-cleanup.timer schedule changed"
    assert re.search(r"^Persistent=true\s*$", text, re.MULTILINE), (
        "orphan-cleanup.timer lost Persistent=true (the catch-up-at-boot behaviour)"
    )


# ----------------------------------------------------------------------------
# Install path -- deploy-pi.sh ships the unit verbatim, so the new directives
# reach the installed copy with no deploy-pi.sh change.  Offline-safe.
# ----------------------------------------------------------------------------

def test_deployPiSh_installsOrphanCleanupUnitVerbatim():
    """step_install_orphan_cleanup_unit syncs deploy/orphan-cleanup.service
    with `install -m 644` (not a heredoc / template), so editing the source
    file is sufficient -- the install picks up IOSchedulingClass/Nice/After
    on the next deploy.
    """
    body = _extractDeployFunctionBody("step_install_orphan_cleanup_unit")
    assert body, "step_install_orphan_cleanup_unit not found in deploy-pi.sh"
    assert "deploy/orphan-cleanup.service" in body, (
        "step_install_orphan_cleanup_unit does not reference the .service source path"
    )
    assert "install -m 644" in body, (
        "step_install_orphan_cleanup_unit does not `install -m 644` the unit "
        "file verbatim -- the new TD-051 directives would not reach the Pi."
    )
    # No heredoc that would shadow the source file's content.
    assert "<<" not in body, (
        "step_install_orphan_cleanup_unit appears to template the unit via a "
        "heredoc; the unit content must come from deploy/orphan-cleanup.service "
        "so editing that file is the single point of change (US-334 stopCondition)."
    )


def _extractDeployFunctionBody(funcName: str) -> str:
    """Return the body of a ``name() {`` bash function in deploy-pi.sh, sliced
    from the declaration to the next top-level ``^[a-z_]+\\(\\) \\{`` line.
    """
    scriptText = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    startMatch = re.search(rf"^{re.escape(funcName)}\(\) \{{", scriptText, re.MULTILINE)
    if not startMatch:
        return ""
    body = scriptText[startMatch.end():]
    endMatch = re.search(r"^[a-z_]+\(\) \{", body, re.MULTILINE)
    if endMatch:
        body = body[: endMatch.start()]
    return body


# ----------------------------------------------------------------------------
# Bash syntax check -- catches any typo introduced in deploy-pi.sh.
# ----------------------------------------------------------------------------

@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_bashSyntaxValid():
    """`bash -n deploy-pi.sh` must parse cleanly."""
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n failed (exit={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
