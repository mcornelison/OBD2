################################################################################
# File Name: test_shutdown_splash_terminal_reason.py
# Purpose/Description: US-549 (I-043, F-103) -- the closeout shutdown splash used
#   to reach ALL FOUR of its terminal states through one silent exit:
#
#       function exitKiosk() { try { window.close(); } catch (e) {} }
#
#   phase=cancelled (a CORRECT abort -- power returned), the state file going
#   missing (may be a legitimate end-of-sequence, may be a cold-start RACE), the
#   60s BLACK_TAIL cap (poweroff never fired) and an unrecognized phase all
#   produced the same two journal lines: `Started` ... `Deactivated
#   successfully`. The one time splash-grace.service has ever fired in the
#   retained journal it lived 2.17s, and whether that was case 1 or case 2 is
#   NOT DETERMINABLE from the evidence -- which matters because the reverse
#   splash can only be validated on a real AC-loss event, and those are rare
#   enough that burning one to learn "it exited after 2s" wastes the drill.
#
#   WHAT THESE TESTS ARE ACTUALLY FOR, and it is not "a log line exists": it is
#   that the four causes are DISTINGUISHABLE from each other. A single reason
#   string that fired on every path would satisfy a naive "did it log?" test and
#   leave I-043 exactly as open as it was. So the headline assertion here is a
#   set-distinctness one over all four scenarios driven end to end.
#
#   These run the SHIPPED shutdown-state-poll.js under the mini-DOM (no jsdom in
#   this repo), fed the payload shape the REAL ShutdownSequencer emits -- phase
#   constants and the reason default are imported from the controller, never
#   retyped -- and read back the console line byte-for-byte, because those bytes
#   are what the operator greps out of the journal.
#
#   MECHANISM, NOT JUST DECLARATION: chromium DISCARDS web-content console output
#   unless the unit passes `--enable-logging=stderr`. A perfect console.log in a
#   unit without that flag is an elaborate no-op, so the unit half is fenced here
#   too -- with a parser self-test, because the flag now also appears in those
#   units' COMMENTS and a substring check would be satisfied by the prose
#   documenting the fix rather than by the fix.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Ralph (Rex)  | Initial -- US-549 (I-043) observable terminal
#               |              | reason for the closeout shutdown splash.
# ================================================================================
################################################################################

