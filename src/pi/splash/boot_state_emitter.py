################################################################################
# File Name: boot_state_emitter.py
# Purpose/Description: F-103 boot-state emitter [Atlas A-1]. Polls
#   `systemctl is-active` for the critical-services set + assesses the tiered
#   eclipse-obd health, then writes the boot-state JSON SSOT that the splash
#   kiosk consumes. The splash NEVER decides system condition -- this emitter is
#   the authority; the splash renders the `healthy`/`degraded` booleans verbatim
#   (specs/ssot-design-pattern.md). Honest-instrument rules per spec
#   docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md §5.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# ================================================================================
################################################################################

"""Boot-state emitter: writes the honest-instrument boot-state JSON SSOT."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

# --- eclipse-obd tiered-health granular strings (spec §5, Spool S-1) ----------
# These are surfaced for POST-BOOT UI consumers; the splash reads only the
# top-level healthy/degraded booleans this module derives from them.
OBD_STARTING = "starting"  # checks in progress -> neither healthy nor degraded
OBD_ADAPTER_MISSING = "adapter-missing"  # T1 fail -> DEGRADED
OBD_ADAPTER_NO_SYNC = "adapter-no-sync"  # T1 ok, T2 fail -> DEGRADED
OBD_SYNCED_NO_DATA = "synced-no-data"  # T1+T2 ok, T3 fail (engine off) -> NOT degraded
OBD_SYNCED_WITH_DATA = "synced-with-data"  # T1+T2+T3 ok -> healthy contributor

# eclipse-obd tier outcomes that count as "good" (not a fault) for the splash.
# synced-no-data is INCLUDED: an engine-off boot with the ECU silent is
# legitimate, not a fault (alarm-fatigue guard, Spool S-1 / failure-mode F-7).
_OBD_GOOD = frozenset({OBD_SYNCED_NO_DATA, OBD_SYNCED_WITH_DATA})

# Tier outcomes worth a single slow-init retry before the verdict settles
# (ISO 9141-2 K-line slow-init can need 2-4s + a retry on first connect).
# T1 (adapter physically missing) is NOT retried -- it is not a transient.
_OBD_RETRYABLE = frozenset({OBD_ADAPTER_NO_SYNC, OBD_SYNCED_NO_DATA})

# Critical-services set owned by this emitter (Spool S-1, set unchanged). The
# splash never decides what counts -- it reads the derived booleans.
CRITICAL_SERVICES_DEFAULT = (
    "eclipse-powerwatch",
    "eclipse-obd",
    "boot-progress-finalize",
)

# Non-eclipse-obd systemctl states that represent a terminal verdict for the
# progress fraction (the unit has finished deciding).
_TERMINAL_SYSTEMCTL = frozenset({"active", "failed"})


def assessObdTier(probeFn: Callable[[], str]) -> str:
    """Probe the eclipse-obd tier health, retrying once on a slow-init transient.

    Args:
        probeFn: Callable returning one of the OBD_* granular strings.

    Returns:
        The settled tier string. A T2/T3-class transient (``adapter-no-sync`` or
        ``synced-no-data``) triggers exactly one re-probe before settling; T1
        (``adapter-missing``) and a healthy ``synced-with-data`` settle on the
        first probe.
    """
    result = probeFn()
    if result in _OBD_RETRYABLE:
        result = probeFn()
    return result


def computeBootState(
    serviceStates: dict[str, str],
    obdTier: str,
    elapsedSeconds: float,
    hardCapSeconds: float,
    criticalServices: tuple[str, ...] | list[str],
    nowIso: str,
) -> dict:
    """Derive the honest-instrument boot-state from raw inputs (pure function).

    Args:
        serviceStates: ``systemctl is-active`` result per non-eclipse-obd
            critical service.
        obdTier: The assessed eclipse-obd granular tier string.
        elapsedSeconds: Seconds since the emitter started.
        hardCapSeconds: Degrade if no healthy verdict is reached by this point.
        criticalServices: The critical-services contract.
        nowIso: ISO-8601 timestamp to stamp into the payload.

    Returns:
        The boot-state dict: ``progress``, ``healthy``, ``degraded``,
        ``services``, ``degradedReason``, ``ts``.
    """
    services: dict[str, str] = dict(serviceStates)
    # The eclipse-obd granular tier string supersedes its raw systemctl state.
    services["eclipse-obd"] = obdTier

    def isTerminal(svc: str, st: str) -> bool:
        if svc == "eclipse-obd":
            return st != OBD_STARTING
        return st in _TERMINAL_SYSTEMCTL

    def isGood(svc: str, st: str) -> bool:
        if svc == "eclipse-obd":
            return st in _OBD_GOOD
        return st == "active"

    terminalCount = sum(
        1 for s in criticalServices if isTerminal(s, services.get(s, "unknown"))
    )
    progress = round(terminalCount / len(criticalServices), 2) if criticalServices else 1.0

    # First degrading failure wins the one-line degradedReason (one-line
    # discipline, spec §5 edge cases). T3 (synced-no-data) is intentionally NOT
    # a degrade trigger.
    degradedReason: str | None = None
    for svc in criticalServices:
        st = services.get(svc, "unknown")
        if svc == "eclipse-obd":
            if st == OBD_ADAPTER_MISSING:
                degradedReason = "OBD adapter not detected"
                break
            if st == OBD_ADAPTER_NO_SYNC:
                degradedReason = "OBD adapter not responding"
                break
        elif st == "failed":
            degradedReason = f"{svc}: failed to start"
            break

    allGood = all(isGood(s, services.get(s, "unknown")) for s in criticalServices)
    healthy = allGood and progress >= 1.0
    degraded = degradedReason is not None

    # Hard-cap timeout: never reached a healthy verdict in time -> degrade with
    # the first not-good service as the reason (no silent green-when-slow).
    if not healthy and not degraded and elapsedSeconds > hardCapSeconds:
        degraded = True
        for svc in criticalServices:
            st = services.get(svc, "unknown")
            if not isGood(svc, st):
                degradedReason = f"{svc}: not ready ({st})"
                break
        if degradedReason is None:
            degradedReason = "boot did not reach healthy state"

    return {
        "progress": progress,
        "healthy": healthy,
        "degraded": degraded,
        "services": services,
        "degradedReason": degradedReason,
        "ts": nowIso,
    }


def ensureStatesDir(statesDir: str) -> None:
    """Create the tmpfs states directory if absent (idempotent).

    Part of the C-5 contract: the F-103 units provision ``states/`` themselves
    so it exists independent of eclipse-obd.service (whose ``RuntimeDirectory``
    is ref-counted + removed on stop and never creates the ``states/`` subdir).
    """
    Path(statesDir).mkdir(parents=True, exist_ok=True)


def writeStateAtomic(path: str, payload: dict) -> None:
    """Write ``payload`` as JSON to ``path`` atomically (temp + os.replace).

    A reader (the HTTP server) never observes a half-written file -- it sees the
    prior complete file until the rename swaps in the new one.
    """
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(str(tmp), str(target))


def _queryServiceState(serviceName: str) -> str:
    """Return ``systemctl is-active <serviceName>`` (stdout), 'unknown' on error."""
    try:
        completed = subprocess.run(
            ["systemctl", "is-active", serviceName],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return completed.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class BootStateEmitter:
    """Polls the critical-services set + eclipse-obd tier, writes boot-state.

    Dependencies are injected (``serviceQueryFn``, ``obdProbeFn``, ``elapsedFn``,
    ``nowIsoFn``) so the verdict logic is testable without systemd or hardware.
    """

    BOOT_STATE_FILENAME = "boot-state"

    def __init__(
        self,
        statesDir: str,
        criticalServices: tuple[str, ...] | list[str] = CRITICAL_SERVICES_DEFAULT,
        hardCapSeconds: float = 12.0,
        serviceQueryFn: Callable[[str], str] = _queryServiceState,
        obdProbeFn: Callable[[], str] | None = None,
        elapsedFn: Callable[[], float] | None = None,
        nowIsoFn: Callable[[], str] | None = None,
    ) -> None:
        self.statesDir = statesDir
        self.criticalServices = tuple(criticalServices)
        self.hardCapSeconds = hardCapSeconds
        self._serviceQueryFn = serviceQueryFn
        self._obdProbeFn = obdProbeFn or (lambda: OBD_STARTING)
        startMono = time.monotonic()
        self._elapsedFn = elapsedFn or (lambda: time.monotonic() - startMono)
        self._nowIsoFn = nowIsoFn or (
            lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    def runOnce(self) -> dict:
        """Provision the states dir, sample one verdict, write it, return it."""
        ensureStatesDir(self.statesDir)
        serviceStates = {
            svc: self._serviceQueryFn(svc)
            for svc in self.criticalServices
            if svc != "eclipse-obd"
        }
        obdTier = assessObdTier(self._obdProbeFn)
        state = computeBootState(
            serviceStates,
            obdTier,
            self._elapsedFn(),
            self.hardCapSeconds,
            self.criticalServices,
            self._nowIsoFn(),
        )
        writeStateAtomic(
            os.path.join(self.statesDir, self.BOOT_STATE_FILENAME), state
        )
        return state


def runForever(
    emitter: BootStateEmitter,
    pollSeconds: float,
    sleepFn: Callable[[float], None] = time.sleep,
    stopAfter: int | None = None,
) -> None:
    """Emit the boot-state repeatedly at ``pollSeconds`` cadence.

    Args:
        emitter: The configured emitter.
        pollSeconds: Delay between emissions.
        sleepFn: Sleep implementation (injected for tests).
        stopAfter: Stop after this many emissions (None = run forever; the unit
            is Type=simple and stays up until systemd stops it on shutdown).
    """
    count = 0
    while True:
        emitter.runOnce()
        count += 1
        if stopAfter is not None and count >= stopAfter:
            return
        sleepFn(pollSeconds)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for eclipse-boot-state.service."""
    import argparse

    parser = argparse.ArgumentParser(description="F-103 boot-state emitter")
    parser.add_argument(
        "--states-dir",
        default="/run/eclipse-obd/states",
        help="tmpfs states directory (default: /run/eclipse-obd/states)",
    )
    parser.add_argument(
        "--poll-ms", type=int, default=500, help="poll interval in ms (default 500)"
    )
    parser.add_argument(
        "--hard-cap-seconds", type=float, default=12.0, help="degrade timeout"
    )
    args = parser.parse_args(argv)

    emitter = BootStateEmitter(
        statesDir=args.states_dir, hardCapSeconds=args.hard_cap_seconds
    )
    runForever(emitter, pollSeconds=args.poll_ms / 1000.0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
