################################################################################
# File Name: test_bluetooth_bond_and_reset.py
# Purpose/Description: US-512 -- bluetooth_helper transport-reset (release then
#                      re-bind, never the idempotent short-circuit) + durable
#                      bond state reading / runtime trust assurance.
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

"""Unit coverage for the US-512 helper layer.

Two capabilities, both driven through the injectable ``subprocessRunner`` seam
so nothing here touches a real ``rfcomm`` / ``bluetoothctl`` (the dev box is
Windows and has neither):

1. :func:`resetRfcommBinding` -- Spool's transport reset.  ``bindRfcomm`` is
   deliberately IDEMPOTENT: when ``/dev/rfcommN`` is already bound to the same
   MAC it short-circuits and returns the path WITHOUT touching the kernel.
   That is correct for a first connect and catastrophic for a recovery -- a
   dead link leaves the bind entry in place, so the short-circuit hands back
   the same dead tty forever (BL-025's stale-rfcomm-retry-forever).  The reset
   forces release-then-bind so the next open gets a genuinely new transport.

2. :func:`readBondState` / :func:`ensureTrusted` -- the runtime half of the
   durable-bond story.  ``scripts/pair_obdlink.sh`` writes Paired+Bonded+
   Trusted at pair time; nothing at runtime ever looked at it again, so a lost
   ``Trusted`` flag (the one half bluez can drop without the dongle present)
   meant a silently un-reconnectable link whose only "fix" was a manual
   re-pair.  Trust is repairable without the dongle powered; pairing is not --
   so ``ensureTrusted`` repairs what it can and reports the rest honestly.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from src.pi.obdii import bluetooth_helper

# ================================================================================
# Fakes
# ================================================================================

class _RecordingRunner:
    """Fake CLI: records every argv and replays scripted results.

    ``results`` maps a joined-argv PREFIX to a ``(returncode, stdout, stderr)``
    triple; the longest matching prefix wins so a test can script
    ``rfcomm show 0`` differently from ``rfcomm bind 0 ...``.
    """

    def __init__(self, results: dict[str, tuple[int, str, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.results = results or {}

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        best: tuple[int, str, str] | None = None
        bestLen = -1
        for prefix, result in self.results.items():
            if joined.startswith(prefix) and len(prefix) > bestLen:
                best, bestLen = result, len(prefix)
        rc, out, err = best if best is not None else (0, "", "")
        return subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=out, stderr=err)

    def commandLines(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


MAC = "00:04:3E:85:0D:FB"
BOUND_SHOW = f"rfcomm0: {MAC} channel 1 clean\n"
UNBOUND_SHOW = (1, "", "Can't get info: No such device\n")


def _infoOutput(paired: str, bonded: str, trusted: str) -> str:
    return (
        f"Device {MAC} (public)\n"
        "\tName: OBDLink LX\n"
        f"\tPaired: {paired}\n"
        f"\tBonded: {bonded}\n"
        f"\tTrusted: {trusted}\n"
        "\tBlocked: no\n"
    )


# ================================================================================
# resetRfcommBinding -- Spool's transport reset
# ================================================================================

class TestResetRfcommBinding:
    """The reset must NEVER take bindRfcomm's already-bound short-circuit."""

    def test_resetRfcommBinding_alreadyBoundToSameMac_stillReleasesThenRebinds(self) -> None:
        """
        Given: /dev/rfcomm0 is already bound to the target MAC (a DEAD link --
               the kernel bind entry outlives the ACL connection)
        When:  the transport is reset
        Then:  release runs and bind runs -- the idempotent short-circuit that
               would hand back the same dead tty is bypassed
        """
        runner = _RecordingRunner({
            f"{bluetooth_helper.RFCOMM_CMD} show 0": (0, BOUND_SHOW, ""),
        })

        path = bluetooth_helper.resetRfcommBinding(
            macAddress=MAC, device=0, channel=1, subprocessRunner=runner
        )

        assert path == "/dev/rfcomm0"
        lines = runner.commandLines()
        assert f"{bluetooth_helper.RFCOMM_CMD} release 0" in lines
        assert f"{bluetooth_helper.RFCOMM_CMD} bind 0 {MAC} 1" in lines
        # Order matters: a bind before the release would fail or no-op.
        assert lines.index(f"{bluetooth_helper.RFCOMM_CMD} release 0") < lines.index(
            f"{bluetooth_helper.RFCOMM_CMD} bind 0 {MAC} 1"
        )

    def test_resetRfcommBinding_notBound_bindsWithoutFailing(self) -> None:
        """
        Given: nothing is bound (release is a no-op)
        When:  the transport is reset
        Then:  a bind is still issued and the path is returned
        """
        runner = _RecordingRunner({
            f"{bluetooth_helper.RFCOMM_CMD} show 0": UNBOUND_SHOW,
        })

        path = bluetooth_helper.resetRfcommBinding(
            macAddress=MAC, device=0, channel=1, subprocessRunner=runner
        )

        assert path == "/dev/rfcomm0"
        assert f"{bluetooth_helper.RFCOMM_CMD} bind 0 {MAC} 1" in runner.commandLines()

    def test_resetRfcommBinding_honorsDeviceAndChannel(self) -> None:
        runner = _RecordingRunner({
            f"{bluetooth_helper.RFCOMM_CMD} show 2": (0, f"rfcomm2: {MAC} channel 3 clean\n", ""),
        })

        path = bluetooth_helper.resetRfcommBinding(
            macAddress=MAC, device=2, channel=3, subprocessRunner=runner
        )

        assert path == "/dev/rfcomm2"
        assert f"{bluetooth_helper.RFCOMM_CMD} bind 2 {MAC} 3" in runner.commandLines()

    def test_resetRfcommBinding_bindFails_raisesBluetoothHelperError(self) -> None:
        """A reset that cannot re-bind must say so -- callers treat that as
        'no transport', not as a fresh one."""
        runner = _RecordingRunner({
            f"{bluetooth_helper.RFCOMM_CMD} show 0": UNBOUND_SHOW,
            f"{bluetooth_helper.RFCOMM_CMD} bind 0": (1, "", "Can't create device: Host is down\n"),
        })

        with pytest.raises(bluetooth_helper.BluetoothHelperError) as excinfo:
            bluetooth_helper.resetRfcommBinding(
                macAddress=MAC, device=0, channel=1, subprocessRunner=runner
            )

        assert "Host is down" in str(excinfo.value)

    def test_resetRfcommBinding_rejectsNonMac(self) -> None:
        runner = _RecordingRunner()
        with pytest.raises(ValueError):
            bluetooth_helper.resetRfcommBinding(
                macAddress="/dev/rfcomm0", subprocessRunner=runner
            )
        assert runner.calls == []

    def test_resetRfcommBinding_neverTouchesTheRadio(self) -> None:
        """AC4: the reset must not re-introduce the rfkill soft-block class.

        The 07-03 capture killer was a PERSISTED rfkill soft-block.  Any
        recovery path that powers the radio down -- rfkill, hciconfig down,
        `bluetoothctl power off`, nmcli -- risks systemd-rfkill saving that
        state at shutdown and re-blocking BT on the next boot.  The reset is
        confined to the rfcomm binding, one layer above the radio.
        """
        runner = _RecordingRunner({
            f"{bluetooth_helper.RFCOMM_CMD} show 0": (0, BOUND_SHOW, ""),
        })

        bluetooth_helper.resetRfcommBinding(macAddress=MAC, subprocessRunner=runner)

        for line in runner.commandLines():
            assert not line.startswith("rfkill")
            assert not line.startswith("hciconfig")
            assert not line.startswith("nmcli")
            assert "power off" not in line


