################################################################################
# File Name: boot_battery_test.py
# Purpose/Description: F-054 boot-time battery test (US-445).  Reads the MAX17048
#   fuel-gauge VCELL (+ SoC) register once at boot, produces a grounded, honest-
#   instrument health verdict (OK / WEAK / UNKNOWN), and writes the result to the
#   `boot-battery-test` state SSOT (same tmpfs states dir + atomic-write idiom as
#   the F-103 boot-state / F-097 battery-health emitters).  Degradation is thus
#   surfaced at every boot without polluting the drain-event-shaped
#   `battery_health_log` table (which is for start/close drain baselines, not
#   snapshots -- see US-442 note in battery_health.py).
#
#   Honest-instrument contract (US-445 AC): an unreadable OR physically
#   implausible VCELL resolves to UNKNOWN -- never a confident wrong health.  The
#   verdict is driven by VCELL (a direct register read, trustworthy the instant
#   the chip powers up); the SoC% register needs a ~3-min ModelGauge warmup, so it
#   is carried as CONTEXT only (with a `socCalibrated` caveat), never as the
#   health basis.  The runner is best-effort: a reader that raises resolves to
#   UNKNOWN and a state-write failure is logged, never raised -- a battery test
#   must never fail boot.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-445) | Initial implementation.  Pure grounded VCELL-band
#                              | assessment + best-effort state emit + a `main()`
#                              | CLI so a boot oneshot unit can run the test.  No
#                              | battery_health_log write (snapshot != drain
#                              | event); VCELL drives the verdict, SoC is context.
# ================================================================================
################################################################################

