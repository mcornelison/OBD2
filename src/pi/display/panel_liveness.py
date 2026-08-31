################################################################################
# File Name: panel_liveness.py
# Purpose/Description: US-654 (F-139) display-liveness probe.  Observes whether
#                      the Pi dashboard is actually RENDERING, and reports when
#                      it is not.  Runs as a systemd oneshot driven by
#                      eclipse-panel-liveness.timer; one tick = one observation,
#                      no daemon.
#
#                      WHY IT EXISTS.  On 2026-08-31 the panel was frozen for
#                      7 h 27 m and NOTHING REPORTED IT.  The kiosk watchdog
#                      (kiosk_watchdog.py) is MARKER-ONLY: it detects the GPU
#                      command-buffer hot-loop by counting `AllocateRingBuffer`
#                      journal lines.  That freeze produced ZERO markers, so the
#                      watchdog reported healthy throughout -- correctly, by its
#                      own contract, and uselessly.  The consequence reaches the
#                      whole F-139 feature: "display stability" CANNOT be
#                      validated by the absence of a complaint, because every
#                      punch-list item that ends with a human looking at a card
#                      assumes the panel was alive when they looked, and until
#                      now nothing established that.
#
#                      THIS IS A SEPARATE DETECTOR ON PURPOSE (Atlas, explicit).
#                      Widening the marker watchdog to cover a class it
#                      structurally cannot see would produce a detector claiming
#                      a coverage it does not have -- the inert-guard shape this
#                      project has spent nine sprints cataloguing.  The two
#                      units observe different signals and fail independently.
#
#                      THE SIGNAL IS A PAIR, AND NEITHER HALF ALONE IS IT:
#                      chromium's CUMULATIVE CPU going FLAT while the state
#                      files KEEP ADVANCING.  This is the instrument that
#                      diagnosed the 7h27m freeze by hand -- CPU 00:00:14 over
#                      26,817 s elapsed while /run/eclipse-obd/states/imu
#                      advanced every ~3 s.
#                        * CPU alone is not it: a parked car with nothing
#                          flowing has a legitimately quiet page, and calling
#                          that dead is the false positive the story names as
#                          worse than having no detector at all.
#                        * State advance alone is not it: the producers are a
#                          different process tree and say nothing about whether
#                          anything was drawn.
#
#                      GROUNDED NUMBERS -- every constant below traces to a
#                      measurement recorded in the Sprint 78 contract, and the
#                      tests cite their own sources:
#                        FROZEN, three independent readings --
#                          14 s / 26,817 s          = 0.052 %
#                          35 s / 26,640 s (7.4 h)  = 0.131 %
#                          1 s  / 600 s             = 0.167 %  (the worst)
#                        HEALTHY, as recorded --     3 % .. 7 %
#                      The bands do NOT overlap, so the floor sits in the empty
#                      gap between them rather than inside either.  That is
#                      US-561's lesson applied before the fact instead of after
#                      it: a threshold placed INSIDE a signal's own operating
#                      band is a coin-flip, not a discriminator, and that is how
#                      one continuous freeze logged "WEDGED -- 101 markers" then
#                      "healthy; markers=84" on consecutive ticks.
#
#                      THE OBSERVATION WINDOW IS ALSO A MEASUREMENT, AND IT IS
#                      THE ONE THIS SPRINT CORRECTED ITSELF ON.  The original
#                      freeze evidence was "CPU flat across an 8 s sample", and
#                      the bigDefinitionOfDone retracted it: a healthy ~3 % page
#                      ALSO reads flat over 8 s at ps's 1-second granularity.
#                      The reading that did discriminate was the 6-min-to-16-min
#                      delta -- 600 s.  So a short observation yields NO VERDICT
#                      here; it is never rounded to "healthy".  Reading
#                      /proc/<pid>/stat gives 10 ms resolution rather than ps's
#                      1 s, which would in principle allow a shorter window --
#                      but SHORTER IS NOT MEASURED, and a window nobody has
#                      tested is exactly the fabricated threshold this file is
#                      trying not to ship.  It is a CLI knob with a grounded
#                      default, not a guess baked in.
#
#                      NEVER-FALSE-POSITIVE RULES (each pinned by its own test):
#                        1. no state advance -> NOT a dead panel.  Nothing to
#                           render is not a fault;
#                        2. the producers must be live at BOTH ENDS of the
#                           window.  "The mtime advanced" is satisfied by one
#                           write in the first second of a 600 s window, after
#                           which the panel is RIGHT to be quiet;
#                        3. elapsed time comes from the MONOTONIC clock, never
#                           the wall clock.  This Pi's RTC starts at 1970 and is
#                           stepped by NTP (A-23), so a wall-clock elapsed of
#                           ~56 years against ~18 s of CPU would report a
#                           perfectly healthy display as dead at every boot.
#                           Same root as US-644-b, fourth surface.  The wall
#                           clock survives only to compare file mtimes;
#                        4. a REPLACED chromium (new pid, or the same pid with a
#                           new start time) resets the CPU counter, so a
#                           differenced reading across it is meaningless -- and
#                           the kiosk watchdog restarts this very unit, so that
#                           is an ordinary event here, not an exotic one;
#                        5. an unreadable instrument is a FAULT, never a health
#                           report.  US-644-a's lesson: an INFO no-op that reads
#                           like a healthy tick is how a dead panel goes
#                           unnoticed for seven hours.
#
#                      SCOPE IS OBSERVATION AND REPORTING.  THIS MODULE RESTARTS
#                      NOTHING, and a test enforces that mechanically.  The
#                      story is explicit: chromium restarts correlate with the
#                      class-B marker storm, so an automatic remedy here could
#                      trade a DETECTED freeze for a CAUSED one.  Whether a
#                      remedy is warranted is a separate decision with a
#                      separate owner.
#
#                      HONEST BOUND, STATED RATHER THAN BURIED: this detects a
#                      panel that has STOPPED DOING WORK.  A page that repaints
#                      but renders WRONG -- stale values on a live compositor --
#                      burns normal CPU and is invisible here.  Closing that
#                      needs a repaint heartbeat published BY the page, which is
#                      a dashboard change, not an observer one.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Rex          | Initial implementation (Sprint 78 US-654)
# ================================================================================
################################################################################

