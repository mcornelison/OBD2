################################################################################
# File Name: test_kiosk_watchdog_install.py
# Purpose/Description: US-523 (F-124) install-path gate for the kiosk watchdog.
#                      Static assertions on deploy/eclipse-kiosk-watchdog.service
#                      + .timer + the deploy-pi.sh step that installs them, so
#                      the watchdog actually REACHES the Pi on the next deploy
#                      (the A-16 lesson: a unit that exists only in the repo
#                      guards nothing).
#
#                      Three guards here are the load-bearing ones:
#                        1. the unit declares NO Requires/Wants/After on
#                           eclipse-dashboard.service -- any of those would START
#                           the kiosk, stealing the splash OnSuccess hand-off
#                           (dashboard.service.x11 A-1);
#                        2. it does NOT declare RuntimeDirectory=eclipse-obd --
#                           systemd deletes a RuntimeDirectory when the unit
#                           exits, so a oneshot claiming eclipse-obd's dir would
#                           wipe the live states/ the emitters write;
#                        3. polkit still grants the Pi user `restart` on
#                           eclipse-dashboard.service -- the watchdog runs
#                           unprivileged, so revoking that grant silently breaks
#                           recovery while every unit test stays green.
#
#                      Directive assertions parse only real `Key=Value` lines
#                      (comments stripped, continuations joined). The unit header
#                      DISCUSSES eclipse-dashboard.service and /run/eclipse-obd
#                      at length, so a raw substring guard would be satisfied --
#                      or tripped -- by prose (the US-501 / US-513 / US-522 trap).
#
#                      Offline-safe: static file reads + one `bash -n`.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex          | Initial implementation (Sprint 70 US-523)
# ================================================================================
################################################################################

