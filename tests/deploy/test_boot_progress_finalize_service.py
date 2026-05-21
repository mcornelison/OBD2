################################################################################
# File Name: test_boot_progress_finalize_service.py
# Purpose/Description: Static-content assertions on
#                      deploy/boot-progress-finalize.service. Sprint 40 / US-345
#                      (F-8 fix): the unit MUST declare Conflicts=shutdown.target
#                      so its ExecStop fires during the shutdown transaction.
#                      Pre-fix, DefaultDependencies=no + Before=shutdown.target
#                      left the unit orphaned -- systemd brought it up at boot
#                      but never stopped it on shutdown, so the CLEAN_COMPLETE
#                      breadcrumb was never written and every clean shutdown was
#                      classified crashed_during_operation. Also locks down the
#                      surrounding ordering directives + ExecStop command body
#                      (Sprint 38 T11 / V0.27.12-DOA invariants) as regression
#                      guards.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-20    | Rex          | Initial implementation (Sprint 40 US-345; F-8 fix).
#                                Mirrors test_eclipse_obd_service.py text-content +
#                                section-block discipline pattern. Atlas finding
#                                offices/architect/findings/2026-05-20-startup-log-
#                                marker-broken-empirical.md is the contract of
#                                record for the Conflicts=shutdown.target gate.
# ================================================================================
################################################################################

