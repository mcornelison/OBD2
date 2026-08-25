################################################################################
# File Name: boot_state_emitter.py
# Purpose/Description: F-103 boot-state emitter [Atlas A-1]. Polls
#   `systemctl is-active` for the CORE-readiness service set + checks the
#   dashboard assets are installed, then writes the boot-state JSON SSOT that the
#   splash kiosk consumes. The splash NEVER decides system condition -- this
#   emitter is the authority; the splash renders the `healthy`/`degraded`
#   booleans verbatim (specs/ssot-design-pattern.md). Honest-instrument rules per
#   spec $FLEET_SHARE/knowledge/superpowers/specs/2026-05-26-b103-splash-animation-design.md §5.
#
#   READINESS MEANS "Pi core / UI is up", NOT "a vehicle is connected"
#   (US-494 / design 2026-07-28-pi-ui-carousel-ssot-wiring-design.md §2). The
#   eclipse-obd tier is SAMPLED and REPORTED for post-boot consumers but does
#   NOT gate the handoff: the Pi lives on a bench with no car most of the time,
#   and gating the dashboard on a vehicle link made the splash unreachable-past
#   forever (see the OBD_NOT_PROBED note below).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# 2026-07-29    | Ralph (Rex)  | US-494 S1: readiness = Pi-core-up. eclipse-obd
#               |              | tier demoted to informational/non-gating;
#               |              | dashboard assets joined the gate; an absent
#               |              | obdProbeFn now reports OBD_NOT_PROBED instead of
#               |              | claiming "starting" forever.
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
# INFORMATIONAL ONLY as of US-494: reported in the payload's `obdTier` field for
# post-boot consumers (the vehicle slice), never a gate on the boot handoff.
OBD_NOT_PROBED = "not-probed"  # no tier probe wired -> reading NOT TAKEN
OBD_STARTING = "starting"  # checks in progress -> verdict not settled yet
OBD_ADAPTER_MISSING = "adapter-missing"  # T1 fail (no adapter / no car)
OBD_ADAPTER_NO_SYNC = "adapter-no-sync"  # T1 ok, T2 fail
OBD_SYNCED_NO_DATA = "synced-no-data"  # T1+T2 ok, T3 fail (engine off)
OBD_SYNCED_WITH_DATA = "synced-with-data"  # T1+T2+T3 ok (live vehicle link)

# OBD_NOT_PROBED vs OBD_STARTING is the load-bearing distinction (US-494).
# "starting" asserts checks are RUNNING; "not-probed" admits no check was ever
# taken. Before US-494 an un-injected probe defaulted to "starting", which is a
# confident claim that stays false forever -- and because the tier then gated the
# handoff, the splash pinned at "eclipse-obd: not ready (starting)" until reboot.
# Same rule as every other instrument here: never dress a missing reading as a
# state.

# Tier outcomes worth a single slow-init retry before the verdict settles
# (ISO 9141-2 K-line slow-init can need 2-4s + a retry on first connect).
# T1 (adapter physically missing) is NOT retried -- it is not a transient.
_OBD_RETRYABLE = frozenset({OBD_ADAPTER_NO_SYNC, OBD_SYNCED_NO_DATA})

# --- CORE readiness: what "the Pi is ready to show its UI" actually means -----
# All three are plain systemd units, queried with `systemctl is-active`:
#   eclipse-states-http     serves boot-state AND the dashboard assets -- without
#                           it the dashboard has no data source at all.
#   eclipse-powerwatch      the D-7/F-7 safe-shutdown guard.
#   boot-progress-finalize  the boot/shutdown bookkeeping unit (oneshot,
#                           RemainAfterExit=yes -> reads `active` once armed).
# eclipse-obd is DELIBERATELY ABSENT: it is the vehicle tier (see module header).
CORE_SERVICES_DEFAULT = (
    "eclipse-states-http",
    "eclipse-powerwatch",
    "boot-progress-finalize",
)

