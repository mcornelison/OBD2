################################################################################
# File Name: wifi_recover.py
# Purpose/Description: US-925-a -- recover a stored-PSK Wi-Fi connection that
#                      NetworkManager failed with NO_SECRETS and will never
#                      retry: ONE `nmcli connection up uuid U` per ACTIVATED.
#                      A pure handler, decide(event, memory), plus a thin
#                      D-Bus loop on Device.StateChanged.  Run by
#                      deploy/eclipse-wifi-recover.service with the SYSTEM
#                      python (dbus + gi come from Debian python3-dbus /
#                      python3-gi, which obd2-venv cannot see).
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex (US-925-a) | Initial implementation
# ================================================================================
################################################################################

"""
Wi-Fi no-secrets recovery (US-925-a, F-155).

The defect, MEASURED on 2 of 25 boots: after a handshake failure
NetworkManager walks a stored-PSK connection need-auth -> no secrets ->
failed and then never retries it.  The Pi stayed offline 8 and 63 minutes,
until a power-cycle.  The key is still stored; nobody asks NM to use it again.

This service asks, once.  The trigger is the failure itself --
``StateChanged`` on the device whose ``Interface`` is wlan0, new state
FAILED, reason NO_SECRETS -- WHATEVER caused it (a reason-15 or reason-17
disconnect, or the boot race).  The preceding disconnect reason is read from
the supplicant's journal lines only to be logged; it never decides.

Rearm rule (no counter, no window): at most ONE retry per ACTIVATED.  ``U`` is
the connection uuid the device last reached ACTIVATED with; a retry spends
the arm and only ACTIVATED re-arms it.  A second failure with no ACTIVATED
between is not retried and logs ONE ERROR line.  No action at all for any
other state reason (NM's own autoconnect owns those), another device, or a
connection whose secret is agent-owned (psk-flags != 0: there is no stored
key to reuse, and asking a person is correct).

Why not a NetworkManager-dispatcher(8) script: the dispatcher has no event
for a failed activation and no state reason, so it cannot see this failure.

Import discipline (Atlas RULED Q-925-1): ONLY the stdlib at module level --
``dbus`` and ``gi.repository.GLib`` are imported inside :func:`main` -- so
the pure handler imports and tests on Windows.  It never imports project code
and never ``gi.repository.NM`` (no typelib on the Pi).  Settings are read with
GetSettings, which returns no secrets.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

# ---- NetworkManager public D-Bus enums -----------------------------------------
# DOCUMENTED: https://networkmanager.dev/docs/api/latest/nm-dbus-types.html
NM_DEVICE_STATE_ACTIVATED = 100  # NMDeviceState NM_DEVICE_STATE_ACTIVATED (nm-dbus-types)
NM_DEVICE_STATE_FAILED = 120  # NMDeviceState NM_DEVICE_STATE_FAILED (nm-dbus-types)
NM_DEVICE_STATE_REASON_NO_SECRETS = 7  # NMDeviceStateReason NM_DEVICE_STATE_REASON_NO_SECRETS
# NMSettingSecretFlags NM_SETTING_SECRET_FLAG_NONE (nm-dbus-types): NM stores the secret.
SECRET_FLAG_NONE = 0

NM_BUS_NAME = "org.freedesktop.NetworkManager"
NM_DEVICE_IFACE = "org.freedesktop.NetworkManager.Device"
NM_ACTIVE_CONNECTION_IFACE = "org.freedesktop.NetworkManager.Connection.Active"
NM_SETTINGS_CONNECTION_IFACE = "org.freedesktop.NetworkManager.Settings.Connection"
DBUS_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"
NO_OBJECT_PATH = "/"

WIFI_INTERFACE = "wlan0"
WIFI_SECURITY_SETTING = "802-11-wireless-security"
PSK_FLAGS_KEY = "psk-flags"

NMCLI = "/usr/bin/nmcli"
JOURNALCTL = "/usr/bin/journalctl"
SUPPLICANT_UNIT = "wpa_supplicant.service"

LOGGER_NAME = "wifi-recover"
LOG_FORMAT = "%(levelname)s wifi-recover: %(message)s"

UNKNOWN = "unknown"

_MAC = r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}"
_CONNECTED_RE = re.compile(rf"CTRL-EVENT-CONNECTED - Connection to ({_MAC})")
_DISCONNECTED_RE = re.compile(rf"CTRL-EVENT-DISCONNECTED bssid=({_MAC}) reason=(\d+)")
_ANY_MAC_RE = re.compile(rf"\b({_MAC})\b")
_NULL_MAC = "00:00:00:00:00:00"

logger = logging.getLogger(LOGGER_NAME)


# ================================================================================
# The pure handler
# ================================================================================


@dataclass(frozen=True)
class SupplicantTrail:
    """What the supplicant's last wlan0 lines say about the failure (logged only).

    Attributes:
        disconnectReason: The IEEE 802.11 reason of the last
            CTRL-EVENT-DISCONNECTED, or None when none was found.
        bssidBefore: The BSSID of the last completed connection, or None.
        bssidAfter: The last BSSID any wlan0 line named, or None.
    """

    disconnectReason: str | None = None
    bssidBefore: str | None = None
    bssidAfter: str | None = None


@dataclass(frozen=True)
class DeviceEvent:
    """One Device.StateChanged, resolved to what the handler needs.

    Attributes:
        interface: The device's ``Interface`` property (e.g. ``wlan0``).
        newState: The NMDeviceState the device entered.
        reason: The NMDeviceStateReason NM gave for it.
        uuid: For ACTIVATED only -- the active connection's uuid.
        pskFlags: For ACTIVATED only -- that connection's psk-flags.
        trail: For a trigger only -- the supplicant's last lines, parsed.
    """

    interface: str
    newState: int
    reason: int
    uuid: str | None = None
    pskFlags: int = SECRET_FLAG_NONE
    trail: SupplicantTrail = field(default_factory=SupplicantTrail)


@dataclass(frozen=True)
class Memory:
    """What the handler remembers between events.

    Attributes:
        uuid: The connection uuid wlan0 last reached ACTIVATED with (U).
        pskFlags: U's psk-flags, read at that ACTIVATED.
        armed: True until the one retry this ACTIVATED allows is spent.
    """

    uuid: str | None = None
    pskFlags: int = SECRET_FLAG_NONE
    armed: bool = False


@dataclass(frozen=True)
class Decision:
    """The handler's answer: the next memory, an action, and one journal line.

    Attributes:
        memory: The memory to carry into the next event.
        action: The argv to run, or None for no action.
        level: The logging level of ``line``.
        line: The one journal line for this event, or None for a silent event.
    """

    memory: Memory
    action: tuple[str, ...] | None = None
    level: int = logging.INFO
    line: str | None = None


def isTrigger(interface: str, newState: int, reason: int) -> bool:
    """True for the one event this service acts on: wlan0 FAILED with NO_SECRETS."""
    return (
        interface == WIFI_INTERFACE
        and newState == NM_DEVICE_STATE_FAILED
        and reason == NM_DEVICE_STATE_REASON_NO_SECRETS
    )


def decide(event: DeviceEvent, memory: Memory) -> Decision:
    """Decide what one StateChanged means.  Pure: no I/O, no logging.

    Args:
        event: The resolved StateChanged.
        memory: What the handler remembered from earlier events.

    Returns:
        The next memory, the action (``nmcli connection up uuid U`` or None)
        and the journal line for the event.
    """
    if event.interface != WIFI_INTERFACE:
        return Decision(memory)

    if event.newState == NM_DEVICE_STATE_ACTIVATED:
        if event.uuid is None:
            return Decision(
                memory,
                level=logging.WARNING,
                line="activated, but its connection uuid could not be read; arm unchanged",
            )
        return Decision(
            Memory(uuid=event.uuid, pskFlags=event.pskFlags, armed=True),
            line=f"activated uuid {event.uuid}, armed for one no-secrets retry",
        )

    if not isTrigger(event.interface, event.newState, event.reason):
        return Decision(memory)

    trail = event.trail
    head = (
        f"no-secrets after reason {trail.disconnectReason or UNKNOWN}, "
        f"bssid {trail.bssidBefore or UNKNOWN}->{trail.bssidAfter or UNKNOWN}, "
    )
    if memory.uuid is None:
        return Decision(
            memory, level=logging.ERROR, line=head + "not retried: connection never activated"
        )
    if not memory.armed:
        return Decision(
            memory,
            level=logging.ERROR,
            line=(
                head + f"not retried: uuid {memory.uuid} already retried once since its "
                "last activation (re-arms on the next ACTIVATED)"
            ),
        )
    if memory.pskFlags != SECRET_FLAG_NONE:
        return Decision(
            memory,
            line=(
                head + f"not retried: uuid {memory.uuid} secret is agent-owned "
                f"(psk-flags={memory.pskFlags}), no stored key to reuse"
            ),
        )
    return Decision(
        replace(memory, armed=False),
        action=(NMCLI, "connection", "up", "uuid", memory.uuid),
        line=head + f"retry connection up uuid {memory.uuid}",
    )


def runEvent(
    event: DeviceEvent,
    memory: Memory,
    launch: Callable[[tuple[str, ...], str], None],
) -> Memory:
    """Decide one event, write its journal line, and launch its action.

    A launch that cannot start is ONE ERROR line; the arm stays spent, so
    there is no retry loop.

    Args:
        event: The resolved StateChanged.
        memory: The current memory.
        launch: Starts ``argv`` without blocking; ``uuid`` names the retry.

    Returns:
        The memory to carry into the next event.
    """
    decision = decide(event, memory)
    if decision.line is not None:
        logger.log(decision.level, decision.line)
    if decision.action is not None and decision.memory.uuid is not None:
        try:
            launch(decision.action, decision.memory.uuid)
        except OSError as exc:
            logger.error(
                "retry failed: nmcli could not start for uuid %s (%s); not retried again "
                "until the next activation",
                decision.memory.uuid,
                exc,
            )
    return decision.memory


def reportRetryExit(uuid: str, exitCode: int) -> None:
    """Write the one journal line for a finished ``nmcli connection up``."""
    if exitCode == 0:
        logger.info("retry accepted: nmcli exit code 0 for uuid %s", uuid)
    else:
        logger.error(
            "retry failed: nmcli exit code %d for uuid %s; not retried again until the "
            "next activation",
            exitCode,
            uuid,
        )


def onChildExit(pid: int, waitStatus: int, uuid: str) -> None:
    """GLib child-watch callback: turn the raw wait status into the exit line."""
    reportRetryExit(uuid, os.waitstatus_to_exitcode(waitStatus))


def parseSupplicantLines(lines: Iterable[str]) -> SupplicantTrail:
    """Read the reason and the BSSIDs before/after from wpa_supplicant's lines.

    Only lines that start with ``wlan0:`` count (``p2p-dev-wlan0:`` does not).

    Args:
        lines: wpa_supplicant journal lines, oldest first (``-o cat``).

    Returns:
        The last disconnect reason, the last completed connection's BSSID and
        the last BSSID any line named; None for each one not found.
    """
    reason: str | None = None
    before: str | None = None
    after: str | None = None
    for line in lines:
        if not line.startswith(f"{WIFI_INTERFACE}:"):
            continue
        connected = _CONNECTED_RE.search(line)
        if connected:
            before = connected.group(1).lower()
        disconnected = _DISCONNECTED_RE.search(line)
        if disconnected:
            reason = disconnected.group(2)
        named = [m.lower() for m in _ANY_MAC_RE.findall(line) if m != _NULL_MAC]
        if named:
            after = named[0]
    return SupplicantTrail(reason, before, after)


def pskFlagsOf(settings: dict[str, Any]) -> int:
    """The psk-flags of a GetSettings result; absent means NM stores the key."""
    security = settings.get(WIFI_SECURITY_SETTING, {})
    return int(security.get(PSK_FLAGS_KEY, SECRET_FLAG_NONE))


# ================================================================================
# The thin I/O edge
# ================================================================================


def readSupplicantTrail() -> SupplicantTrail:
    """Parse this boot's wpa_supplicant journal lines; an unreadable journal is all-unknown."""
    try:
        completed = subprocess.run(
            [JOURNALCTL, "--boot", "--unit", SUPPLICANT_UNIT, "--output", "cat", "--no-pager"],
            capture_output=True,
            text=True,
            # An SSID in a journal line can carry any byte; one bad byte must
            # cost that line's text, not the handler.
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        logger.warning("could not read the %s journal (%s)", SUPPLICANT_UNIT, exc)
        return SupplicantTrail()
    return parseSupplicantLines(completed.stdout.splitlines())


class NmDeviceReader:
    """Reads device and connection facts over the bus the service already holds.

    Every read resolves the object path afresh: device paths change when
    NetworkManager restarts, so nothing is cached.
    """

    def __init__(self, bus: Any) -> None:
        self._bus = bus

    def _object(self, path: str) -> Any:
        return self._bus.get_object(NM_BUS_NAME, path, introspect=False)

    def _property(self, path: str, interface: str, name: str) -> Any:
        return self._object(path).Get(interface, name, dbus_interface=DBUS_PROPERTIES_IFACE)

    def interfaceOf(self, devicePath: str) -> str:
        """The device's ``Interface`` (e.g. ``wlan0``)."""
        return str(self._property(devicePath, NM_DEVICE_IFACE, "Interface"))

    def activatedConnection(self, devicePath: str) -> tuple[str | None, int]:
        """The active connection's uuid and psk-flags (GetSettings: no secrets)."""
        active = str(self._property(devicePath, NM_DEVICE_IFACE, "ActiveConnection"))
        if active == NO_OBJECT_PATH:
            return None, SECRET_FLAG_NONE
        uuid = str(self._property(active, NM_ACTIVE_CONNECTION_IFACE, "Uuid"))
        settingsPath = str(self._property(active, NM_ACTIVE_CONNECTION_IFACE, "Connection"))
        settings = self._object(settingsPath).GetSettings(
            dbus_interface=NM_SETTINGS_CONNECTION_IFACE
        )
        return uuid, pskFlagsOf(settings)


def buildEvent(
    reader: Any,
    devicePath: str,
    newState: int,
    reason: int,
    readTrail: Callable[[], SupplicantTrail],
) -> DeviceEvent:
    """Resolve a raw StateChanged into a DeviceEvent, reading only what it needs.

    Args:
        reader: An :class:`NmDeviceReader` (or a test double with its methods).
        devicePath: The signal's object path.
        newState: The new NMDeviceState.
        reason: The NMDeviceStateReason.
        readTrail: Reads the supplicant trail; called for a trigger only.

    Returns:
        The event: the uuid + psk-flags on a wlan0 ACTIVATED, the trail on a
        trigger, the bare states otherwise.
    """
    interface = reader.interfaceOf(devicePath)
    if interface != WIFI_INTERFACE:
        return DeviceEvent(interface, newState, reason)
    if newState == NM_DEVICE_STATE_ACTIVATED:
        uuid, pskFlags = reader.activatedConnection(devicePath)
        return DeviceEvent(interface, newState, reason, uuid=uuid, pskFlags=pskFlags)
    if isTrigger(interface, newState, reason):
        return DeviceEvent(interface, newState, reason, trail=readTrail())
    return DeviceEvent(interface, newState, reason)


def main() -> int:
    """Subscribe to Device.StateChanged on ANY path and run until stopped."""
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    reader = NmDeviceReader(bus)
    memory = [Memory()]

    def launch(argv: tuple[str, ...], uuid: str) -> None:
        # Never blocks the signal loop: GLib reaps the child and reports it.
        child = subprocess.Popen(list(argv))
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, child.pid, onChildExit, uuid)

    def onStateChanged(newState: Any, oldState: Any, reason: Any, path: str = "") -> None:
        try:
            event = buildEvent(reader, path, int(newState), int(reason), readSupplicantTrail)
        except dbus.exceptions.DBusException as exc:
            logger.warning(
                "could not read device %s for StateChanged %s->%s reason %s (%s)",
                path,
                oldState,
                newState,
                reason,
                exc,
            )
            return
        memory[0] = runEvent(event, memory[0], launch)

    bus.add_signal_receiver(
        onStateChanged,
        signal_name="StateChanged",
        dbus_interface=NM_DEVICE_IFACE,
        path_keyword="path",
    )
    logger.info("watching %s for NetworkManager no-secrets failures", WIFI_INTERFACE)
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
