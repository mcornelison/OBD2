################################################################################
# File Name: test_shutdown_splash_terminal_reason.py
# Purpose/Description: US-549 (I-043, F-103) -- the closeout shutdown splash used
#   to reach ALL FOUR of its terminal states through one silent exit:
#
#       function exitKiosk() { try { window.close(); } catch (e) {} }
#
#   phase=cancelled (a CORRECT abort -- power returned), the state file going
#   missing (may be a legitimate end-of-sequence, may be a cold-start RACE), the
#   60s cap (poweroff never fired) and an unrecognized phase all
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
#
#   US-870-a (S114, Atlas A-sd; CIO "Remove it"): the page's own clocks are gone
#   -- the 1s pre-roll, the 60s cap and the three-miss count. Three exits remain
#   (cancelled, a FIRST 404, an unrecognized phase); a refused connection HOLDS
#   the last paint; the page paints on the first flushing/powering_off read and
#   never on grace. elapsedMs stays in the record as REPORT-ONLY (C-Atlas-7),
#   fenced statically below.
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
# 2026-10-25    | Ralph (Rex)  | US-870-a: black-tail-cap scenario and the
#               |              | pre-roll/three-miss pins retired; paint-on-
#               |              | flushing, 404-vs-refused, no-timer cases added.
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
    PHASE_FLUSHING,
    PHASE_GRACE,
    PHASE_POWERING_OFF,
)
from tests.deploy.test_dashboard_kit import _execStartFlags
from tests.ui.render_harness import REFUSED, ProbeError, runShutdownSplash

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


PROBE_POLL_MS = 250  # shutdown_probe.js advances one poll of virtual time per round

# The 120 s at-home drain of spec AC 10: longer than the retired 60 s cap, so a
# page that still timed itself out would close inside it.
AT_HOME_DRAIN_MS = 120_000


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


def _run(states: list[dict | None], rounds: int = 80, emitIntervalMs: int = 500) -> dict:
    try:
        return runShutdownSplash(states, rounds=rounds, emitIntervalMs=emitIntervalMs)
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
SCENARIOS = {
    "cancelled": ([_state(PHASE_CANCELLED)], 80),
    "state-missing": ([None], 80),
    "unrecognized-phase": ([_state("reticulating_splines")], 80),
}