# ================================================================================
# Bond state -- the runtime half of the durable-bond story
# ================================================================================

class TestParseBondState:

    def test_parseBondState_fullyBonded_allFlagsTrue(self) -> None:
        state = bluetooth_helper.parseBondState(_infoOutput("yes", "yes", "yes"))
        assert state.known is True
        assert (state.paired, state.bonded, state.trusted) == (True, True, True)

    def test_parseBondState_pairedButNotTrusted_trustedFalse(self) -> None:
        state = bluetooth_helper.parseBondState(_infoOutput("yes", "yes", "no"))
        assert state.known is True
        assert state.trusted is False

    def test_parseBondState_deviceUnknownToBluez_nothingIsAsserted(self) -> None:
        """Honest instrument: an unread flag is never rendered as a positive."""
        state = bluetooth_helper.parseBondState(f"Device {MAC} not available\n")
        assert state.known is False
        assert (state.paired, state.bonded, state.trusted) == (False, False, False)

    def test_parseBondState_ansiColouredOutput_isParsed(self) -> None:
        """bluez colours its output; the escape must not defeat the match."""
        coloured = (
            f"\x1b[0;94mDevice {MAC}\x1b[0m\n"
            "\tPaired: yes\n\tBonded: yes\n\tTrusted: yes\n"
        )
        state = bluetooth_helper.parseBondState(coloured)
        assert bluetooth_helper.isDurableBond(state) is True


