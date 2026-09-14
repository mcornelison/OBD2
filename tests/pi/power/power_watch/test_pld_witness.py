################################################################################
# File Name: test_pld_witness.py
# Purpose/Description: ARCH-019 -- the PLD transition WITNESS.
#
#   THE DEFECT. powerwatch's arm self-check reads the PLD pin once at startup,
#   sees power-present, and logs:
#
#       ARM DECISION = ARMED -- safe-shutdown protection is ON ...
#       A sustained external-power loss WILL run the bounded pre-shutdown
#       pipeline and then poweroff.
#
#   That last sentence is a PREDICTION ABOUT FUTURE BEHAVIOUR asserted from a
#   single instantaneous read. The check proves the pin can be READ. It does not
#   prove the pin CHANGES.
#
#   ⚠️ A signal that reads correctly but has never been observed to transition is
#   INDISTINGUISHABLE FROM A WIRE THAT IS NOT CONNECTED. On 2026-08-31 the Pi
#   died a hard cut in the car -- no detection, no splash, no poweroff -- while
#   this line had been reporting ARMED for weeks. The root cause turned out to be
#   topology (the UPS was never in the power path at all), which is exactly the
#   condition under which the pin would never move and the check would still pass.
#
#   THE FIX IS NOT TO STOP ARMING. It is to say what was actually verified, and
#   to make PROVEN reachable: record the first real transition, persist it across
#   reboots, and report ARMED (PROVEN) only once the pin has been SEEN to change.
#
#   This is the inert-guard pattern (specs/anti-patterns.md) in hardware:
#   presence verified, function assumed.
# Author: Atlas (Architect)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Atlas        | Initial -- ARCH-019 PLD transition witness.
# 2026-09-03    | Rex (US-667) | Pinned the WARNING on an unwritable path. The
#                                pre-existing unwritable-path test asserts only
#                                the return value, so deleting the logger call
#                                outright left it green -- measured (M3).
# 2026-09-13    | Rex (US-682) | The witness write is ATOMIC and BOUNDED. On
#                                2026-09-04 a real transition left a 0-byte
#                                witness: the old write truncated the target
#                                and lost the race with the power loss. Pins:
#                                a failed commit leaves the previous record,
#                                kill -9 mid-write never leaves empty/partial,
#                                a hung fsync cannot hold the power-loss path,
#                                and an EMPTY file warns as a LOST WRITE.
# ================================================================================
################################################################################

"""ARCH-019 tests for the PLD transition witness."""

from __future__ import annotations

import json
import logging
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.pi.power.power_watch import __main__ as powerWatchMain
from src.pi.power.power_watch import pld_witness
from src.pi.power.power_watch.pld_witness import (
    readWitness,
    recordTransitionWitnessed,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PREVIOUS = "2026-06-01T00:00:00Z"
NEWER = "2026-09-04T15:46:37Z"


def test_a_fresh_install_has_NOT_witnessed_a_transition(tmp_path):
    """The honest default. Never observed is not the same as not armed."""
    assert readWitness(tmp_path / "nothing-here.json") is None


def test_recording_a_transition_persists_it(tmp_path):
    """The witness must survive a reboot -- that is the whole point.

    A transition observed once and forgotten at poweroff would leave the check
    permanently unproven, which is no better than never recording it.
    """
    p = tmp_path / "witness.json"
    recordTransitionWitnessed(p, atIso="2026-08-31T20:15:00Z")
    got = readWitness(p)
    assert got == "2026-08-31T20:15:00Z"
    assert json.loads(p.read_text(encoding="utf-8"))["lastTransitionUtc"] == (
        "2026-08-31T20:15:00Z"
    )


def test_a_later_transition_replaces_the_earlier_one(tmp_path):
    """Most recent wins -- the operator wants to know it still works, not that
    it worked once in June."""
    p = tmp_path / "witness.json"
    recordTransitionWitnessed(p, atIso="2026-06-01T00:00:00Z")
    recordTransitionWitnessed(p, atIso="2026-08-31T20:15:00Z")
    assert readWitness(p) == "2026-08-31T20:15:00Z"


def test_a_corrupt_witness_file_reads_as_NEVER_not_as_a_crash(tmp_path):
    """⚠️ Fail to the HONEST side, and never take powerwatch down with it.

    An unreadable witness means we do not know whether the pin has ever moved.
    That is 'never proven', not 'proven', and certainly not a crashed service --
    the arm check must still run and still say something true.
    """
    p = tmp_path / "witness.json"
    p.write_text("{ this is not json", encoding="utf-8")
    assert readWitness(p) is None


def test_an_unwritable_path_does_not_raise(tmp_path):
    """Recording is best-effort. Losing the witness must never cost a shutdown.

    This runs during a power-loss event, on a machine that is about to lose
    power. An exception here would abort the very pipeline it is observing.
    """
    target = tmp_path / "no-such-dir" / "deep" / "witness.json"
    assert recordTransitionWitnessed(target, atIso="2026-08-31T20:15:00Z") is False


def test_an_unwritable_path_SAYS_SO_at_WARNING(tmp_path, caplog):
    """⚠️ US-667. Best-effort must not mean SILENT.

    A witness that cannot record is worse than no witness at all: the arm line
    then reports UNPROVEN forever and nobody can tell 'the pin never moved'
    from 'the pin moved and we failed to write it down'. That ambiguity is the
    same defect US-663 fixed for obdLink, and it is exactly what happened on
    2026-08-31 -- a real transition fired, the write failed against a
    /var/lib/eclipse-obd that the deploy never created, and the next boot's
    arm line gave no hint why it still said UNPROVEN.

    The swallow at :func:`recordTransitionWitnessed` is CORRECT and must stay
    -- raising here would abort the shutdown pipeline this code exists to
    observe. What must not be swallowed is the FACT that it failed.

    Pinned separately from the does-not-raise test above deliberately: that
    one asserts only the return value, so deleting the ``logger.warning`` call
    outright leaves it green. Measured.
    """
    target = tmp_path / "no-such-dir" / "witness.json"
    with caplog.at_level(logging.WARNING, logger=pld_witness.__name__):
        assert recordTransitionWitnessed(target, atIso="2026-08-31T20:15:00Z") is False

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "recording failed and logged NOTHING at WARNING or above. A witness "
        "that cannot write must say so -- silence here is indistinguishable "
        "from a transition that never happened."
    )
    assert any(str(target) in r.getMessage() for r in warnings), (
        "the warning does not name the path that could not be written, so an "
        "operator reading the journal cannot tell WHICH file is missing or "
        f"why. Records: {[r.getMessage() for r in warnings]}"
    )