"""Static unit + deploy-path assertions for the US-523 kiosk watchdog."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "eclipse-kiosk-watchdog.service"
TIMER_FILE = REPO_ROOT / "deploy" / "eclipse-kiosk-watchdog.timer"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
POLKIT_RULES = REPO_ROOT / "deploy" / "polkit-rules" / "51-eclipse-service-control.rules"
WATCHDOG_MODULE = REPO_ROOT / "src" / "pi" / "display" / "kiosk_watchdog.py"


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


def _serviceDirectives() -> list[tuple[str, str]]:
    assert SERVICE_FILE.is_file(), f"missing unit: {SERVICE_FILE}"
    return _directives(SERVICE_FILE.read_text(encoding="utf-8"))


def _timerDirectives() -> list[tuple[str, str]]:
    assert TIMER_FILE.is_file(), f"missing timer: {TIMER_FILE}"
    return _directives(TIMER_FILE.read_text(encoding="utf-8"))


def _value(pairs: list[tuple[str, str]], key: str) -> str | None:
    for foundKey, value in pairs:
        if foundKey == key:
            return value
    return None


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


# ----------------------------------------------------------------------------
# The directive parser itself -- fed known-bad input, per the US-513 rule that
# every static guard carries a self-test.
# ----------------------------------------------------------------------------


def test_directiveParser_ignoresCommentsAndJoinsContinuations():
    """
    Given: a unit whose COMMENT mentions a directive that is not really set, and
           a real directive split across a backslash continuation
    When:  parsed
    Then:  the commented text is invisible and the continuation is one value --
           without this, "no Wants=eclipse-dashboard" and "ExecStart runs the
           watchdog module" could both be satisfied by prose
    """
    text = "\n".join(
        [
            "# Wants=eclipse-dashboard.service  <- discussion only",
            "[Service]",
            "Type=oneshot",
            "ExecStart=/bin/python -m pkg.mod \\",
            "    --flag value",
        ]
    )

    pairs = _directives(text)

    assert ("Wants", "eclipse-dashboard.service") not in pairs
    assert _value(pairs, "Type") == "oneshot"
    assert _value(pairs, "ExecStart") == "/bin/python -m pkg.mod --flag value"


# ----------------------------------------------------------------------------
# Service unit
# ----------------------------------------------------------------------------


def test_service_isAOneshotRunningTheWatchdogModule():
    """
    Given: the watchdog service
    When:  inspected
    Then:  Type=oneshot invoking `-m pi.display.kiosk_watchdog` -- one decision
           per timer fire, no daemon to keep alive
    """
    pairs = _serviceDirectives()

    assert _value(pairs, "Type") == "oneshot"
    execStart = _value(pairs, "ExecStart") or ""
    assert "-m pi.display.kiosk_watchdog" in execStart


def test_service_hasTheDualPythonPath():
    """
    Given: the `pi.` package import convention
    When:  the unit sets PYTHONPATH
    Then:  BOTH repo root and repo/src are on it, matching
           eclipse-states-http.service -- repo-root-only fails `import pi.*`
    """
    values = [value for key, value in _serviceDirectives() if key == "Environment"]
    pythonPath = next((v for v in values if v.startswith("PYTHONPATH=")), "")

    assert pythonPath, "PYTHONPATH not set"
    assert pythonPath.rstrip("/").endswith("/src")
    assert ":" in pythonPath


def test_service_readsTheJournalWithoutRoot():
    """
    Given: the watchdog must read eclipse-dashboard's journal
    When:  it runs unprivileged as the Pi user
    Then:  it joins systemd-journal, so the read does not depend on journald's
           per-uid file split
    """
    pairs = _serviceDirectives()

    assert _value(pairs, "User"), "watchdog must declare a non-root User"
    assert "systemd-journal" in (_value(pairs, "SupplementaryGroups") or "")


def test_service_declaresNoDependencyOnTheKioskItGuards():
    """
    Given: eclipse-dashboard is started ONLY by splash-boot's OnSuccess hand-off
    When:  the watchdog declares its dependencies
    Then:  no Requires/Wants/BindsTo/After/PartOf names it -- a Wants= would
           start the kiosk out of band, and an After= would pull it into the
           timer's transaction. The watchdog probes `is-active` instead.
    """
    orderingKeys = {"Requires", "Wants", "BindsTo", "Requisite", "After", "Before", "PartOf"}

    offenders = [
        (key, value)
        for key, value in _serviceDirectives()
        if key in orderingKeys and "eclipse-dashboard" in value
    ]

    assert offenders == [], f"watchdog must not depend on the kiosk it restarts: {offenders}"


def test_service_ownsItsRuntimeDirAndNeverClaimsEclipseObd():
    """
    Given: systemd DELETES a RuntimeDirectory when the owning unit exits
    When:  this oneshot declares one
    Then:  it is its own dir, never `eclipse-obd` -- claiming that one would
           delete /run/eclipse-obd (and the live states/ inside it) every 30s
    """
    runtimeDirs = [value for key, value in _serviceDirectives() if key == "RuntimeDirectory"]

    assert runtimeDirs, "the ledger needs a RuntimeDirectory"
    for value in runtimeDirs:
        for entry in value.split():
            assert entry != "eclipse-obd", (
                "RuntimeDirectory=eclipse-obd would delete the live states dir on exit"
            )
    assert "eclipse-kiosk-watchdog" in runtimeDirs


def test_service_preservesTheRuntimeDirBetweenFires():
    """
    Given: a oneshot's RuntimeDirectory is removed on exit by default
    When:  the restart ledger lives in it
    Then:  RuntimeDirectoryPreserve=yes -- otherwise the ledger evaporates every
           fire, the cooldown/budget always read empty, and the watchdog could
           restart the kiosk on every single tick
    """
    assert _value(_serviceDirectives(), "RuntimeDirectoryPreserve") == "yes"


def test_service_ledgerPathMatchesTheModuleDefault():
    """
    Given: the ledger path is named in the unit AND in the module
    When:  both are read
    Then:  they agree, and it is under /run (tmpfs) -- two copies of one path
           are exactly the divergence class A-15 exists for
    """
    execStart = _value(_serviceDirectives(), "ExecStart") or ""
    tokens = execStart.split()
    assert "--state-path" in tokens, "the unit must pin the ledger path explicitly"
    unitPath = tokens[tokens.index("--state-path") + 1]

    assert unitPath.startswith("/run/")
    moduleText = WATCHDOG_MODULE.read_text(encoding="utf-8")
    assert f'DEFAULT_STATE_PATH = "{unitPath}"' in moduleText


def test_service_capsItsOwnResourceUse():
    """
    Given: the watchdog fires exactly when chromium has pegged the CPU
    When:  it runs
    Then:  it is capped + de-prioritised, so recovery never competes with the
           thing it is recovering
    """
    pairs = _serviceDirectives()

    assert _value(pairs, "MemoryMax")
    assert _value(pairs, "CPUQuota")
    assert _value(pairs, "Nice")


def test_service_treatsTheFaultExitAsAFailure():
    """
    Given: the module exits 2 when the recovery path is broken or spent
    When:  systemd evaluates the fire
    Then:  only 0 is success -- a recurring wedge must show as FAILED in
           `systemctl status`, which is the AC's "surface, don't silence"
    """
    successCodes = _value(_serviceDirectives(), "SuccessExitStatus")

    assert successCodes == "0"


# ----------------------------------------------------------------------------
# Timer
# ----------------------------------------------------------------------------


def test_timer_cadenceIsAtMostHalfTheJournalWindow():
    """
    Given: the module's 60s default journal window
    When:  the timer sets its cadence
    Then:  the tick is <= 30s, so a wedge cannot sit unnoticed longer than
           roughly one window
    """
    onUnitActive = _value(_timerDirectives(), "OnUnitActiveSec") or ""

    assert onUnitActive.endswith("s")
    assert int(onUnitActive.rstrip("s")) <= 30


def test_timer_waitsOutTheBootStorm():
    """
    Given: the dashboard does not exist until the splash hands off
    When:  the timer arms at boot
    Then:  OnBootSec gives the boot storm room (>= 60s)
    """
    onBoot = _value(_timerDirectives(), "OnBootSec") or ""

    assert onBoot.endswith("s")
    assert int(onBoot.rstrip("s")) >= 60


def test_timer_isEnableableAndBoundToItsService():
    """
    Given: `systemctl enable eclipse-kiosk-watchdog.timer` is the install hook
    When:  the timer is inspected
    Then:  it is WantedBy=timers.target and Requires its own service
    """
    pairs = _timerDirectives()

    assert _value(pairs, "WantedBy") == "timers.target"
    assert _value(pairs, "Requires") == "eclipse-kiosk-watchdog.service"


# ----------------------------------------------------------------------------
# Deploy path -- the A-16 gate: does it actually reach the Pi?
# ----------------------------------------------------------------------------


def test_deployScript_installsBothUnitFilesCmpGuarded():
    """
    Given: deploy-pi.sh owns systemd install
    When:  the watchdog step runs
    Then:  it install -m 644's BOTH files, cmp-guards them, daemon-reloads on
           change and `enable --now`s the timer -- the same posture as the
           drain-forensics / orphan-cleanup pairs
    """
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "step_install_kiosk_watchdog_unit() {" in text
    assert "eclipse-kiosk-watchdog.service" in text
    assert "eclipse-kiosk-watchdog.timer" in text
    assert "systemctl enable --now eclipse-kiosk-watchdog.timer" in text
    assert "cmp -s \\\"\\$SRC_SVC\\\" \\\"\\$DST_SVC\\\"" in text
    assert "cmp -s \\\"\\$SRC_TIM\\\" \\\"\\$DST_TIM\\\"" in text


def test_deployScript_callsTheStepAfterTheKioskUnitsItGuards():
    """
    Given: the watchdog restarts a unit the kiosk step installs
    When:  deploy-pi.sh sequences its steps
    Then:  the watchdog step is CALLED (not merely defined) and lands after
           step_install_ui_kiosk_units -- a defined-but-uncalled step is the
           A-16 deploy-contract gap verbatim
    """
    lines = DEPLOY_SCRIPT.read_text(encoding="utf-8").splitlines()

    callSites = [i for i, line in enumerate(lines) if line.strip() == "step_install_kiosk_watchdog_unit"]
    kioskSites = [i for i, line in enumerate(lines) if line.strip() == "step_install_ui_kiosk_units"]

    assert callSites, "step_install_kiosk_watchdog_unit is never called"
    assert kioskSites, "step_install_ui_kiosk_units call site not found"
    assert min(callSites) > min(kioskSites)


def test_deployScript_dryRunDescribesTheWatchdogInstall():
    """
    Given: --dry-run must describe every real action
    When:  the watchdog step runs dry
    Then:  it echoes the install + enable it would perform
    """
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    stepBody = text.split("step_install_kiosk_watchdog_unit() {", 1)[1].split("\nstep_", 1)[0]

    assert "DRY-RUN would" in stepBody
    assert stepBody.count("DRY-RUN would") >= 3


@pytest.mark.skipif(not _bashAvailable(), reason="bash not on PATH")
def test_deployScript_isStillSyntacticallyValid():
    """
    Given: a new heredoc-heavy remote block was added
    When:  bash parses the script
    Then:  no syntax error -- a broken deploy script fails the whole deploy
    """
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


# ----------------------------------------------------------------------------
# Privilege coupling -- the half that can be silently revoked elsewhere
# ----------------------------------------------------------------------------


def test_polkit_stillGrantsRestartOnTheKioskUnit():
    """
    Given: the watchdog runs unprivileged and calls `systemctl restart`
    When:  polkit's service-control rule is read
    Then:  eclipse-dashboard.service is still listed with the restart verb.
           This is the two-correct-halves trap: revoke the grant and every
           watchdog unit test stays green while recovery is dead on the Pi.
    """
    rules = POLKIT_RULES.read_text(encoding="utf-8")

    assert "eclipse-dashboard.service" in rules
    dashboardBlock = rules.split("eclipse-dashboard.service", 1)[1]
    assert '"restart"' in dashboardBlock.split("}", 1)[0] or "restart" in dashboardBlock[:400]