"""US-549 (I-043) terminal-reason observability for the F-103 closeout splash."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pi.power.power_watch.controller import (
    DEFAULT_SHUTDOWN_REASON,
    PHASE_CANCELLED,
    PHASE_GRACE,
)
from tests.deploy.test_dashboard_kit import _execStartFlags
from tests.ui.render_harness import ProbeError, runShutdownSplash

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_DIR = REPO_ROOT / "src" / "pi" / "ui" / "splash"
POLL_JS = KIT_DIR / "shutdown-state-poll.js"

GRACE_UNITS = ("splash-grace.service.x11", "splash-grace.service.wayland")

# The grep string the issue's acceptance is written in terms of: "journalctl -u
# splash-grace.service ALONE should say which of the four terminal cases fired".
# Pinned as a literal ON PURPOSE -- it is an operator-facing interface, and the
# unit comments tell the operator to grep for exactly this.
LOG_PREFIX = "[shutdown-splash] terminal "

# The `--enable-logging=stderr` half. Without it the console sink does not exist
# on the Pi and every assertion below would still pass (see the module docstring).
LOGGING_FLAG = "--enable-logging=stderr"

# A flag the repo has explicitly REFUSED (US-522): an unauthenticated DevTools
# surface on a car-mounted kiosk. Adopting a logging flag must not smuggle it in.
FORBIDDEN_FLAG_PREFIX = "--remote-debugging-"


def _pollJsText() -> str:
    return POLL_JS.read_text(encoding="utf-8")


def _jsConst(name: str) -> float:
    """Read a numeric ``var NAME = <n>;`` out of the SHIPPED poll script.

    Grounded, not retyped: MAX_MISSING_RETRIES and BLACK_TAIL_CAP_MS are the
    script's own thresholds, and a test that hardcodes them silently stops
    testing the shipped behaviour the moment either is retuned.
    """
    match = re.search(rf"var\s+{re.escape(name)}\s*=\s*(\d+)", _pollJsText())
    assert match, f"{POLL_JS.name} declares no {name}"
    return float(match.group(1))


MAX_MISSING_RETRIES = int(_jsConst("MAX_MISSING_RETRIES"))
BLACK_TAIL_CAP_MS = _jsConst("BLACK_TAIL_CAP_MS")
PRE_ROLL_MS = _jsConst("PRE_ROLL_MS")
PROBE_POLL_MS = 250  # shutdown_probe.js advances one poll of virtual time per round


def _state(phase: str, reason: str = DEFAULT_SHUTDOWN_REASON) -> dict:
    """A shutdown-state payload in the shape makeShutdownPhaseEmitter writes."""
    return {
        "phase": phase,
        "tGraceStartedAt": "2026-08-10T00:00:00Z",
        "tGraceTotalS": 7.0,
        "tRemainingS": 0.0,
        "reason": reason,
        "ts": "2026-08-10T00:00:00Z",
    }


def _run(states: list[dict | None], rounds: int = 80) -> dict:
    try:
        return runShutdownSplash(states, rounds=rounds)
    except FileNotFoundError as exc:  # node absent on this machine
        pytest.skip(f"node is required for the shutdown render probe: {exc}")
    except ProbeError as exc:
        pytest.fail(f"the shipped shutdown poll script failed under the probe: {exc}")


def _terminalLines(result: dict) -> list[str]:
    return [line for line in result["consoleLines"] if line.startswith(LOG_PREFIX)]


# ---------------------------------------------------------------------------
# The four scenarios, each driven end to end through the SHIPPED script.
# ---------------------------------------------------------------------------

# `None` = the state file is ABSENT (the server 404s), which is a materially
# different event from a `cancelled` phase. Conflating the two is I-043.
_NEVER_TERMINATES = [_state(PHASE_GRACE)]
_CAP_ROUNDS = int(BLACK_TAIL_CAP_MS / PROBE_POLL_MS) + 10

SCENARIOS = {
    "cancelled": ([_state(PHASE_CANCELLED)], 80),
    "state-missing": ([None], 80),
    "unrecognized-phase": ([_state("reticulating_splines")], 80),
    "black-tail-cap": (_NEVER_TERMINATES, _CAP_ROUNDS),
}


@pytest.fixture(scope="module")
def outcomes() -> dict[str, dict]:
    """Every terminal scenario, run once (node startup dominates the cost)."""
    return {name: _run(states, rounds=rounds) for name, (states, rounds) in SCENARIOS.items()}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_everyTerminalExit_reportsExactlyOneReason(outcomes, scenario):
    """
    Given: each of the four ways the closeout splash can end
    When: the shipped script runs to its terminal state
    Then: it exits AND leaves exactly one terminal report behind

    Exactly one, not at-least-one: a report emitted on every poll would drown the
    journal, and a second report after `aborted` is set would mean the exit
    latch leaked. The exit itself is asserted alongside, so a script that logged
    beautifully and then hung could not pass.
    """
    result = outcomes[scenario]
    assert result["closed"], f"{scenario}: the splash never exited"
    assert len(_terminalLines(result)) == 1, (
        f"{scenario}: expected one terminal report, got {result['consoleLines']!r}"
    )
    assert result["terminalRecord"] is not None, f"{scenario}: no terminal record on <body>"


def test_theFourTerminalCauses_areDistinguishableFromEachOther(outcomes):
    """
    Given: the four outcomes that used to funnel through one silent window.close()
    Then: each reports its OWN cause -- four scenarios, four distinct strings

    THE headline assertion of this story. A single generic "splash exited" reason
    would satisfy every other test in this file and leave I-043 fully open: the
    defect was never "nothing is logged", it was "a correct abort and a race are
    indistinguishable". Distinctness is the property, so distinctness is asserted.
    """
    causes = {name: result["terminalCause"] for name, result in outcomes.items()}
    assert None not in causes.values(), f"a terminal exit reported no cause at all: {causes}"
    assert len(set(causes.values())) == len(SCENARIOS), (
        f"terminal causes collide -- the exits stay indistinguishable: {causes}"
    )
    # And each names its own scenario, so the mapping cannot silently transpose.
    assert causes == {name: name for name in SCENARIOS}, causes


def test_cancelledExit_carriesTheSequencersOwnPhaseAndReason(outcomes):
    """
    Given: the ShutdownSequencer is the SSOT of WHY the Pi is going down
    Then: the splash's report quotes that phase+reason rather than inventing one

    The splash stays a pure CONSUMER (spec §6): `cause` is the splash's own
    business (why the RENDER stopped), while `phase`/`reason` are lifted verbatim
    off the last state file it read. Two facts, both reported, neither
    substituted for the other.
    """
    record = outcomes["cancelled"]["terminalRecord"]
    assert record["cause"] == "cancelled"
    assert record["phase"] == PHASE_CANCELLED
    assert record["reason"] == DEFAULT_SHUTDOWN_REASON


def test_missingState_reportsNullPhase_ratherThanAPlausibleDefault(outcomes):
    """
    Given: the state file was never readable, so the sequencer said NOTHING
    Then: phase and reason are null -- not "unknown", not the grace default

    The honest-instrument half, and the one that actually resolves the open
    question in I-043. A defaulted `phase: "cancelled"` here would recreate the
    exact ambiguity this story exists to remove: the null IS the evidence that
    the splash raced the sequencer instead of watching it cancel.
    """
    record = outcomes["state-missing"]["terminalRecord"]
    assert record["cause"] == "state-missing"
    assert record["phase"] is None, f"a phase was invented for a file we never read: {record}"
    assert record["reason"] is None, f"a reason was invented for a file we never read: {record}"
    assert record["polls"] == MAX_MISSING_RETRIES, (
        "the report must show how many polls were spent before giving up "
        f"(shipped MAX_MISSING_RETRIES={MAX_MISSING_RETRIES}, reported {record['polls']})"
    )


def test_unrecognizedPhase_carriesTheOffendingValue(outcomes):
    """
    Given: the sequencer wrote a phase this kit does not know about
    Then: the report names the value, not merely the fact of rejection

    "Unrecognized phase" without the phase sends the next investigator back to
    the same place I-043 started: knowing something went wrong and not what.
    """
    record = outcomes["unrecognized-phase"]["terminalRecord"]
    assert record["cause"] == "unrecognized-phase"
    assert record["phase"] == "reticulating_splines"


def test_blackTailCap_isReportedAsATimeout_notAsACancellation(outcomes):
    """
    Given: `grace` on disk forever -- poweroff never fired
    Then: the cap fires, is named as the cap, and the last live phase is kept

    This is the failure that most needs its own name: the state file said the
    shutdown was still in progress right up to the moment the splash gave up, so
    reading it as a cancellation would point the investigation at the power
    supply instead of at the sequencer that never reached poweroff.
    """
    result = outcomes["black-tail-cap"]
    record = result["terminalRecord"]
    assert record["cause"] == "black-tail-cap"
    assert record["phase"] == PHASE_GRACE
    assert record["elapsedMs"] >= BLACK_TAIL_CAP_MS, (
        f"the cap fired early at {record['elapsedMs']}ms of a {BLACK_TAIL_CAP_MS}ms cap"
    )


# ---------------------------------------------------------------------------
# The paint discriminator -- the specific question I-043 could not answer
# ---------------------------------------------------------------------------


def test_report_saysWhetherTheOperatorEverSawAFrame():
    """
    Given: two cancellations -- one before the PRE_ROLL reveal, one after
    Then: the reports differ on `painted`, and on elapsed time

    The 2.17s journal entry in I-043 is ambiguous precisely because nothing
    recorded whether a frame was ever painted. PRE_ROLL is a deliberate 1s
    no-paint window, so "cancelled at 0.5s" (correct: nothing should be shown)
    and "cancelled at 5s having shown the mark" are different events that the
    unit's lifetime alone cannot separate. Both are driven here, and the fields
    are asserted to actually disagree -- a hardcoded `painted: false` would pass
    the first half of this test on its own.
    """
    early = _run([_state(PHASE_CANCELLED)])
    late = _run([_state(PHASE_GRACE)] * 4 + [_state(PHASE_CANCELLED)])

    assert early["terminalRecord"]["painted"] is False
    assert early["terminalRecord"]["elapsedMs"] < PRE_ROLL_MS

    assert late["terminalRecord"]["painted"] is True, (
        "a grace that ran past PRE_ROLL must report that the mark was on screen"
    )
    assert late["terminalRecord"]["elapsedMs"] >= PRE_ROLL_MS
    # Same cause, different story -- which is the whole point.
    assert early["terminalCause"] == late["terminalCause"] == "cancelled"


def test_theConsoleLine_isTheJournalLine_andIsMachineReadable():
    """
    Given: the operator's only tool is `journalctl -u splash-grace.service`
    Then: the line carries the documented grep prefix and a parseable payload

    The probe captures the same bytes the console emits, so this asserts the
    operator-facing interface rather than an internal object. JSON after the
    prefix keeps it greppable by eye AND parseable by a future triage script.
    """
    result = _run([_state(PHASE_CANCELLED)])
    line = _terminalLines(result)[0]

    payload = json.loads(line[len(LOG_PREFIX) :])
    assert payload == result["terminalRecord"], (
        "the journal line and the DOM record disagree -- one of the two sinks is lying"
    )
    assert set(payload) == {"cause", "phase", "reason", "painted", "elapsedMs", "polls"}


# ---------------------------------------------------------------------------
# Static fences -- the exit path and the mechanism that carries it
# ---------------------------------------------------------------------------


def test_noExitPathCanBeAddedSilently():
    """
    Given: a future edit adds a fifth way out of the closeout splash
    Then: it cannot reach `abort()` without naming a cause

    The runtime tests above can only cover the exits that exist TODAY, which is
    how I-043 survived four of them. This is the structural half: every abort
    call site must pass an argument, so re-introducing an anonymous exit fails
    here rather than on a Pi during the one AC-loss drill of the year.
    """
    body = re.sub(r"/\*.*?\*/", "", _pollJsText(), flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)

    bare = re.findall(r"\babort\(\s*\)", body)
    assert bare == [], f"{POLL_JS.name} still has {len(bare)} anonymous abort() call(s)"

    callSites = re.findall(r"\babort\(([^)]*)\)", body)
    callSites = [arg.strip() for arg in callSites if arg.strip() != "cause"]
    assert callSites, "no abort() call sites found at all -- has the exit been renamed?"
    for arg in callSites:
        assert arg.startswith("CAUSE_"), (
            f"abort({arg}) does not pass one of the named CAUSE_* constants"
        )


def test_execStartFlagParser_selfTest_us549():
    """The unit guard's own parser, fed the input that would fool a substring check.

    Both grace units now DISCUSS `--enable-logging=stderr` in their header
    comments (that is where the reasoning lives). A guard satisfied by the prose
    documenting a fix is the US-501/US-513 trap, and here it would report green
    on a unit that never actually enables logging.
    """
    assert _execStartFlags(
        f"# ExecStart=/bogus {LOGGING_FLAG}\nExecStart=/usr/bin/chromium --kiosk http://h/\n"
    ) == ["/usr/bin/chromium", "--kiosk", "http://h/"]
    # Positive control: it must still FIND the flag when it is genuinely there.
    assert LOGGING_FLAG in _execStartFlags(
        f"ExecStart=/usr/bin/chromium \\\n  {LOGGING_FLAG} \\\n  http://h/\n"
    )


@pytest.mark.parametrize("unitName", GRACE_UNITS)
def test_graceUnits_enableStderrLogging_us549(unitName):
    """
    Given: chromium discards web-content console output by default
    Then: both grace variants pass --enable-logging=stderr on their ExecStart

    Declaration vs mechanism. Every other test in this file passes on a unit
    without this flag, and on the Pi the splash would go on exiting in silence.
    Both variants, because install.sh picks one by session type -- fixing only
    the one this dev box would have chosen is how a Wayland/X11 pair drifts.
    """
    flags = _execStartFlags((KIT_DIR / unitName).read_text(encoding="utf-8"))
    assert LOGGING_FLAG in flags, (
        f"{unitName}: without {LOGGING_FLAG} the terminal reason never reaches "
        "the journal and I-043 is unfixed"
    )
    offenders = [f for f in flags if f.startswith(FORBIDDEN_FLAG_PREFIX)]
    assert offenders == [], (
        f"{unitName}: a logging flag must not smuggle in DevTools ({offenders!r})"
    )
