################################################################################
# File Name: kiosk_watchdog.py
# Purpose/Description: US-523 (F-124) kiosk watchdog -- detects a WEDGED
#                      chromium renderer on the Pi dashboard and restarts
#                      eclipse-dashboard.service to hand it a fresh GPU
#                      context (the mitigation Atlas proved live).  Runs as a
#                      systemd oneshot driven by eclipse-kiosk-watchdog.timer;
#                      one tick = one decision, no daemon.
#
#                      DEFENSE IN DEPTH, NOT THE FIX.  US-522 removed the
#                      failure mechanism (`--disable-gpu` overrides the
#                      OS-injected --enable-gpu-rasterization).  This watchdog
#                      exists for the case where that fix did NOT hold: every
#                      restart is logged at WARNING and a recurring wedge
#                      escalates to ERROR + a NON-ZERO exit, so the unit shows
#                      as failed instead of quietly papering over a live freeze
#                      class (US-523 AC: "must surface recurring wedges, not
#                      silence them").
#
#                      WHAT COUNTS AS A WEDGE (and what deliberately does not):
#                      the ONE signature used is the GPU command-buffer
#                      hot-loop -- `AllocateRingBuffer` fatal errors in
#                      eclipse-dashboard's journal.  Atlas measured 6,063,554
#                      in a single boot (~500/sec) while frozen, and exactly 0
#                      after the restart that unfroze it.  The AC's other
#                      candidate signal -- "a CPU-pegged chromium with no
#                      state-file-driven repaint" -- is NOT implemented, on
#                      purpose: repaint is not observable from outside the
#                      browser, and the CPU half alone has no post-US-522
#                      baseline to threshold against.  Guessing that number
#                      would be a fabricated threshold, so the honest bound is:
#                      a wedge with a DIFFERENT signature is not detected here.
#                      See offices/architect/findings/
#                      2026-08-02-pi-ui-freeze-chromium-gpu-command-buffer-hotloop.md
#
#                      HOW WEDGED IS TOLD FROM HEALTHY -- PRESENCE + DWELL, NOT
#                      A COUNT (US-561, and this is the load-bearing part).
#                      US-523 asked `markers >= 100`, calibrated against the
#                      ~30,000-per-window catastrophic wedge.  The regime the
#                      CIO actually drove into runs 84-101 per window, so the
#                      constant sat INSIDE the signal's own operating band and
#                      two consecutive ticks of ONE continuous freeze logged
#                      "WEDGED -- 101 markers" then "healthy; markers=84".  A
#                      threshold inside a band is a coin-flip, not a detector --
#                      the identical lesson Spool reached on the coolant
#                      fan-cycle ceiling, arrived at from the opposite side.
#                      The fix is NOT a re-tuned constant (that only moves the
#                      coin-flip to the next regime).  Healthy was MEASURED as
#                      exactly zero, so:
#                        * ANY marker at all  -> the failure class is live;
#                        * sustained for a DWELL (60s, two timer ticks) without
#                          a single clean tick in between -> wedged.
#                      That needs no magnitude, so it cannot be mis-calibrated
#                      against a rate nobody has measured yet.  `100` survives
#                      only as `DEFAULT_MARKER_READ_CAP`, an I/O bound.
#
#                      HONEST BOUND ON LATENCY (US-561 defect 3c, NOT fixed and
#                      not fixable from here): the markers are a LAGGING
#                      indicator.  They appear when an allocation is finally
#                      attempted, not when painting stops -- Atlas saw the
#                      display freeze at ~16:15 and the burst arrive at
#                      16:18:32.  So this watchdog CANNOT claim "detected within
#                      60s of the freeze"; it detects within ~a dwell of the
#                      markers, and the markers themselves may trail the freeze
#                      by minutes.  Closing that gap needs a signal that leads
#                      rather than lags (a repaint heartbeat published BY the
#                      page), which is a dashboard change, not a watchdog one.
#                      Detection did get EARLIER anyway: presence is observable
#                      long before a count reaches 100 -- Atlas measured 1
#                      marker at 16:16:39 and dismissed it, and that same
#                      sample now starts the dwell clock.
#
#                      NEVER-FLAP RULES (each pinned by its own test):
#                        1. an inactive kiosk is left alone -- `systemctl
#                           restart` would START it, stealing the hand-off that
#                           belongs to splash-boot's OnSuccess (A-1);
#                        2. an unreadable journal is UNCERTAIN, never a wedge --
#                           and never "healthy" either.  US-644-a adds the
#                           distinction that was missing: a journal read that
#                           TIMES OUT is not "uncertain", it is a FAULT in this
#                           watchdog, reported at ERROR and exiting non-zero;
#                        3. the journal window never reaches back past the last
#                           restart, so pre-restart errors cannot re-trigger;
#                        4. a cooldown separates consecutive restarts;
#                        5. an hourly restart budget caps the loop -- once spent
#                           the watchdog stops restarting and starts shouting;
#                        6. the attempt is recorded BEFORE the restart, so an
#                           unwritable ledger disables the restart rather than
#                           silently disabling rules 3-5;
#                        7. (US-561) the dwell requires UNBROKEN presence -- one
#                           measured-zero tick clears the clock, so an isolated
#                           GL complaint can never combine with another minutes
#                           later to fake a sustained wedge.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex          | Initial implementation (Sprint 70 US-523)
# 2026-08-21    | Rex          | US-561: Atlas's four 08-17 watchdog defects.
#               |              | 3a presence+dwell replaces the in-band count
#               |              | threshold; 3b a readability PROBE stops a
#               |              | zero-match grep exit-1 reading as "unreadable";
#               |              | 3c documented above as an honest bound, not
#               |              | fixed; 3d the restart budget is now stated on
#               |              | every tick as "N of M (K left)".
# 2026-08-31    | Rex          | US-644-a: the readability probe was an
#               |              | UNSCOPED `journalctl --lines=1` whose cost grew
#               |              | with the journal, so it succeeded on a young
#               |              | one and TIMED OUT on a grown one -- an
#               |              | INTERMITTENT detector, whose successes made it
#               |              | look trustworthy.  Fix: scope the read to the
#               |              | ONE active journal file (`--file=`), whose size
#               |              | journald caps, so probe runtime no longer
#               |              | depends on journal size.  And stop collapsing
#               |              | "timed out" into "unreadable": a timeout is now
#               |              | its own reason, logged at ERROR and exiting
#               |              | non-zero, instead of an INFO no-op that read
#               |              | like a healthy tick.
# ================================================================================
################################################################################

