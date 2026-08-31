################################################################################
# File Name: pld_witness.py
# Purpose/Description: ARCH-019 -- a durable record of whether the PLD pin has
#   ever been OBSERVED TO CHANGE.
#
#   WHY THIS EXISTS. powerwatch's startup arm check reads the PLD pin once, sees
#   power-present, and declares safe-shutdown protection ON -- then predicts that
#   "a sustained external-power loss WILL run the bounded pre-shutdown pipeline
#   and then poweroff". That prediction is asserted from a single instantaneous
#   read. The check proves the pin can be READ. It does not prove the pin CHANGES.
#
#   ⚠️ A signal that reads correctly but has never been seen to transition is
#   INDISTINGUISHABLE FROM A WIRE THAT IS NOT CONNECTED. On 2026-08-31 the Pi died
#   a hard cut in the car -- no detection, no splash, no poweroff -- while that
#   line had been reporting ARMED for weeks. The root cause was topology: the UPS
#   was never in the power path, which is precisely the condition under which the
#   pin never moves and the arm check still passes.
#
#   THE FIX IS NOT TO STOP ARMING. It is to say what was actually verified, and
#   to make PROVEN reachable -- record the first real transition, persist it
#   across reboots, and only then let the message claim what it will do.
#
#   This is the inert-guard pattern (specs/anti-patterns.md) in hardware:
#   presence verified, function assumed.
#
#   DESIGN NOTES
#   - Persisted, because a witness forgotten at poweroff leaves the check
#     permanently unproven -- no better than never recording it.
#   - Every operation FAILS TO THE HONEST SIDE: an unreadable or corrupt witness
#     reads as NEVER, never as proven.
#   - Recording is BEST-EFFORT and must never raise. It runs during a power-loss
#     event, on a machine that is about to lose power; an exception here would
#     abort the very pipeline it exists to observe.
# Author: Atlas (Architect)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Atlas        | Initial -- ARCH-019 PLD transition witness.
# ================================================================================
################################################################################

"""Durable record of whether the PLD pin has ever been observed to change."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Default location. Under /var/lib so it survives a reboot -- /run would be
#: wiped exactly when the record matters most, on the boot after the event.
DEFAULT_WITNESS_PATH = Path("/var/lib/eclipse-obd/pld-transition-witness.json")

#: The single key. Named for what it holds rather than for the feature, so a
#: human reading the file with no context can tell what it means.
WITNESS_KEY = "lastTransitionUtc"


def readWitness(path: Path | str = DEFAULT_WITNESS_PATH) -> str | None:
    """The UTC instant a PLD transition was last observed, or None.

    Args:
        path: Witness file location.

    Returns:
        ISO-8601 UTC string, or None if no transition has ever been witnessed
        -- which is ALSO what a missing, unreadable or corrupt file returns.
        Absence of the record is not evidence the pin works, so every failure
        mode resolves to the honest answer rather than to an optimistic one.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        value = json.loads(raw).get(WITNESS_KEY)
    except (ValueError, AttributeError):
        # A corrupt witness means we do not KNOW whether the pin has moved.
        # That is "never proven", and it must not take powerwatch down with it.
        logger.warning("pld-witness: unreadable witness at %s -- treating as NEVER", path)
        return None
    return value if isinstance(value, str) and value else None


def recordTransitionWitnessed(path: Path | str = DEFAULT_WITNESS_PATH, *, atIso: str) -> bool:
    """Record that the PLD pin was OBSERVED to change. Best-effort, never raises.

    Called from the power-loss path, so it runs on a machine that is losing
    power. Every failure is swallowed: losing the witness costs a future log
    line, whereas raising here would abort the shutdown pipeline itself.

    Args:
        path: Witness file location.
        atIso: ISO-8601 UTC instant of the observed transition.

    Returns:
        Whether the record was durably written.
    """
    target = Path(path)
    # ⚠️ Deliberately does NOT create the directory tree. The witness belongs
    # beside the application's existing state; if that directory is absent we
    # are not on a deployed system, and a test run on a developer machine must
    # not invent filesystem layout under /var. Found the hard way -- the first
    # version of this created C:\var\lib\eclipse-obd on a Windows dev box.
    try:
        target.write_text(
            json.dumps({WITNESS_KEY: atIso}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.warning("pld-witness: could not record transition (%s)", exc)
        return False
