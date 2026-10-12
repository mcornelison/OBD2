################################################################################
# File Name: test_obd_connection_force_mandatory.py
# Purpose/Description: US-432 (BL-016, Option B) -- the ObdConnection WRAPPER
#                      carries an engine-confirmed latch that forces KNOWN-
#                      MANDATORY Mode-01 PIDs (RPM) past python-obd's dark-ECU
#                      support cache via a force read.  After a cold-boot-key-OFF
#                      connect, python-obd's supported_commands is probed with
#                      the engine off, so RPM is masked and query() returns a
#                      null response WITHOUT wire traffic -- the escalation
#                      swallows it and drive_start never fires.  The latch (set
#                      on the engine-on escalation edge, cleared on drive_end +
#                      disconnect) makes query() pass force=True for RPM only --
#                      SCOPED, never blanket (a blanket force re-exposes the
#                      0x42/0x0B/0x15 garbage the US-199 probe silent-skips).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-432) | Initial -- the connection-scoped force-mandatory
#               |              | latch contract (RPM only; scoped, not blanket;
#               |              | cleared on disconnect).
# ================================================================================
################################################################################

"""US-432 / BL-016 -- connection-scoped force-mandatory-PID latch contract.

RPM is a mandatory Mode-01 PID (0x0C) -- always supported by any OBD-II ECU
when the engine is running.  But the US-199 supported-PID probe runs once at
connect time; on a cold-boot-key-OFF sequence that connect happens with the
engine OFF and the dark ECU answers "RPM unsupported", poisoning python-obd's
internal ``supported_commands`` cache for the life of the connection.  Every
subsequent ``obd.query(RPM)`` then returns a null response WITHOUT sending an
010C frame -- the escalation probe reads ``None`` and the drive never starts.

Atlas Option B (BL-016): un-mask RPM past that stale cache with a force read,
SCOPED to known-mandatory Mode-01 PIDs.  The latch is connection-scoped: the
orchestrator sets it on the engine-on escalation edge and clears it on
drive_end; ``disconnect()`` clears it too (a fresh connection re-probes and is
dark again until the next escalation).  These tests hit the real
``ObdConnection.query()`` path with a recording ``python-obd`` double.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.pi.obdii.obd_connection import ObdConnection

# ================================================================================
# Fakes
# ================================================================================


class _RecordingObd:
    """A ``python-obd`` double that records the ``force`` kwarg per query.

    The real ``obd.OBD.query(cmd, force=False)`` skips the supported-command
    check when ``force=True``.  This double records ``(commandName, force)`` for
    every query so a test can assert the wrapper forwards force exactly for the
    scoped mandatory PIDs.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, bool]] = []
        # python-obd exposes this; the US-199 probe reads it (no query).
        self.supported_commands: list[Any] = []

    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def query(self, cmd: Any, force: bool = False) -> Any:
        name = getattr(cmd, "name", None)
        if name is None and isinstance(cmd, str):
            name = cmd
        self.calls.append((name, force))
        return SimpleNamespace(value=800.0, unit="rpm", is_null=lambda: False)


def _buildConnectedConnection() -> tuple[ObdConnection, _RecordingObd]:
    """A connected ``ObdConnection`` backed by a fresh ``_RecordingObd``.

    ``macAddress`` is a literal path so ``_resolvePort`` skips the real rfcomm
    bind; the injected factory bypasses the real ``obd.OBD(...)`` ctor so no
    serial hardware is touched.
    """
    theObd = _RecordingObd()
    conn = ObdConnection(
        config={
            "pi": {
                "bluetooth": {
                    "macAddress": "/dev/rfcomm-test",
                    "retryDelays": [0],
                    "maxRetries": 0,
                    "connectionTimeoutSeconds": 1,
                },
            },
        },
        obdFactory=lambda serialPort, timeout: theObd,
    )
    assert conn.connect() is True
    return conn, theObd


def _rpmCommand() -> Any:
    """A command object with ``.name == 'RPM'`` (mirrors obdlib.commands.RPM)."""
    return SimpleNamespace(name="RPM")


def _coolantCommand() -> Any:
    """A NON-mandatory command object (must never be force-read)."""
    return SimpleNamespace(name="COOLANT_TEMP")


# ================================================================================
# Default: latch off -> no force (regression guard -- unchanged read path)
# ================================================================================


class TestDefaultNoForce:
    """With the latch unset, every query goes through un-forced (status quo)."""

    def test_latchOffByDefault(self) -> None:
        conn, _ = _buildConnectedConnection()
        assert conn.isForcingMandatoryPids() is False

    def test_rpmQuery_notForced_whenLatchOff(self) -> None:
        conn, theObd = _buildConnectedConnection()
        conn.query(_rpmCommand())
        assert theObd.calls == [("RPM", False)], (
            "With the engine-confirmed latch OFF, RPM must be queried WITHOUT "
            f"force (status quo read path); got {theObd.calls}"
        )


# ================================================================================
# Latch on -> force scoped to mandatory PIDs only (Option B, not blanket)
# ================================================================================


class TestForceMandatoryLatch:
    """Setting the latch forces RPM past the dark-ECU support cache -- RPM only."""

    def test_latchSet_forcesRpm(self) -> None:
        conn, theObd = _buildConnectedConnection()
        conn.setEngineConfirmedForceMandatory(True)
        assert conn.isForcingMandatoryPids() is True
        conn.query(_rpmCommand())
        assert theObd.calls == [("RPM", True)], (
            "Engine-confirmed latch ON: RPM (mandatory Mode-01) must be "
            f"force-read past python-obd's stale support cache; got {theObd.calls}"
        )

    def test_latchSet_doesNotForceNonMandatoryPid(self) -> None:
        conn, theObd = _buildConnectedConnection()
        conn.setEngineConfirmedForceMandatory(True)
        conn.query(_coolantCommand())
        assert theObd.calls == [("COOLANT_TEMP", False)], (
            "SCOPED, not blanket: a NON-mandatory PID must NEVER be force-read "
            "even with the latch on (blanket forcing re-exposes the "
            f"0x42/0x0B/0x15 garbage US-199 silent-skips); got {theObd.calls}"
        )

    def test_stringCommand_rpm_isForced(self) -> None:
        """When obdlib is absent, _getObdCommand returns the bare string 'RPM'."""
        conn, theObd = _buildConnectedConnection()
        conn.setEngineConfirmedForceMandatory(True)
        conn.query("RPM")
        assert theObd.calls == [("RPM", True)]

    def test_latchCleared_returnsToNoForce(self) -> None:
        conn, theObd = _buildConnectedConnection()
        conn.setEngineConfirmedForceMandatory(True)
        conn.setEngineConfirmedForceMandatory(False)
        assert conn.isForcingMandatoryPids() is False
        conn.query(_rpmCommand())
        assert theObd.calls == [("RPM", False)]


# ================================================================================
# Latch lifecycle: cleared on disconnect (fresh connection is dark again)
# ================================================================================


class TestLatchClearedOnDisconnect:
    """A disconnect clears the latch so a reconnect starts un-forced."""

    def test_disconnect_clearsLatch(self) -> None:
        conn, _ = _buildConnectedConnection()
        conn.setEngineConfirmedForceMandatory(True)
        assert conn.isForcingMandatoryPids() is True

        conn.disconnect()

        assert conn.isForcingMandatoryPids() is False, (
            "disconnect() must clear the engine-confirmed latch -- the next "
            "connection re-probes supported_commands and is dark again until a "
            "new escalation re-arms it (no stale force carried across connects)."
        )