@pytest.fixture(scope="module")
def outcomes() -> dict[str, dict]:
    """Every terminal scenario, run once (node startup dominates the cost)."""
    return {name: _run(states, rounds=rounds) for name, (states, rounds) in SCENARIOS.items()}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_everyTerminalExit_reportsExactlyOneReason(outcomes, scenario):
    """
    Given: each of the three ways the closeout splash can end
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
    Given: the exits that used to funnel through one silent window.close()
    Then: each reports its OWN cause -- one distinct string per scenario

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


def test_oneNotFound_exitsStateMissingAtOnce_us870a(outcomes):
    """
    Given: the states server answers 404 for shutdown-state on the first poll
    Then: the page exits state-missing on THAT poll -- no retry count

    The file is written atomically and never deleted (Atlas A-sd 2), so a 404
    means it was never written; the retired three-miss count only delayed the
    same verdict by two polls.
    """
    result = outcomes["state-missing"]
    assert result["closed"]
    assert result["terminalRecord"]["polls"] == 1, result["terminalRecord"]
    # The probe settles a poll's answer in the NEXT round, so the first poll's
    # verdict lands at one POLL_MS.
    assert result["closedAtMs"] == PROBE_POLL_MS, (
        f"closed at {result['closedAtMs']} ms, not on the first poll's answer"
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


# ---------------------------------------------------------------------------
# US-870-a: the paint trigger, the hold, and no timer
# ---------------------------------------------------------------------------


def test_graceThenCancelled_paintsNothing_us870a():
    """
    Given: a blip -- the sequencer writes grace, then cancelled
    Then: zero paints, and the exit is cancelled

    The sequencer's smoothing window is the one debounce (CIO: keep it): during
    grace the dashboard is still up, so a blip must never flash a frame.
    """
    states = [_state(PHASE_GRACE)] * 6 + [_state(PHASE_CANCELLED)]
    result = _run(states, emitIntervalMs=PROBE_POLL_MS)

    assert result["terminalCause"] == "cancelled"
    assert result["paintedOnPoll"] is None
    assert result["terminalRecord"]["painted"] is False
    assert result["stageVisibility"] != "visible"


@pytest.mark.parametrize("paintPhase", [PHASE_FLUSHING, PHASE_POWERING_OFF])
def test_graceThenFlushing_paintsOnThatRead_us870a(paintPhase):
    """
    Given: a real key-off -- grace for eight polls (2 s, past the retired 1 s
           pre-roll), then flushing (or powering_off)
    Then: nothing paints during grace; the stage is revealed on poll 9, the first
          read of the painting phase, and the page stays up
    """
    states = [_state(PHASE_GRACE)] * 8 + [_state(paintPhase)]
    result = _run(states, rounds=20, emitIntervalMs=PROBE_POLL_MS)

    assert result["paintedOnPoll"] == 9, result["paintedOnPoll"]
    assert result["painted"] is True
    assert result["stageVisibility"] == "visible"
    assert result["closed"] is False


def test_tenRefusedPolls_holdTheLastPaint_us870a():
    """
    Given: flushing painted, then the states server refuses ten polls in a row
    Then: no exit, no terminal report, the paint holds

    A refused connection is power-off in progress (spec §2.1): the page dies with
    the power. The retired three-miss count read it as a missing file and closed
    the splash just before the screen went dark.
    """
    states = [_state(PHASE_FLUSHING)] + [REFUSED] * 10
    result = _run(states, rounds=11, emitIntervalMs=PROBE_POLL_MS)

    assert result["polls"] == 11
    assert result["closed"] is False
    assert result["terminalCause"] is None
    assert _terminalLines(result) == []
    assert result["painted"] is True
    assert result["stageVisibility"] == "visible"


def test_aNon404Failure_holdsLikeARefusal_us870a():
    """
    Given: a painted page, then the server answers 503 (no body) for ten polls
    Then: it holds -- only a 404 is evidence the file was never written
    """
    states = [_state(PHASE_FLUSHING)] + [{"__status": 503}] * 10
    result = _run(states, rounds=11, emitIntervalMs=PROBE_POLL_MS)

    assert result["polls"] == 11
    assert result["closed"] is False
    assert result["painted"] is True


def test_refusedThenNotFound_stillExitsStateMissing_us870a():
    """The hold is not a latch: a 404 after refusals still exits at once."""
    states = [REFUSED] * 3 + [None]
    result = _run(states, rounds=10, emitIntervalMs=PROBE_POLL_MS)

    assert result["terminalCause"] == "state-missing"
    assert result["terminalRecord"]["polls"] == 4


def test_aLongAtHomeDrain_keepsThePageUpThroughout_us870a():
    """
    Given: a 120 s at-home drain -- flushing on disk for all of it
    Then: the page is up and painted at the end; no timer closed it

    The retired 60 s cap would have closed the splash half way through a drain
    that ARCH-065 lets run to completion.
    """
    rounds = AT_HOME_DRAIN_MS // PROBE_POLL_MS
    result = _run([_state(PHASE_GRACE), _state(PHASE_FLUSHING)], rounds=rounds)

    assert result["elapsedMs"] >= AT_HOME_DRAIN_MS
    assert result["polls"] == rounds
    assert result["closed"] is False
    assert result["terminalCause"] is None
    assert result["painted"] is True


def test_report_saysWhetherTheOperatorEverSawAFrame():
    """
    Given: two cancellations -- one during grace, one after flushing painted
    Then: the reports differ on `painted`

    The 2.17s journal entry in I-043 is ambiguous precisely because nothing
    recorded whether a frame was ever painted. "Cancelled during grace"
    (correct: nothing should be shown) and "cancelled having shown the mark" are
    different events that the unit's lifetime alone cannot separate. Both are
    driven here, and the fields are asserted to actually disagree -- a
    hardcoded `painted: false` would pass the first half of this test on its own.
    """
    early = _run([_state(PHASE_GRACE)] * 4 + [_state(PHASE_CANCELLED)])
    late = _run([_state(PHASE_GRACE), _state(PHASE_FLUSHING), _state(PHASE_CANCELLED)])

    assert early["terminalRecord"]["painted"] is False
    assert late["terminalRecord"]["painted"] is True, (
        "a cancel after flushing painted must report that the mark was on screen"
    )
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


#: A read of the elapsed-time seam: the report field or the function call.
_ELAPSED_READ = re.compile(r"\belapsed(?:Ms\b|\s*\()")


def _code(js: str | None = None) -> str:
    """``js`` (default: the shipped poll script) with every comment stripped."""
    body = re.sub(r"/\*.*?\*/", "", _pollJsText() if js is None else js, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", body)


def _balanced(text: str, openAt: int, opener: str, closer: str) -> str:
    """The text between ``text[openAt]`` (an opener) and its matching closer."""
    depth = 0
    for i in range(openAt, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[openAt + 1 : i]
    raise AssertionError(f"unbalanced {opener}{closer} from offset {openAt}")


def _conditions(code: str) -> list[str]:
    """Every if/while/for condition, and every ternary test, in ``code``."""
    found = [
        _balanced(code, m.end() - 1, "(", ")")
        for m in re.finditer(r"\b(?:if|while|for)\s*\(", code)
    ]
    # A ternary's test: the expression before a `?` back to the statement start.
    found += re.findall(r"([^;{}?:]+)\?(?![?.])", code)
    return found


def test_elapsedIsReportOnly_noConditionReadsIt_us870a():
    """
    Given: the shipped shutdown-state-poll.js
    Then: no condition reads elapsedMs or elapsed(), and elapsed() is called
          only inside reportTerminal (Atlas C-Atlas-7)

    elapsedMs stays in the US-549 record because the journal needs to know how
    long the page lived; the moment a branch consults it, it is a timer again.
    """
    code = _code()
    readers = [c.strip() for c in _conditions(code) if _ELAPSED_READ.search(c)]
    assert readers == [], f"a condition reads elapsed time: {readers!r}"

    report = re.search(r"function\s+reportTerminal\s*\([^)]*\)\s*\{", code)
    assert report, "reportTerminal is gone"
    reportBody = _balanced(code, report.end() - 1, "{", "}")
    outside = code.replace(reportBody, "")
    calls = re.findall(r"(?<!function )\belapsed\s*\(", outside)
    assert calls == [], f"elapsed() called outside reportTerminal: {len(calls)} call(s)"
    assert re.search(r"\belapsed\s*\(", reportBody), "the report no longer carries elapsedMs"


@pytest.mark.parametrize(
    "js",
    [
        "if (elapsed() >= CAP) { abort(X); }",
        "while (record.elapsedMs < 5) {}",
        "var go = elapsed() > 1 ? 1 : 0;",
    ],
)
def test_elapsedFence_selfTest_seesATimer_us870a(js):
    """The fence sees a timer written as an if, a while or a ternary."""
    assert any(_ELAPSED_READ.search(c) for c in _conditions(_code(js))), js


def test_elapsedFence_selfTest_ignoresTheReport_us870a():
    """...and does not mistake the report's own field for a condition."""
    js = "var r = { elapsedMs: Math.round(elapsed()) }; var t = ok ? 1 : 0;"
    assert not any(_ELAPSED_READ.search(c) for c in _conditions(_code(js)))


def test_noClockNamesRemain_us870a():
    """The retired clocks are gone from the code, not merely unused."""
    code = _code()
    for name in ("PRE_ROLL", "BLACK_TAIL", "MAX_MISSING", "missingCount", "black-tail-cap"):
        assert name not in code, f"{POLL_JS.name} still carries {name}"


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
