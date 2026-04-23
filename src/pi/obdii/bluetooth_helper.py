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
