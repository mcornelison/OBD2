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


class FakeBtStack:
    """Fake ``rfcomm(1)`` + ``bluetoothctl(1)`` over a single modelled dongle.

    Args:
        mac: The dongle MAC.
        paired / bonded / trusted: Initial bluez bond flags.
        known: False to model a device bluez has never seen.
    """

    def __init__(
        self,
        mac: str = DEFAULT_MAC,
        *,
        paired: bool = True,
        bonded: bool = True,
        trusted: bool = True,
        known: bool = True,
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

    # ------------------------------------------------------------------
    # Scenario control
    # ------------------------------------------------------------------

    def dropLink(self) -> None:
        """The BT link goes away.  The bind entry deliberately STAYS."""
        self.linkEpoch += 1

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

    # ------------------------------------------------------------------
    # The fake CLIs
    # ------------------------------------------------------------------

    def runner(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """``subprocessRunner``-compatible dispatcher."""
        self.commands.append(list(cmd))
        if cmd[0] == "rfcomm":
            return self._rfcomm(cmd)
        if cmd[0] == "bluetoothctl":
            return self._bluetoothctl(cmd)
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
            if not self.known:
                return subprocess.CompletedProcess(
                    cmd, 0, f"Device {self.mac} not available\n", ""
                )
            yesNo = {True: "yes", False: "no"}
            return subprocess.CompletedProcess(
                cmd,
                0,
                (
                    f"Device {self.mac} (public)\n"
                    "\tName: OBDLink LX\n"
                    f"\tPaired: {yesNo[self.paired]}\n"
                    f"\tBonded: {yesNo[self.bonded]}\n"
                    f"\tTrusted: {yesNo[self.trusted]}\n"
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
        return subprocess.CompletedProcess(cmd, 0, "", "")

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
