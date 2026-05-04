################################################################################
# File Name: test_powersource_module_identity.py
# Purpose/Description: V0.24.1 hotfix regression -- cross-module PowerSource
#                      enum identity gate.  Drain Tests 1-9 across Sprints
#                      21-24 all hard-crashed at LiPo dropout (~3.30V) because
#                      every PowerDownOrchestrator tick bailed
#                      reason=power_source!=BATTERY.  Sprint 24 (US-279) wired
#                      an event-driven callback path that LOOKED correct in
#                      isolation but failed in production for a reason no test
#                      caught: src/pi/power/orchestrator.py imports
#                      `from src.pi.hardware.ups_monitor import PowerSource`
#                      while src/pi/obdii/orchestrator/lifecycle.py imports
#                      `from pi.hardware.ups_monitor import (...)` (no prefix).
#                      Production main.py adds BOTH `<repo>/` and `<repo>/src/`
#                      to sys.path -- so both forms resolve, but Python loads
#                      them as DISTINCT module objects with DISTINCT enum
#                      classes.  pi.PowerSource.BATTERY != src.pi.PowerSource.
#                      BATTERY -- the cross-boundary equality check fails on
#                      every tick.  Tests pre-fix all imported via a single
#                      consistent path so the bug was invisible in CI.
#                      This regression test reproduces the production scenario
#                      by deliberately mixing import paths and asserting the
#                      ladder still fires.  MUST FAIL pre-fix, MUST PASS post-
#                      fix where orchestrator.py uses `from pi.hardware.X`.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-03    | Rex (V0.24.1)| Initial -- closes the 9-drain saga via the
#                              | actual root cause (module identity), not the
#                              | wiring fault Spool's note diagnosed.
# ================================================================================
################################################################################

