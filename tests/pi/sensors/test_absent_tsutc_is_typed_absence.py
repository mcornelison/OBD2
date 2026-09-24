################################################################################
# File Name: test_absent_tsutc_is_typed_absence.py
# Purpose/Description: US-809-c -- the five NA fallbacks stop fabricating. An
#                      absent tsUtc must reach the state files as a TYPED
#                      ABSENCE, never as the current time, because a fabricated
#                      freshness marker is indistinguishable from a live one.
# Author: Ralph (US-809-c)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-c) | Initial -- the five fallbacks.
# ================================================================================
################################################################################
"""An absent tsUtc is a typed absence, never `now` (US-809-c acceptance 5).

THE SHAPE, and it is the second instance of it inside this one story: these
five lines are INERT TODAY and become defects the moment the thing near them is
fixed. tsUtc is always set right now, so ``or self._nowIsoFn()`` never fires.
US-809-c makes a typed absence REACHABLE -- at which point those lines would
silently publish a fabricated freshness marker into the state files the
dashboard reads, and the dashboard would render a stale card as live.

A change that creates the defect it is fixing, one layer up, is not a fix.
That is why this is an acceptance criterion of this story and not a follow-up.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.pi.sensors.imu_state_bridge import REASON_NO_TIMESTAMP, buildImuState
from src.pi.sensors.light_state_bridge import buildLightState

_REPO_ROOT = Path(__file__).resolve().parents[3]

_BRIDGES = (
    "src/pi/sensors/imu_state_bridge.py",
    "src/pi/sensors/light_state_bridge.py",
)


class TestTheBuildersTypeTheAbsence:
    """An absent instant is reported as absent, with a reason."""

    def test_buildImuState_absentTsUtc_isNullWithAReason(self) -> None:
        """
        Given: a state built with no capture instant
        When:  the payload is assembled
        Then:  ts is null and reasons names it, rather than carrying a clock read
        """
        state = buildImuState(tsUtc="")

        assert state["ts"] is None
        assert state["reasons"]["ts"] == REASON_NO_TIMESTAMP

    def test_buildImuState_presentTsUtc_isCarriedUntouched(self) -> None:
        """
        Given: a state built with a real capture instant
        When:  the payload is assembled
        Then:  ts is that instant and no ts reason is raised

        The absence branch must not fire on a healthy reading -- otherwise the
        fix erases the freshness marker it is protecting.
        """
        state = buildImuState(tsUtc="2026-09-23T17:00:00Z")

        assert state["ts"] == "2026-09-23T17:00:00Z"
        assert "ts" not in state["reasons"]

    def test_buildLightState_absentTsUtc_isNull(self) -> None:
        """
        Given: a light state built with no capture instant
        When:  the payload is assembled
        Then:  ts is null rather than the current time

        The US-483-b consumer compares ts against luxStaleSec. A fabricated ts
        is always fresh, so the staleness check silently never fires -- the
        check is still there and has stopped being able to fail.
        """
        assert buildLightState(lux=12.0, tsUtc="")["ts"] is None

    def test_buildLightState_presentTsUtc_isCarriedUntouched(self) -> None:
        assert buildLightState(lux=12.0, tsUtc="2026-09-23T17:00:00Z")["ts"] == (
            "2026-09-23T17:00:00Z"
        )


class TestNoBridgeSubstitutesTheClock:
    """The five call sites no longer reach for `now` when tsUtc is missing."""

    def test_noTsUtcFallbackReachesTheClock(self) -> None:
        """
        Given: both state bridges
        When:  their ASTs are walked for `<tsUtc expr> or self._nowIsoFn()`
        Then:  no such fallback remains

        An AST walk rather than a grep: the phrase `_nowIsoFn` legitimately
        survives in these files (the bridges still stamp their OWN writes with
        it, which is honest -- that IS a write time). What must not survive is
        a BoolOp that substitutes it for a reading's instant.
        """
        offenders: list[str] = []

        for rel in _BRIDGES:
            tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
                    continue
                if not _mentionsTsUtc(node.values[0]):
                    continue
                if any(_isNowIsoCall(v) for v in node.values[1:]):
                    offenders.append(f"{rel}:{node.lineno}")

        assert not offenders, (
            "a missing capture instant is still being replaced by the clock at "
            f"{offenders} -- a fabricated freshness marker reads as a live one"
        )


def _mentionsTsUtc(node: ast.AST) -> bool:
    """True when the expression fetches a sample's tsUtc."""
    return any(
        isinstance(sub, ast.Constant) and sub.value == "tsUtc" for sub in ast.walk(node)
    )


def _isNowIsoCall(node: ast.AST) -> bool:
    """True for a ``self._nowIsoFn()`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_nowIsoFn"
    )