"""Wedged-kiosk detection + bounded self-recovery for the Pi dashboard (US-523)."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Grounded constants.  Every number below traces to Atlas's live measurements
# in the RCA named in the header, or is a stated policy choice -- none is a
# guess dressed as a measurement.
# ----------------------------------------------------------------------------

#: The kiosk unit this watchdog guards.  Not started, only restarted.
DEFAULT_UNIT = "eclipse-dashboard.service"

#: The journal marker that IS the freeze (chromium's fatal command-buffer
#: allocation, retried sub-millisecond apart with no crash).
WEDGE_MARKER = "AllocateRingBuffer"

#: Journal look-back per tick.  Atlas measured 2,500 markers in a 5s window
#: during the wedge, so any 60s slice of a live wedge yields ~30,000.
DEFAULT_WINDOW_SECONDS = 60

#: Maximum journal lines pulled per tick.  This is an I/O BOUND, NOT A VERDICT.
#: US-523 shipped the same number as `DEFAULT_ERROR_THRESHOLD`, a wedged/healthy
#: decision constant -- and US-561 removed it in that role (see the header).  It
#: survives only as what it always genuinely was: a cap that stops an uncapped
#: read pulling megabytes per tick off a Pi the wedge has already pegged.
DEFAULT_MARKER_READ_CAP = 100

#: How long markers must be CONTINUOUSLY present before the tick calls it a
#: wedge.  Threshold(>0) + dwell, deliberately -- the discriminator is
#: PERSISTENCE, not magnitude.  60s spans two 30s timer ticks, so "sustained"
#: means more than one observation, and it is well inside the 180s cooldown.
DEFAULT_WEDGE_DWELL_SECONDS = 60

#: The timer cadence declared in eclipse-kiosk-watchdog.timer, mirrored here so
#: the dwell can be checked against it.  Not a knob -- change the timer and this
#: must follow, which a test asserts.
TIMER_CADENCE_SECONDS = 30

#: Minimum gap between restart attempts.  Longer than the window (so a tick can
#: never see a pre-restart error) and long enough for chromium to relaunch, load
#: the page and either settle or genuinely re-wedge.
DEFAULT_COOLDOWN_SECONDS = 180

#: Restart attempts allowed per budget window before the watchdog gives up and
#: escalates.  Policy: five self-heals in an hour is not a recovered display, it
#: is a live freeze class that a human needs to see.
DEFAULT_MAX_RESTARTS_PER_HOUR = 5

#: Rolling window the budget is counted over.
RESTART_BUDGET_WINDOW_SECONDS = 3600

#: Restart ledger.  Lives on tmpfs under the watchdog's OWN RuntimeDirectory --
#: deliberately NOT /run/eclipse-obd (that dir belongs to eclipse-obd.service
#: and holds the live states/; a oneshot declaring it would delete it on exit).
#: Clearing at boot is correct: the budget is a per-uptime fault counter.
DEFAULT_STATE_PATH = "/run/eclipse-kiosk-watchdog/ledger.json"

_LEDGER_KEY = "restartAttempts"
_LEDGER_PRESENCE_KEY = "markerPresentSince"

# Decision actions.
ACTION_RESTART = "restart"
ACTION_NOOP = "noop"

# Outcome / decision reasons -- one per branch so every tick is explainable.
REASON_KIOSK_INACTIVE = "kiosk_inactive"
REASON_JOURNAL_UNREADABLE = "journal_unreadable"
REASON_JOURNAL_TIMEOUT = "journal_read_timed_out"
REASON_HEALTHY = "healthy"
REASON_WEDGE_SUSPECTED = "wedge_suspected"
REASON_COOLDOWN = "cooldown"
REASON_BUDGET_EXHAUSTED = "restart_budget_exhausted"
REASON_WEDGE_DETECTED = "wedge_detected"
REASON_WEDGE_RESTARTED = "wedge_restarted"
REASON_RESTART_FAILED = "restart_failed"
REASON_LEDGER_UNWRITABLE = "ledger_unwritable"

#: Outcomes that mean the RECOVERY PATH itself is broken or spent.  These exit
#: non-zero so `systemctl status eclipse-kiosk-watchdog` shows a fault.
#:
#: US-644-a ADDS the journal-read timeout.  A watchdog whose journal read does
#: not complete is not "uncertain", it is BROKEN -- it cannot observe the one
#: signal it exists to observe -- so it belongs with the other three faults
#: rather than with the routine no-ops.
_FAULT_REASONS = frozenset(
    {
        REASON_BUDGET_EXHAUSTED,
        REASON_RESTART_FAILED,
        REASON_LEDGER_UNWRITABLE,
        REASON_JOURNAL_TIMEOUT,
    }
)

EXIT_OK = 0
EXIT_RUNTIME = 2

#: Wall-clock ceiling on each external command, so a hung journalctl cannot
#: pin a timer-driven oneshot open forever.
_COMMAND_TIMEOUT_SECONDS = 20

#: Wall-clock ceiling on the readability PROBE specifically (US-644-a).  The
#: probe reads ONE line out of ONE size-capped file; it has no business
#: spending the full command budget, and a tick that spends
#: _COMMAND_TIMEOUT_SECONDS on the query and another 20s on the probe would
#: overrun the 30s timer cadence and start overlapping its successor.  The
#: number is DERIVED from that: 20 + 5 <= TIMER_CADENCE_SECONDS, pinned by a
#: test.  This narrowing is NOT the fix -- the scoping below is.
_PROBE_TIMEOUT_SECONDS = 5

#: journald's two storage roots, in the order journald itself prefers them: it
#: writes to the volatile /run tree when the persistent one is absent (or has
#: not been created yet at early boot), so a /var file found alongside a /run
#: one is the STALE one.  `system.journal` is journald's fixed name for the
#: ACTIVE system journal -- every other file in those directories is an
#: archived rotation, and it is the accumulated pile of those that made an
#: unscoped read scale with uptime.
_ACTIVE_JOURNAL_GLOBS: tuple[str, ...] = (
    "/run/log/journal/*/system.journal",
    "/var/log/journal/*/system.journal",
)

# Readability-probe verdicts.  THREE, not two: US-644-a's whole point is that
# "it timed out" and "it cannot be read" are different facts about different
# problems, and collapsing them made an intermittently-blind watchdog log
# healthy-looking no-ops.
PROBE_READABLE = "readable"
PROBE_UNREADABLE = "unreadable"
PROBE_TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class WatchdogPolicy:
    """The tunable half of the watchdog. Every field is CLI-overridable."""

    windowSeconds: int
    markerReadCap: int
    wedgeDwellSeconds: int
    cooldownSeconds: int
    maxRestartsPerHour: int


@dataclass(frozen=True)
class LedgerState:
    """The whole of what one tick remembers for the next one.

    Two facts, one file, one write: the restart attempts that bound recovery,
    and the instant markers were FIRST seen in the current unbroken run of
    marker-present ticks (None when the last readable tick measured zero).
    """

    restartAttempts: list[float]
    markerPresentSince: float | None

    @classmethod
    def empty(cls) -> LedgerState:
        """The state of a watchdog that remembers nothing (fresh tmpfs boot)."""
        return cls(restartAttempts=[], markerPresentSince=None)


@dataclass(frozen=True)
class JournalReading:
    """One tick's attempt to read the journal -- the count AND how it went.

    US-644-a. This used to be a bare ``int | None``, and that shape is the
    defect: ``None`` had to mean "permission denied", "journalctl is missing"
    AND "the read did not finish in time" all at once, so the tick could only
    ever report the mildest of the three. A count of markers is a measurement;
    a timeout is a statement about the INSTRUMENT, and the two cannot share a
    channel.

    ``timedOut`` covers a timeout in EITHER journalctl call -- the marker query
    or the readability probe -- because the collapse being removed was never
    specific to one of them.
    """

    count: int | None
    timedOut: bool = False

    @classmethod
    def unreadable(cls) -> JournalReading:
        """The journal could not be read, and we know that in bounded time."""
        return cls(count=None, timedOut=False)

    @classmethod
    def timeout(cls) -> JournalReading:
        """The read did not finish inside its budget -- a FAULT, not a verdict."""
        return cls(count=None, timedOut=True)


@dataclass(frozen=True)
class WatchdogDecision:
    """What one tick decided, and why -- the `reason` is the log line's subject."""

    action: str
    reason: str
    errorCount: int | None
    restartsInWindow: int
    wedged: bool = False
    dwellSeconds: float | None = None