"""Boot-time battery test: read the fuel gauge once, assess health, emit state.

A single VCELL register read at boot cannot distinguish a *degraded* pack from a
merely *discharged* one, so this reports a coarse, honest health verdict grounded
in the known LiPo operating bands for this UPS HAT:

- ``OK``      -- VCELL at/above the discharge knee (~3.70 V): usable reserve.
- ``WEAK``    -- VCELL plausible but below the discharge knee (the pack is low --
  surfaced early); a read below the buck-converter dropout knee (~3.30 V, the
  Drain-7 empirical) carries a distinct reason but the same coarse verdict (we do
  not invent a confident third tier from one reading).
- ``UNKNOWN`` -- the read failed OR is physically implausible (e.g. the classic
  ~20 V un-byte-swapped MAX17048 read).  Honest instrument: never a wrong health.

Grounding (specs/grounded-knowledge.md + ups_monitor.py):

- Buck-converter dropout knee ``VCELL ~= 3.30 V`` (Drain Test 7 empirical).
- Discharge knee ~3.70 V; healthy AC float ~4.10 V; full ~4.20 V (ups_monitor).
- Physical LiPo plausibility band ~2.5-4.35 V; a read outside it is a sensor/
  byte-order fault, not a health signal.

Usage::

    result = runBootBatteryTest(
        readVcell=monitor.getBatteryVoltage,
        readSoc=monitor.getBatteryPercentage,
        statesDir="/run/eclipse-obd/states",
    )
    # result.verdict in {OK, WEAK, UNKNOWN}; state file also written for the UI.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

# Reuse the F-103 state primitives (one provisioning + atomic-write impl, no dup).
from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

logger = logging.getLogger(__name__)


# ================================================================================
# Constants (grounded -- see module docstring)
# ================================================================================

# The single SSOT slot for the boot battery-test result (tmpfs state file).
BOOT_BATTERY_TEST_FILENAME = "boot-battery-test"

# Physical plausibility band for a single-cell LiPo on the MAX17048.  A read
# outside this band is a sensor / byte-order fault (e.g. ~20 V un-byte-swapped),
# NOT a health claim -> resolves to UNKNOWN.
VCELL_PLAUSIBLE_MIN_V = 2.5
VCELL_PLAUSIBLE_MAX_V = 4.35

# Discharge knee: at/above this the pack has usable reserve (OK); below it the
# pack is low and the test surfaces WEAK early.
VCELL_HEALTHY_FLOOR_V = 3.70

# Buck-converter dropout knee (Drain Test 7, 2026-05-02 empirical): below this
# the HAT cannot hold the Pi rail.  Used only to sharpen the WEAK reason string.
VCELL_DROPOUT_KNEE_V = 3.30

# The ISO-8601 instant format the F-103 emitters stamp (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

__all__ = [
    "BOOT_BATTERY_TEST_FILENAME",
    "VCELL_DROPOUT_KNEE_V",
    "VCELL_HEALTHY_FLOOR_V",
    "VCELL_PLAUSIBLE_MAX_V",
    "VCELL_PLAUSIBLE_MIN_V",
    "BootBatteryTestResult",
    "BootBatteryVerdict",
    "assessBootBatteryHealth",
    "buildBootBatteryTestState",
    "runBootBatteryTest",
]


class BootBatteryVerdict(Enum):
    """Coarse boot-time battery-health verdict.

    Deliberately two determinate tiers plus UNKNOWN -- a single boot reading is
    not enough to claim a fine-grained health grade, so the verdict stays honest.
    """

    OK = "ok"
    WEAK = "weak"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BootBatteryTestResult:
    """The outcome of one boot battery test.

    Attributes:
        verdict: The assessed :class:`BootBatteryVerdict`.
        reason: A short grounded reason string (why this verdict).
        vcellV: The VCELL reading in volts, or None if the read failed.
        socPct: The raw SoC register percent, or None if unavailable/skipped.
        socCalibrated: Whether the SoC register is past its ModelGauge warmup
            (context only -- the verdict never depends on SoC).
    """

    verdict: BootBatteryVerdict
    reason: str
    vcellV: float | None
    socPct: int | None
    socCalibrated: bool


# ================================================================================
# Assessment (pure)
# ================================================================================


def assessBootBatteryHealth(
    vcellV: float | None,
) -> tuple[BootBatteryVerdict, str]:
    """Return the grounded health verdict for a single VCELL reading.

    Honest-instrument: an unreadable (``None``) or physically implausible reading
    resolves to :attr:`BootBatteryVerdict.UNKNOWN` -- never a confident wrong
    health.  Otherwise the plausible VCELL is banded against the grounded knees.

    Args:
        vcellV: The VCELL reading in volts, or None if the register read failed.

    Returns:
        A ``(verdict, reason)`` pair.
    """
    if vcellV is None:
        return BootBatteryVerdict.UNKNOWN, "vcell-unreadable"

    if not (VCELL_PLAUSIBLE_MIN_V <= vcellV <= VCELL_PLAUSIBLE_MAX_V):
        return BootBatteryVerdict.UNKNOWN, "vcell-implausible"

    if vcellV >= VCELL_HEALTHY_FLOOR_V:
        return BootBatteryVerdict.OK, "vcell-healthy"

    if vcellV < VCELL_DROPOUT_KNEE_V:
        return BootBatteryVerdict.WEAK, "vcell-below-dropout-knee"

    return BootBatteryVerdict.WEAK, "vcell-below-healthy-floor"


def buildBootBatteryTestState(
    *,
    verdict: BootBatteryVerdict,
    reason: str,
    vcellV: float | None,
    socPct: int | None,
    socCalibrated: bool,
    nowIso: str,
) -> dict:
    """Assemble the boot battery-test state payload (pure).

    Args:
        verdict: The assessed :class:`BootBatteryVerdict`.
        reason: The grounded reason string.
        vcellV: VCELL in volts, or None.
        socPct: Raw SoC register percent, or None.
        socCalibrated: Whether the SoC register is past its warmup (context).
        nowIso: ISO-8601 emission timestamp (freshness marker).

    Returns:
        The state dict with exactly the documented keys.
    """
    return {
        "verdict": verdict.value,
        "reason": reason,
        "vcellV": vcellV,
        "socPct": socPct,
        "socCalibrated": socCalibrated,
        "ts": nowIso,
    }


# ================================================================================
# Runner (read + assess + emit)
# ================================================================================


def _safeRead(reader: Callable[[], float | int] | None) -> float | int | None:
    """Call ``reader`` returning its value, or None on any failure/absence.

    A hardware read at boot may raise (missing/broken fuel gauge); the boot test
    must degrade to UNKNOWN, never crash the boot path.
    """
    if reader is None:
        return None
    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 -- boot must never fail on a read
        logger.debug("boot battery test: reader failed (%s) -> None", exc)
        return None


def runBootBatteryTest(
    *,
    readVcell: Callable[[], float] | None,
    readSoc: Callable[[], int] | None = None,
    statesDir: str,
    socCalibrated: bool = False,
    nowIsoFn: Callable[[], str] | None = None,
) -> BootBatteryTestResult:
    """Read the fuel gauge once, assess health, and emit the result state.

    Best-effort by contract: a reader that raises resolves to UNKNOWN, and a
    state-write failure is logged but NEVER raised, so the boot test can never
    fail the boot.

    Args:
        readVcell: Zero-arg callable returning VCELL in volts (e.g.
            ``UpsMonitor.getBatteryVoltage``).  A raise resolves to UNKNOWN.
        readSoc: Optional zero-arg callable returning the SoC register percent.
            Carried as context only (the verdict never depends on it).
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        socCalibrated: Whether the SoC register is past its ModelGauge warmup.
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        The :class:`BootBatteryTestResult`.
    """
    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))

    rawVcell = _safeRead(readVcell)
    vcellV = float(rawVcell) if rawVcell is not None else None

    rawSoc = _safeRead(readSoc)
    socPct = int(rawSoc) if rawSoc is not None else None

    verdict, reason = assessBootBatteryHealth(vcellV)

    payload = buildBootBatteryTestState(
        verdict=verdict,
        reason=reason,
        vcellV=vcellV,
        socPct=socPct,
        socCalibrated=socCalibrated,
        nowIso=nowFn(),
    )

    try:
        ensureStatesDir(statesDir)
        writeStateAtomic(os.path.join(statesDir, BOOT_BATTERY_TEST_FILENAME), payload)
    except Exception as exc:  # noqa: BLE001 -- best-effort, never block/fail boot
        logger.error(
            "boot battery-test state emit failed (%s) -- ignored (a battery test "
            "never fails the boot)",
            exc,
        )

    logger.info(
        "boot battery test | verdict=%s | reason=%s | vcell=%s | soc=%s%s",
        verdict.value,
        reason,
        f"{vcellV:.3f}V" if vcellV is not None else "n/a",
        socPct if socPct is not None else "n/a",
        "" if socCalibrated else " (uncalibrated)",
    )
    return BootBatteryTestResult(
        verdict=verdict,
        reason=reason,
        vcellV=vcellV,
        socPct=socPct,
        socCalibrated=socCalibrated,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for a boot oneshot unit (e.g. eclipse-boot-battery-test).

    Builds real MAX17048 readers from :class:`UpsMonitor`.  On a non-Pi host, or
    if the gauge is absent, the readers raise and the test honestly records
    UNKNOWN.  Always returns 0 -- a battery test must never fail the boot.
    """
    import argparse

    parser = argparse.ArgumentParser(description="F-054 boot-time battery test")
    parser.add_argument(
        "--states-dir",
        default="/run/eclipse-obd/states",
        help="tmpfs states directory (default: /run/eclipse-obd/states)",
    )
    parser.add_argument(
        "--ups-address",
        type=lambda s: int(s, 0),
        default=0x36,
        help="MAX17048 I2C address (default: 0x36)",
    )
    parser.add_argument(
        "--i2c-bus", type=int, default=1, help="I2C bus number (default: 1)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    # Import here (not at module load) so the pure assessment layer stays free of
    # the hardware dependency and importable on any host.
    from pi.hardware.ups_monitor import UpsMonitor

    monitor = UpsMonitor(address=args.ups_address, bus=args.i2c_bus)
    try:
        runBootBatteryTest(
            readVcell=monitor.getBatteryVoltage,
            readSoc=monitor.getBatteryPercentage,
            statesDir=args.states_dir,
        )
    finally:
        monitor.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
