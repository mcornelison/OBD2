################################################################################
# File Name: bluetooth_helper.py
# Purpose/Description: Bluetooth + rfcomm wrapper (MAC -> /dev/rfcommN resolution)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-193 / TD-023 fix — MAC-vs-path resolution)
# 2026-04-21    | Rex (US-211) | Added isRfcommReachable() probe for the
#                                BT-resilient reconnect loop.  Lightweight
#                                stat(/dev/rfcommN)-style check; does not
#                                reconstruct a python-obd OBD() instance.
# 2026-08-02    | Rex (US-512) | BL-025 P1 capture hardening.  (1) resetRfcommBinding:
#                                a FORCED release-then-bind, because bindRfcomm's
#                                already-bound short-circuit is exactly what hands a
#                                recovery attempt the same dead tty forever.
#                                (2) BondState / parseBondState / isDurableBond /
#                                readBondState / ensureTrusted: the runtime half of
#                                the durable-bond story that scripts/pair_obdlink.sh
#                                only ever wrote at pair time.
# ================================================================================
################################################################################

"""
Thin wrapper over the system `rfcomm(1)` utility.

python-OBD expects a serial device path (e.g. `/dev/rfcomm0`) — it does
not perform Bluetooth discovery or binding. This helper bridges that
gap: given a Bluetooth MAC address, it idempotently binds an rfcomm
device and returns the resulting serial path so the path can be handed
to `obd.OBD(portstr=...)`.

Design invariants (enforced by specs/standards.md + TD-023):

- No `sudo` from Python. Callers either run as root, use sudoers
  NOPASSWD for `/usr/sbin/rfcomm`, or wrap with a shell helper.
- Idempotent: if `/dev/rfcommN` is already bound to the requested MAC,
  `bindRfcomm()` is a no-op. If bound to a *different* MAC, release
  first then re-bind.
- All subprocess invocations are injectable via `subprocessRunner=` for
  Windows-based unit testing.
- Stderr from failing `rfcomm` is surfaced verbatim into the raised
  `BluetoothHelperError` so operators can see the exact reason.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ================================================================================
# Public constants
# ================================================================================

# Regex for Bluetooth MAC — six hex octets separated by colons.
# Matches the form emitted by `bluetoothctl` / Linux BlueZ.
MAC_REGEX = re.compile(r'^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$')

# Name of the external utility. Left as a bare name so $PATH resolves it
# (caller may alternatively symlink / sudoers-allow `/usr/sbin/rfcomm`).
RFCOMM_CMD = "rfcomm"

# US-512: bluez CLI used for the runtime bond check.  Bare name for the same
# $PATH reason as RFCOMM_CMD.
BLUETOOTHCTL_CMD = "bluetoothctl"

# US-512: `bluetoothctl` is an interactive REPL by default; with a command in
# argv it runs once and exits, but the --timeout guard means a wedged bluez
# (bluetoothd restarting, D-Bus stalled) can never park a connect attempt.
BLUETOOTHCTL_TIMEOUT_S = 5


# ================================================================================
# Types
# ================================================================================

class SubprocessRunner(Protocol):
    """Callable signature for the injected subprocess runner."""

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        ...


@dataclass(frozen=True)
class RfcommBindInfo:
    """Parsed output of `rfcomm show /dev/rfcommN`."""

    macAddress: str
    channel: int


@dataclass(frozen=True)
class BondState:
    """Parsed bluez bond flags for one device (US-512).

    ``known`` is False when bluez has no record of the device at all -- an
    unread flag is reported as False rather than guessed, so a missing
    bluetoothctl or an absent record can never render as a confident "bonded"
    (honest-instrument).

    Attributes:
        known: True when bluez printed any bond flag for this MAC.
        paired: The pairing handshake completed.
        bonded: Link keys are persisted -- the pairing survives a reboot.
        trusted: bluez will let the device reconnect unattended (the in-car
            case; without it the link needs an interactive authorization).
    """

    known: bool = False
    paired: bool = False
    bonded: bool = False
    trusted: bool = False


class BluetoothHelperError(Exception):
    """Raised when rfcomm invocations fail."""


# ================================================================================
# Public API
# ================================================================================

def isMacAddress(value: str) -> bool:
    """
    Return True if ``value`` matches the Bluetooth MAC format.

    Args:
        value: String to test.

    Returns:
        True if ``value`` is exactly six colon-separated hex octets.
    """
    if not value:
        return False
    return bool(MAC_REGEX.match(value))


def bindRfcomm(
    macAddress: str,
    device: int = 0,
    channel: int = 1,
    subprocessRunner: SubprocessRunner | None = None,
) -> str:
    """
    Idempotently bind a Bluetooth MAC to an rfcomm serial device.

    Args:
        macAddress: Target Bluetooth MAC (e.g. ``"00:04:3E:85:0D:FB"``).
        device: rfcomm device number (the ``N`` in ``/dev/rfcommN``). Default 0.
        channel: SPP RFCOMM channel on the remote device. OBDLink LX = 1.
        subprocessRunner: Optional subprocess-runner override for testing.

    Returns:
        Absolute serial path ``/dev/rfcommN`` that `obd.OBD()` can open.

    Raises:
        ValueError: If ``macAddress`` isn't in MAC format.
        BluetoothHelperError: If ``rfcomm bind`` fails or isn't present.
    """
    if not isMacAddress(macAddress):
        raise ValueError(
            f"bindRfcomm requires a MAC address, got: {macAddress!r}"
        )

    runner = subprocessRunner or _defaultRunner
    devicePath = _devicePath(device)

    existing = _runShow(device, runner)
    if existing is not None and existing.macAddress.lower() == macAddress.lower():
        logger.debug(
            "rfcomm bind short-circuited | device=%s mac=%s already bound",
            devicePath,
            macAddress,
        )
        return devicePath

    if existing is not None:
        logger.info(
            "rfcomm %s bound to %s; releasing before re-bind to %s",
            devicePath,
            existing.macAddress,
            macAddress,
        )
        _runRelease(device, runner)

    _runBind(device, macAddress, channel, runner)
    logger.info(
        "rfcomm bind OK | device=%s mac=%s channel=%d",
        devicePath,
        macAddress,
        channel,
    )
    return devicePath


def releaseRfcomm(
    device: int = 0,
    subprocessRunner: SubprocessRunner | None = None,
) -> None:
    """
    Release an rfcomm device. No-op if nothing is bound.

    Args:
        device: rfcomm device number to release (default 0).
        subprocessRunner: Optional subprocess-runner override for testing.

    Raises:
        BluetoothHelperError: If ``rfcomm release`` fails for a bound device.
    """
    runner = subprocessRunner or _defaultRunner

    existing = _runShow(device, runner)
    if existing is None:
        logger.debug("rfcomm %s not bound; release is a no-op", _devicePath(device))
        return

    _runRelease(device, runner)
    logger.info("rfcomm release OK | device=%s", _devicePath(device))


def resetRfcommBinding(
    macAddress: str,
    device: int = 0,
    channel: int = 1,
    subprocessRunner: SubprocessRunner | None = None,
) -> str:
    """Force a FRESH rfcomm binding: release, then bind (US-512).

    :func:`bindRfcomm` is deliberately idempotent -- when ``/dev/rfcommN`` is
    already bound to the requested MAC it short-circuits and hands the path
    back without touching the kernel.  That is right for a first connect and
    wrong for a recovery: an rfcomm bind is a kernel table entry that OUTLIVES
    the ACL link, so after the dongle drops, the entry (and the device node)
    are still there.  The short-circuit therefore returns the same DEAD tty on
    every retry, forever -- BL-025's stale-rfcomm-retry-forever signature, and
    the reason a reconnect could loop for 24 days without recovering.

    This is Spool's prescribed transport reset.  Release is unconditional (a
    no-op when nothing is bound), the bind that follows always reaches the
    kernel, and the caller gets a binding that is genuinely new.

    Deliberately does NOT touch the radio: no rfkill, no ``hciconfig down``, no
    ``bluetoothctl power off``.  The 07-03 capture killer was a PERSISTED
    rfkill soft-block, and systemd-rfkill saves radio state at shutdown -- a
    recovery path that cycles the radio can re-arm exactly that failure on the
    next boot.  The reset stays one layer above, on the binding.

    Args:
        macAddress: Target Bluetooth MAC.
        device: rfcomm device number (the ``N`` in ``/dev/rfcommN``).
        channel: SPP RFCOMM channel on the remote device. OBDLink LX = 1.
        subprocessRunner: Optional subprocess-runner override for testing.

    Returns:
        The freshly-bound ``/dev/rfcommN`` path.

    Raises:
        ValueError: If ``macAddress`` isn't in MAC format.
        BluetoothHelperError: If the re-bind fails.  Callers must treat this
            as "no transport", never as a fresh one.
    """
    if not isMacAddress(macAddress):
        raise ValueError(
            f"resetRfcommBinding requires a MAC address, got: {macAddress!r}"
        )

    runner = subprocessRunner or _defaultRunner

    # Release first.  Tolerated when nothing is bound -- the point is to
    # guarantee the bind below is not short-circuited, not to prove there was
    # something to drop.
    try:
        releaseRfcomm(device=device, subprocessRunner=runner)
    except BluetoothHelperError as exc:
        # A release that fails still leaves the stale entry, so the bind that
        # follows will short-circuit -- say so rather than silently returning
        # the dead path.
        logger.warning(
            "rfcomm release during transport reset failed | device=%s | %s",
            _devicePath(device),
            exc,
        )

    _runBind(device, macAddress, channel, runner)
    logger.info(
        "rfcomm transport RESET | device=%s mac=%s channel=%d "
        "(released + re-bound; stale binding cannot survive)",
        _devicePath(device),
        macAddress,
        channel,
    )
    return _devicePath(device)


def isRfcommBound(
    device: int = 0,
    subprocessRunner: SubprocessRunner | None = None,
) -> bool:
    """
    Return True if ``/dev/rfcommN`` is currently bound to any MAC.

    Args:
        device: rfcomm device number (default 0).
        subprocessRunner: Optional subprocess-runner override for testing.
    """
    runner = subprocessRunner or _defaultRunner
    return _runShow(device, runner) is not None


# ================================================================================
# US-512 -- durable bond state (the RUNTIME half of the pairing story)
# ================================================================================

# bluez prints one flag per line under `info <MAC>`; a device it has never seen
# prints "Device <MAC> not available" and no flags at all.
_BOND_FLAG_RE = {
    'paired': re.compile(r'^\s*Paired:\s*(yes|no)\s*$', re.MULTILINE),
    'bonded': re.compile(r'^\s*Bonded:\s*(yes|no)\s*$', re.MULTILINE),
    'trusted': re.compile(r'^\s*Trusted:\s*(yes|no)\s*$', re.MULTILINE),
}

_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')


def parseBondState(infoOutput: str) -> BondState:
    """Parse ``bluetoothctl info <MAC>`` output into a :class:`BondState`.

    Args:
        infoOutput: Raw (possibly ANSI-coloured) bluetoothctl output.

    Returns:
        The parsed flags.  ``known`` is False when no flag was present at all.
    """
    plain = _ANSI_RE.sub('', infoOutput or '')
    flags: dict[str, bool] = {}
    known = False
    for flag, pattern in _BOND_FLAG_RE.items():
        match = pattern.search(plain)
        if match is not None:
            known = True
            flags[flag] = match.group(1) == 'yes'
    return BondState(
        known=known,
        paired=flags.get('paired', False),
        bonded=flags.get('bonded', False),
        trusted=flags.get('trusted', False),
    )


def isDurableBond(state: BondState) -> bool:
    """True only when the bond survives a reboot AND auto-reconnects.

    ``Paired`` alone is not enough: without ``Bonded`` the link keys are not
    persisted, and without ``Trusted`` bluez refuses an unattended reconnect --
    which is precisely the in-car case (BL-025).

    NOTE (one vocabulary): ``scripts/pair_obdlink_driver.py`` holds the same
    rule for the PAIR-time decision.  The two are pinned against each other
    across the whole truth table by
    ``tests/pi/obdii/test_bluetooth_bond_and_reset.py`` so a change to one
    fails loudly rather than drifting.  See TD-072 for the consolidation.
    """
    return bool(state.paired and state.bonded and state.trusted)


def readBondState(
    macAddress: str,
    subprocessRunner: SubprocessRunner | None = None,
) -> BondState:
    """Read the current bluez bond flags for ``macAddress`` (US-512).

    Best-effort and non-raising: a missing ``bluetoothctl`` (the Windows dev
    box, a stripped bench image), a stalled bluez, or an unparseable reply all
    resolve to ``BondState(known=False)``.  Reporting "unknown" is the honest
    answer; reporting "bonded" off an unread flag would let the connect path
    claim a durable link it never verified.

    Args:
        macAddress: Target Bluetooth MAC.
        subprocessRunner: Optional subprocess-runner override for testing.

    Returns:
        The parsed :class:`BondState`; ``known=False`` when nothing was read.
    """
    runner = subprocessRunner or _defaultRunner
    cmd = [
        BLUETOOTHCTL_CMD, '--timeout', str(BLUETOOTHCTL_TIMEOUT_S),
        'info', macAddress,
    ]
    try:
        result = runner(cmd)
    except Exception as exc:  # noqa: BLE001 -- a bond probe must never raise
        logger.debug("bond-state read failed (%s): %s", _formatCommand(cmd), exc)
        return BondState()
    return parseBondState(result.stdout or '')


def ensureTrusted(
    macAddress: str,
    subprocessRunner: SubprocessRunner | None = None,
) -> BondState:
    """Restore the ``Trusted`` flag when it is the only thing missing (US-512).

    ``scripts/pair_obdlink.sh`` writes Paired+Bonded+Trusted at pair time and
    verifies all three before claiming success -- but nothing at runtime ever
    looked at them again.  A bond that loses ``Trusted`` (a stray
    ``bluetoothctl untrust``, a bluez cache rewrite) still shows as paired, so
    the failure reads as a mystery dead link whose only apparent fix is a
    manual re-pair -- which needs the dongle powered, i.e. the car running.

    Trust is the one half that IS repairable unattended: it is a local bluez
    flag, not a radio handshake.  Pairing is not, so this function repairs
    trust and reports the rest of the state honestly rather than issuing a
    ``trust`` that cannot help.

    Never raises -- bond assurance must not be able to fail a connect attempt
    that would otherwise have worked.

    Args:
        macAddress: Target Bluetooth MAC.
        subprocessRunner: Optional subprocess-runner override for testing.

    Returns:
        The bond state AFTER any repair.  Callers use
        :func:`isDurableBond` on it to decide whether to warn.
    """
    runner = subprocessRunner or _defaultRunner

    state = readBondState(macAddress, subprocessRunner=runner)
    if not state.known:
        logger.warning(
            "No bluez bond record for %s -- a re-pair is required "
            "(scripts/pair_obdlink.sh, dongle powered + in pair mode)",
            macAddress,
        )
        return state
    if state.trusted:
        return state

    logger.warning(
        "Bond for %s is not Trusted (paired=%s bonded=%s) -- bluez will refuse "
        "an unattended reconnect; restoring trust",
        macAddress,
        state.paired,
        state.bonded,
    )
    cmd = [
        BLUETOOTHCTL_CMD, '--timeout', str(BLUETOOTHCTL_TIMEOUT_S),
        'trust', macAddress,
    ]
    try:
        result = runner(cmd)
    except Exception as exc:  # noqa: BLE001 -- best-effort
        logger.warning("trust %s failed to run: %s", macAddress, exc)
        return state
    if result.returncode != 0:
        logger.warning(
            "trust %s failed (rc=%d): %s",
            macAddress,
            result.returncode,
            (result.stderr or result.stdout or '').strip(),
        )
        return state

    # Re-read rather than assume: "Changing trust succeeded" describes the
    # command, not the resulting state.
    repaired = readBondState(macAddress, subprocessRunner=runner)
    if isDurableBond(repaired):
        logger.info(
            "Bond for %s restored to Paired+Bonded+Trusted -- reconnect no "
            "longer needs a manual re-pair",
            macAddress,
        )
    return repaired


# ================================================================================
# US-211 -- lightweight adapter-reachability probe for the reconnect loop
# ================================================================================

# Injection seam for the reachability probe.  Unit tests replace these
# with lambdas so we never hit a real filesystem or run rfcomm.  The
# default wires to os.path.exists + stat.
import os  # noqa: E402 -- kept below public API block for readability

ReachabilityOsChecker = Callable[[str], bool]


def _defaultPathExists(path: str) -> bool:
    """Default exists-check. Isolates the :func:`os.path.exists` call so
    the :func:`isRfcommReachable` probe stays trivially injectable in
    unit tests (Windows dev runner has no /dev/rfcomm0)."""
    return os.path.exists(path)


def isRfcommReachable(
    device: int = 0,
    subprocessRunner: SubprocessRunner | None = None,
    pathExists: ReachabilityOsChecker | None = None,
) -> bool:
    """Return True when ``/dev/rfcommN`` is ready to carry OBD traffic.

    The US-211 reconnect loop fires this probe on every backoff cycle.
    Intentionally lightweight: no full :class:`obd.OBD` reconstruction,
    no ATI/ATZ round-trip -- just the kernel device node + a peek at
    ``rfcomm show`` to confirm a MAC is bound. The loop's caller is
    responsible for reopening python-obd once this returns True.

    Layers:

    1. Stat ``/dev/rfcommN``. If the node is missing, the kernel side of
       the rfcomm binding is not present -- not reachable.
    2. Run ``rfcomm show N`` via the same injectable runner that
       :func:`isRfcommBound` uses. If rfcomm reports the device bound,
       the MAC is live enough for a reopen attempt.

    This two-step check catches both the "rfcomm never bound" state
    (device node missing) and the "bound but adapter dropped" state
    (device node present but ``rfcomm show`` fails). Layer 1 is cheap
    and short-circuits when the node is missing on boot.

    Args:
        device: rfcomm device number (default 0 for OBDLink LX).
        subprocessRunner: Optional subprocess-runner override for tests.
        pathExists: Optional :func:`os.path.exists`-compatible callable
            for unit tests that need to simulate /dev/rfcomm0 presence
            without touching the real filesystem.

    Returns:
        True if both layers pass; False otherwise (including any
        exception raised by the underlying checks).
    """
    devicePath = _devicePath(device)

    # Layer 1: cheap path stat.  On Windows dev runners this always
    # returns False, which is fine -- the probe correctly reports "not
    # reachable" and the reconnect loop keeps waiting.  Unit tests
    # inject pathExists to simulate the Pi side.
    exists = pathExists or _defaultPathExists
    try:
        if not exists(devicePath):
            return False
    except Exception:  # noqa: BLE001 -- probe never raises
        return False

    # Layer 2: rfcomm show confirms the kernel still has the MAC bound.
    try:
        return isRfcommBound(device=device, subprocessRunner=subprocessRunner)
    except Exception:  # noqa: BLE001 -- probe never raises
        return False


# ================================================================================
# Internals
# ================================================================================

def _devicePath(device: int) -> str:
    """Compose the ``/dev/rfcommN`` path for a given device number."""
    return f"/dev/rfcomm{device}"


def _defaultRunner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Default subprocess runner. Never invokes a shell; never pipes input."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    return subprocess.run(cmd, **kwargs)  # noqa: S603 — command list is vetted


#: US-545: the same default runner, under a public name.  Siblings that drive
#: OTHER CLIs (``systemctl``, the pair script) need the identical
#: no-shell/capture/never-check posture, and a second private copy would be a
#: second place for that posture to drift.  Deliberately an alias, not a
#: wrapper: :mod:`bond_self_heal` passes it back INTO this module's functions,
#: so the fake a test injects must be the exact object those functions see.
defaultSubprocessRunner = _defaultRunner


def _formatCommand(cmd: list[str]) -> str:
    """Render a command list back to a human-readable string for error messages."""
    return " ".join(cmd)


def _safeRun(
    cmd: list[str], runner: Callable[..., subprocess.CompletedProcess[str]]
) -> subprocess.CompletedProcess[str]:
    """Execute a command, converting FileNotFoundError to BluetoothHelperError."""
    try:
        return runner(cmd)
    except FileNotFoundError as exc:
        raise BluetoothHelperError(
            f"{RFCOMM_CMD} not found on PATH; is bluez installed? "
            f"(attempted: {_formatCommand(cmd)})"
        ) from exc


def _runShow(
    device: int, runner: SubprocessRunner
) -> RfcommBindInfo | None:
    """
    Query current bind state of /dev/rfcommN.

    Returns parsed info if bound, None if not bound.
    Any other non-zero exit + unrecognised stderr raises.
    """
    cmd = [RFCOMM_CMD, "show", str(device)]
    result = _safeRun(cmd, runner)
    if result.returncode == 0:
        return _parseShowOutput(result.stdout)
    # rfcomm exits non-zero when the device is simply not bound; treat as "not bound"
    stderrLower = (result.stderr or "").lower()
    if "no such device" in stderrLower or "can't get info" in stderrLower:
        return None
    raise BluetoothHelperError(
        f"{_formatCommand(cmd)} failed (rc={result.returncode}): "
        f"{(result.stderr or result.stdout or '').strip()}"
    )


def _runBind(
    device: int,
    macAddress: str,
    channel: int,
    runner: SubprocessRunner,
) -> None:
    cmd = [RFCOMM_CMD, "bind", str(device), macAddress, str(channel)]
    result = _safeRun(cmd, runner)
    if result.returncode != 0:
        raise BluetoothHelperError(
            f"{_formatCommand(cmd)} failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )


def _runRelease(device: int, runner: SubprocessRunner) -> None:
    cmd = [RFCOMM_CMD, "release", str(device)]
    result = _safeRun(cmd, runner)
    if result.returncode != 0:
        raise BluetoothHelperError(
            f"{_formatCommand(cmd)} failed (rc={result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )


# ``rfcomm show`` emits, for a bound device, something like:
#   rfcomm0: 00:04:3E:85:0D:FB channel 1 clean
# For an unbound device it exits non-zero to stderr.
_SHOW_RE = re.compile(
    r'([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}).*?channel\s+(\d+)',
    re.IGNORECASE,
)


def _parseShowOutput(output: str) -> RfcommBindInfo | None:
    """Parse the first line of `rfcomm show` output; return None on no match."""
    if not output:
        return None
    match = _SHOW_RE.search(output)
    if not match:
        return None
    return RfcommBindInfo(macAddress=match.group(1), channel=int(match.group(2)))
