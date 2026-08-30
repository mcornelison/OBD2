################################################################################
# File Name: test_drain_checkpoint_wiring.py
# Purpose/Description: US-605 (F-138) WIRING guards for the 30 s open-drain
#                      checkpoint.  The mechanism itself is covered by
#                      tests/pi/power/test_drain_checkpoint.py; this file exists
#                      because a mechanism nothing CALLS ships inert with a
#                      fully green suite.
#
#                      US-625 measured exactly that: its mutation M13 ("the
#                      bound is never armed at _startDrive") was MISSED because
#                      every test armed the bound by hand, so the whole fix
#                      could have gone dead in production while the suite stayed
#                      green.  These guards assert the CALL SITE, and one of
#                      them drives the REAL lifecycle wiring end to end so
#                      "the loop checkpoints the writer the lifecycle built" is
#                      pinned rather than assumed.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-605) | Initial -- run-loop call site + lifecycle seam.
# ================================================================================
################################################################################

"""US-605 wiring guards: the run loop actually drives the drain checkpoint."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.database import ObdDatabase
from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.obdii.orchestrator.lifecycle import LifecycleMixin
from pi.power.battery_health import BATTERY_HEALTH_LOG_TABLE
from pi.power.power import PowerMonitor

_CONFIG: dict[str, Any] = {
    'pi': {
        'power': {'power_monitor': {'enabled': True}},
        'hardware': {'upsMonitor': {'socColdStartWindowSeconds': 1.0}},
    },
}

#: Any monotonic reading far enough ahead that the 30 s interval has
#: unambiguously elapsed, without the test sleeping through it.
_WELL_PAST_THE_INTERVAL = 1e9


class FakeUps:
    def __init__(self, *, vcell: float = 3.47, socPct: int = 41) -> None:
        self.vcell = vcell
        self.socPct = socPct

    def getVcell(self) -> float:
        return self.vcell

    def getBatteryPercentage(self) -> int:
        return self.socPct


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / 'drain_checkpoint_wiring.db'), walMode=False)
    db.initialize()
    return db


def _orch(*, database: Any, powerMonitor: Any, hardwareManager: Any = None) -> Any:
    """A bare LifecycleMixin carrying only what the drain wiring touches."""
    orch = LifecycleMixin.__new__(LifecycleMixin)
    orch._config = _CONFIG
    orch._database = database
    orch._powerMonitor = powerMonitor
    orch._hardwareManager = hardwareManager
    return orch


def _openRow(database: ObdDatabase) -> tuple[Any, ...]:
    with database.connect() as conn:
        return conn.execute(
            "SELECT drain_event_id, end_timestamp, end_vcell_v, end_soc_pct, "
            f"runtime_seconds FROM {BATTERY_HEALTH_LOG_TABLE} "
            "ORDER BY drain_event_id DESC"
        ).fetchone()


# ================================================================================
# The call site
# ================================================================================


class TestTheRunLoopCallsTheCheckpoint:
    """A mechanism nothing calls is a mechanism that shipped inert (US-625 M13)."""

    def test_runLoopCallsMaybeTriggerDrainCheckpoint(self) -> None:
        """
        Given: the checkpoint's whole value is that it fires PERIODICALLY.
        When:  runLoop's own body is parsed.
        Then:  it calls _maybeTriggerDrainCheckpoint.

        Parsed as an AST rather than grepped as text on purpose: a substring
        search over the file would stay green if the call were deleted from the
        loop and left sitting in a comment, in a docstring, or in some other
        method entirely -- which is precisely the inert shape this guard exists
        to catch.
        """
        source = textwrap.dedent(
            inspect.getsource(ApplicationOrchestrator.runLoop)
        )
        tree = ast.parse(source)
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert '_maybeTriggerDrainCheckpoint' in called

        # Premise check: if this ever stops finding the sibling triggers the
        # loop is known to make, the parse itself has broken and the assertion
        # above proves nothing.
        assert '_maybeTriggerIntervalSync' in called

    def test_theCheckpointIsUngatedByDriveState(self) -> None:
        """
        Given: a drain is a POWER event; it can start and end with no drive in
               progress, and the run-to-cutoff drain happens after the engine
               is already off.
        When:  the trigger is read.
        Then:  it takes no drive-state or connection-state argument and is
               called unconditionally, like the interval sync (whose US-226
               invariant is the same one for the same reason).
        """
        signature = inspect.signature(
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint
        )
        assert list(signature.parameters) == ['self']


# ================================================================================
# The trigger's own posture
# ================================================================================


class TestTriggerPosture:
    """Soft-fail: battery bookkeeping must never cost a drive."""

    def test_noWriter_isASkipNotACrash(self) -> None:
        """
        Given: the drain writer failed to wire (no PowerMonitor, no database,
               or a wiring fault) so _drainEventWriter is None.
        When:  the loop ticks.
        Then:  it returns False quietly -- boot continues without the writer by
               design, and the loop must not notice.
        """
        orch = LifecycleMixin.__new__(LifecycleMixin)
        orch._drainEventWriter = None
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is False
        )

    def test_theAttributeMissingEntirely_isASkip(self) -> None:
        """
        Given: an orchestrator whose component init never reached the drain
               writer at all, so the attribute does not exist.
        When:  the loop ticks.
        Then:  it returns False rather than raising AttributeError into the
               loop that also drives OBD capture.
        """
        orch = LifecycleMixin.__new__(LifecycleMixin)
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is False
        )

    def test_aWriterFault_isSwallowed(self) -> None:
        """
        Given: a writer whose checkpoint raises (it is total by contract, so
               this is defence in depth on the loop's side).
        When:  the loop ticks.
        Then:  the exception does not escape.
        """
        orch = LifecycleMixin.__new__(LifecycleMixin)
        orch._drainEventWriter = MagicMock()
        orch._drainEventWriter.checkpointOpenDrainEvent.side_effect = OSError(
            'database is locked'
        )
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is False
        )

    def test_reportsTrueOnlyWhenACheckpointWasActuallyWritten(self) -> None:
        """
        Given: a writer that reports "not due" (None) and then reports a
               written checkpoint (a drain_event_id).
        When:  the loop ticks each time.
        Then:  the return distinguishes them.  "Not due" and "wrote a
               checkpoint" must never render alike, or the tick becomes
               unobservable in exactly the conditions worth observing.
        """
        orch = LifecycleMixin.__new__(LifecycleMixin)
        orch._drainEventWriter = MagicMock()
        orch._drainEventWriter.checkpointOpenDrainEvent.return_value = None
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is False
        )
        orch._drainEventWriter.checkpointOpenDrainEvent.return_value = 7
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is True
        )


# ================================================================================
# End to end through the REAL lifecycle wiring
# ================================================================================


class TestTheLoopCheckpointsTheWriterTheLifecycleBuilt:
    """The strongest guard here: one seam, not two that merely look alike."""

    def test_aRealWallPowerLossIsCheckpointedByTheRealTrigger(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: the real lifecycle wiring, a real PowerMonitor and a live gauge.
        When:  GPIO6 truth reports wall power LOST (opening a real row), and
               the run loop's own trigger then fires past the interval.
        Then:  the OPEN row carries live end_vcell_v / end_soc_pct /
               runtime_seconds and is STILL open.

        This is what proves the loop checkpoints the SAME writer instance the
        lifecycle registered on PowerMonitor.onTransition.  A test that built
        its own writer would pass even if _drainEventWriter were never set,
        which is the inert failure mode.
        """
        monitor = PowerMonitor(database=freshDb, enabled=True)
        hardware = MagicMock()
        hardware.upsMonitor = FakeUps()
        orch = _orch(
            database=freshDb, powerMonitor=monitor, hardwareManager=hardware,
        )
        orch._initializeDrainEventWriter()
        assert orch._drainEventWriter is not None, 'wiring premise failed'

        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)  # wall power LOST -> a row opens

        beforeId, beforeEndTs, beforeVcell, _, beforeRuntime = _openRow(freshDb)
        assert beforeEndTs is None and beforeVcell is None
        assert beforeRuntime is None, 'no checkpoint should exist yet'

        # Jump the writer's own monotonic source past the 30 s interval rather
        # than sleeping through it.  The cadence gate is the thing under test
        # everywhere else; here the subject is the CALL SITE.
        orch._drainEventWriter._monotonic = lambda: _WELL_PAST_THE_INTERVAL
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is True
        )

        afterId, afterEndTs, afterVcell, _, afterRuntime = _openRow(freshDb)
        assert afterId == beforeId, 'the checkpoint must not open a second row'
        assert afterEndTs is None, 'a checkpoint must never close the row'
        assert afterVcell == pytest.approx(3.47)
        assert afterRuntime is not None
        # end_soc_pct is deliberately NOT asserted here: this wiring test runs
        # the REAL uptime reader, which has no /proc/uptime on the dev bench,
        # so the US-234 cold-start guard correctly suppresses the register
        # SoC%% to NULL.  That suppression is a feature and is covered
        # explicitly in tests/pi/power/test_drain_checkpoint.py; pinning it
        # here would make this call-site guard fail for a platform reason.

    def test_onWallPowerWithNoDrainOpen_theTickWritesNothing(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: the real wiring and a Pi sitting on wall power -- the state it
               is in for almost all of its uptime.
        When:  the run-loop trigger fires past the interval.
        Then:  nothing is written and no row appears.  The common case must
               cost nothing and, above all, must not manufacture a drain
               record for a drain that is not happening.
        """
        monitor = PowerMonitor(database=freshDb, enabled=True)
        hardware = MagicMock()
        hardware.upsMonitor = FakeUps()
        orch = _orch(
            database=freshDb, powerMonitor=monitor, hardwareManager=hardware,
        )
        orch._initializeDrainEventWriter()

        monitor.checkPowerStatus(True)
        orch._drainEventWriter._monotonic = lambda: _WELL_PAST_THE_INTERVAL
        assert (
            ApplicationOrchestrator._maybeTriggerDrainCheckpoint(orch) is False
        )

        assert _openRow(freshDb) is None
