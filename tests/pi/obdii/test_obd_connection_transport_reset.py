################################################################################
# File Name: test_obd_connection_transport_reset.py
# Purpose/Description: US-512 -- ObdConnection.resetTransport() + the failed-
#                      attempt binding drop that ends BL-025's stale-rfcomm-
#                      retry-forever, plus runtime bond assurance on connect.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Rex (US-512) | Initial -- BT capture hardening (BL-025 P1).
# ================================================================================
################################################################################

"""The defect these tests pin.

``rfcomm bind`` is a KERNEL TABLE ENTRY.  It outlives the ACL link: when the
dongle drops (engine off, out of range, adapter reset), ``/dev/rfcomm0`` and
the bind record are both still there.  :func:`bluetooth_helper.bindRfcomm` is
idempotent by design, so it sees "already bound to the right MAC", short-
circuits, and returns the same path.  ``obd.OBD()`` then opens a DEAD tty.
Retry, and the exact same thing happens -- forever.  That is the
stale-rfcomm-retry-forever behaviour in BL-025.

The fix is Spool's transport reset: disconnect -> releaseRfcomm -> re-bind ->
reconnect, so a recovery attempt always gets a genuinely new transport.  Two
call sites need it and only one of them goes through ``reconnect()``:

* :meth:`ObdConnection.reconnect` -- the ADAPTER_UNREACHABLE / recovery-mixin path.
* the per-attempt failure path inside ``_performConnect`` -- which is what the
  US-338 post-failure heartbeat drives, since it calls ``connect()`` directly
  and never touches ``reconnect()``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.pi.obdii import bluetooth_helper
from src.pi.obdii.obd_connection import ObdConnection
from tests.pi.obdii.bt_stack_fake import DEFAULT_MAC, FakeBtStack

MAC = DEFAULT_MAC


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> FakeBtStack:
    """A fake dongle wired in at the SUBPROCESS seam.

    The real ``bindRfcomm`` / ``releaseRfcomm`` / ``resetRfcommBinding`` run --
    including the already-bound short-circuit that IS the defect.  Stubbing
    those functions instead would delete the bug from the test.
    """
    fake = FakeBtStack()
    monkeypatch.setattr(
        "src.pi.obdii.bluetooth_helper._defaultRunner", fake.runner
    )
    return fake


def _buildConfig(port: str = MAC, **overrides: Any) -> dict[str, Any]:
    bluetooth = {
        "macAddress": port,
        "retryDelays": [],
        "maxRetries": 0,
        "connectionTimeoutSeconds": 5,
    }
    bluetooth.update(overrides)
    return {"pi": {"bluetooth": bluetooth}}


# ================================================================================
# resetTransport
# ================================================================================

class TestResetTransport:

    def test_resetTransport_afterLinkDrop_yieldsAFreshBinding(self, stack) -> None:
        """
        Given: a connection whose BT link has dropped (bind entry still present)
        When:  the transport is reset
        Then:  the binding is released and re-bound, and the fresh path returns
        """
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        assert conn.connect() is True

        stack.dropLink()
        assert stack.isBound() is True      # the entry survives the link...
        assert stack.isFresh() is False     # ...and is dead

        path = conn.resetTransport()

        assert path == "/dev/rfcomm0"
        assert stack.isFresh() is True
        assert stack.releaseCount() >= 1

    def test_resetTransport_leavesTheTransportBound_notReleased(self, stack) -> None:
        """The reconnect loop's probe requires the binding to EXIST.

        A recovery that only released would leave
        ``bluetooth_helper.isRfcommReachable`` permanently False -- the loop
        would then wait forever for a state its own teardown made unreachable.
        """
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        conn.connect()
        stack.dropLink()

        conn.resetTransport()

        assert stack.isBound() is True
        assert bluetooth_helper.isRfcommReachable(
            device=0, subprocessRunner=stack.runner, pathExists=stack.pathExists
        ) is True

    def test_resetTransport_pathStylePort_doesNotTouchTheBinding(self, stack) -> None:
        """BC: a literal /dev/rfcommN means someone else owns the bind."""
        stack.seedInheritedBinding()        # bound by connect_obdlink.sh
        conn = ObdConnection(_buildConfig("/dev/rfcomm0"), obdFactory=stack.obdFactory)
        conn.connect()

        path = conn.resetTransport()

        assert path is None
        assert stack.releaseCount() == 0
        assert stack.bindCount() == 0

    def test_resetTransport_rebindFails_returnsNoneNeverRaises(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No transport is an honest answer; an exception out of a recovery
        path is not -- it would surface as FATAL and bounce the service."""
        def failingReset(macAddress: str, device: int = 0, channel: int = 1,
                         subprocessRunner: Any = None) -> str:
            raise bluetooth_helper.BluetoothHelperError(
                "rfcomm bind 0 failed (rc=1): Can't create device: Host is down"
            )

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.resetRfcommBinding",
            failingReset,
        )
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)

        assert conn.resetTransport() is None

    def test_resetTransport_advancesGenerationSoOrphanedDaemonsAreFenced(
        self, stack
    ) -> None:
        """The US-441 epoch fence must still hold across a reset -- a daemon
        holding the pre-reset generation must not drive the new transport."""
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        conn.connect()
        before = conn.activeGeneration()

        conn.resetTransport()

        assert conn.activeGeneration() > before

    def test_resetTransport_neverTouchesTheRadio(self, stack) -> None:
        """AC4: no rfkill / hciconfig / power-off anywhere on the reset path.

        The 07-03 capture killer was a PERSISTED rfkill soft-block that
        systemd-rfkill restored on every boot.  A recovery that cycles the
        radio can re-arm exactly that.
        """
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        conn.connect()
        stack.dropLink()

        conn.resetTransport()

        for line in stack.commandLines():
            assert not line.startswith("rfkill")
            assert not line.startswith("hciconfig")
            assert not line.startswith("nmcli")
            assert "power off" not in line


