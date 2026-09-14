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
# 2026-09-03    | Rex (US-667) | The failure WARNING now names the path
#                                explicitly instead of relying on the OSError
#                                repr to carry it. The dev-box guard below is
#                                UNCHANGED and deliberately so -- deploy-pi.sh
#                                now provisions /var/lib/eclipse-obd, because
#                                the deploy owns the filesystem and the
#                                application owns the file.
# 2026-09-13    | Rex (US-682) | The write is ATOMIC and BOUNDED. On 2026-09-04
#                                a real transition left a 0-byte witness: the
#                                old write_text truncated the target, then lost
#                                the race with the power loss it was recording.
#                                Now temp in the same dir -> fsync -> os.replace
#                                -> fsync the dir (the boot_progress.py:214-221
#                                shape), in a worker bounded by one smoothing
#                                poll. readWitness names an EMPTY file a LOST
#                                WRITE at WARNING; it still reads as NEVER.
# 2026-09-13    | Rex (US-666) | The record-failure WARNING names the arm
#                                line's new unwitnessed verdict, TRANSITION
#                                UNVERIFIED (was UNPROVEN).
# ================================================================================
################################################################################

"""Durable record of whether the PLD pin has ever been observed to change."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

#: Default location. Under /var/lib so it survives a reboot -- /run would be
#: wiped exactly when the record matters most, on the boot after the event.
DEFAULT_WITNESS_PATH = Path("/var/lib/eclipse-obd/pld-transition-witness.json")

#: The single key. Named for what it holds rather than for the feature, so a
#: human reading the file with no context can tell what it means.
WITNESS_KEY = "lastTransitionUtc"

#: US-682: the longest the power-loss path waits for the witness write. The
#: write is the first statement of ``handleOnBattery``, ahead of the T=0 grace
#: emit and the smoothing window, against a 45 s totalCap. Grounded on
#: config.json ``pi.powerWatch.smoothingPollSec`` = 1: the witness may cost that
#: path at most one poll interval of the loop it precedes. A write still in
#: flight at the bound is not abandoned -- it may land later, atomically.
WITNESS_WRITE_TIMEOUT_SEC: float = 1.0


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
    if not raw.strip():
        # US-682: a file that EXISTS with no content is a write that did not
        # land -- not a transition that never happened. NEVER stays the safe
        # answer, but the journal must not collapse the two into one line.
        logger.warning(
            "pld-witness: witness at %s EXISTS but is EMPTY -- a LOST WRITE, not "
            "an absent event: the file was created and its content never landed. "
            "Treating as NEVER.",
            path,
        )
        return None
    try:
        value = json.loads(raw).get(WITNESS_KEY)
    except (ValueError, AttributeError):
        # A corrupt witness means we do not KNOW whether the pin has moved.
        # That is "never proven", and it must not take powerwatch down with it.
        logger.warning("pld-witness: unreadable witness at %s -- treating as NEVER", path)
        return None
    return value if isinstance(value, str) and value else None


def recordTransitionWitnessed(
    path: Path | str = DEFAULT_WITNESS_PATH,
    *,
    atIso: str,
    timeoutSec: float = WITNESS_WRITE_TIMEOUT_SEC,
) -> bool:
    """Record that the PLD pin was OBSERVED to change. Best-effort, never raises.

    Called from the power-loss path, so it runs on a machine that is losing
    power. Every failure is swallowed: losing the witness costs a future log
    line, whereas raising here would abort the shutdown pipeline itself.

    US-682: the write runs in a daemon worker and the caller waits at most
    ``timeoutSec`` -- the same bounded-wait shape ``ShutdownSequencer`` uses for
    its pipeline -- so a storage stall cannot hold the power-loss path.

    Args:
        path: Witness file location.
        atIso: ISO-8601 UTC instant of the observed transition.
        timeoutSec: Longest the caller waits for the write to finish.

    Returns:
        Whether the record was durably written within the bound.
    """
    target = Path(path)
    outcome: list[bool] = []
    done = threading.Event()

    def _write() -> None:
        try:
            outcome.append(_writeWitnessAtomically(target, atIso))
        finally:
            done.set()

    threading.Thread(target=_write, name="pld-witness-write", daemon=True).start()
    if not done.wait(timeout=timeoutSec):
        logger.warning(
            "pld-witness: write to %s did not finish within %.1fs -- not holding the "
            "power-loss path for it; the previous witness is intact and this one "
            "may still land",
            target,
            timeoutSec,
        )
        return False
    return bool(outcome and outcome[0])


def _writeWitnessAtomically(target: Path, atIso: str) -> bool:
    """Temp in the same directory -> fsync -> os.replace -> fsync the directory.

    A reader only ever sees the whole previous witness or the whole new one.
    The target is never opened for writing, so dying at any instant cannot
    leave it empty or partial. Mirrors ``boot_progress._autoTrimAndAppend``.

    Args:
        target: Witness file location.
        atIso: ISO-8601 UTC instant of the observed transition.

    Returns:
        Whether the record was committed.
    """
    payload = (json.dumps({WITNESS_KEY: atIso}, ensure_ascii=False) + "\n").encode("utf-8")
    # Unique per writer: power_log shows a transition handled twice, and two
    # writers must not share (and truncate) one temp file.
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    # ⚠️ Deliberately does NOT create the directory tree. The witness belongs
    # beside the application's existing state; if that directory is absent we
    # are not on a deployed system, and a test run on a developer machine must
    # not invent filesystem layout under /var. Found the hard way -- the first
    # version of this created C:\var\lib\eclipse-obd on a Windows dev box.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(tmp, flags, 0o644)
        try:
            view = memoryview(payload)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)
        _fsyncDirectoryBestEffort(target.parent)
        return True
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        # US-667: name the PATH explicitly rather than relying on the OSError
        # repr to carry it. Some OSError variants omit filename entirely, and
        # on Windows the repr escapes separators -- so an operator grepping the
        # journal for the witness path would miss its own failure. The one
        # thing this line exists to say is WHICH file could not be written.
        logger.warning(
            "pld-witness: could not record transition at %s (%s) -- the arm "
            "line will read TRANSITION UNVERIFIED despite a witnessed transition; is the "
            "parent directory provisioned?",
            target,
            exc,
        )
        return False


def _fsyncDirectoryBestEffort(directory: Path) -> None:
    """fsync the directory so the rename itself survives a power loss. Never raises.

    ``os.replace`` is atomic, but the new directory entry is only durable once
    the directory is synced. Windows cannot open a directory for fsync; the dev
    box degrades at DEBUG while the Pi keeps the guarantee.

    Args:
        directory: Parent directory of the witness.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        logger.debug("pld-witness: directory fsync skipped for %s: %s", directory, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        logger.debug("pld-witness: directory fsync failed for %s: %s", directory, exc)
    finally:
        os.close(fd)