@dataclass(frozen=True)
class WatchdogOutcome:
    """What one tick actually did, after effects."""

    reason: str
    restarted: bool
    errorCount: int | None
    restartsInWindow: int
    maxRestartsPerHour: int = 0
    wedged: bool = False
    dwellSeconds: float | None = None


# ----------------------------------------------------------------------------
# Pure decision
# ----------------------------------------------------------------------------


def pruneRestartHistory(
    history: Sequence[float],
    now: float,
    windowSeconds: float = RESTART_BUDGET_WINDOW_SECONDS,
) -> list[float]:
    """Drop attempts older than the budget window (and any future-dated junk).

    Args:
        history: Recorded restart-attempt epochs.
        now: Current epoch seconds.
        windowSeconds: Budget window length.

    Returns:
        The attempts still inside the window, oldest first.
    """
    cutoff = now - windowSeconds
    return sorted(t for t in history if cutoff <= t <= now)


def decideAction(
    *,
    unitActive: bool,
    errorCount: int | None,
    now: float,
    restartHistory: Sequence[float],
    policy: WatchdogPolicy,
    markerPresentSince: float | None = None,
    journalTimedOut: bool = False,
) -> WatchdogDecision:
    """Decide whether this tick should restart the kiosk.

    Pure: no journal, no systemctl, no clock. The whole never-flap contract
    lives here, which is why it is testable as a table.

    Args:
        unitActive: Whether the kiosk unit is currently active.
        errorCount: Wedge markers observed in the window, or None if the
            journal could not be read.
        now: Current epoch seconds.
        restartHistory: Prior restart-attempt epochs (unpruned is fine).
        policy: Thresholds in force.
        markerPresentSince: Start of the current unbroken run of marker-present
            ticks, or None.
        journalTimedOut: Whether the journal read ran out of time rather than
            failing outright. Same action, DIFFERENT reason (US-644-a).

    Returns:
        The decision, carrying the reason + observed count for logging.
    """
    recent = pruneRestartHistory(restartHistory, now)
    restartsInWindow = len(recent)

    def noop(
        reason: str, *, wedged: bool = False, dwellSeconds: float | None = None
    ) -> WatchdogDecision:
        return WatchdogDecision(
            action=ACTION_NOOP,
            reason=reason,
            errorCount=errorCount,
            restartsInWindow=restartsInWindow,
            wedged=wedged,
            dwellSeconds=dwellSeconds,
        )

    # Rule 1: never touch a kiosk that is not running. `systemctl restart` on
    # an inactive unit STARTS it, and the dashboard is deliberately started
    # only by splash-boot's OnSuccess hand-off.
    if not unitActive:
        return noop(REASON_KIOSK_INACTIVE)

    # Rule 2: no evidence is not evidence of a wedge.
    #
    # US-644-a splits the ONE way this used to be reported into two. Both are
    # no-ops -- absence of evidence still never justifies a restart -- but a
    # journal that will not READ is an uncertain tick, while a journal read
    # that will not FINISH is a broken detector, and only the second one is
    # something a human has to go and fix. Reporting them identically is how a
    # panel stayed frozen for 7h27m behind a stream of INFO no-ops.
    if errorCount is None:
        return noop(REASON_JOURNAL_TIMEOUT if journalTimedOut else REASON_JOURNAL_UNREADABLE)

    # Rule 7 (US-561): MEASURED ZERO is the only healthy verdict.
    #
    # US-523 asked `errorCount < 100`, a number calibrated against a
    # ~30,000-per-window catastrophic wedge. The regime the CIO actually drove
    # into runs 84-101 per window, so the threshold sat INSIDE the signal's own
    # band and consecutive ticks of ONE continuous freeze read
    # "WEDGED -- 101 markers" then "healthy; markers=84". A constant inside a
    # band is a coin-flip, not a discriminator -- the same lesson Spool reached
    # on the coolant fan-cycle ceiling from the opposite direction. Atlas
    # measured healthy as EXACTLY zero after the restart that unfroze it, so
    # zero is the boundary of the band rather than a point inside it, and
    # presence needs no tuned magnitude at all.
    if errorCount <= 0:
        return noop(REASON_HEALTHY)

    # ...and DWELL is what separates a live wedge from a startup hiccup, since
    # magnitude no longer can. Presence must be UNBROKEN: runOnce clears the
    # clock on any tick that measures a clean zero.
    dwellSeconds = 0.0 if markerPresentSince is None else max(0.0, now - markerPresentSince)
    if dwellSeconds < policy.wedgeDwellSeconds:
        return noop(REASON_WEDGE_SUSPECTED, dwellSeconds=dwellSeconds)

    # --- from here the kiosk IS wedged; the only question is whether we are
    # --- still allowed to act on it. Every branch below carries wedged=True:
    # --- declining to act is not a claim that the display is well.

    # Rule 5 before rule 4: when both apply, report the louder fault.
    if restartsInWindow >= policy.maxRestartsPerHour:
        return noop(REASON_BUDGET_EXHAUSTED, wedged=True, dwellSeconds=dwellSeconds)

    if recent and (now - recent[-1]) < policy.cooldownSeconds:
        return noop(REASON_COOLDOWN, wedged=True, dwellSeconds=dwellSeconds)

    return WatchdogDecision(
        action=ACTION_RESTART,
        reason=REASON_WEDGE_DETECTED,
        errorCount=errorCount,
        restartsInWindow=restartsInWindow,
        wedged=True,
        dwellSeconds=dwellSeconds,
    )