class TestIsDurableBond:

    @pytest.mark.parametrize(
        "paired,bonded,trusted,expected",
        [
            (True, True, True, True),
            (True, True, False, False),   # not trusted -> no unattended reconnect
            (True, False, True, False),   # not bonded -> link keys not persisted
            (False, True, True, False),
            (False, False, False, False),
        ],
    )
    def test_isDurableBond_requiresAllThree(
        self, paired: bool, bonded: bool, trusted: bool, expected: bool
    ) -> None:
        state = bluetooth_helper.BondState(
            known=True, paired=paired, bonded=bonded, trusted=trusted
        )
        assert bluetooth_helper.isDurableBond(state) is expected


class TestBondVocabularyMatchesThePairingDriver:
    """One definition of 'durable bond' across the two modules that hold one.

    ``scripts/pair_obdlink_driver.py`` decides at PAIR time whether the bond it
    just wrote is durable; ``bluetooth_helper`` decides the same thing at
    CONNECT time.  Two independent definitions of the same fact is the
    cross-module enum-identity drift that cost the 9-drain saga, so pin them
    against each other over the whole truth table rather than trusting that
    two files stay in step.  (Consolidating to one function needs the pairing
    driver -- a live P0 hotfix -- to gain a src import path: TD filed.)
    """

    def test_isDurableBond_agreesWithPairDriverOverEveryCombination(self) -> None:
        import importlib.util
        from pathlib import Path

        driverPath = Path(__file__).resolve().parents[3] / "scripts" / "pair_obdlink_driver.py"
        spec = importlib.util.spec_from_file_location("_pairDriverUnderTest", driverPath)
        assert spec is not None and spec.loader is not None
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)

        for paired in (False, True):
            for bonded in (False, True):
                for trusted in (False, True):
                    helperVerdict = bluetooth_helper.isDurableBond(
                        bluetooth_helper.BondState(
                            known=True, paired=paired, bonded=bonded, trusted=trusted
                        )
                    )
                    driverVerdict = driver.isDurableBond(
                        {"known": True, "paired": paired, "bonded": bonded,
                         "trusted": trusted}
                    )
                    assert helperVerdict == driverVerdict, (
                        f"durable-bond definitions diverged for paired={paired} "
                        f"bonded={bonded} trusted={trusted}"
                    )


