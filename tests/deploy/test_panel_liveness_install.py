################################################################################
# File Name: test_panel_liveness_install.py
# Purpose/Description: US-654 (F-139) install-path gate for the display-liveness
#                      probe.  Static assertions on
#                      deploy/eclipse-panel-liveness.service + .timer and the
#                      deploy-pi.sh step that installs them, so the probe
#                      actually REACHES the Pi on the next deploy (the A-16
#                      lesson: a unit that exists only in the repo observes
#                      nothing).
#
#                      The load-bearing guards here:
#                        1. the unit declares NO Requires/Wants/After on
#                           eclipse-dashboard.service -- any of those would
#                           START the kiosk, stealing the splash OnSuccess
#                           hand-off (dashboard.service.x11 A-1);
#                        2. it does NOT declare RuntimeDirectory=eclipse-obd --
#                           systemd deletes a RuntimeDirectory when the unit
#                           exits, so a oneshot claiming eclipse-obd's dir would
#                           wipe the live states/ THIS PROBE READS AS ITS OWN
#                           SIGNAL.  The sibling watchdog carries the same
#                           fence; here the self-harm is direct;
#                        3. the unit's ExecStart arguments are reconciled
#                           against the module's own defaults, so the two cannot
#                           drift into asserting different paths;
#                        4. the timer cadence is reconciled against
#                           panel_liveness.TIMER_CADENCE_SECONDS, which the
#                           observation window is checked against in turn;
#                        5. the deploy step is not merely DEFINED but CALLED --
#                           a shell function nobody invokes is the exact
#                           inert-guard shape this sprint has been cataloguing.
#
#                      Directive assertions parse only real `Key=Value` lines
#                      (comments stripped, continuations joined).  The unit
#                      header DISCUSSES eclipse-dashboard.service, /run/
#                      eclipse-obd and restarting at length, so a raw substring
#                      guard would be satisfied -- or tripped -- by prose (the
#                      US-501 / US-513 / US-522 trap).
#
#                      Offline-safe: static file reads + one `bash -n`.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex          | Initial implementation (Sprint 78 US-654)
# ================================================================================
################################################################################