def updatedPresenceClock(
    previous: float | None, errorCount: int | None, now: float
) -> float | None:
    """Advance the marker-presence clock for one tick's observation.

    Three cases, and the middle one is the whole point of the clock:

    * journal UNREADABLE -> leave it alone. Absence of evidence must not
      forgive an accruing wedge, or a journalctl hiccup silently restarts the
      dwell from scratch every time.
    * measured ZERO -> clear it. Dwell means CONTINUOUS presence, so one clean
      tick breaks the run and an isolated GL complaint can never combine with
      another minutes later to fake a sustained wedge.
    * markers present -> stamp it if unset, otherwise KEEP the original stamp.
      Re-stamping each tick would reset the dwell forever.

    Args:
        previous: The clock as the ledger last recorded it.
        errorCount: This tick's marker count, or None if unreadable.
        now: Current epoch seconds.

    Returns:
        The clock to persist for the next tick.
    """
    if errorCount is None:
        return previous
    if errorCount <= 0:
        return None
    return now if previous is None else previous


def journalWindowStart(now: float, restartHistory: Sequence[float], windowSeconds: int) -> float:
    """Earliest instant this tick may count markers from.

    Rule 3: never reach back past the last restart attempt. The errors that
    justified that restart are still inside the raw window and would otherwise
    re-trigger on the very next tick.

    Args:
        now: Current epoch seconds.
        restartHistory: Prior restart-attempt epochs.
        windowSeconds: Nominal look-back.

    Returns:
        Epoch seconds to pass to the journal query.
    """
    windowStart = now - windowSeconds
    if not restartHistory:
        return windowStart
    return max(windowStart, max(restartHistory))


# ----------------------------------------------------------------------------
# External seams: journal, systemctl, ledger
# ----------------------------------------------------------------------------