class TestReadBondState:

    def test_readBondState_queriesBluetoothctlInfoForTheMac(self) -> None:
        runner = _RecordingRunner({
            bluetooth_helper.BLUETOOTHCTL_CMD: (0, _infoOutput("yes", "yes", "yes"), ""),
        })

        state = bluetooth_helper.readBondState(MAC, subprocessRunner=runner)

        assert bluetooth_helper.isDurableBond(state) is True
        assert any("info" in line and MAC in line for line in runner.commandLines())

    def test_readBondState_bluetoothctlMissing_reportsUnknownNotDurable(self) -> None:
        """No bluetoothctl (bench/dev box) must degrade to 'unknown', never to
        a confident 'bonded'."""
        def missing(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError(cmd[0])

        state = bluetooth_helper.readBondState(MAC, subprocessRunner=missing)

        assert state.known is False
        assert bluetooth_helper.isDurableBond(state) is False


class TestEnsureTrusted:

    def test_ensureTrusted_bondedButNotTrusted_issuesTrustAndReportsRepaired(self) -> None:
        """
        Given: bluez holds a paired+bonded record whose Trusted flag was lost
        When:  the connect path assures the bond
        Then:  `trust <MAC>` is issued and the re-read state is durable -- the
               link re-establishes with no manual re-pair
        """
        calls: list[list[str]] = []
        infoReplies = iter([
            _infoOutput("yes", "yes", "no"),    # before
            _infoOutput("yes", "yes", "yes"),   # after the trust
        ])

        def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(list(cmd))
            if "info" in cmd:
                return subprocess.CompletedProcess(cmd, 0, next(infoReplies), "")
            return subprocess.CompletedProcess(cmd, 0, "Changing trust succeeded\n", "")

        state = bluetooth_helper.ensureTrusted(MAC, subprocessRunner=runner)

        assert bluetooth_helper.isDurableBond(state) is True
        assert any("trust" in call and MAC in call for call in calls)

    def test_ensureTrusted_alreadyDurable_doesNotIssueTrust(self) -> None:
        """Idempotent: a healthy bond costs one read, no state change."""
        runner = _RecordingRunner({
            bluetooth_helper.BLUETOOTHCTL_CMD: (0, _infoOutput("yes", "yes", "yes"), ""),
        })

        state = bluetooth_helper.ensureTrusted(MAC, subprocessRunner=runner)

        assert bluetooth_helper.isDurableBond(state) is True
        assert not any("trust" in line for line in runner.commandLines())

    def test_ensureTrusted_bluezHasNoRecord_doesNotClaimRepair(self) -> None:
        """Trust is repairable at runtime; PAIRING is not (it needs the dongle
        powered + in pair mode + an operator).  Report the truth instead of
        issuing a trust that cannot help."""
        runner = _RecordingRunner({
            bluetooth_helper.BLUETOOTHCTL_CMD: (0, f"Device {MAC} not available\n", ""),
        })

        state = bluetooth_helper.ensureTrusted(MAC, subprocessRunner=runner)

        assert state.known is False
        assert bluetooth_helper.isDurableBond(state) is False
        assert not any("trust" in line for line in runner.commandLines())

    def test_ensureTrusted_trustCommandFails_reportsNotDurableNeverRaises(self) -> None:
        """Bond assurance is best-effort: it must never be able to fail a
        connect attempt that would otherwise have worked."""
        def runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "info" in cmd:
                return subprocess.CompletedProcess(cmd, 0, _infoOutput("yes", "yes", "no"), "")
            return subprocess.CompletedProcess(cmd, 1, "", "org.bluez.Error.Failed\n")

        state = bluetooth_helper.ensureTrusted(MAC, subprocessRunner=runner)

        assert bluetooth_helper.isDurableBond(state) is False

    def test_ensureTrusted_runnerExplodes_returnsUnknownNeverRaises(self) -> None:
        def boom(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise OSError("bluetoothd is not running")

        state = bluetooth_helper.ensureTrusted(MAC, subprocessRunner=boom)

        assert state.known is False

    def test_ensureTrusted_neverPowersTheRadioDown(self) -> None:
        """AC4 again, on the other new command surface."""
        runner = _RecordingRunner({
            bluetooth_helper.BLUETOOTHCTL_CMD: (0, _infoOutput("yes", "yes", "no"), ""),
        })

        bluetooth_helper.ensureTrusted(MAC, subprocessRunner=runner)

        for line in runner.commandLines():
            assert "power off" not in line
            assert not line.startswith("rfkill")