"""Static unit-file assertions for deploy/boot-progress-finalize.service.

We deliberately keep these as plain text-content checks rather than parsing
the file as INI -- systemd unit files are close to INI but have enough quirks
(drop-in directive lists, continuation lines, comments mid-section that
include literal section headers) that a full parser would be overkill for the
handful of invariants we care about.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "boot-progress-finalize.service"


def _serviceText() -> str:
    assert SERVICE_FILE.is_file(), f"Service file missing: {SERVICE_FILE}"
    return SERVICE_FILE.read_text(encoding="utf-8")


def _unitBlock(text: str) -> str:
    """Return the [Unit] section body only (excludes the file's comment header).

    Matters because the file's docstring header references directive names
    (After=, Before=, DefaultDependencies=) inside comments that would
    otherwise pollute a naive whole-file regex. Mirrors the section-discipline
    pattern in test_eclipse_obd_service.py::test_eclipseObdService_flapProtectionInUnitNotService.
    """
    headers = {
        m.group(1): m.start()
        for m in re.finditer(r"^\[(Unit|Service|Install)\]", text, re.MULTILINE)
    }
    assert {"Unit", "Service", "Install"}.issubset(headers), f"Missing sections: {headers}"
    return text[headers["Unit"]:headers["Service"]]


def test_bootProgressFinalizeService_exists():
    assert SERVICE_FILE.is_file()


def test_bootProgressFinalizeService_hasConflictsShutdownTarget():
    """US-345 / F-8 fix: [Unit] MUST declare Conflicts=shutdown.target.

    Atlas finding 2026-05-20-startup-log-marker-broken-empirical.md root cause:
    DefaultDependencies=no opts out of the auto-synthesized
    Conflicts=shutdown.target that systemd would normally provide. Without
    that directive, the unit is never pulled into the shutdown transaction,
    its ExecStop never fires, and CLEAN_COMPLETE is never written. The Before=
    line is ordering only -- it does not establish activation in the
    transaction. This is the exact one-line fix Atlas prescribed.

    Pre-fix RED: this assertion fails (no Conflicts= directive present).
    Post-fix GREEN: assertion passes.
    """
    text = _serviceText()
    unit = _unitBlock(text)
    assert re.search(r"^Conflicts=shutdown\.target\s*$", unit, re.MULTILINE), (
        "F-8: [Unit] must declare `Conflicts=shutdown.target` so the unit is "
        "pulled into the shutdown transaction and ExecStop fires. Without it, "
        "systemd never tells this unit to stop on shutdown and CLEAN_COMPLETE "
        "is never written -- every clean shutdown is mis-classified "
        "crashed_during_operation. See "
        "offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md."
    )


def test_bootProgressFinalizeService_preservesShutdownOrderingDirectives():
    """Invariants from Sprint 38 T11 design: keep the surrounding ordering intact.

    DefaultDependencies=no + After=eclipse-obd.service drain-forensics.service
    + Before=shutdown.target together establish *where* in the shutdown
    transaction this unit's ExecStop runs (late, after the app + forensics
    logger have stopped, before shutdown.target is reached). The F-8 fix
    adds Conflicts=shutdown.target without disturbing this ordering frame.
    """
    text = _serviceText()
    unit = _unitBlock(text)
    assert re.search(r"^DefaultDependencies=no\s*$", unit, re.MULTILINE), (
        "DefaultDependencies=no required (preserves custom ordering control)"
    )
    assert re.search(
        r"^After=eclipse-obd\.service drain-forensics\.service\s*$",
        unit,
        re.MULTILINE,
    ), "After=eclipse-obd.service drain-forensics.service required"
    assert re.search(r"^Before=shutdown\.target\s*$", unit, re.MULTILINE), (
        "Before=shutdown.target required (ordering within shutdown transaction)"
    )


def test_bootProgressFinalizeService_execStopWritesCleanCompleteBreadcrumb():
    """Sprint 38 T11 invariant: ExecStop command body unchanged by US-345.

    The fix is purely a [Unit] dependency-graph change. The ExecStop command
    (which writes the CLEAN_COMPLETE rung when systemd actually invokes it)
    must remain identical so once Conflicts=shutdown.target pulls the unit
    into the shutdown transaction, the correct breadcrumb gets written.
    """
    text = _serviceText()
    execStopMatch = re.search(r"^ExecStop=(.+)$", text, re.MULTILINE)
    assert execStopMatch is not None, "ExecStop= directive missing"
    execStop = execStopMatch.group(1)
    assert "src.pi.diagnostics.boot_progress" in execStop, (
        f"ExecStop must invoke boot_progress finalizer: {execStop}"
    )
    assert "--finalize" in execStop, f"ExecStop must pass --finalize flag: {execStop}"
    assert "data/boot_progress" in execStop, (
        f"ExecStop must point at the boot_progress breadcrumb file: {execStop}"
    )


def test_bootProgressFinalizeService_pythonpathIncludesBothRepoAndSrc():
    """V0.27.12-DOA hotfix invariant (2026-05-17): PYTHONPATH = repo:repo/src.

    Required so `python -m src.pi.diagnostics.boot_progress` resolves AND the
    project's bare-`from pi.X` imports resolve under the finalize subprocess.
    Mirrors src/pi/main.py:47-57 and tests/conftest. Locked down here so a
    future "simplify the env" cleanup cannot silently no-op the finalizer.
    """
    text = _serviceText()
    pythonPathMatch = re.search(r"^Environment=PYTHONPATH=(.+)$", text, re.MULTILINE)
    assert pythonPathMatch is not None, "Environment=PYTHONPATH= directive missing"
    pythonPath = pythonPathMatch.group(1)
    repoRoot = "/home/mcornelison/Projects/Eclipse-01"
    assert repoRoot in pythonPath, f"PYTHONPATH must include repo root: {pythonPath}"
    assert f"{repoRoot}/src" in pythonPath, (
        f"PYTHONPATH must include <repo>/src per V0.27.12-DOA fix: {pythonPath}"
    )


def test_bootProgressFinalizeService_oneshotRemainAfterExitContract():
    """Type=oneshot + RemainAfterExit=yes is the contract that makes ExecStop fire.

    A oneshot service that exits before shutdown only runs ExecStop if
    RemainAfterExit=yes keeps it "active" until the shutdown transaction
    stops it. Without this pairing, even Conflicts=shutdown.target would not
    cause ExecStop to fire (the unit would have already deactivated).
    """
    text = _serviceText()
    assert re.search(r"^Type=oneshot\s*$", text, re.MULTILINE), "Type=oneshot required"
    assert re.search(r"^RemainAfterExit=yes\s*$", text, re.MULTILINE), (
        "RemainAfterExit=yes required so ExecStop can fire at shutdown"
    )


def test_bootProgressFinalizeService_conflictsDirectiveLivesInUnitNotService():
    """Regression guard: Conflicts= belongs in [Unit], not [Service].

    systemd silently ignores Conflicts= placed under [Service] -- same class
    of bug as the StartLimitBurst-in-[Service] foot-gun guarded against in
    test_eclipse_obd_service.py::test_eclipseObdService_flapProtectionInUnitNotService.
    """
    text = _serviceText()
    headers = {
        m.group(1): m.start()
        for m in re.finditer(r"^\[(Unit|Service|Install)\]", text, re.MULTILINE)
    }
    serviceBlock = text[headers["Service"]:headers["Install"]]
    assert re.search(r"^Conflicts=", serviceBlock, re.MULTILINE) is None, (
        "Conflicts= must live in [Unit], not [Service] (systemd would silently ignore it)"
    )
