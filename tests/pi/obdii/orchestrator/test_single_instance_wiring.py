################################################################################
# File Name: test_single_instance_wiring.py
# Purpose/Description: US-361 (F-107) -- wiring tests for the orchestrator
#                      single-instance guard inside LifecycleMixin.
#                      _initializeSingleInstanceGuard is default-OFF (no-op
#                      unless pi.runtime.singleInstanceGuard.enabled is True);
#                      when enabled, a live foreign lock holder makes the
#                      orchestrator REFUSE to start (Mechanism B prevention).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-361) | Initial -- default-OFF no-op + enabled refuse +
#                               enabled stale-reclaim wiring coverage.
# ================================================================================
################################################################################

"""US-361 -- LifecycleMixin single-instance guard wiring (F-107 Mechanism B).

These exercise ``_initializeSingleInstanceGuard`` directly on a bare
``ApplicationOrchestrator`` (no full component boot needed).  Process liveness
is controlled by monkeypatching ``single_instance.processIsAlive`` so the
refuse-vs-reclaim decision is deterministic without spawning processes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import src.pi.obdii.orchestrator.single_instance as single_instance_mod
from src.pi.obdii.orchestrator.core import ApplicationOrchestrator
from src.pi.obdii.orchestrator.types import ComponentInitializationError


def _config(enabled: bool, lockPath: Path | None = None) -> dict[str, Any]:
    """Minimal tier-aware config toggling the single-instance guard."""
    guard: dict[str, Any] = {"enabled": enabled}
    if lockPath is not None:
        guard["lockPath"] = str(lockPath)
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {"runtime": {"singleInstanceGuard": guard}},
        "server": {},
    }


class TestSingleInstanceWiring:
    """Default-OFF no-op, enabled refusal, and enabled stale-reclaim."""

    def test_disabledByDefault_isNoOp(self, tmp_path: Path) -> None:
        """
        Given: config without the guard enabled.
        When: the guard init step runs.
        Then: it is a no-op -- no lockfile, guard reference stays None.
        """
        lockPath = tmp_path / "orchestrator.lock"
        orchestrator = ApplicationOrchestrator(
            config=_config(enabled=False, lockPath=lockPath), simulate=True
        )

        orchestrator._initializeSingleInstanceGuard()

        assert orchestrator._singleInstanceGuard is None
        assert not lockPath.exists()

    def test_enabled_liveForeignHolder_refusesStart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: the guard is enabled and a live foreign pid holds the lock.
        When: a second orchestrator runs the guard init step.
        Then: ComponentInitializationError is raised (refuse to start) and the
            orchestrator holds NO guard (so shutdown won't free the live lock).
        """
        lockPath = tmp_path / "orchestrator.lock"
        lockPath.write_text("999999", encoding="utf-8")
        monkeypatch.setattr(
            single_instance_mod, "processIsAlive", lambda _pid: True
        )
        orchestrator = ApplicationOrchestrator(
            config=_config(enabled=True, lockPath=lockPath), simulate=True
        )

        with pytest.raises(ComponentInitializationError) as excinfo:
            orchestrator._initializeSingleInstanceGuard()

        assert "single-instance" in str(excinfo.value).lower()
        assert orchestrator._singleInstanceGuard is None
        # Live holder's lock left intact.
        assert lockPath.read_text(encoding="utf-8").strip() == "999999"

    def test_enabled_staleLock_acquiresAndStampsOwnPid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: the guard is enabled and the lock holds a dead foreign pid.
        When: the guard init step runs.
        Then: the stale lock is reclaimed, stamped with our pid, and the guard
            reference is retained so shutdown can release it.
        """
        lockPath = tmp_path / "orchestrator.lock"
        lockPath.write_text("999999", encoding="utf-8")
        monkeypatch.setattr(
            single_instance_mod, "processIsAlive", lambda _pid: False
        )
        orchestrator = ApplicationOrchestrator(
            config=_config(enabled=True, lockPath=lockPath), simulate=True
        )

        orchestrator._initializeSingleInstanceGuard()

        assert orchestrator._singleInstanceGuard is not None
        assert lockPath.read_text(encoding="utf-8").strip() == str(os.getpid())

        # Release path frees the lock so a later start re-acquires cleanly.
        orchestrator._shutdownSingleInstanceGuard()
        assert orchestrator._singleInstanceGuard is None
        assert not lockPath.exists()