# ================================================================================
# reconnect() goes through the reset
# ================================================================================

class TestReconnectResetsTheTransport:

    def test_reconnect_afterLinkDrop_recovers(self, stack) -> None:
        """
        Given: a live connection whose link then drops
        When:  reconnect() runs
        Then:  it re-binds a fresh transport and comes back connected
        """
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        assert conn.connect() is True

        stack.dropLink()

        assert conn.reconnect() is True
        assert conn.isConnected() is True

    def test_reconnect_inheritedBinding_recovers(self, stack) -> None:
        """The case plain disconnect()+connect() CANNOT fix.

        ``disconnect()`` releases only a binding this instance created.  When
        the entry came from a killed predecessor, ``_boundRfcomm`` is False, the
        release is skipped, ``bindRfcomm`` short-circuits on the inherited entry
        and the "reconnect" re-opens the dead tty.
        """
        stack.seedInheritedBinding()
        stack.dropLink()
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        assert conn._boundRfcomm is False

        assert conn.reconnect() is True

    def test_reconnect_releasesBeforeRebinding_notTheIdempotentShortCircuit(
        self, stack
    ) -> None:
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        conn.connect()
        releasesBefore = stack.releaseCount()

        stack.dropLink()
        conn.reconnect()

        assert stack.releaseCount() > releasesBefore


# ================================================================================
# The heartbeat path -- connect(), never reconnect()
# ================================================================================