"""Static unit + deploy-path assertions for the US-654 panel-liveness probe."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pi.display import panel_liveness as pl

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "eclipse-panel-liveness.service"
TIMER_FILE = REPO_ROOT / "deploy" / "eclipse-panel-liveness.timer"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
STEP_NAME = "step_install_panel_liveness_unit"


def _directives(text: str) -> list[tuple[str, str]]:
    """Parse a systemd unit into (key, value) pairs, comments stripped.

    Comment lines and blanks are dropped and backslash continuations are joined
    BEFORE splitting, so neither prose in the header nor a wrapped ExecStart can
    satisfy (or trip) a directive assertion.
    """
    joined: list[str] = []
    buffer = ""
    for rawLine in text.splitlines():
        line = rawLine.strip()
        if not buffer and (not line or line.startswith("#") or line.startswith(";")):
            continue
        if line.endswith("\\"):
            buffer += line[:-1].strip() + " "
            continue
        joined.append((buffer + line).strip())
        buffer = ""
    if buffer:
        joined.append(buffer.strip())

    pairs: list[tuple[str, str]] = []
    for line in joined:
        if line.startswith("[") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs.append((key.strip(), value.strip()))
    return pairs


@pytest.fixture(scope="module")
def serviceDirectives() -> list[tuple[str, str]]:
    return _directives(SERVICE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def timerDirectives() -> list[tuple[str, str]]:
    return _directives(TIMER_FILE.read_text(encoding="utf-8"))


def _values(pairs: list[tuple[str, str]], key: str) -> list[str]:
    return [value for name, value in pairs if name == key]


# ============================================================================
# The service unit
# ============================================================================


def test_service_isAOneshotWithABoundedStart_us654(serviceDirectives):
    """
    Given: the liveness service unit
    When: its type and start timeout are read
    Then: it is a oneshot with a bounded TimeoutStartSec

    systemd defaults TimeoutStartSec to INFINITY for Type=oneshot, so an
    unbounded hang holds a start job forever and blocks everything ordered
    After= it -- drain-forensics.service hung ~4h exactly this way on
    2026-08-27 and hung the deploy with it.
    """
    assert _values(serviceDirectives, "Type") == ["oneshot"]
    assert _values(serviceDirectives, "TimeoutStartSec") == ["60s"]


def test_service_neverDependsOnTheKiosk_us654(serviceDirectives):
    """
    Given: the liveness service unit
    When: its ordering and requirement directives are read
    Then: none of them names eclipse-dashboard.service

    A Requires=/Wants=/After= would START the kiosk, and the dashboard is
    started ONLY by splash-boot's OnSuccess hand-off after HEALTHY_YIELD
    (dashboard.service.x11 A-1). This probe asks systemd for the kiosk's
    MainPID and, finding none, does nothing.
    """
    for key in ("Requires", "Wants", "After", "BindsTo", "PartOf", "Requisite"):
        for value in _values(serviceDirectives, key):
            assert "eclipse-dashboard" not in value


def test_service_neverClaimsTheStatesRuntimeDirectory_us654(serviceDirectives):
    """
    Given: the liveness service unit
    When: its RuntimeDirectory is read
    Then: it is its own, and never eclipse-obd

    systemd DELETES a RuntimeDirectory when the unit exits. A oneshot claiming
    eclipse-obd's dir would wipe the live states/ the emitters write -- which
    for THIS unit is not just collateral damage but the destruction of half its
    own signal, every single tick.
    """
    runtimeDirs = _values(serviceDirectives, "RuntimeDirectory")

    assert runtimeDirs == ["eclipse-panel-liveness"]
    assert "eclipse-obd" not in runtimeDirs


def test_service_preservesItsRuntimeDirectoryBetweenFires_us654(serviceDirectives):
    """
    Given: a oneshot whose only cross-fire state is the baseline sample
    When: RuntimeDirectoryPreserve is read
    Then: it is yes

    Without it systemd removes the directory when the oneshot exits, the
    baseline is lost every tick, and the probe can NEVER complete a 600s
    observation window -- it would log routine no-ops forever while observing
    nothing. Green, deployed, and completely inert.
    """
    assert _values(serviceDirectives, "RuntimeDirectoryPreserve") == ["yes"]


def test_service_execStartArgumentsMatchTheModuleDefaults_us654(serviceDirectives):
    """
    Given: the ExecStart line and the module's own default paths
    When: the two are compared
    Then: they agree

    The unit passes paths explicitly and the module declares defaults for the
    same paths. Two copies of one truth drift; this reconciles them, so a
    states-dir move cannot leave the deployed unit pointed at the old one while
    every unit test stays green.
    """
    execStart = " ".join(_values(serviceDirectives, "ExecStart"))

    assert "-m pi.display.panel_liveness" in execStart
    assert f"--states-dir {pl.DEFAULT_STATES_DIR}" in execStart
    assert f"--state-path {pl.DEFAULT_STATE_PATH}" in execStart
    assert f"--unit {pl.DEFAULT_UNIT}" in execStart


def test_service_baselineLivesInsideItsOwnRuntimeDirectory_us654(serviceDirectives):
    """
    Given: the declared RuntimeDirectory and the module's baseline path
    When: the two are compared
    Then: the baseline is inside the directory systemd actually provisions

    A baseline path outside the RuntimeDirectory would be unwritable at runtime
    (or, worse, writable somewhere that is never cleared at boot -- and a CPU
    counter from a previous boot is not comparable to this one's).
    """
    runtimeDir = _values(serviceDirectives, "RuntimeDirectory")[0]

    assert pl.DEFAULT_STATE_PATH.startswith(f"/run/{runtimeDir}/")


def test_service_exitTwoIsLeftAsAFailure_us654(serviceDirectives):
    """
    Given: the liveness service unit
    When: SuccessExitStatus is read
    Then: only 0 counts as success

    Exit 2 means the panel is DEAD or the probe cannot observe it. Widening
    SuccessExitStatus would make `systemctl status` green during a live freeze,
    which is precisely the invisibility US-654 exists to end.
    """
    successCodes = _values(serviceDirectives, "SuccessExitStatus")

    assert successCodes == ["0"]


def test_service_addsNoPrivileges_us654(serviceDirectives):
    """
    Given: a probe that only ever READS
    When: its privilege directives are read
    Then: it runs as the Pi user with no supplementary groups

    Stated as a guard rather than left to review because the SIBLING watchdog
    legitimately needs two grants (polkit restart + systemd-journal), and the
    obvious way to write this unit is to copy that one. This probe reads
    `systemctl show`, world-readable /proc, and a 0755 states dir -- it needs
    nothing, and acquiring a grant it does not use is how a privilege outlives
    its justification.
    """
    assert _values(serviceDirectives, "User") == ["mcornelison"]
    assert _values(serviceDirectives, "SupplementaryGroups") == []


def test_service_restartsNothing_us654(serviceDirectives):
    """
    Given: the liveness service unit
    When: every directive VALUE is searched for a restart verb
    Then: there is none

    The story's scope fence at the unit level: chromium restarts correlate with
    the class-B marker storm, so an automatic remedy could trade a DETECTED
    freeze for a CAUSED one. Checked against parsed directives, not raw text --
    the header discusses restarting at length and a substring grep would be
    tripped by that prose.
    """
    for key, value in serviceDirectives:
        assert "systemctl" not in value or "restart" not in value
        assert key != "ExecStartPost" or "restart" not in value


# ============================================================================
# The timer
# ============================================================================


def test_timer_cadenceMatchesTheModuleConstant_us654(timerDirectives):
    """
    Given: the timer's OnUnitActiveSec and the module's mirrored constant
    When: the two are compared
    Then: they agree

    panel_liveness.TIMER_CADENCE_SECONDS exists only to be checked against the
    observation window. If it drifts from the real cadence, that window guard
    is asserting something about a number nobody uses.
    """
    assert _values(timerDirectives, "OnUnitActiveSec") == [f"{pl.TIMER_CADENCE_SECONDS}s"]


def test_timer_waitsForTheSplashHandoffBeforeItsFirstTick_us654(timerDirectives):
    """
    Given: the dashboard is started by splash-boot's OnSuccess after
           HEALTHY_YIELD
    When: OnBootSec is read
    Then: the first tick is well clear of the boot storm
    """
    onBoot = _values(timerDirectives, "OnBootSec")

    assert onBoot == ["180s"]


def test_timer_isInstalledAndDrivesTheService_us654(timerDirectives):
    """
    Given: the timer unit
    When: its wiring is read
    Then: it requires the service and is enabled into timers.target

    `systemctl enable eclipse-panel-liveness.timer` is the only install hook;
    without WantedBy=timers.target the enable is a no-op and the probe never
    fires.
    """
    assert _values(timerDirectives, "Requires") == ["eclipse-panel-liveness.service"]
    assert _values(timerDirectives, "WantedBy") == ["timers.target"]


def test_observationWindowStillSpansSeveralTimerTicks_us654():
    """
    Given: the shipped cadence and observation window
    When: the window is divided by the cadence
    Then: it spans at least two ticks

    A window shorter than the cadence could never be reached, so the probe
    would withhold every verdict forever -- and its logs would be
    indistinguishable from a healthy display's.
    """
    assert pl.DEFAULT_OBSERVATION_SECONDS >= 2 * pl.TIMER_CADENCE_SECONDS


# ============================================================================
# The deploy path.  A unit that exists only in the repo observes nothing.
# ============================================================================


def test_deployScript_definesTheInstallStep_us654():
    """
    Given: deploy-pi.sh
    When: it is searched for the install step
    Then: the function is defined, and it installs BOTH units
    """
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert f"{STEP_NAME}()" in text
    assert "eclipse-panel-liveness.service" in text
    assert "eclipse-panel-liveness.timer" in text


def test_deployScript_actuallyCallsTheInstallStep_us654():
    """
    Given: deploy-pi.sh
    When: its top-level invocations are searched
    Then: the step is CALLED, not merely defined

    THE A-16 LESSON, AND THE ONE THAT MATTERS MOST IN THIS FILE. A step that is
    defined but never invoked passes every "the unit exists" assertion, ships,
    and installs nothing. That is the same inert-guard shape as a rationale
    without its flag (US-522) and a census that skips a row (US-644-a): the
    artefact is present and the enforcement is absent.
    """
    lines = [
        line.strip()
        for line in DEPLOY_SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert STEP_NAME in lines, f"{STEP_NAME} is defined but never invoked"


def test_deployScript_enablesTheTimerNotTheService_us654():
    """
    Given: the install step
    When: its enable command is read
    Then: it enables the .timer

    Enabling the .service instead would run the probe exactly once, at boot,
    and never again -- a detector that observes one 600s window per uptime and
    then goes quiet, which reads in the journal as a healthy display.
    """
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "systemctl enable --now eclipse-panel-liveness.timer" in text


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_deployScript_stillParses_us654():
    """
    Given: the edited deploy script
    When: bash parses it
    Then: it is syntactically valid

    The install step is heredoc-quoted shell inside a Python-formatted string;
    a stray quote there breaks the whole deploy, not just this step.
    """
    completed = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
