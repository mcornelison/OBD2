################################################################################
# File Name: test_service_control.py
# Purpose/Description: US-403 [Atlas A-7] tests for the System Setup menu's
#   service-control action path -- the install-fixed allow-list + the
#   action-path re-check (defense-in-depth). The chromium kiosk is unprivileged;
#   the privilege to run `systemctl <verb> <unit>` comes from the net-new 51-
#   polkit rule (NOT a root helper). This module is the SSOT for WHICH (unit,
#   verb) pairs are permitted, and it RE-CHECKS that allow-list at the action
#   path so a tampered/bypassed UI can never drive an off-list action (the F-092
#   analog of US-407's S-10 clear-gate re-check).
#
#   Cardinal safety rule (D-7 / F-7): `eclipse-powerwatch` (the safe-shutdown
#   guard) is RESTART-ONLY -- a stop/kill is rejected here, never executed, even
#   though the polkit rule is the ultimate backstop (layered defense).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-403 service control).
# ================================================================================
################################################################################

"""Tests for the US-403 service-control allow-list + action-path re-check."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pi.splash import service_control

# ---------------------------------------------------------------------------
# isAllowed -- the install-fixed allow-list (S-6 / F-13 / D-7 / F-7).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit,verb",
    [
        ("eclipse-obd.service", "start"),
        ("eclipse-obd.service", "stop"),
        ("eclipse-obd.service", "restart"),
        ("eclipse-sync.service", "stop"),
        ("eclipse-sync.service", "restart"),
        ("eclipse-powerwatch.service", "restart"),  # D-7: restart IS allowed
        ("eclipse-dashboard.service", "stop"),  # A-8: Exit = stop the kiosk
        ("eclipse-dashboard.service", "restart"),
    ],
)
def test_isAllowed_permitsAllowListedPairs(unit, verb):
    """Each (unit, verb) on the install-fixed allow-list is permitted."""
    assert service_control.isAllowed(unit, verb) is True


@pytest.mark.parametrize(
    "verb",
    ["stop", "kill", "start", "mask", "disable"],
)
def test_isAllowed_powerwatchStopDenied_d7_f7(verb):
    """D-7 / F-7: the safe-shutdown guard is RESTART-ONLY. Stopping/killing it
    could leave the Pi unprotected on key-off -> denied at the action path."""
    assert service_control.isAllowed("eclipse-powerwatch.service", verb) is False


@pytest.mark.parametrize(
    "unit",
    [
        "ssh.service",
        "eclipse-states-http.service",  # not operator-controllable from the kiosk
        "systemd-journald.service",
        "eclipse-obd",  # bare name (no .service) is NOT the allow-listed unit
    ],
)
def test_isAllowed_offListUnitsRejected_s6_f13(unit):
    """S-6 / F-13: a unit NOT on the install-fixed allow-list is rejected."""
    assert service_control.isAllowed(unit, "restart") is False


def test_isAllowed_unknownVerbRejected():
    """An allow-listed unit with a verb outside its set is rejected."""
    assert service_control.isAllowed("eclipse-obd.service", "mask") is False


# ---------------------------------------------------------------------------
# runServiceAction -- executes ONLY allow-listed actions; re-checks the gate.
# ---------------------------------------------------------------------------


def _okRunner(calls):
    def runner(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return runner


def test_runServiceAction_allowed_invokesSystemctl():
    """An allow-listed action shells out to `systemctl <verb> <unit>` and is ok."""
    calls: list[list[str]] = []
    result = service_control.runServiceAction(
        "eclipse-obd.service", "restart", runner=_okRunner(calls)
    )
    assert result.ok is True
    assert result.returnCode == 0
    assert calls == [["systemctl", "restart", "eclipse-obd.service"]]


def test_runServiceAction_powerwatchStop_rejectedNeverExecuted_a7():
    """A-7 defense-in-depth: a powerwatch STOP at the action path is REJECTED and
    systemctl is NEVER invoked -- the disabled UI button is not the only guard."""
    calls: list[list[str]] = []
    result = service_control.runServiceAction(
        "eclipse-powerwatch.service", "stop", runner=_okRunner(calls)
    )
    assert result.ok is False
    assert calls == [], "systemctl must not be called for an off-list action"
    assert "allow-list" in result.reason.lower()


def test_runServiceAction_offListUnit_rejectedNeverExecuted_s6():
    """S-6: an off-list unit is rejected at the action path; systemctl not called."""
    calls: list[list[str]] = []
    result = service_control.runServiceAction(
        "ssh.service", "stop", runner=_okRunner(calls)
    )
    assert result.ok is False
    assert calls == []


def test_runServiceAction_systemctlNonZero_reportsHonestFailure():
    """A failed systemctl call -> ok=False with the stderr surfaced (honest
    instrument: a stop that fails shows the service still running, never a fake
    success)."""

    def failRunner(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="Failed to stop unit")

    result = service_control.runServiceAction(
        "eclipse-obd.service", "stop", runner=failRunner
    )
    assert result.ok is False
    assert result.returnCode == 1
    assert "Failed to stop unit" in result.reason


def test_runServiceAction_runnerRaises_handledNeverPropagates():
    """A subprocess error (timeout/OSError) is caught -> ok=False, never raised
    (the action endpoint must not 500 / crash the state server)."""

    def boomRunner(argv, **kwargs):
        raise TimeoutError("systemctl timed out")

    result = service_control.runServiceAction(
        "eclipse-obd.service", "restart", runner=boomRunner
    )
    assert result.ok is False
    assert result.returnCode is None