class TestFailedAttemptDropsTheStaleBinding:
    """US-338's post-failure heartbeat calls ``connect()`` directly.

    If a failed attempt leaves the stale binding in place, every subsequent
    heartbeat tick re-opens the same dead tty via bindRfcomm's short-circuit --
    the literal forever-loop of BL-025.
    """

    def test_connect_afterFailedAttempt_nextConnectRebindsAndSucceeds(
        self, stack
    ) -> None:
        """
        Given: the link dropped while nothing called disconnect() (the
               heartbeat path -- there is no teardown between ticks)
        When:  connect() is retried
        Then:  the stale binding is dropped, a fresh one is bound, capture
               can resume
        """
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        assert conn.connect() is True

        stack.dropLink()
        # Tick 1: the open lands on the stale binding and fails...
        assert conn.connect() is False
        # ...but the failure must have dropped it, so tick 2 re-binds fresh.
        assert conn.connect() is True

    def test_connect_staleBindingInheritedFromAPriorProcess_isDroppedNotReused(
        self, stack
    ) -> None:
        """The version of BL-025 that survives `systemctl restart`.

        A SIGKILLed / crashed predecessor never ran disconnect(), so its rfcomm
        bind is still in the kernel table when the new process starts.  The new
        ObdConnection has ``_boundRfcomm=False`` -- it did not bind it -- so a
        release keyed on "did WE bind it?" skips, bindRfcomm short-circuits on
        the inherited entry, and the fresh process opens the same dead tty.
        Restarting the service therefore does NOT clear the fault, which is why
        this looked unfixable in the field.  The drop must be keyed on "the
        configured port is a MAC", not on our own bookkeeping.
        """
        stack.seedInheritedBinding()     # predecessor's bind, still in the table
        stack.dropLink()                 # ...and its link is long gone
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        assert conn._boundRfcomm is False

        assert conn.connect() is False   # attempt 1 lands on the inherited entry
        assert conn.connect() is True    # attempt 2 must get a fresh binding

    def test_connect_failedAttempt_releasesTheBinding(self, stack) -> None:
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)
        conn.connect()
        stack.dropLink()
        releasesBefore = stack.releaseCount()

        conn.connect()

        assert stack.releaseCount() > releasesBefore

    def test_connect_failedAttempt_pathStylePort_doesNotReleaseSomeoneElsesBind(
        self, stack
    ) -> None:
        stack.seedInheritedBinding()
        conn = ObdConnection(
            _buildConfig("/dev/rfcomm0"), obdFactory=stack.obdFactory
        )
        conn.connect()
        stack.dropLink()

        conn.connect()

        assert stack.releaseCount() == 0

    def test_connect_withRetries_recoversWithinASingleCall(self, stack) -> None:
        """Within one connect(), retry N+1 must not inherit N's dead tty.

        With retries configured the recovery does not even need a second
        connect(): attempt 1 fails on the stale binding and drops it, attempt 2
        binds fresh and succeeds.  A short-circuiting retry loop would burn
        every attempt on the same dead tty.
        """
        conn = ObdConnection(
            _buildConfig(retryDelays=[0, 0], maxRetries=2),
            obdFactory=stack.obdFactory,
        )
        conn.connect()
        stack.dropLink()
        bindsBefore = stack.bindCount()

        assert conn.connect() is True
        assert stack.bindCount() == bindsBefore + 1   # exactly one fresh bind


# ================================================================================
# Runtime bond assurance
# ================================================================================

class TestBondAssuranceOnConnect:

    def test_connect_lostTrust_isRestoredBeforeTheBind(self, stack) -> None:
        """
        Given: the bluez bond lost its Trusted flag (bluez then refuses an
               unattended reconnect -- a dead link whose only apparent fix is
               a manual re-pair, which needs the car running)
        When:  the capture service connects
        Then:  trust is restored, with the `trust` issued BEFORE the bind
        """
        stack.trusted = False
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)

        assert conn.connect() is True
        assert stack.trusted is True

        lines = stack.commandLines()
        trustAt = next(i for i, line in enumerate(lines) if "trust" in line)
        bindAt = next(i for i, line in enumerate(lines) if "rfcomm bind" in line)
        assert trustAt < bindAt

    def test_connect_alreadyTrusted_doesNotIssueTrust(self, stack) -> None:
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)

        conn.connect()

        assert not any("trust" in line for line in stack.commandLines())

    def test_connect_pathStylePort_skipsBondAssurance(self, stack) -> None:
        """A /dev/rfcommN literal carries no MAC to assure."""
        stack.seedInheritedBinding()
        conn = ObdConnection(
            _buildConfig("/dev/rfcomm0"), obdFactory=stack.obdFactory
        )

        conn.connect()

        assert not any("bluetoothctl" in line for line in stack.commandLines())

    def test_connect_bondAssuranceExplodes_connectStillProceeds(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Best-effort: the check must never be able to fail a connect that
        would otherwise have worked."""
        def boom(macAddress: str, subprocessRunner: Any = None):
            raise RuntimeError("bluetoothd not running")

        monkeypatch.setattr(
            "src.pi.obdii.obd_connection.bluetooth_helper.ensureTrusted", boom
        )
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)

        assert conn.connect() is True

    def test_connect_bondNotDurable_warnsWithTheRepairInstruction(
        self, stack, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An un-repairable bond (bluez has no record) must be LOUD -- silence
        here is a mystery dead link on a car dashboard."""
        stack.known = False
        conn = ObdConnection(_buildConfig(), obdFactory=stack.obdFactory)

        caplog.set_level("WARNING")
        conn.connect()

        assert any("pair_obdlink" in rec.message for rec in caplog.records)


