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
# ================================================================================
################################################################################

"""ARCH-019 tests for the PLD transition witness."""

from __future__ import annotations

import json
import logging

from src.pi.power.power_watch import pld_witness
from src.pi.power.power_watch.pld_witness import (
    readWitness,
    recordTransitionWitnessed,
)


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