def test_recording_NEVER_creates_directories(tmp_path):
    """⚠️ A missing parent means we are not on a deployed system.

    The first version of this called mkdir(parents=True) and duly created
    C:\\var\\lib\\eclipse-obd on a Windows dev box during a test run. A module
    that invents filesystem layout under /var to record a diagnostic is doing
    more than it was asked to.
    """
    absent = tmp_path / "not-created"
    recordTransitionWitnessed(absent / "witness.json", atIso="2026-08-31T20:15:00Z")
    assert not absent.exists(), "recording created a directory tree it was not given"


# ================================================================================
# US-682 -- the write is ATOMIC and BOUNDED; an empty witness is a LOST WRITE
# ================================================================================


def test_a_commit_that_fails_leaves_the_PREVIOUS_record_whole(tmp_path, monkeypatch):
    """🔴 US-682. The target must never be the thing that gets truncated.

    On 2026-09-04 a real transition produced a 0-byte witness: the old write
    opened the target with truncation and lost the race with the power loss.
    Fail the commit step and the previous record must still read back intact.
    """
    p = tmp_path / "witness.json"
    assert recordTransitionWitnessed(p, atIso=PREVIOUS) is True

    def _commitFails(src, dst):
        raise OSError(5, "Input/output error (simulated at commit)")

    monkeypatch.setattr("os.replace", _commitFails)
    assert recordTransitionWitnessed(p, atIso=NEWER) is False

    assert readWitness(p) == PREVIOUS, (
        "a write that did not commit changed the witness on disk -- the target "
        "was written in place, so a power loss mid-write leaves it empty"
    )
    assert sorted(x.name for x in tmp_path.iterdir()) == ["witness.json"], (
        "a failed write left its temp file behind"
    )


def test_a_successful_write_leaves_no_temp_file(tmp_path):
    p = tmp_path / "witness.json"
    assert recordTransitionWitnessed(p, atIso=NEWER) is True
    assert sorted(x.name for x in tmp_path.iterdir()) == ["witness.json"]


_KILL_CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
from src.pi.power.power_watch.pld_witness import recordTransitionWitnessed
target = sys.argv[2]
stamps = (sys.argv[3], sys.argv[4])
print("go", flush=True)
i = 0
while True:
    recordTransitionWitnessed(target, atIso=stamps[i % 2])
    i += 1
