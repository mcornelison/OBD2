################################################################################
# File Name: bt_stack_fake.py
# Purpose/Description: US-512 -- shared CLI-level fake of the Pi's Bluetooth
#                      stack (rfcomm(1) + bluetoothctl(1)) plus an epoch-aware
#                      python-obd factory, so the REAL bluetooth_helper logic
#                      runs under test on a Windows dev box.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Rex (US-512) | Initial -- one dongle model for the unit +
#               |              | integration halves of the transport-reset story.
# 2026-08-10    | Rex (US-545) | A-18 bond self-heal.  Model the rest of the
#               |              | surface the healer drives at the SAME CLI seam:
#               |              | adapter power (`show` / `power on|off`),
#               |              | discovery (`scan on` -> an RSSI line in `info`,
#               |              | which is what separates "in range NOW" from
#               |              | "bluez merely remembers it"), `remove`, the
#               |              | pair-script invocation, and systemctl service
#               |              | control.  Additive: every US-512 behaviour and
#               |              | default is unchanged.
# ================================================================================
################################################################################

"""One model of the dongle, faked at the CLI boundary.

Faking at the ``subprocess`` seam rather than at the
:mod:`~src.pi.obdii.bluetooth_helper` function seam is deliberate: the bug
US-512 fixes LIVES INSIDE those functions.  ``bindRfcomm``'s already-bound
short-circuit is precisely what hands a recovery attempt the same dead tty, so
a test that stubs ``bindRfcomm`` cannot see it.  Driving the real functions
over a fake ``rfcomm`` / ``bluetoothctl`` keeps the short-circuit, the
``rfcomm show`` parsing and the release semantics all in the loop.

The one behaviour everything turns on:

    **A bind entry is a kernel table entry.  It outlives the ACL link, and it
    outlives the process.**

:attr:`FakeBtStack.linkEpoch` advances each time the link drops; a binding
remembers the epoch it was created in.  Opening a binding whose epoch is stale
fails the way pyserial does over a dead rfcomm node.  Nothing else about the
adapter is modelled -- that single fact is the whole defect.
"""

from __future__ import annotations

import subprocess
from typing import Any

DEFAULT_MAC = "00:04:3E:85:0D:FB"


class StaleTransportError(OSError):
    """Opening/reading a binding whose link has dropped.

    ``OSError`` on purpose -- that is what
    :func:`src.pi.obdii.error_classification.classifyCaptureError` buckets as
    ADAPTER_UNREACHABLE, and it carries pyserial's real wording so the
    substring heuristics in that classifier are exercised too.
    """


#: US-545: the RSSI figure the fake reports for an in-range dongle.  Any
#: negative dBm reads the same to the parser; the value is arbitrary but fixed
#: so assertions never depend on a number that could drift.
IN_RANGE_RSSI_DBM = -62

#: US-545: the systemd unit the healer serialises against.
OBD_UNIT = "eclipse-obd.service"