"""Display-liveness observation for the Pi dashboard (US-654). Reports, never restarts."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Grounded constants.  See the header for the measurements each traces to.
# ----------------------------------------------------------------------------

#: The kiosk unit whose rendering is observed.  Never started, never restarted.
DEFAULT_UNIT = "eclipse-dashboard.service"

#: Where the emitters publish.  Their mtimes are the "is there anything to
#: render" half of the signal -- this module never reads their CONTENTS, only
#: whether they moved, so no payload schema is coupled to liveness detection.
DEFAULT_STATES_DIR = "/run/eclipse-obd/states"

#: The baseline sample, on this unit's OWN tmpfs RuntimeDirectory.  Deliberately
#: NOT under /run/eclipse-obd: that directory belongs to eclipse-obd.service and
#: holds the live states/, and a oneshot declaring it as its RuntimeDirectory
#: would make systemd DELETE it on exit -- taking the very signal this module
#: reads. The kiosk watchdog carries the same note for the same reason.
DEFAULT_STATE_PATH = "/run/eclipse-panel-liveness/baseline.json"

#: How long chromium's CPU must be averaged before the reading means anything.
#:
#: MEASURED, and it is the number this sprint corrected itself on. The original
#: freeze evidence was "CPU flat across an 8s sample"; the bigDefinitionOfDone
#: retracted it, because a healthy ~3% page also reads flat over 8s. The reading
#: that DID discriminate spanned 600s (a 6-min to 16-min delta: 00:00:17 ->
#: 00:00:18, one second of CPU across ten minutes = 0.17%). Shortening this is
#: not a tuning choice -- it re-enters the regime where a healthy panel and a
#: frozen one produce the same reading.
DEFAULT_OBSERVATION_SECONDS = 600

#: CPU fraction at or above which the panel is doing work.
#:
#: DERIVED FROM TWO NON-OVERLAPPING MEASURED BANDS, not picked. Frozen tops out
#: at 0.167% (1s/600s); healthy is recorded as 3-7%. 0.005 clears the worst
#: frozen reading by 3x and sits 6x below the mildest healthy one, so it is in
#: the empty gap rather than inside either band.
#:
#: The margins are DELIBERATELY ASYMMETRIC toward the frozen side. The two
#: failure directions are not equally bad: a false negative returns us to the
#: status quo where nothing reports, while a false positive accuses a working
#: display -- and the story is explicit that an unreliable liveness signal is
#: worse than none, because it would be trusted.
DEFAULT_LIVE_CPU_FRACTION = 0.005

#: How recently a state file must have been written for the producers to count
#: as live AT AN END of the window. 20x the measured ~3s states/imu cadence, so
#: ordinary producer jitter can never trip it.
DEFAULT_STATE_FRESHNESS_SECONDS = 60

#: The cadence declared in eclipse-panel-liveness.timer, mirrored here so the
#: observation window can be checked against it. Not a knob -- change the timer
#: and this must follow, which a test asserts. A window shorter than the cadence
#: could never be reached, and the detector would withhold forever while looking
#: exactly like a healthy one.
TIMER_CADENCE_SECONDS = 60

#: Linux's USER_HZ. Only ever used when os.sysconf is unavailable, which means a
#: platform with no /proc to read anyway -- it exists so the module imports on a
#: unit-test box rather than to be relied on in production.
_FALLBACK_CLOCK_TICKS = 100.0

#: Wall-clock ceiling on the systemctl call, so a hung systemd cannot pin a
#: timer-driven oneshot open. Well inside the unit's TimeoutStartSec.
_COMMAND_TIMEOUT_SECONDS = 10

# Outcome reasons -- one per branch, so every tick is explainable from its own
# log line without re-deriving the decision.
REASON_KIOSK_INACTIVE = "kiosk_inactive"
REASON_CPU_UNREADABLE = "cpu_unreadable"
REASON_NO_BASELINE = "baseline_recorded"
REASON_PROCESS_REPLACED = "process_replaced"
REASON_OBSERVATION_TOO_SHORT = "observation_too_short"
REASON_PRODUCERS_IDLE = "producers_idle"
REASON_PANEL_ALIVE = "panel_alive"
REASON_PANEL_DEAD = "panel_dead"
REASON_BASELINE_UNWRITABLE = "baseline_unwritable"

EXIT_OK = 0
EXIT_RUNTIME = 2

#: Reason -> exit code, extracted as a TABLE rather than written as a chain of
#: comparisons so it can be reconciled against the REASON_* the module declares.
#: An exit-code table is an ENUMERATION of reasons, i.e. exactly the shape where
#: a citation gets mistaken for a census; a new reason added without an exit
#: decision would otherwise inherit whatever the fallthrough happened to be.
#:
#: Two things exit non-zero, and they are different facts sharing a channel by
#: design: PANEL_DEAD is the FINDING (the display is not rendering), while
#: CPU_UNREADABLE and BASELINE_UNWRITABLE say the INSTRUMENT is broken. Both
#: must be visible in `systemctl status`, because the failure this module exists
#: to fix was a real fault that nothing surfaced.
_EXIT_CODE_TABLE: dict[str, int] = {
    REASON_KIOSK_INACTIVE: EXIT_OK,
    REASON_NO_BASELINE: EXIT_OK,
    REASON_PROCESS_REPLACED: EXIT_OK,
    REASON_OBSERVATION_TOO_SHORT: EXIT_OK,
    REASON_PRODUCERS_IDLE: EXIT_OK,
    REASON_PANEL_ALIVE: EXIT_OK,
    REASON_PANEL_DEAD: EXIT_RUNTIME,
    REASON_CPU_UNREADABLE: EXIT_RUNTIME,
    REASON_BASELINE_UNWRITABLE: EXIT_RUNTIME,
}


@dataclass(frozen=True)
class LivenessPolicy:
    """The tunable half of the probe. Every field is CLI-overridable."""

    observationSeconds: int
    liveCpuFraction: float
    stateFreshnessSeconds: int


@dataclass(frozen=True)
class ProcessCpu:
    """One read of a process's cumulative CPU, with its identity attached.

    ``startTicks`` travels WITH the CPU total on purpose. The total is only
    comparable against another read of the SAME process, and a pid alone does
    not establish that -- pids are recycled, and this particular pid belongs to
    a unit another watchdog restarts.
    """

    cpuSeconds: float
    startTicks: int


@dataclass(frozen=True)
class StatesReading:
    """What the states directory looked like at one instant.

    ``fresh`` is a fact about THIS instant, not about the window: it answers
    "were the producers alive just now". Two of these, one at each end, are
    what establish that the producers were live for the whole span.
    """

    newestMtime: float | None
    fresh: bool


@dataclass(frozen=True)
class PanelSample:
    """One complete observation -- the whole of what a tick hands its successor.

    Carries BOTH clocks, and that is load-bearing rather than redundant.
    ``monotonic`` measures elapsed time and is immune to the NTP step this box
    performs at every boot; ``epoch`` exists only to compare against file
    mtimes, which are stamped in wall-clock time and have no monotonic form.
    Using ``epoch`` for elapsed would report a healthy display as dead forever.
    """

    epoch: float
    monotonic: float
    pid: int
    startTicks: int
    cpuSeconds: float
    newestStateMtime: float | None
    statesFresh: bool


@dataclass(frozen=True)
class LivenessVerdict:
    """What one tick concluded, and the measurement it concluded it from.

    ``panelDead`` is the reportable finding; every other reason is a no-report.
    The measurements ride along so a log line can be audited later instead of
    being taken on trust -- the failure that created this story was a claim
    nobody could check.
    """

    reason: str
    panelDead: bool
    cpuFraction: float | None = None
    elapsedSeconds: float | None = None
    statesAdvanced: bool | None = None


# ----------------------------------------------------------------------------
# Pure decision
# ----------------------------------------------------------------------------


def decideLiveness(
    *,
    baseline: PanelSample | None,
    current: PanelSample,
    policy: LivenessPolicy,
) -> LivenessVerdict:
    """Decide whether the panel rendered anything across the window.

    Pure: no /proc, no systemctl, no clock. The whole never-false-positive
    contract lives here, which is why it is testable as a table.

    The order of the guards is itself the design. Every withholding case is
    checked BEFORE the CPU comparison, because each one describes a window in
    which a low CPU reading is the correct behaviour of a healthy panel rather
    than evidence against it.

    Args:
        baseline: The previous tick's sample, or None on the first tick after
            the tmpfs was cleared at boot.
        current: This tick's sample.
        policy: Thresholds in force.

    Returns:
        The verdict. ``panelDead`` is True for exactly one reason; everything
        else is an explicit no-report, never a silent "healthy".
    """
    if baseline is None:
        return LivenessVerdict(reason=REASON_NO_BASELINE, panelDead=False)

    # A rate differenced across two DIFFERENT processes is not a rate. The
    # start time is what makes the identity real: a pid check alone is
    # satisfied by reuse, which is precisely what makes a counter reset
    # invisible.
    if current.pid != baseline.pid or current.startTicks != baseline.startTicks:
        return LivenessVerdict(reason=REASON_PROCESS_REPLACED, panelDead=False)

    # MONOTONIC, never wall-clock -- see the class docstring and header rule 3.
    elapsedSeconds = current.monotonic - baseline.monotonic
    if elapsedSeconds < policy.observationSeconds:
        return LivenessVerdict(
            reason=REASON_OBSERVATION_TOO_SHORT,
            panelDead=False,
            elapsedSeconds=elapsedSeconds,
        )

    cpuDelta = current.cpuSeconds - baseline.cpuSeconds
    if cpuDelta < 0:
        # A monotonic counter that decreased means the identity check above did
        # not catch a replacement. Reporting a negative rate as "below the
        # floor" would turn an instrument fault into a confident accusation.
        return LivenessVerdict(reason=REASON_PROCESS_REPLACED, panelDead=False)

    # The other half of the signal. Both ends must be live, not just the fact
    # that the newest mtime moved: one write in the first second of a 600s
    # window satisfies "advanced" while leaving 599s the panel was right to
    # spend quiet.
    statesAdvanced = (
        baseline.newestStateMtime is not None
        and current.newestStateMtime is not None
        and current.newestStateMtime > baseline.newestStateMtime
    )
    if not (statesAdvanced and baseline.statesFresh and current.statesFresh):
        return LivenessVerdict(
            reason=REASON_PRODUCERS_IDLE,
            panelDead=False,
            elapsedSeconds=elapsedSeconds,
            statesAdvanced=statesAdvanced,
        )

    cpuFraction = cpuDelta / elapsedSeconds
    # Inclusive on the LIVE side: a boundary reading should resolve toward not
    # accusing a working display.
    dead = cpuFraction < policy.liveCpuFraction
    return LivenessVerdict(
        reason=REASON_PANEL_DEAD if dead else REASON_PANEL_ALIVE,
        panelDead=dead,
        cpuFraction=cpuFraction,
        elapsedSeconds=elapsedSeconds,
        statesAdvanced=True,
    )


# ----------------------------------------------------------------------------
# External seams: systemd, /proc, the states dir, the baseline file
# ----------------------------------------------------------------------------


def clockTicksPerSecond() -> float:
    """Resolve USER_HZ, the unit /proc reports CPU time in.

    Returns:
        The platform's clock tick rate, or the Linux default of 100 where
        os.sysconf is unavailable (a platform with no /proc to read anyway).
    """
    try:
        value = os.sysconf("SC_CLK_TCK")
    except (AttributeError, ValueError, OSError):
        return _FALLBACK_CLOCK_TICKS
    return float(value) if value and value > 0 else _FALLBACK_CLOCK_TICKS


def dashboardMainPid(
    unitName: str,
    *,
    runFn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int | None:
    """The kiosk unit's main process id, or None if it is not running.

    Reads systemd's own MainPID rather than scanning for a process named
    chromium: the unit is the thing this project deploys, and a name scan would
    happily find some other browser.

    Args:
        unitName: The kiosk unit to ask about.
        runFn: Injection seam for subprocess.run.

    Returns:
        The pid, or None when the unit is inactive, when systemd reports
        MainPID=0, or when systemctl cannot be run at all. Zero is systemd's way
        of saying "no process" and is a valid pid-shaped integer, so it is
        translated here rather than being passed on to a /proc read.
    """
    try:
        completed = runFn(
            ["systemctl", "show", "-p", "MainPID", "--value", unitName],
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("panel-liveness: could not ask systemd for %s's pid (%s)", unitName, exc)
        return None

    if completed.returncode != 0:
        return None
    try:
        pid = int((completed.stdout or "").strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def readProcessCpu(
    pid: int,
    *,
    procRoot: str | Path = "/proc",
    ticksPerSecond: float | None = None,
) -> ProcessCpu | None:
    """Read a process's cumulative CPU time and start time from /proc.

    Both user and system time count: a page spinning in syscalls is doing work,
    and reading utime alone would under-report it.

    The parse takes everything after the LAST ``)``. /proc/<pid>/stat's second
    field is the unescaped process name, so it can contain spaces and
    parentheses -- a naive ``split()`` shifts every later field, and chromium
    renames its processes at runtime, so this is a real layout rather than a
    hypothetical one.

    Args:
        pid: Process to read.
        procRoot: Root of the proc filesystem (injected for tests).
        ticksPerSecond: USER_HZ override; resolved from the platform if omitted.

    Returns:
        The reading, or None if the process is gone or its stat will not parse.
        NEVER a zero -- a zero is indistinguishable from a frozen process, which
        is the exact confusion this module exists to remove.
    """
    statPath = Path(procRoot) / str(pid) / "stat"
    try:
        text = statPath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    close = text.rfind(")")
    if close < 0:
        return None
    fields = text[close + 1 :].split()
    # After the comm, the first token is field 3 (state), so field N is at
    # index N-3: utime=14, stime=15, starttime=22.
    if len(fields) <= 19:
        return None
    try:
        utimeTicks = int(fields[11])
        stimeTicks = int(fields[12])
        startTicks = int(fields[19])
    except ValueError:
        return None

    hz = ticksPerSecond if ticksPerSecond else clockTicksPerSecond()
    return ProcessCpu(cpuSeconds=(utimeTicks + stimeTicks) / hz, startTicks=startTicks)


def sampleStates(
    statesDir: str | Path,
    *,
    now: float,
    freshnessSeconds: float,
) -> StatesReading:
    """Look at the states directory: how recently did any producer write?

    Dotfiles are ignored. ``/run/eclipse-obd/states/.http-token`` is written
    ONCE by the state server and is not a producer heartbeat -- counting it
    would make an idle box look live exactly once, right after boot, which is
    the worst possible moment for a false reading.

    Args:
        statesDir: The tmpfs states directory.
        now: Current wall-clock epoch (mtimes are wall-clock, so this must be
            too).
        freshnessSeconds: How recent a write has to be to count as live.

    Returns:
        The newest state mtime and whether it is fresh. A missing, empty or
        unreadable directory reads as "nothing to render" -- never as a signal.
    """
    newest: float | None = None
    try:
        with os.scandir(statesDir) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if not entry.is_file():
                        continue
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
    except OSError:
        return StatesReading(newestMtime=None, fresh=False)

    fresh = newest is not None and newest >= now - freshnessSeconds
    return StatesReading(newestMtime=newest, fresh=fresh)


def readBaseline(path: str | Path) -> PanelSample | None:
    """Load the previous tick's sample.

    Args:
        path: Baseline file path (tmpfs).

    Returns:
        The sample, or None if it is absent, unreadable or does not carry every
        field. A partial record is discarded rather than defaulted: a missing
        field would silently disable the check that reads it, and the next tick
        simply re-baselines, which costs one window.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return PanelSample(
            epoch=float(raw["epoch"]),
            monotonic=float(raw["monotonic"]),
            pid=int(raw["pid"]),
            startTicks=int(raw["startTicks"]),
            cpuSeconds=float(raw["cpuSeconds"]),
            newestStateMtime=(
                None if raw["newestStateMtime"] is None else float(raw["newestStateMtime"])
            ),
            statesFresh=bool(raw["statesFresh"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def writeBaseline(path: str | Path, sample: PanelSample) -> bool:
    """Persist this tick's sample for its successor.

    Args:
        path: Baseline file path (tmpfs).
        sample: The sample to record.

    Returns:
        True on success. False -- never an exception -- on failure, so the
        caller can REPORT the loss of memory instead of continuing blind.
    """
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(sample)), encoding="utf-8")
    except OSError as exc:
        logger.warning("panel-liveness: baseline write failed (%s)", exc)
        return False
    return True


# ----------------------------------------------------------------------------
# One tick
# ----------------------------------------------------------------------------


def runOnce(
    *,
    policy: LivenessPolicy,
    unitName: str,
    mainPidFn: Callable[[str], int | None],
    cpuFn: Callable[[int], ProcessCpu | None],
    statesFn: Callable[[float], StatesReading],
    readBaselineFn: Callable[[], PanelSample | None],
    writeBaselineFn: Callable[[PanelSample], bool],
    clockFn: Callable[[], float],
    monotonicFn: Callable[[], float],
) -> LivenessVerdict:
    """Take one observation, decide, rotate the baseline, and report.

    THE BASELINE ROTATION POLICY IS THE PART THAT MAKES ANY OF THIS WORK, and
    it is invisible to the decision table:

      * an observation SHORTER than the window KEEPS the existing baseline.
        Rotating it would restart the window on every tick, the 600s span would
        never be reached, and the detector would withhold forever while logging
        routine no-ops -- perfectly green, entirely inert;
      * every tick that REACHES a conclusion rotates, including "the producers
        were idle". Holding the baseline across an hour of a parked car would
        make the next window average chromium's CPU over that hour and report a
        healthy panel dead the moment data started flowing again -- a false
        positive manufactured by the detector's own bookkeeping.

    Args:
        policy: Thresholds in force.
        unitName: The kiosk unit to observe.
        mainPidFn: Resolves the unit's main pid.
        cpuFn: Reads a pid's cumulative CPU.
        statesFn: Samples the states directory at a given epoch.
        readBaselineFn: Loads the previous sample.
        writeBaselineFn: Persists a sample; False means it did not land.
        clockFn: Wall clock, for mtime comparison only.
        monotonicFn: Monotonic clock, for elapsed time.

    Returns:
        The verdict this tick reached.
    """
    pid = mainPidFn(unitName)
    if pid is None:
        # Nothing to measure, and nothing to record against. Writing a baseline
        # here would stamp a sample against a process that does not exist.
        logger.info("panel-liveness: no action (%s)", REASON_KIOSK_INACTIVE)
        return LivenessVerdict(reason=REASON_KIOSK_INACTIVE, panelDead=False)

    cpu = cpuFn(pid)
    if cpu is None:
        logger.error(
            "panel-liveness: %s is running as pid %s but its CPU could not be read -- this "
            "tick observed NOTHING and is NOT a health report. A frozen panel would go "
            "unnoticed until this is fixed.",
            unitName,
            pid,
        )
        return LivenessVerdict(reason=REASON_CPU_UNREADABLE, panelDead=False)

    now = clockFn()
    states = statesFn(now)
    current = PanelSample(
        epoch=now,
        monotonic=monotonicFn(),
        pid=pid,
        startTicks=cpu.startTicks,
        cpuSeconds=cpu.cpuSeconds,
        newestStateMtime=states.newestMtime,
        statesFresh=states.fresh,
    )

    verdict = decideLiveness(baseline=readBaselineFn(), current=current, policy=policy)

    if verdict.reason != REASON_OBSERVATION_TOO_SHORT and not writeBaselineFn(current):
        logger.error(
            "panel-liveness: the baseline could not be written -- this probe has NO MEMORY "
            "and can never complete an observation window. It is blind, not healthy.",
        )
        return LivenessVerdict(reason=REASON_BASELINE_UNWRITABLE, panelDead=False)

    _report(verdict, unitName, policy)
    return verdict


def _report(verdict: LivenessVerdict, unitName: str, policy: LivenessPolicy) -> None:
    """Log one tick at the level its reason deserves.

    The shipped failure was a panel dead for 7h27m with nothing above INFO in
    the journal, so the one line that matters is emitted at ERROR and carries
    the measurement it was derived from -- a report nobody greps for is not a
    report, and a report without its own numbers cannot be audited later.
    """
    if verdict.reason == REASON_PANEL_DEAD:
        logger.error(
            "panel-liveness: %s IS NOT RENDERING. chromium burned %.4f%% CPU over %.0fs "
            "while the state files kept advancing -- below the %.3f%% floor that separates "
            "a working panel from a frozen one. The display is dead; nothing here restarts "
            "it, by design.",
            unitName,
            (verdict.cpuFraction or 0.0) * 100.0,
            verdict.elapsedSeconds or 0.0,
            policy.liveCpuFraction * 100.0,
        )
        return
    if verdict.reason == REASON_PANEL_ALIVE:
        logger.info(
            "panel-liveness: %s is rendering (%.3f%% CPU over %.0fs)",
            unitName,
            (verdict.cpuFraction or 0.0) * 100.0,
            verdict.elapsedSeconds or 0.0,
        )
        return
    if verdict.reason == REASON_PRODUCERS_IDLE:
        # NOT a health report, and it must not read as one: this says the
        # producers were quiet, which is a fact about them and says nothing
        # about the panel.
        logger.info(
            "panel-liveness: no verdict (%s) -- the state files did not advance across the "
            "window, so there was nothing to render and the panel is not at fault",
            verdict.reason,
        )
        return
    if verdict.reason == REASON_OBSERVATION_TOO_SHORT:
        logger.info(
            "panel-liveness: no verdict (%s) -- %.0fs of the %ss window has elapsed. A "
            "shorter sample cannot tell a healthy panel from a frozen one.",
            verdict.reason,
            verdict.elapsedSeconds or 0.0,
            policy.observationSeconds,
        )
        return
    logger.info("panel-liveness: no verdict (%s)", verdict.reason)


# ----------------------------------------------------------------------------
# CLI (systemd oneshot entry point)
# ----------------------------------------------------------------------------


def _buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report when the Pi dashboard panel stops rendering (US-654).",
    )
    parser.add_argument("--unit", default=DEFAULT_UNIT, help="kiosk unit to observe")
    parser.add_argument(
        "--states-dir", default=DEFAULT_STATES_DIR, help="tmpfs states directory"
    )
    parser.add_argument(
        "--observation-seconds",
        type=int,
        default=DEFAULT_OBSERVATION_SECONDS,
        help="how long CPU must be averaged before the reading discriminates",
    )
    parser.add_argument(
        "--live-cpu-fraction",
        type=float,
        default=DEFAULT_LIVE_CPU_FRACTION,
        help="CPU fraction at or above which the panel counts as rendering",
    )
    parser.add_argument(
        "--state-freshness-seconds",
        type=int,
        default=DEFAULT_STATE_FRESHNESS_SECONDS,
        help="how recent a state write must be for the producers to count as live",
    )
    parser.add_argument(
        "--state-path", default=DEFAULT_STATE_PATH, help="baseline-sample path (tmpfs)"
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runOnceFn: Callable[..., LivenessVerdict] = runOnce,
) -> int:
    """CLI entry point for one observation.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).
        runOnceFn: Injection seam for the tick body.

    Returns:
        0 for every no-report outcome; 2 when the panel is DEAD or the probe
        itself is broken, so the oneshot registers as failed in systemctl. The
        whole finding of US-654 is that the freeze was invisible, and a oneshot
        that always exits 0 is invisible by construction.
    """
    args = _buildParser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    policy = LivenessPolicy(
        observationSeconds=args.observation_seconds,
        liveCpuFraction=args.live_cpu_fraction,
        stateFreshnessSeconds=args.state_freshness_seconds,
    )
    statePath = Path(args.state_path)
    ticks = clockTicksPerSecond()

    verdict = runOnceFn(
        policy=policy,
        unitName=args.unit,
        mainPidFn=dashboardMainPid,
        cpuFn=lambda pid: readProcessCpu(pid, ticksPerSecond=ticks),
        statesFn=lambda now: sampleStates(
            args.states_dir, now=now, freshnessSeconds=policy.stateFreshnessSeconds
        ),
        readBaselineFn=lambda: readBaseline(statePath),
        writeBaselineFn=lambda sample: writeBaseline(statePath, sample),
        clockFn=time.time,
        monotonicFn=time.monotonic,
    )
    return _EXIT_CODE_TABLE.get(verdict.reason, EXIT_RUNTIME)


if __name__ == "__main__":  # pragma: no cover - systemd entry point
    raise SystemExit(main())