# Sampled + reported, never gating. Keeps the OBD unit's real state visible in
# `services` so an operator can see it without it holding the splash hostage.
INFORMATIONAL_SERVICES_DEFAULT = ("eclipse-obd",)

# The dashboard the splash hands off to. Handing off when this is absent is the
# A-16 blank-screen bug, so its presence is part of CORE readiness. Installed by
# deploy-pi.sh step_install_dashboard_assets.
UI_ASSET_PATH_DEFAULT = "/opt/dashboard/dashboard.html"
UI_ASSETS_PRESENT = "present"
UI_ASSETS_MISSING = "missing"

# systemctl states that represent a terminal verdict for the progress fraction
# (the unit has finished deciding).
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
    coreServiceStates: dict[str, str],
    uiAssetsPresent: bool,
    elapsedSeconds: float,
    hardCapSeconds: float,
    coreServices: tuple[str, ...] | list[str],
    nowIso: str,
    obdTier: str = OBD_NOT_PROBED,
    informationalServiceStates: dict[str, str] | None = None,
) -> dict:
    """Derive the honest-instrument boot-state from raw inputs (pure function).

    Readiness is "Pi core / UI up": every CORE service good AND the dashboard
    assets installed. The eclipse-obd tier is carried through untouched in
    ``obdTier`` and never influences ``healthy``/``degraded`` (US-494 AC-1).

    Args:
        coreServiceStates: ``systemctl is-active`` result per CORE service.
        uiAssetsPresent: True when the dashboard assets are installed.
        elapsedSeconds: Seconds since the emitter started.
        hardCapSeconds: Degrade if no healthy verdict is reached by this point.
        coreServices: The CORE-readiness contract (the gate's membership).
        nowIso: ISO-8601 timestamp to stamp into the payload.
        obdTier: Assessed eclipse-obd granular tier string (informational).
        informationalServiceStates: ``systemctl is-active`` per non-gating
            service, merged into ``services`` for visibility.

    Returns:
        The boot-state dict: ``progress``, ``healthy``, ``degraded``,
        ``services``, ``coreServices``, ``uiAssets``, ``obdTier``,
        ``degradedReason``, ``ts``.
    """
    # `services` holds ONE vocabulary -- raw systemctl states, gating or not.
    # The OBD tier is a different kind of fact (a vehicle-link assessment) and
    # therefore gets its own field rather than overwriting a unit's state.
    services: dict[str, str] = dict(coreServiceStates)
    services.update(informationalServiceStates or {})

    terminalCount = sum(
        1
        for svc in coreServices
        if services.get(svc, "unknown") in _TERMINAL_SYSTEMCTL
    )
    progress = round(terminalCount / len(coreServices), 2) if coreServices else 1.0

    # First degrading failure wins the one-line degradedReason (one-line
    # discipline, spec §5 edge cases). A failed unit outranks missing assets:
    # it is the more fundamental fault.
    degradedReason: str | None = None
    for svc in coreServices:
        if services.get(svc, "unknown") == "failed":
            degradedReason = f"{svc}: failed to start"
            break
    if degradedReason is None and not uiAssetsPresent:
        # A-16: yielding to a dashboard that was never installed is the
        # blank-screen bug. Hold the splash and name the reason.
        degradedReason = "dashboard assets not installed"

    allCoreGood = all(
        services.get(svc, "unknown") == "active" for svc in coreServices
    )
    healthy = allCoreGood and progress >= 1.0 and uiAssetsPresent
    degraded = degradedReason is not None

    # Hard-cap timeout: never reached a healthy verdict in time -> degrade with
    # the first not-good CORE service as the reason (no silent green-when-slow).
    # Only CORE components can appear here -- the OBD tier is not consulted.
    if not healthy and not degraded and elapsedSeconds > hardCapSeconds:
        degraded = True
        for svc in coreServices:
            st = services.get(svc, "unknown")
            if st != "active":
                degradedReason = f"{svc}: not ready ({st})"
                break
        if degradedReason is None:
            degradedReason = "boot did not reach healthy state"

    return {
        "progress": progress,
        "healthy": healthy,
        "degraded": degraded,
        "services": services,
        "coreServices": list(coreServices),
        "uiAssets": UI_ASSETS_PRESENT if uiAssetsPresent else UI_ASSETS_MISSING,
        "obdTier": obdTier,
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
    """Polls the CORE-readiness set + dashboard assets, writes boot-state.

    Dependencies are injected (``serviceQueryFn``, ``obdProbeFn``,
    ``uiAssetProbeFn``, ``elapsedFn``, ``nowIsoFn``) so the verdict logic is
    testable without systemd or hardware.
    """

    BOOT_STATE_FILENAME = "boot-state"

    def __init__(
        self,
        statesDir: str,
        coreServices: tuple[str, ...] | list[str] = CORE_SERVICES_DEFAULT,
        informationalServices: tuple[str, ...]
        | list[str] = INFORMATIONAL_SERVICES_DEFAULT,
        hardCapSeconds: float = 12.0,
        serviceQueryFn: Callable[[str], str] = _queryServiceState,
        obdProbeFn: Callable[[], str] | None = None,
        uiAssetPath: str = UI_ASSET_PATH_DEFAULT,
        uiAssetProbeFn: Callable[[], bool] | None = None,
        elapsedFn: Callable[[], float] | None = None,
        nowIsoFn: Callable[[], str] | None = None,
    ) -> None:
        self.statesDir = statesDir
        self.coreServices = tuple(coreServices)
        self.informationalServices = tuple(informationalServices)
        self.hardCapSeconds = hardCapSeconds
        self.uiAssetPath = uiAssetPath
        self._serviceQueryFn = serviceQueryFn
        # No tier probe wired -> say so (OBD_NOT_PROBED). Never fabricate a
        # "starting" that can never settle; the tier is non-gating either way.
        self._obdProbeFn = obdProbeFn or (lambda: OBD_NOT_PROBED)
        self._uiAssetProbeFn = uiAssetProbeFn or (
            lambda: Path(self.uiAssetPath).is_file()
        )
        startMono = time.monotonic()
        self._elapsedFn = elapsedFn or (lambda: time.monotonic() - startMono)
        self._nowIsoFn = nowIsoFn or (
            lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    def runOnce(self) -> dict:
        """Provision the states dir, sample one verdict, write it, return it."""
        ensureStatesDir(self.statesDir)
        coreStates = {svc: self._serviceQueryFn(svc) for svc in self.coreServices}
        informationalStates = {
            svc: self._serviceQueryFn(svc) for svc in self.informationalServices
        }
        state = computeBootState(
            coreServiceStates=coreStates,
            uiAssetsPresent=self._uiAssetProbeFn(),
            elapsedSeconds=self._elapsedFn(),
            hardCapSeconds=self.hardCapSeconds,
            coreServices=self.coreServices,
            nowIso=self._nowIsoFn(),
            obdTier=assessObdTier(self._obdProbeFn),
            informationalServiceStates=informationalStates,
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


def buildEmitter(
    statesDir: str, hardCapSeconds: float, uiAssetPath: str
) -> BootStateEmitter:
    """Construct the emitter the systemd unit runs (the production wiring).

    Extracted from ``main`` so the wiring itself is assertable: US-494's root
    cause was a dependency the entry point silently never injected.
    """
    return BootStateEmitter(
        statesDir=statesDir,
        hardCapSeconds=hardCapSeconds,
        uiAssetPath=uiAssetPath,
    )


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
    parser.add_argument(
        "--ui-asset-path",
        default=UI_ASSET_PATH_DEFAULT,
        help=(
            "dashboard asset whose presence proves the UI is installed "
            f"(default: {UI_ASSET_PATH_DEFAULT})"
        ),
    )
    args = parser.parse_args(argv)

    emitter = buildEmitter(
        statesDir=args.states_dir,
        hardCapSeconds=args.hard_cap_seconds,
        uiAssetPath=args.ui_asset_path,
    )
    runForever(emitter, pollSeconds=args.poll_ms / 1000.0)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
