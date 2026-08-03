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
#                      in a single boot (~500/sec, 2,500 per 5s window) while
#                      frozen, and exactly 0 after the restart that unfroze it,
#                      so the marker separates wedged from healthy with orders
#                      of magnitude to spare.  The AC's other candidate signal
#                      -- "a CPU-pegged chromium with no state-file-driven
#                      repaint" -- is NOT implemented, on purpose: repaint is
#                      not observable from outside the browser, and the CPU half
#                      alone has no post-US-522 baseline to threshold against
#                      (software rendering raises healthy CPU by an unmeasured
#                      amount, and Atlas's 39/31/24%-wedged vs 18/9/8%-healthy
#                      figures predate `--disable-gpu`).  Guessing that number
#                      would be a fabricated threshold, so the honest bound is:
#                      a wedge with a DIFFERENT signature is not detected here.
#                      See offices/architect/findings/
#                      2026-08-02-pi-ui-freeze-chromium-gpu-command-buffer-hotloop.md
#
#                      NEVER-FLAP RULES (each pinned by its own test):
#                        1. an inactive kiosk is left alone -- `systemctl
#                           restart` would START it, stealing the hand-off that
#                           belongs to splash-boot's OnSuccess (A-1);
#                        2. an unreadable journal is UNCERTAIN, never a wedge;
#                        3. the journal window never reaches back past the last
#                           restart, so pre-restart errors cannot re-trigger;
#                        4. a cooldown separates consecutive restarts;
#                        5. an hourly restart budget caps the loop -- once spent
#                           the watchdog stops restarting and starts shouting;
#                        6. the attempt is recorded BEFORE the restart, so an
#                           unwritable ledger disables the restart rather than
#                           silently disabling rules 3-5.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex          | Initial implementation (Sprint 70 US-523)
# ================================================================================
################################################################################

"""Wedged-kiosk detection + bounded self-recovery for the Pi dashboard (US-523)."""

from __future__ import annotations

import argparse
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

#: Markers-in-window that mean "wedged".  Healthy is 0 (measured, post-restart);
#: wedged is ~30,000 per window.  100 sits ~300x below the wedge rate and above
#: zero, so neither a clean kiosk nor a couple of startup GL complaints trip it.
DEFAULT_ERROR_THRESHOLD = 100

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

# Decision actions.
ACTION_RESTART = "restart"
ACTION_NOOP = "noop"

# Outcome / decision reasons -- one per branch so every tick is explainable.
REASON_KIOSK_INACTIVE = "kiosk_inactive"
REASON_JOURNAL_UNREADABLE = "journal_unreadable"
REASON_HEALTHY = "healthy"
REASON_COOLDOWN = "cooldown"
REASON_BUDGET_EXHAUSTED = "restart_budget_exhausted"
REASON_WEDGE_DETECTED = "wedge_detected"
REASON_WEDGE_RESTARTED = "wedge_restarted"
REASON_RESTART_FAILED = "restart_failed"
REASON_LEDGER_UNWRITABLE = "ledger_unwritable"

#: Outcomes that mean the RECOVERY PATH itself is broken or spent.  These exit
#: non-zero so `systemctl status eclipse-kiosk-watchdog` shows a fault.
_FAULT_REASONS = frozenset(
    {REASON_BUDGET_EXHAUSTED, REASON_RESTART_FAILED, REASON_LEDGER_UNWRITABLE}
)

EXIT_OK = 0
EXIT_RUNTIME = 2

#: Wall-clock ceiling on each external command, so a hung journalctl cannot
#: pin a timer-driven oneshot open forever.
_COMMAND_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class WatchdogPolicy:
    """The tunable half of the watchdog. Every field is CLI-overridable."""

    windowSeconds: int
    errorThreshold: int
    cooldownSeconds: int
    maxRestartsPerHour: int


@dataclass(frozen=True)
class WatchdogDecision:
    """What one tick decided, and why -- the `reason` is the log line's subject."""

    action: str
    reason: str
    errorCount: int | None
    restartsInWindow: int