def countWedgeMarkers(
    unitName: str,
    *,
    sinceEpoch: float,
    cap: int,
    marker: str = WEDGE_MARKER,
    runFn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    journalGlobs: Sequence[str] = _ACTIVE_JOURNAL_GLOBS,
) -> JournalReading:
    """Count wedge markers in a unit's journal since an instant.

    The count is CAPPED at ``cap`` lines: a live wedge emits ~500 markers a
    second, so an uncapped read would pull megabytes per tick off a Pi whose
    CPU is already pegged by the wedge. The caller only needs "at least the
    threshold", so pass ``threshold + 1``.

    Args:
        unitName: systemd unit whose journal to read.
        sinceEpoch: Lower time bound, sent as ``@<epoch>`` (locale-proof).
        cap: Maximum lines to retrieve.
        marker: Substring journalctl greps for.
        runFn: Injection seam for subprocess.run.
        journalGlobs: Where the readability probe looks for journald's active
            journal file; injected only so tests need no real journal.

    Returns:
        A :class:`JournalReading`: a count (0 == readable and clean), an honest
        "unreadable", or a "timed out" -- three states, never collapsed into
        one, because the tick has to report them differently (US-644-a).
    """
    argv = [
        "journalctl",
        "-u",
        unitName,
        f"--since=@{int(sinceEpoch)}",
        f"--grep={marker}",
        f"--lines={cap}",
        "--no-pager",
        "--output=cat",
    ]
    try:
        completed = runFn(
            argv,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # US-644-a. NOT "unreadable". The journal may be perfectly readable and
        # this query simply could not finish -- which is a fault in the
        # detector, and the caller escalates it as one.
        logger.error(
            "kiosk-watchdog: the '%s' marker query did not finish within %ss -- the "
            "DETECTOR is faulty, not the display. This tick observed NOTHING; do not "
            "read it as a healthy kiosk.",
            marker,
            _COMMAND_TIMEOUT_SECONDS,
        )
        return JournalReading.timeout()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("kiosk-watchdog: journal unreadable (%s: %s)", type(exc).__name__, exc)
        return JournalReading.unreadable()

    stdout = completed.stdout or ""

    if completed.returncode != 0:
        # US-561 defect 3b. `journalctl --grep=` exits 1 when NOTHING MATCHED,
        # which on a healthy kiosk is every single tick. US-523 read any
        # non-zero exit as "unreadable" and so reported a clean kiosk as an
        # honest-unknown -- the exact inverse of this function's own docstring,
        # and it made a genuinely broken journal indistinguishable from a
        # working one. The fix MEASURES readability instead of inferring it
        # from an exit code: if the journal reads fine and the grep printed
        # nothing, the zero is real.
        if not stdout.strip():
            verdict = probeJournal(runFn=runFn, journalGlobs=journalGlobs)
            if verdict == PROBE_READABLE:
                return JournalReading(count=0)
            if verdict == PROBE_TIMED_OUT:
                return JournalReading.timeout()
        logger.warning(
            "kiosk-watchdog: journalctl exited %s and the journal does not read -- "
            "treating the count as unreadable (not as a clean zero)",
            completed.returncode,
        )
        return JournalReading.unreadable()

    return JournalReading(count=sum(1 for line in stdout.splitlines() if line.strip()))


def unitIsActive(
    unitName: str,
    runFn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """True only if systemd reports the unit active.

    Anything else -- inactive, failed, unknown, or a systemctl that will not
    run -- returns False, which the decision table turns into "leave it alone".

    Args:
        unitName: Unit to probe.
        runFn: Injection seam for subprocess.run.

    Returns:
        Whether the unit is active.
    """
    try:
        completed = runFn(
            ["systemctl", "is-active", "--quiet", unitName],
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("kiosk-watchdog: is-active probe failed (%s)", exc)
        return False
    return completed.returncode == 0


def restartUnit(
    unitName: str,
    runFn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """Restart the kiosk unit.

    Runs unprivileged: deploy/polkit-rules/51-eclipse-service-control.rules
    already grants the Pi user the ``restart`` verb on
    ``eclipse-dashboard.service``. That grant is load-bearing for this
    watchdog -- tests/deploy/test_kiosk_watchdog_install.py pins it so a future
    polkit edit cannot silently revoke the recovery path.

    Args:
        unitName: Unit to restart.
        runFn: Injection seam for subprocess.run.

    Returns:
        True if systemctl reported success.
    """
    try:
        completed = runFn(
            ["systemctl", "restart", unitName],
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("kiosk-watchdog: restart of %s could not run (%s)", unitName, exc)
        return False

    if completed.returncode != 0:
        logger.error(
            "kiosk-watchdog: restart of %s FAILED rc=%s stderr=%s",
            unitName,
            completed.returncode,
            (completed.stderr or "").strip(),
        )
        return False
    return True


def activeJournalFile(journalGlobs: Sequence[str] = _ACTIVE_JOURNAL_GLOBS) -> str | None:
    """Locate journald's ACTIVE system journal, or None if there is none.

    The glob order IS the preference order (see ``_ACTIVE_JOURNAL_GLOBS``): the
    volatile root wins, because when journald is writing there a ``/var`` file
    is a leftover from a previous configuration and answering "can I read the
    journal" against it would answer about the wrong journal.

    Discovered rather than hardcoded: the directory in between is the
    machine-id, which differs per Pi image.

    WITHIN a root, the most recently written file wins. A reimage that
    regenerates /etc/machine-id while /var survives leaves two machine-id
    directories, and only one of them is still being appended to. Taking the
    alphabetically first would point the probe at an ABANDONED journal, which
    would answer "readable" on a box whose live journal is broken -- and
    ``countWedgeMarkers`` turns a readable probe into a clean ZERO, i.e. it
    would report a wedged panel as healthy. That is the one direction this
    function must not fail in.

    Args:
        journalGlobs: Patterns to try, most-preferred first.

    Returns:
        Path to the active system journal, or None when nothing matches.
    """
    for pattern in journalGlobs:
        stamped: list[tuple[float, str]] = []
        for path in glob.glob(pattern):
            try:
                stamped.append((os.stat(path).st_mtime, path))
            except OSError:
                # Journald rotating underneath the glob. DEFENCE IN DEPTH, and
                # stated as such rather than dressed up as a covered path: the
                # race cannot be staged from outside this function, so no test
                # exercises this line. It is here because a watchdog that
                # crashes reports nothing at all.
                continue
        if stamped:
            return max(stamped)[1]
    return None


def probeJournal(
    *,
    runFn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    journalGlobs: Sequence[str] = _ACTIVE_JOURNAL_GLOBS,
) -> str:
    """Probe whether this process can read the journal AT ALL, in BOUNDED time.

    US-644-a, and the scoping is the whole fix. This probe used to run a plain
    ``journalctl --lines=1``, which opens and merges EVERY journal file on the
    box -- every archived rotation of every previous boot. That cost grows with
    uptime, so the probe SUCCEEDED on a young journal and TIMED OUT on a grown
    one: an intermittent detector, which is worse than a dead one because its
    successes make it look trustworthy. Atlas measured it blowing the 20s
    budget against a 6M-entry journal on 2026-08-30, while PM watched the same
    probe answer fine ~90 minutes earlier on the same boot.

    ``--file=`` pins the read to the ONE active journal file, whose size
    journald itself caps (``SystemMaxFileSize``). The probe's runtime therefore
    stops depending on how much journal has accumulated. Widening the timeout
    would have left the unbounded read in place and only moved the failure to a
    larger journal.

    ``--file=`` does not weaken the privilege question this probe exists to
    answer: the journal files are ``root:systemd-journal``, and the unit's
    ``SupplementaryGroups=systemd-journal`` is what grants the read either way.
    A revoked grant still shows up here as UNREADABLE.

    Still deliberately UNFILTERED by unit and by ``--grep``: the question is
    "does the journal read", and a unit-scoped probe would answer it wrongly
    for a unit that simply has no entries yet (US-561 defect 3b).

    Only ever called on ``countWedgeMarkers``' failure path, so a healthy tick
    still costs exactly one journalctl.

    Args:
        runFn: Injection seam for subprocess.run.
        journalGlobs: Where to look for the active journal file.

    Returns:
        One of ``PROBE_READABLE``, ``PROBE_UNREADABLE``, ``PROBE_TIMED_OUT``.
    """
    journalFile = activeJournalFile(journalGlobs)
    if journalFile is None:
        # NO unscoped fallback. Reinstating `journalctl --lines=1` here would
        # reinstate the unbounded scan on exactly the box most likely to need
        # the bound. And if neither storage root holds an active journal there
        # is nothing to read, so "unreadable" is the honest answer -- reached
        # immediately instead of after a 20s hang.
        logger.warning(
            "kiosk-watchdog: no active journal file under %s -- reporting the journal "
            "as unreadable rather than falling back to an unbounded read",
            ", ".join(journalGlobs),
        )
        return PROBE_UNREADABLE

    argv = [
        "journalctl",
        f"--file={journalFile}",
        "--lines=1",
        "--no-pager",
        "--output=cat",
    ]
    try:
        completed = runFn(
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            "kiosk-watchdog: the readability probe did not finish within %ss even scoped "
            "to a single journal file (%s) -- that is a FAULT in the watchdog itself, not "
            "a report about the display.",
            _PROBE_TIMEOUT_SECONDS,
            journalFile,
        )
        return PROBE_TIMED_OUT
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("kiosk-watchdog: journal readability probe failed (%s)", exc)
        return PROBE_UNREADABLE
    return PROBE_READABLE if completed.returncode == 0 else PROBE_UNREADABLE


def _asEpoch(value: object) -> float | None:
    """Coerce a ledger value to an epoch, or None if it is not one.

    bool is a subclass of int, so a JSON ``true`` would otherwise become 1.0 --
    a plausible-looking 1970 timestamp (the float(True) trap from US-517). For
    the presence clock that is worse than having no clock at all: ``now - 1.0``
    is a 56-year dwell, so the very next tick carrying one marker would restart
    the panel.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def readLedger(statePath: str | Path) -> LedgerState:
    """Read the watchdog ledger, degrading to "remembers nothing".

    A missing file is normal (the ledger lives on tmpfs and clears at boot). A
    corrupt or wrong-shaped file must not crash the tick either -- but note the
    caller still refuses to restart when the ledger cannot be WRITTEN, so a
    permanently broken ledger cannot turn into an unbounded restart loop.

    A pre-US-561 file (no presence key) reads as attempts + no clock, so the
    single tick that straddles a deploy keeps its restart budget.

    Args:
        statePath: Ledger path.

    Returns:
        The recorded state; ``LedgerState.empty()`` when unknown.
    """
    path = Path(statePath)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LedgerState.empty()
    except (OSError, ValueError) as exc:
        logger.warning("kiosk-watchdog: ledger unreadable (%s) -- assuming no history", exc)
        return LedgerState.empty()

    if not isinstance(raw, dict):
        logger.warning("kiosk-watchdog: ledger has unexpected shape -- assuming no history")
        return LedgerState.empty()

    attempts = raw.get(_LEDGER_KEY)
    recorded = attempts if isinstance(attempts, list) else []
    epochs = [epoch for epoch in (_asEpoch(value) for value in recorded) if epoch is not None]

    return LedgerState(
        restartAttempts=epochs,
        markerPresentSince=_asEpoch(raw.get(_LEDGER_PRESENCE_KEY)),
    )


def writeLedger(statePath: str | Path, state: LedgerState) -> bool:
    """Persist the watchdog ledger atomically.

    Args:
        statePath: Ledger path.
        state: The state to record.

    Returns:
        True on success; False (never an exception) when the ledger cannot be
        written -- the caller treats that as "do not restart, and do not call
        this healthy".
    """
    path = Path(statePath)
    payload = json.dumps(
        {
            _LEDGER_KEY: list(state.restartAttempts),
            _LEDGER_PRESENCE_KEY: state.markerPresentSince,
        }
    )
    tmpPath = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmpPath.write_text(payload, encoding="utf-8")
        os.replace(tmpPath, path)
    except OSError as exc:
        logger.error("kiosk-watchdog: cannot persist the watchdog ledger at %s (%s)", path, exc)
        return False
    return True


# ----------------------------------------------------------------------------
# One tick
# ----------------------------------------------------------------------------


def runOnce(
    *,
    policy: WatchdogPolicy,
    unitName: str,
    isActiveFn: Callable[[str], bool],
    errorCountFn: Callable[[str, float], JournalReading],
    restartFn: Callable[[str], bool],
    readLedgerFn: Callable[[], LedgerState],
    writeLedgerFn: Callable[[LedgerState], bool],
    clockFn: Callable[[], float] = time.time,
) -> WatchdogOutcome:
    """Run one watchdog tick: observe, decide, and act at most once.

    Args:
        policy: Thresholds in force.
        unitName: Kiosk unit to guard.
        isActiveFn: Unit-active probe.
        errorCountFn: ``(unitName, sinceEpoch) -> JournalReading`` journal probe.
        restartFn: Restart action.
        readHistoryFn: Restart-ledger reader.
        writeHistoryFn: Restart-ledger writer, returning success.
        clockFn: Epoch-seconds clock.

    Returns:
        What the tick did and why.
    """
    now = clockFn()
    active = isActiveFn(unitName)

    ledger = LedgerState.empty()
    reading = JournalReading(count=None)
    if active:
        ledger = readLedgerFn()
        sinceEpoch = journalWindowStart(now, ledger.restartAttempts, policy.windowSeconds)
        reading = errorCountFn(unitName, sinceEpoch)

    errorCount = reading.count
    history = ledger.restartAttempts
    markerPresentSince = updatedPresenceClock(ledger.markerPresentSince, errorCount, now)

    decision = decideAction(
        unitActive=active,
        errorCount=errorCount,
        now=now,
        restartHistory=history,
        markerPresentSince=markerPresentSince,
        policy=policy,
        journalTimedOut=reading.timedOut,
    )

    def outcomeOf(reason: str, *, restarted: bool, restartsInWindow: int) -> WatchdogOutcome:
        return WatchdogOutcome(
            reason=reason,
            restarted=restarted,
            errorCount=decision.errorCount,
            restartsInWindow=restartsInWindow,
            maxRestartsPerHour=policy.maxRestartsPerHour,
            wedged=decision.wedged,
            dwellSeconds=decision.dwellSeconds,
        )

    if decision.action != ACTION_RESTART:
        # The dwell lives in the ledger, so a clock change has to survive the
        # tick or the discriminator has no memory. Persist ONLY on a change --
        # a quiet tick still leaves no footprint.
        if markerPresentSince != ledger.markerPresentSince and not writeLedgerFn(
            LedgerState(restartAttempts=history, markerPresentSince=markerPresentSince)
        ):
            logger.error(
                "kiosk-watchdog: %s reported %s '%s' markers but the ledger is unwritable -- "
                "the wedge clock cannot advance, so this tick is UNCERTAIN, not healthy",
                unitName,
                decision.errorCount,
                WEDGE_MARKER,
            )
            return outcomeOf(
                REASON_LEDGER_UNWRITABLE,
                restarted=False,
                restartsInWindow=decision.restartsInWindow,
            )

        _logNoop(decision, unitName, policy)
        return outcomeOf(
            decision.reason, restarted=False, restartsInWindow=decision.restartsInWindow
        )

    # Rule 6: record the attempt FIRST. The cooldown + budget only bound
    # anything if no restart can happen without its bookkeeping landing, so an
    # unwritable ledger cancels the restart instead of quietly uncapping it.
    # The presence clock is CLEARED with the restart: the fresh chromium
    # generation must earn its own dwell. Inheriting the dead one's clock would
    # restart the new kiosk on its very first marker.
    updated = pruneRestartHistory(history, now) + [now]
    if not writeLedgerFn(LedgerState(restartAttempts=updated, markerPresentSince=None)):
        logger.error(
            "kiosk-watchdog: kiosk %s looks WEDGED (%s '%s' sustained %.0fs) but the "
            "restart ledger is unwritable -- refusing to restart, because an unrecorded "
            "restart cannot be rate-limited",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            decision.dwellSeconds or 0.0,
        )
        return outcomeOf(
            REASON_LEDGER_UNWRITABLE,
            restarted=False,
            restartsInWindow=decision.restartsInWindow,
        )

    restartsInWindow = len(updated)
    logger.warning(
        "kiosk-watchdog: kiosk %s WEDGED -- %s '%s' errors sustained for %.0fs; restarting "
        "(attempt %s of %s this hour, %s left). US-522 was supposed to remove this failure "
        "class: a restart here means it is still live.",
        unitName,
        decision.errorCount,
        WEDGE_MARKER,
        decision.dwellSeconds or 0.0,
        restartsInWindow,
        policy.maxRestartsPerHour,
        max(0, policy.maxRestartsPerHour - restartsInWindow),
    )

    if not restartFn(unitName):
        return outcomeOf(
            REASON_RESTART_FAILED, restarted=False, restartsInWindow=restartsInWindow
        )

    logger.warning("kiosk-watchdog: %s restarted; display should be live again", unitName)
    return outcomeOf(
        REASON_WEDGE_RESTARTED, restarted=True, restartsInWindow=restartsInWindow
    )


def _budgetPhrase(decision: WatchdogDecision, policy: WatchdogPolicy) -> str:
    """"N of M restarts this hour (K left)" -- the observable form.

    US-561 defect 3d: on 2026-08-20 two of five restarts were consumed mid-drive
    and nothing surfaced it. "2 restarts" is not observable; "2 of 5" is.
    """
    remaining = max(0, policy.maxRestartsPerHour - decision.restartsInWindow)
    return (
        f"{decision.restartsInWindow} of {policy.maxRestartsPerHour} restarts this hour "
        f"({remaining} left)"
    )


def _logNoop(decision: WatchdogDecision, unitName: str, policy: WatchdogPolicy) -> None:
    """Log a no-op tick at the level its reason deserves."""
    budget = _budgetPhrase(decision, policy)

    if decision.reason == REASON_BUDGET_EXHAUSTED:
        logger.error(
            "kiosk-watchdog: %s is WEDGED AGAIN (%s '%s' sustained %.0fs) and the restart "
            "budget is spent (%s) -- NOT restarting. The freeze class is live; this needs "
            "a human, not another restart.",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            decision.dwellSeconds or 0.0,
            budget,
        )
        return
    if decision.reason == REASON_COOLDOWN:
        logger.warning(
            "kiosk-watchdog: %s is WEDGED (%s '%s' sustained %.0fs) but the %ss cooldown "
            "from the last restart has not elapsed -- holding off; %s",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            decision.dwellSeconds or 0.0,
            policy.cooldownSeconds,
            budget,
        )
        return
    if decision.reason == REASON_JOURNAL_TIMEOUT:
        # US-644-a. The shipped line for this tick was
        # `INFO ... no action (journal_unreadable; markers=None)` -- routine,
        # reassuring, and emitted while the watchdog was blind. Say what
        # actually happened, at a level that is looked at.
        logger.error(
            "kiosk-watchdog: the journal read for %s did NOT COMPLETE in time -- this "
            "tick observed nothing and is NOT a health report. The watchdog is blind "
            "until this is fixed; a frozen panel would go unnoticed. %s",
            unitName,
            budget,
        )
        return
    if decision.reason == REASON_WEDGE_SUSPECTED:
        # NOT healthy, and it must not read as healthy. Markers are present;
        # the only open question is whether they persist.
        logger.warning(
            "kiosk-watchdog: %s is NOT healthy -- %s '%s' markers present for %.0fs of the "
            "%ss needed to call it wedged. Healthy is measured ZERO; this is not zero. %s",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            decision.dwellSeconds or 0.0,
            policy.wedgeDwellSeconds,
            budget,
        )
        return

    # Routine tick. A partly-spent budget is a standing fact about the
    # display's health, so it is stated every tick until it ages out -- rather
    # than only in the one WARNING line emitted at the moment of the restart.
    if decision.restartsInWindow > 0:
        logger.warning(
            "kiosk-watchdog: no action (%s; markers=%s) but the display has already "
            "self-healed this hour -- %s",
            decision.reason,
            decision.errorCount,
            budget,
        )
        return
    logger.info(
        "kiosk-watchdog: no action (%s; markers=%s, %s)",
        decision.reason,
        decision.errorCount,
        budget,
    )


# ----------------------------------------------------------------------------
# CLI (systemd oneshot entry point)
# ----------------------------------------------------------------------------


def _buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restart the Pi dashboard kiosk when its renderer wedges (US-523).",
    )
    parser.add_argument("--unit", default=DEFAULT_UNIT, help="kiosk unit to guard")
    parser.add_argument(
        "--window-seconds", type=int, default=DEFAULT_WINDOW_SECONDS, help="journal look-back"
    )
    parser.add_argument(
        "--marker-read-cap",
        type=int,
        default=DEFAULT_MARKER_READ_CAP,
        help=f"max '{WEDGE_MARKER}' journal lines read per tick (an I/O bound, NOT a verdict)",
    )
    parser.add_argument(
        "--wedge-dwell-seconds",
        type=int,
        default=DEFAULT_WEDGE_DWELL_SECONDS,
        help="how long markers must be CONTINUOUSLY present before it counts as wedged",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=int,
        default=DEFAULT_COOLDOWN_SECONDS,
        help="minimum gap between restart attempts",
    )
    parser.add_argument(
        "--max-restarts-per-hour",
        type=int,
        default=DEFAULT_MAX_RESTARTS_PER_HOUR,
        help="restart attempts per hour before escalating instead of restarting",
    )
    parser.add_argument(
        "--state-path", default=DEFAULT_STATE_PATH, help="restart-ledger path (tmpfs)"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runOnceFn: Callable[..., WatchdogOutcome] = runOnce,
) -> int:
    """CLI entry point for one watchdog tick.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).
        runOnceFn: Injection seam for the tick body.

    Returns:
        0 for every routine outcome, including a successful self-heal; 2 when
        the RECOVERY PATH is broken or spent (budget exhausted, restart failed,
        ledger unwritable) so the oneshot registers as failed in systemctl.
    """
    args = _buildParser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    policy = WatchdogPolicy(
        windowSeconds=args.window_seconds,
        markerReadCap=args.marker_read_cap,
        wedgeDwellSeconds=args.wedge_dwell_seconds,
        cooldownSeconds=args.cooldown_seconds,
        maxRestartsPerHour=args.max_restarts_per_hour,
    )
    statePath = Path(args.state_path)

    outcome = runOnceFn(
        policy=policy,
        unitName=args.unit,
        isActiveFn=unitIsActive,
        errorCountFn=lambda unit, since: countWedgeMarkers(
            unit, sinceEpoch=since, cap=policy.markerReadCap
        ),
        restartFn=restartUnit,
        readLedgerFn=lambda: readLedger(statePath),
        writeLedgerFn=lambda state: writeLedger(statePath, state),
        clockFn=time.time,
    )
    return EXIT_RUNTIME if outcome.reason in _FAULT_REASONS else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - systemd entry point
    raise SystemExit(main())