class FakeBtStack:
    """Fake ``rfcomm(1)`` + ``bluetoothctl(1)`` + ``systemctl(1)`` over one dongle.

    Args:
        mac: The dongle MAC.
        paired / bonded / trusted: Initial bluez bond flags.
        known: False to model a device bluez has never seen.
        radioPowered: US-545 -- the adapter's bluez ``Powered`` property.
        inRange: US-545 -- whether a scan can actually SEE the dongle.  The
            OBDLink LX is bus-powered, so "out of range" is the normal
            engine-off state, not an exotic one.
        adapterPresent: US-545 -- False models bluez answering but reporting
            "No default controller available" (a wedged/absent controller).
        bluetoothctlPresent: US-545 -- False models the binary being missing
            entirely (the Windows dev box, a stripped image).  The runner
            raises ``FileNotFoundError``, exactly as ``subprocess.run`` does.
        pairScriptSucceeds: US-545 -- False makes the pair script exit non-zero.
        pairScriptLies: US-545 -- the script exits 0 but the bond is NOT
            actually durable afterwards.  Models the failure a caller that
            trusts an exit code instead of re-reading the state cannot see.
    """

    def __init__(
        self,
        mac: str = DEFAULT_MAC,
        *,
        paired: bool = True,
        bonded: bool = True,
        trusted: bool = True,
        known: bool = True,
        radioPowered: bool = True,
        inRange: bool = True,
        adapterPresent: bool = True,
        bluetoothctlPresent: bool = True,
        pairScriptSucceeds: bool = True,
        pairScriptLies: bool = False,
    ) -> None:
        self.mac = mac
        self.known = known
        self.paired = paired
        self.bonded = bonded
        self.trusted = trusted
        # device number -> (mac, channel, epoch the binding was created in)
        self.binds: dict[int, tuple[str, int, int]] = {}
        self.linkEpoch = 0
        self.commands: list[list[str]] = []

        # ---- US-545 additions ----
        self.radioPowered = radioPowered
        self.inRange = inRange
        self.adapterPresent = adapterPresent
        self.bluetoothctlPresent = bluetoothctlPresent
        self.pairScriptSucceeds = pairScriptSucceeds
        self.pairScriptLies = pairScriptLies
        #: Set by `scan on` when the dongle is genuinely in range + the radio
        #: is up.  This -- NOT the persisted bond record -- is what makes
        #: `info` emit an RSSI line, which is the only signal that separates
        #: "the dongle is HERE" from "bluez remembers a dongle".
        self.discovered = False
        #: unit -> is-active.  eclipse-obd starts running (the in-car case);
        #: tests set it False to model the boot case.
        self.services: dict[str, bool] = {OBD_UNIT: True}
        #: (unit, verb) pairs that must fail, e.g. {('eclipse-obd.service', 'stop')}.
        self.serviceControlFails: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Scenario control
    # ------------------------------------------------------------------

    def dropLink(self) -> None:
        """The BT link goes away.  The bind entry deliberately STAYS."""
        self.linkEpoch += 1

    def clearBond(self) -> None:
        """US-545: bluez forgets the device entirely (`bluetoothctl remove`).

        This is the state the story's validation criteria create by hand, and
        the one a de-bonded dongle presents: no record at all, so every flag
        reads no -- indistinguishable from "never seen" by the flags alone.
        """
        self.known = False
        self.paired = False
        self.bonded = False
        self.trusted = False

    def seedInheritedBinding(self, device: int = 0, channel: int = 1) -> None:
        """Model a binding left behind by a killed predecessor process."""
        self.binds[device] = (self.mac, channel, self.linkEpoch)

    def isBound(self, device: int = 0) -> bool:
        return device in self.binds

    def isFresh(self, device: int = 0) -> bool:
        entry = self.binds.get(device)
        return entry is not None and entry[2] == self.linkEpoch

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def commandLines(self) -> list[str]:
        return [" ".join(cmd) for cmd in self.commands]

    def countMatching(self, *tokens: str) -> int:
        return sum(
            1 for cmd in self.commands if all(token in cmd for token in tokens)
        )

    def bindCount(self, device: int = 0) -> int:
        return self.countMatching("rfcomm", "bind", str(device))

    def releaseCount(self, device: int = 0) -> int:
        return self.countMatching("rfcomm", "release", str(device))

    def indexOf(self, *tokens: str) -> int:
        """US-545: index of the FIRST command matching every token, or -1.

        Ordering assertions are the whole point of the serialisation AC --
        "stopped the logger" and "ran the pair script" are both true in a
        broken implementation that did them the wrong way round.

        A token matches an argv element exactly OR as a substring of one.  The
        substring half is not laziness: the pair path is invoked by ABSOLUTE
        path, so an exact-element match silently never fires and the ordering
        assertion degrades into `-1 < -1` -- a guard that cannot fail.
        """
        for index, cmd in enumerate(self.commands):
            if all(any(token in element for element in cmd) for token in tokens):
                return index
        return -1

    def pairScriptRuns(self) -> int:
        """US-545: how many times the pair path was actually invoked."""
        return sum(
            1 for cmd in self.commands
            if cmd and cmd[0].replace("\\", "/").endswith("pair_obdlink.sh")
        )

    # ------------------------------------------------------------------
    # The fake CLIs
    # ------------------------------------------------------------------

    def runner(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """``subprocessRunner``-compatible dispatcher."""
        self.commands.append(list(cmd))
        if cmd[0] == "rfcomm":
            return self._rfcomm(cmd)
        if cmd[0] == "bluetoothctl":
            if not self.bluetoothctlPresent:
                # Exactly what subprocess.run does for a missing binary.  The
                # production code must survive it, not merely be spared it.
                raise FileNotFoundError("bluetoothctl")
            return self._bluetoothctl(cmd)
        if cmd[0] == "systemctl":
            return self._systemctl(cmd)
        if cmd[0].replace("\\", "/").endswith("pair_obdlink.sh"):
            return self._pairScript(cmd)
        if cmd[0].replace("\\", "/").endswith("verify_bt_pair.sh"):
            return self._verifyScript(cmd)
        raise FileNotFoundError(cmd[0])

    def _rfcomm(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        action = cmd[1]
        if action == "show":
            device = int(cmd[2])
            entry = self.binds.get(device)
            if entry is None:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "Can't get info: No such device\n"
                )
            mac, channel, _epoch = entry
            return subprocess.CompletedProcess(
                cmd, 0, f"rfcomm{device}: {mac} channel {channel} clean\n", ""
            )
        if action == "bind":
            device, mac, channel = int(cmd[2]), cmd[3], int(cmd[4])
            # A bind over an existing entry is what the kernel rejects; the
            # helper is expected to have released first.
            if device in self.binds:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "Can't create device: Address already in use\n"
                )
            self.binds[device] = (mac, channel, self.linkEpoch)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if action == "release":
            device = int(cmd[2])
            self.binds.pop(device, None)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", f"unknown rfcomm verb {action}\n")

    def _bluetoothctl(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "info" in cmd:
            if not (self.known or self.discovered):
                return subprocess.CompletedProcess(
                    cmd, 0, f"Device {self.mac} not available\n", ""
                )
            yesNo = {True: "yes", False: "no"}
            # The RSSI line is present ONLY while the device is in the
            # discovery cache.  A device bluez merely REMEMBERS has flags but
            # no RSSI -- which is precisely how a stale record is told apart
            # from a dongle that is actually powered and in range.
            rssi = (
                f"\tRSSI: {IN_RANGE_RSSI_DBM}\n" if self.discovered else ""
            )
            return subprocess.CompletedProcess(
                cmd,
                0,
                (
                    f"Device {self.mac} (public)\n"
                    "\tName: OBDLink LX\n"
                    f"\tPaired: {yesNo[self.paired]}\n"
                    f"\tBonded: {yesNo[self.bonded]}\n"
                    f"\tTrusted: {yesNo[self.trusted]}\n"
                    f"{rssi}"
                ),
                "",
            )
        if "trust" in cmd:
            if not self.known:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "Device not available\n"
                )
            self.trusted = True
            return subprocess.CompletedProcess(cmd, 0, "Changing trust succeeded\n", "")
        if "show" in cmd:
            if not self.adapterPresent:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "No default controller available\n"
                )
            return subprocess.CompletedProcess(
                cmd,
                0,
                (
                    "Controller B8:27:EB:00:11:22 (public)\n"
                    "\tName: chi-eclipse-01\n"
                    f"\tPowered: {'yes' if self.radioPowered else 'no'}\n"
                ),
                "",
            )
        if "power" in cmd:
            wanted = cmd[cmd.index("power") + 1] == "on"
            if not self.adapterPresent:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "No default controller available\n"
                )
            self.radioPowered = wanted
            if not wanted:
                # Cycling the adapter empties the discovery cache -- which is
                # the whole reason a wedge reset must be followed by a NEW
                # scan rather than a re-read of the old answer.
                self.discovered = False
            return subprocess.CompletedProcess(
                cmd, 0, f"Changing power {'on' if wanted else 'off'} succeeded\n", ""
            )
        if "scan" in cmd:
            if cmd[cmd.index("scan") + 1] == "on":
                self.discovered = self.inRange and self.radioPowered
            return subprocess.CompletedProcess(cmd, 0, "Discovery started\n", "")
        if "remove" in cmd:
            self.clearBond()
            return subprocess.CompletedProcess(cmd, 0, "Device has been removed\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def _systemctl(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Model `is-active` / `stop` / `start` for the units the healer touches."""
        verbs = [token for token in cmd[1:] if not token.startswith("-")]
        if not verbs:
            return subprocess.CompletedProcess(cmd, 1, "", "missing verb\n")
        verb = verbs[0]
        unit = verbs[1] if len(verbs) > 1 else ""

        if verb == "is-active":
            active = self.services.get(unit, False)
            # systemd exits 3 for an inactive unit, not 1 -- a caller that
            # only checks `rc != 0` still works, but one that checks `rc == 1`
            # would silently misread every boot.
            return subprocess.CompletedProcess(
                cmd, 0 if active else 3, "active\n" if active else "inactive\n", ""
            )
        if verb in ("stop", "start", "restart"):
            if (unit, verb) in self.serviceControlFails:
                return subprocess.CompletedProcess(
                    cmd, 1, "", f"Failed to {verb} {unit}: Access denied\n"
                )
            self.services[unit] = verb != "stop"
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def _pairScript(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Model `scripts/pair_obdlink.sh <MAC>`.

        A pair can only succeed against a dongle the radio can actually reach.
        ``pairScriptLies`` decouples the exit code from the resulting bond so a
        caller that trusts rc==0 instead of re-reading bluez is caught.
        """
        if not self.pairScriptSucceeds:
            return subprocess.CompletedProcess(
                cmd, 1,
                "",
                "pair timed out -- is the LX powered (engine on) and in pair mode?\n",
            )
        if self.pairScriptLies:
            return subprocess.CompletedProcess(cmd, 0, "Pairing successful\n", "")
        if not (self.radioPowered and self.inRange):
            return subprocess.CompletedProcess(
                cmd, 1, "", "Device not available\n"
            )
        self.known = True
        self.paired = True
        self.bonded = True
        self.trusted = True
        return subprocess.CompletedProcess(cmd, 0, "Pairing successful\n", "")

    def _verifyScript(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Model `scripts/verify_bt_pair.sh <MAC>` -- INCLUDING its blind spot.

        The real script reports an unset ``Bonded`` flag as ``[INFO]``, not
        ``[FAIL]`` ("some BT stacks only set Bonded on first connection"), so
        it EXITS 0 over a bond that is paired+trusted but not bonded.  That is
        reproduced here on purpose: it is exactly why the healer runs this
        script for the operator-readable snapshot but never lets its exit code
        decide whether the bond is durable.
        """
        checks = [self.known, self.paired, self.trusted]
        rc = 0 if all(checks) else 1
        yesNo = {True: "[ OK ]", False: "[FAIL]"}
        report = (
            f"=== BT pair + rfcomm verification for {self.mac} ===\n"
            f"{yesNo[self.paired]} Paired\n"
            f"{yesNo[self.trusted]} Trusted (reboot-survive)\n"
            f"{'[ OK ]' if self.bonded else '[INFO]'} Bonded\n"
        )
        return subprocess.CompletedProcess(cmd, rc, report, "")

    # ------------------------------------------------------------------
    # Seams the production code reads the world through
    # ------------------------------------------------------------------

    def pathExists(self, path: str) -> bool:
        """``os.path.exists``-compatible: /dev/rfcommN exists iff bound."""
        if not path.startswith("/dev/rfcomm"):
            return False
        try:
            return self.isBound(int(path[len("/dev/rfcomm"):]))
        except ValueError:
            return False

    def obdFactory(self, portstr: str | None, timeout: int) -> Any:
        """python-obd factory: opening a STALE binding fails, like the real one."""
        device = 0
        if portstr and portstr.startswith("/dev/rfcomm"):
            try:
                device = int(portstr[len("/dev/rfcomm"):])
            except ValueError:
                device = 0
        if not self.isFresh(device):
            raise StaleTransportError(
                f"[Errno 5] could not open port {portstr}: device reports "
                "readiness to read but returned no data (device disconnected "
                "or multiple access on port?)"
            )
        return _LiveObd(self, self.linkEpoch)


class _LiveObd:
    """A python-obd stand-in bound to the link epoch it was opened in."""

    def __init__(self, stack: FakeBtStack, epoch: int) -> None:
        self._stack = stack
        self._epoch = epoch
        self.queryCount = 0

    def _linkIsUp(self) -> bool:
        return self._stack.linkEpoch == self._epoch

    def is_connected(self) -> bool:
        return self._linkIsUp()

    def query(self, command: Any, force: bool = False) -> Any:
        if not self._linkIsUp():
            raise StaleTransportError(
                "rfcomm read failed: transport endpoint is not connected"
            )
        self.queryCount += 1
        return _Response()

    def close(self) -> None:
        pass


class _Response:
    """Minimal python-obd response with a real value."""

    def __init__(self, value: float = 1000.0, unit: str = "rpm") -> None:
        self.value = value
        self.unit = unit

    def is_null(self) -> bool:
        return False