"""V0.24.1 hotfix: cross-module PowerSource enum identity regression.

The bug
-------
Drain Test 9 evidence on chi-eclipse-01 confirmed live::

    A module: pi.hardware.ups_monitor              (loaded via lifecycle.py)
    B module: src.pi.hardware.ups_monitor          (loaded via orchestrator.py)
    A.BATTERY == B.BATTERY:  False                 ← THE BUG

UpsMonitor's polling thread fires the registered callback with
``pi.hardware.ups_monitor.PowerSource.BATTERY`` (the no-prefix module's
enum, used by HardwareManager + lifecycle).  Orchestrator's
``_tickBody`` performs ``currentSource != _PS.BATTERY`` where ``_PS`` was
imported from ``src.pi.hardware.ups_monitor`` -- a distinct module
object with a distinct enum class.  The comparison is structurally
equivalent to ``EnumClassA.BATTERY != EnumClassB.BATTERY`` -- always
True.  Ticks bail 100% on every drain.  EXTERNAL comparison ALSO fails
for the same reason, which is why post-reboot ticks on AC also log
``reason=power_source!=BATTERY``.

The test fidelity gap that hid this for 4 sprints
-------------------------------------------------
Every test in ``tests/pi/`` imports via a single consistent path
(``from src.pi.X import ...``).  When pytest runs, only one module
object exists, so the enum equality works.  The bug requires BOTH
paths to be loaded simultaneously -- the production sys.path setup --
which never happens in unit tests.

This test deliberately imports via both paths and runs the
production-equivalent ladder firing flow.  It must fail pre-fix and
pass post-fix.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Production import shape mirrors hardware_manager.py:100 + lifecycle.py:1489.
# We want PowerDownOrchestrator loaded under the `src.pi.power.orchestrator`
# module name (matches hardware_manager.py:100), and PowerSource loaded
# under the `pi.hardware.ups_monitor` module name (matches lifecycle.py:1489
# which constructs the UpsMonitor instance and whose polling thread
# delivers enum values into the registered callback).
_orchestratorMod = importlib.import_module('src.pi.power.orchestrator')
_upsViaPiPath = importlib.import_module('pi.hardware.ups_monitor')
_upsViaSrcPath = importlib.import_module('src.pi.hardware.ups_monitor')

PowerDownOrchestrator = _orchestratorMod.PowerDownOrchestrator
PowerState = _orchestratorMod.PowerState
ShutdownThresholds = _orchestratorMod.ShutdownThresholds

# The production-equivalent enum classes -- the polling thread (lifecycle
# import) delivers PowerSourcePi values; the orchestrator's tick body
# imports its own _PS at call time and compares against THAT class.
PowerSourcePi = _upsViaPiPath.PowerSource
PowerSourceSrc = _upsViaSrcPath.PowerSource


# ============================================================================
# TestModulePathSeparation -- proves the dual-load condition is real
# ============================================================================


class TestModulePathSeparation:
    """Sanity gate: confirm both module paths resolve and produce DISTINCT
    enum classes when production sys.path is in effect.  Without this
    precondition, the regression test below would pass trivially even
    pre-fix and the gate would be meaningless.
    """

    def test_both_import_paths_resolve_under_test_runner(self) -> None:
        """pytest's rootdir discovery + tests/conftest.py adding src/
        together make both `pi.X` and `src.pi.X` importable -- mirroring
        production main.py.  This is the precondition the bug requires.

        Post-fix the self-alias collapses both names onto one module
        object whose internal ``__name__`` reflects whichever path
        loaded the file first; the assertion below only proves that
        both names resolve to importable modules, not what their
        canonical ``__name__`` happens to be.
        """
        assert _upsViaPiPath is not None
        assert _upsViaSrcPath is not None
        assert hasattr(_upsViaPiPath, 'PowerSource')
        assert hasattr(_upsViaSrcPath, 'PowerSource')

    def test_dual_paths_collapse_to_same_module_post_fix(self) -> None:
        """V0.24.1 fix invariant: ups_monitor.py's self-alias guard
        registers the module under BOTH ``pi.hardware.ups_monitor`` and
        ``src.pi.hardware.ups_monitor`` in sys.modules.  Subsequent
        imports under either name return the SAME module object,
        restoring enum identity across the boundary.

        Pre-fix this assertion FAILS (two distinct module objects, two
        distinct PowerSource enum classes -- the dual-load that caused
        every cross-module comparison to evaluate to inequality).
        Post-fix the alias collapses both names to one module object
        and enum identity is preserved.
        """
        assert _upsViaPiPath is _upsViaSrcPath, (
            "Self-alias guard in src/pi/hardware/ups_monitor.py must "
            "register the module under both `pi.hardware.ups_monitor` "
            "and `src.pi.hardware.ups_monitor` so cross-prefix imports "
            "return the same module object."
        )
        assert PowerSourcePi is PowerSourceSrc
        assert PowerSourcePi.BATTERY is PowerSourceSrc.BATTERY


# ============================================================================
# TestProductionImportPathLadderFires -- the actual hotfix regression gate
# ============================================================================


@pytest.fixture()
def thresholds() -> 'ShutdownThresholds':
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def orchestrator(thresholds: 'ShutdownThresholds') -> 'PowerDownOrchestrator':
    """A PowerDownOrchestrator instance loaded via the SAME module path
    HardwareManager uses in production (`src.pi.power.orchestrator`).
    Mocks recorder + shutdownAction so the test stays unit-scope; the
    only thing under test is the cross-module enum comparison in tick().
    """
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=MagicMock(),
        shutdownAction=MagicMock(),
    )


class TestProductionImportPathLadderFires:
    """Pre-fix gate for V0.24.1.

    The orchestrator class is loaded via ``src.pi.power.orchestrator``
    (matching ``hardware_manager.py:100``).  Inside ``_tickBody``, the
    function-local import ``from src.pi.hardware.ups_monitor import
    PowerSource as _PS`` produces an enum class from the ``src.pi``
    module.

    The polling-thread analogue -- mirroring how ``UpsMonitor`` instances
    constructed via ``lifecycle.py:1489`` (no prefix) deliver enum values
    into the registered callback -- pushes ``PowerSourcePi.BATTERY`` (the
    no-prefix module's enum) into ``orchestrator._onPowerSourceChange``.

    Pre-fix: the comparison ``effectiveSource != _PS.BATTERY`` evaluates
    to True (different classes), tick bails on every iteration, ladder
    never fires.

    Post-fix (orchestrator.py imports ``from pi.hardware.ups_monitor``
    instead of ``from src.pi.hardware.ups_monitor``): both sides of the
    comparison reference the SAME enum class, equality works, ladder
    fires.
    """

    def test_callback_with_pi_module_battery_advances_state(
        self, orchestrator: 'PowerDownOrchestrator',
    ) -> None:
        """Production-equivalent flow: callback fires with the PiPowerSource
        BATTERY value (the polling thread's enum), then tick reads
        self._powerSource and must advance from NORMAL to WARNING when
        VCELL crosses the threshold.

        This is the surgical end-to-end of the bug: pre-fix
        self._powerSource is set to PiPowerSource.BATTERY but
        ``_PS.BATTERY`` (loaded inside _tickBody from src.pi) is a
        different class, so the inequality fires and tick bails.
        """
        # Polling-thread analogue: deliver enum from the `pi.hardware.X`
        # module (the way lifecycle.py-constructed UpsMonitor delivers).
        orchestrator._onPowerSourceChange(PowerSourcePi.BATTERY)

        # VCELL has crossed the WARNING threshold.  Caller passes
        # PiPowerSource.BATTERY too -- the orchestrator's internal
        # comparison is what we're testing.
        orchestrator.tick(
            currentVcell=3.65,
            currentSource=PowerSourcePi.BATTERY,
        )

        assert orchestrator.state == PowerState.WARNING, (
            "After callback delivers BATTERY enum from pi.hardware.X, "
            "tick() must advance state.  Failure here means the "
            "orchestrator's internal _PS import resolves to a different "
            "module than the callback-delivered enum -- the V0.24.1 "
            "module identity bug."
        )

    def test_full_drain_ladder_fires_with_cross_module_enum(
        self, orchestrator: 'PowerDownOrchestrator',
    ) -> None:
        """Stair-step drain crosses all three thresholds; ladder must
        traverse NORMAL -> WARNING -> IMMINENT -> TRIGGER and invoke
        shutdownAction exactly once, all using enums from the
        `pi.hardware.X` module the polling thread uses in production.
        """
        orchestrator._onPowerSourceChange(PowerSourcePi.BATTERY)

        for stepVcell in (3.80, 3.65, 3.50, 3.40):
            orchestrator.tick(
                currentVcell=stepVcell,
                currentSource=PowerSourcePi.BATTERY,
            )

        assert orchestrator.state == PowerState.TRIGGER
        assert orchestrator._shutdownAction.call_count == 1

    def test_ac_restore_with_pi_module_external_resets_to_normal(
        self, orchestrator: 'PowerDownOrchestrator',
    ) -> None:
        """Symmetry guard: BATTERY -> EXTERNAL transition delivered as
        ``PiPowerSource.EXTERNAL`` must trigger _acRestore, returning the
        orchestrator to NORMAL.  Pre-fix the ``currentSource ==
        _PS.EXTERNAL`` check fails for the same module-identity reason
        and the orchestrator stays in WARNING/IMMINENT after AC return.
        """
        # Drain into WARNING.
        orchestrator._onPowerSourceChange(PowerSourcePi.BATTERY)
        orchestrator.tick(
            currentVcell=3.65, currentSource=PowerSourcePi.BATTERY,
        )
        assert orchestrator.state == PowerState.WARNING

        # AC restore -- callback delivers EXTERNAL from pi.hardware.X.
        orchestrator._onPowerSourceChange(PowerSourcePi.EXTERNAL)
        orchestrator.tick(
            currentVcell=3.95, currentSource=PowerSourcePi.EXTERNAL,
        )

        assert orchestrator.state == PowerState.NORMAL, (
            "AC restore must reset state to NORMAL.  Failure here means "
            "the EXTERNAL comparison hit the same module-identity bug "
            "that broke BATTERY -- both branches of _tickBody's source "
            "guard need to share the import path with the callback."
        )
