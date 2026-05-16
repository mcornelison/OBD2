################################################################################
# File Name: test_orchestrator_boot_progress.py
# Purpose/Description: Orchestrator emits the exact boot-progress rungs at the
#                      exact seams of the low-battery shutdown ladder.
# Author: (implementation plan 2026-05-15)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- T8 orchestrator boot_progress marks.
# ================================================================================
################################################################################

"""T8: PowerDownOrchestrator boot-progress milestone seam verification.

The orchestrator must emit boot-progress breadcrumb rungs at the exact
statement seams of the low-battery shutdown ladder so the next boot can
derive how far the shutdown sequence progressed:

* ``_enterWarning``  -> ``WARNING``  (right after the opening logger.warning)
* ``_enterImminent`` -> ``IMMINENT`` (right after the opening logger.warning)
* ``_enterTrigger``  -> ``TRIGGER`` (before ``_closeDrainEvent``),
  ``DRAIN_CLOSED`` (after ``_closeDrainEvent`` returns),
  ``TRIGGER_ROW_WRITTEN`` (after ``_writePowerLogStage``)

The writer is injected via the constructor (production wires the default
``boot_progress.markMilestone`` closure; tests inject a capturing fake).
A breadcrumb-write failure must NEVER break the ladder -- that fail-safe
isolation is the entire point of the thin ``_markBootProgress`` wrapper.
"""

from __future__ import annotations

from src.pi.diagnostics.boot_progress import Stage
from src.pi.power.orchestrator import PowerDownOrchestrator, ShutdownThresholds


class _FakeRecorder:
    """Minimal BatteryHealthRecorder stand-in.

    Implements only the two methods the orchestrator calls
    (:meth:`startDrainEvent` / :meth:`endDrainEvent`) as no-ops so the
    test exercises the ladder seams without a real database.
    """

    def startDrainEvent(self, *, startSoc: float, loadClass: str = "production") -> int:
        return 1

    def endDrainEvent(
        self,
        *,
        drainEventId: int,
        endSoc: float,
        ambientTempC: float | None = None,
    ) -> None:
        return None


def _buildOrchestrator(captured: list[str]) -> PowerDownOrchestrator:
    """Construct an orchestrator with a capturing boot-progress writer.

    Args:
        captured: List that each emitted ``stage.value`` is appended to.

    Returns:
        A wired :class:`PowerDownOrchestrator` whose ``shutdownAction`` is
        a no-op (TRIGGER must not actually power off the test host).
    """
    thresholds = ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=_FakeRecorder(),
        shutdownAction=lambda: None,
        bootProgressWriter=lambda stage, vcell: captured.append(stage.value),
    )


class TestEnterTriggerSeamOrder:
    """``_enterTrigger`` emits TRIGGER -> DRAIN_CLOSED -> TRIGGER_ROW_WRITTEN
    at the exact seams of the ladder's terminal stage."""

    def test_enterTrigger_emitsThreeMarksInLadderSeamOrder(self) -> None:
        """
        Given: an orchestrator with a capturing boot-progress writer.
        When: ``_enterTrigger`` is driven at a vcell at the trigger threshold.
        Then: the first three captured marks are TRIGGER (before
            _closeDrainEvent), DRAIN_CLOSED (after it returns),
            TRIGGER_ROW_WRITTEN (after _writePowerLogStage), in that order.
        """
        # Arrange
        captured: list[str] = []
        orchestrator = _buildOrchestrator(captured)

        # Act -- vcell AT the trigger threshold (3.45V <= triggerVcell).
        orchestrator._enterTrigger(3.45)  # noqa: SLF001

        # Assert
        assert captured[:3] == [
            Stage.TRIGGER.value,
            Stage.DRAIN_CLOSED.value,
            Stage.TRIGGER_ROW_WRITTEN.value,
        ]


class TestWarningAndImminentMarks:
    """``_enterWarning`` / ``_enterImminent`` emit their rungs immediately
    after each method's opening logger.warning."""

    def test_enterWarning_thenEnterImminent_emitWarningThenImminent(
        self,
    ) -> None:
        """
        Given: an orchestrator with a capturing boot-progress writer.
        When: ``_enterWarning`` then ``_enterImminent`` are driven.
        Then: a WARNING mark is emitted, then an IMMINENT mark.
        """
        # Arrange
        captured: list[str] = []
        orchestrator = _buildOrchestrator(captured)

        # Act
        orchestrator._enterWarning(3.68)  # noqa: SLF001
        orchestrator._enterImminent(3.54)  # noqa: SLF001

        # Assert
        assert Stage.WARNING.value in captured
        assert Stage.IMMINENT.value in captured
        assert captured.index(Stage.WARNING.value) < captured.index(
            Stage.IMMINENT.value
        )