"""


def test_kill_9_mid_write_never_leaves_an_empty_or_partial_witness(tmp_path):
    """🔴 US-682 VC1: kill the writer mid-write, repeatedly.

    The witness is written DURING a power loss -- the process is racing the
    thing that kills it. Whatever instant it dies, the file on disk is the
    previous complete record or the new one. Never 0 bytes, never partial.
    """
    p = tmp_path / "witness.json"
    assert recordTransitionWitnessed(p, atIso=PREVIOUS) is True
    rng = random.Random(682)  # deterministic kill offsets

    for attempt in range(12):
        child = subprocess.Popen(
            [sys.executable, "-c", _KILL_CHILD, str(REPO_ROOT), str(p), PREVIOUS, NEWER],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert child.stdout is not None
            assert child.stdout.readline().strip() == "go", "writer child failed to start"
            time.sleep(rng.uniform(0.0, 0.05))
        finally:
            child.kill()  # SIGKILL on POSIX, TerminateProcess on Windows
            child.wait(timeout=10)
            if child.stdout is not None:
                child.stdout.close()

        raw = p.read_bytes()
        assert raw, f"attempt {attempt}: kill -9 left a 0-byte witness"
        assert json.loads(raw.decode("utf-8"))["lastTransitionUtc"] in (PREVIOUS, NEWER), (
            f"attempt {attempt}: witness is partial or foreign: {raw!r}"
        )


def test_a_hung_fsync_cannot_hold_the_power_loss_path(tmp_path, monkeypatch, caplog):
    """🔴 US-682. The write is the FIRST statement of handleOnBattery, before the
    T=0 grace emit and the smoothing window, against a 45 s totalCap. A storage
    stall must cost at most the bound -- and must SAY it was cut short.
    """
    release = threading.Event()

    def _stalledFsync(fd):
        release.wait(timeout=10)

    monkeypatch.setattr("os.fsync", _stalledFsync)
    p = tmp_path / "witness.json"
    try:
        with caplog.at_level(logging.WARNING, logger=pld_witness.__name__):
            started = time.monotonic()
            result = recordTransitionWitnessed(p, atIso=NEWER, timeoutSec=0.2)
            elapsed = time.monotonic() - started
    finally:
        release.set()

    assert result is False, "a write that did not finish in the bound reported success"
    assert elapsed < 2.0, f"the power-loss path waited {elapsed:.2f}s on a 0.2s bound"
    assert any(str(p) in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING), (
        "a write cut short by the bound was silent"
    )


def test_the_default_bound_is_one_smoothing_poll():
    """Grounding: config.json pi.powerWatch.smoothingPollSec = 1. The witness may
    cost the power-loss path at most one poll interval of the loop it precedes."""
    assert pld_witness.WITNESS_WRITE_TIMEOUT_SEC == 1.0


def test_an_EMPTY_witness_reads_NEVER_and_warns_LOST_WRITE(tmp_path, caplog):
    """🔴 US-682 VC3. The exact file found on the Pi on 2026-09-04.

    NEVER stays the safe default. But a file that EXISTS with no content is a
    write that did not land -- a different fact from a transition that never
    happened, and the journal must say which one it is.
    """
    p = tmp_path / "witness.json"
    p.write_bytes(b"")
    with caplog.at_level(logging.WARNING, logger=pld_witness.__name__):
        assert readWitness(p) is None

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("LOST WRITE" in m and str(p) in m for m in messages), (
        f"an empty witness was not named as a lost write. Records: {messages}"
    )


def test_a_MISSING_witness_is_silent_and_a_corrupt_one_is_not_called_a_lost_write(
    tmp_path, caplog
):
    """Three facts, three strings: absent (never recorded), empty (lost write),
    corrupt (unreadable). Only the empty case claims a lost write."""
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{ this is not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=pld_witness.__name__):
        assert readWitness(tmp_path / "absent.json") is None
        absentMessages = [r.getMessage() for r in caplog.records]
        assert readWitness(corrupt) is None

    assert absentMessages == [], f"a never-written witness warned: {absentMessages}"
    corruptMessages = [r.getMessage() for r in caplog.records]
    assert corruptMessages and not any("LOST WRITE" in m for m in corruptMessages)


def test_a_written_witness_renders_the_arm_line_PROVEN(tmp_path):
    """🔴 US-682 VC2: write, read back through readWitness, render the arm line."""
    p = tmp_path / "witness.json"
    assert recordTransitionWitnessed(p, atIso=NEWER) is True

    line = powerWatchMain.buildArmDecisionMessage(
        armed=True,
        pldGpioPin=6,
        pldAvailable=True,
        readsPowerPresent=True,
        lastTransitionUtc=readWitness(p),
    )
    assert "(PROVEN)" in line and "UNPROVEN" not in line
    assert f"last transition {NEWER}" in line