@dataclass(frozen=True)
class WatchdogOutcome:
    """What one tick actually did, after effects."""

    reason: str
    restarted: bool
    errorCount: int | None
    restartsInWindow: int


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

    Returns:
        The decision, carrying the reason + observed count for logging.
    """
    recent = pruneRestartHistory(restartHistory, now)
    restartsInWindow = len(recent)

    def noop(reason: str) -> WatchdogDecision:
        return WatchdogDecision(
            action=ACTION_NOOP,
            reason=reason,
            errorCount=errorCount,
            restartsInWindow=restartsInWindow,
        )

    # Rule 1: never touch a kiosk that is not running. `systemctl restart` on
    # an inactive unit STARTS it, and the dashboard is deliberately started
    # only by splash-boot's OnSuccess hand-off.
    if not unitActive:
        return noop(REASON_KIOSK_INACTIVE)

    # Rule 2: no evidence is not evidence of a wedge.
    if errorCount is None:
        return noop(REASON_JOURNAL_UNREADABLE)

    if errorCount < policy.errorThreshold:
        return noop(REASON_HEALTHY)

    # --- from here the kiosk IS wedged; the only question is whether we are
    # --- still allowed to act on it.

    # Rule 5 before rule 4: when both apply, report the louder fault.
    if restartsInWindow >= policy.maxRestartsPerHour:
        return noop(REASON_BUDGET_EXHAUSTED)

    if recent and (now - recent[-1]) < policy.cooldownSeconds:
        return noop(REASON_COOLDOWN)

    return WatchdogDecision(
        action=ACTION_RESTART,
        reason=REASON_WEDGE_DETECTED,
        errorCount=errorCount,
        restartsInWindow=restartsInWindow,
    )


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
) -> int | None:
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

    Returns:
        Marker count (0 == readable and clean), or None if the journal could
        not be read at all -- an honest "unknown", never a silent 0.
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
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("kiosk-watchdog: journal unreadable (%s: %s)", type(exc).__name__, exc)
        return None

    if completed.returncode != 0:
        logger.warning(
            "kiosk-watchdog: journalctl exited %s -- treating the journal as unreadable",
            completed.returncode,
        )
        return None

    stdout = completed.stdout or ""
    return sum(1 for line in stdout.splitlines() if line.strip())


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


def readRestartHistory(statePath: str | Path) -> list[float]:
    """Read the restart ledger, degrading to "no known restarts".

    A missing file is normal (the ledger lives on tmpfs and clears at boot). A
    corrupt or wrong-shaped file must not crash the tick either -- but note the
    caller still refuses to restart when the ledger cannot be WRITTEN, so a
    permanently broken ledger cannot turn into an unbounded restart loop.

    Args:
        statePath: Ledger path.

    Returns:
        Recorded attempt epochs; empty when unknown.
    """
    path = Path(statePath)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        logger.warning("kiosk-watchdog: ledger unreadable (%s) -- assuming no restarts", exc)
        return []

    if not isinstance(raw, dict):
        logger.warning("kiosk-watchdog: ledger has unexpected shape -- assuming no restarts")
        return []

    attempts = raw.get(_LEDGER_KEY)
    if not isinstance(attempts, list):
        return []

    # bool is a subclass of int: a JSON `true` would otherwise become 1.0 and
    # read as a plausible 1970 timestamp (the float(True) trap from US-517).
    return [
        float(value)
        for value in attempts
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def writeRestartHistory(statePath: str | Path, history: Sequence[float]) -> bool:
    """Persist the restart ledger atomically.

    Args:
        statePath: Ledger path.
        history: Attempt epochs to record.

    Returns:
        True on success; False (never an exception) when the ledger cannot be
        written -- the caller treats that as "do not restart".
    """
    path = Path(statePath)
    payload = json.dumps({_LEDGER_KEY: list(history)})
    tmpPath = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmpPath.write_text(payload, encoding="utf-8")
        os.replace(tmpPath, path)
    except OSError as exc:
        logger.error("kiosk-watchdog: cannot persist the restart ledger at %s (%s)", path, exc)
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
    errorCountFn: Callable[[str, float], int | None],
    restartFn: Callable[[str], bool],
    readHistoryFn: Callable[[], list[float]],
    writeHistoryFn: Callable[[list[float]], bool],
    clockFn: Callable[[], float] = time.time,
) -> WatchdogOutcome:
    """Run one watchdog tick: observe, decide, and act at most once.

    Args:
        policy: Thresholds in force.
        unitName: Kiosk unit to guard.
        isActiveFn: Unit-active probe.
        errorCountFn: ``(unitName, sinceEpoch) -> count | None`` journal probe.
        restartFn: Restart action.
        readHistoryFn: Restart-ledger reader.
        writeHistoryFn: Restart-ledger writer, returning success.
        clockFn: Epoch-seconds clock.

    Returns:
        What the tick did and why.
    """
    now = clockFn()
    active = isActiveFn(unitName)

    history: list[float] = []
    errorCount: int | None = None
    if active:
        history = readHistoryFn()
        sinceEpoch = journalWindowStart(now, history, policy.windowSeconds)
        errorCount = errorCountFn(unitName, sinceEpoch)

    decision = decideAction(
        unitActive=active,
        errorCount=errorCount,
        now=now,
        restartHistory=history,
        policy=policy,
    )

    if decision.action != ACTION_RESTART:
        _logNoop(decision, unitName, policy)
        return WatchdogOutcome(
            reason=decision.reason,
            restarted=False,
            errorCount=decision.errorCount,
            restartsInWindow=decision.restartsInWindow,
        )

    # Rule 6: record the attempt FIRST. The cooldown + budget only bound
    # anything if no restart can happen without its bookkeeping landing, so an
    # unwritable ledger cancels the restart instead of quietly uncapping it.
    updated = pruneRestartHistory(history, now) + [now]
    if not writeHistoryFn(updated):
        logger.error(
            "kiosk-watchdog: kiosk %s looks WEDGED (%s '%s' in %ss) but the restart "
            "ledger is unwritable -- refusing to restart, because an unrecorded "
            "restart cannot be rate-limited",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            policy.windowSeconds,
        )
        return WatchdogOutcome(
            reason=REASON_LEDGER_UNWRITABLE,
            restarted=False,
            errorCount=decision.errorCount,
            restartsInWindow=decision.restartsInWindow,
        )

    restartsInWindow = len(updated)
    logger.warning(
        "kiosk-watchdog: kiosk %s WEDGED -- %s '%s' errors within %ss; restarting "
        "(attempt %s of %s this hour). US-522 was supposed to remove this failure "
        "class: a restart here means it is still live.",
        unitName,
        decision.errorCount,
        WEDGE_MARKER,
        policy.windowSeconds,
        restartsInWindow,
        policy.maxRestartsPerHour,
    )

    if not restartFn(unitName):
        return WatchdogOutcome(
            reason=REASON_RESTART_FAILED,
            restarted=False,
            errorCount=decision.errorCount,
            restartsInWindow=restartsInWindow,
        )

    logger.warning("kiosk-watchdog: %s restarted; display should be live again", unitName)
    return WatchdogOutcome(
        reason=REASON_WEDGE_RESTARTED,
        restarted=True,
        errorCount=decision.errorCount,
        restartsInWindow=restartsInWindow,
    )


def _logNoop(decision: WatchdogDecision, unitName: str, policy: WatchdogPolicy) -> None:
    """Log a no-op tick at the level its reason deserves."""
    if decision.reason == REASON_BUDGET_EXHAUSTED:
        logger.error(
            "kiosk-watchdog: %s is WEDGED AGAIN (%s '%s' in %ss) and the restart budget "
            "is spent (%s in the last hour) -- NOT restarting. The freeze class is live; "
            "this needs a human, not another restart.",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            policy.windowSeconds,
            decision.restartsInWindow,
        )
        return
    if decision.reason == REASON_COOLDOWN:
        logger.warning(
            "kiosk-watchdog: %s still reporting %s '%s' errors but the %ss cooldown from "
            "the last restart has not elapsed -- holding off",
            unitName,
            decision.errorCount,
            WEDGE_MARKER,
            policy.cooldownSeconds,
        )
        return
    logger.info(
        "kiosk-watchdog: no action (%s; markers=%s, restarts this hour=%s)",
        decision.reason,
        decision.errorCount,
        decision.restartsInWindow,
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
        "--error-threshold",
        type=int,
        default=DEFAULT_ERROR_THRESHOLD,
        help=f"'{WEDGE_MARKER}' errors within the window that mean wedged",
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
        errorThreshold=args.error_threshold,
        cooldownSeconds=args.cooldown_seconds,
        maxRestartsPerHour=args.max_restarts_per_hour,
    )
    statePath = Path(args.state_path)
    # Cap the journal read one line past the threshold: the decision only needs
    # "at or above", and a live wedge would otherwise return ~30,000 lines.
    markerCap = policy.errorThreshold + 1

    outcome = runOnceFn(
        policy=policy,
        unitName=args.unit,
        isActiveFn=unitIsActive,
        errorCountFn=lambda unit, since: countWedgeMarkers(
            unit, sinceEpoch=since, cap=markerCap
        ),
        restartFn=restartUnit,
        readHistoryFn=lambda: readRestartHistory(statePath),
        writeHistoryFn=lambda history: writeRestartHistory(statePath, history),
        clockFn=time.time,
    )
    return EXIT_RUNTIME if outcome.reason in _FAULT_REASONS else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - systemd entry point
    raise SystemExit(main())
