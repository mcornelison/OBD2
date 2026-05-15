################################################################################
# File Name: boot_reason.py
# Purpose/Description: Detect prior-boot disposition (clean shutdown vs hard
#                      crash) at Pi startup and write one row to the
#                      ``startup_log`` table per boot.  Reads the current boot
#                      id from ``/proc/sys/kernel/random/boot_id``, parses
#                      ``journalctl --list-boots`` to enumerate prior boots,
#                      then probes the prior boot's tail journal for graceful
#                      shutdown markers (``Reached target Shutdown`` / ``Power-Off``
#                      / ``Reboot``, ``systemd-shutdown``, ``Halting system``,
#                      ``Powering off``, ``System is powering down``).  Writer
#                      uses ``INSERT OR IGNORE`` on the ``boot_id`` PK so
#                      re-invocation on the same boot is a no-op (idempotent).
#                      Drain Test post-mortem becomes queryable from SQL alone
#                      -- no operator inspection of journalctl required.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-02    | Rex (US-263) | Initial -- boot-reason detector + idempotent
#                                startup_log writer.  Sprint 22 forensic
#                                instrumentation (the queryable side of the
#                                Drain-N post-mortem surface; US-262 ships the
#                                CSV side).
# 2026-05-15    | Ralph        | I-037 fix: LADDER_GRACEFUL_GREP_PATTERN repointed
#                 (US-342)     | from the orchestrator INTENT marker
#                              | ("PowerDownOrchestrator: TRIGGER at") to the
#                              | post-success marker ("PowerDownOrchestrator:
#                              | poweroff accepted by systemd") emitted by
#                              | shutdown_handler._executeShutdown after
#                              | subprocess.run returncode==0.  Drain 22
#                              | forensic (2026-05-15) showed the pre-fix
#                              | pattern was matching even when poweroff
#                              | FAILED (I-036 PolicyKit denial), promoting
#                              | prior_boot_clean to True on every
#                              | hard-crash since V0.24.1 deploy.
#                              | Spool's initial hypothesis (US-330 retry-
#                              | fallback default of 1) was empirically wrong --
#                              | US-330's retry-fallback returns [], not 1;
#                              | the regression was in US-308's ladder-probe
#                              | pattern semantics (intent vs success).
#                              | US-330's race-guard retry code is innocent
#                              | of this regression and is left untouched.
# 2026-05-12    | Rex (US-330) | I-030 fix: retry ``journalctl --list-boots``.
#                                The V0.27.6 post-Drain-17 boot wrote a
#                                ``startup_log`` row with EMPTY
#                                ``prior_boot_clean`` AND ``prior_last_entry_ts``
#                                -- a regression from the ``prior_boot_clean=1``
#                                rows V0.27.4/.5 boots produced.  Pre-flight
#                                (code archaeology; live ``journalctl`` on
#                                chi-eclipse-01 is a CIO follow-up, same
#                                pattern as US-326/327/328 this sprint): the
#                                writer emits NULL for BOTH columns only via
#                                :func:`detectBootReason`'s ``priorEntry is
#                                None`` branch, which is reached when
#                                ``journalctl --list-boots`` returns ``None``
#                                (the :func:`runJournalctl` failure sentinel
#                                -- e.g. the subprocess timing out under
#                                boot-time I/O contention; the leading
#                                suspect is the V0.27.6 US-322
#                                ``orphan-cleanup.timer`` ``Persistent=true``
#                                catch-up DELETE on ``realtime_data`` that now
#                                fires at boot and contends with the
#                                concurrently-launching orchestrator on the
#                                SD card -- the V0.27.5 -> V0.27.6 delta).
#                                Pre-fix the call was made exactly once and a
#                                transient failure permanently lost the
#                                prior-boot classification.  Fix ("race-guard"
#                                path per the US-330 scope -- a *timing* change
#                                around the ``--list-boots`` lookup only; the
#                                US-308 graceful-detection logic is untouched):
#                                :func:`_readBootList` retries the call up to
#                                ``LIST_BOOTS_RETRY_ATTEMPTS`` times with a
#                                ``LIST_BOOTS_RETRY_SLEEP_SECONDS`` backoff
#                                (the happy path never retries -> zero added
#                                latency when ``--list-boots`` works first
#                                try) and logs loudly if every attempt fails
#                                (the I-030 row was written *silently* -- no
#                                silent failures, per the V0.24.1 anti-pattern
#                                lesson).  Sleep is DI'd (``sleeper`` kwarg)
#                                so the suite never blocks.
# 2026-05-09    | Rex (US-308) | Recognize V0.24.1 ladder graceful shutdown.
#                                Empirical pre-flight audit (chi-eclipse-01
#                                boot -2 e6ebde20.../2026-05-09 post-Drain-8):
#                                the 100-line tail contained ZERO systemd
#                                shutdown markers (`Reached target Shutdown.`
#                                / `Powering off.` / `systemd-shutdown[1]:`)
#                                because they were rate-limited / dropped
#                                under the orchestrator + drain_forensics +
#                                obd.obd log storm + lost to abrupt journald
#                                halt.  The application-emitted
#                                `PowerDownOrchestrator: TRIGGER at ... --
#                                initiating poweroff` line IS persisted (~3
#                                min before the journal cut), but is buried
#                                >700 lines back -- well outside the 100-line
#                                tail window.  Fix: add a second narrow
#                                journalctl probe via `-g LADDER_GREP_PATTERN`
#                                that finds the application marker anywhere
#                                in the prior boot's journal regardless of
#                                position.  Tail-based scan is preserved as
#                                the legacy primary path; the ladder probe
#                                is a SECOND positive signal that cannot
#                                false-positive a hard crash (the marker
#                                only fires on _enterTrigger -> systemctl
#                                poweroff invocation).
# ================================================================================
################################################################################

"""Boot-reason detector -- writes one ``startup_log`` row per Pi boot.

The Sprint 22 drain-forensics theme requires that "did the prior shutdown
crash?" be answerable from SQL without operator-driven ``journalctl
--list-boots`` inspection.  This module is the queryable side of that
contract; :mod:`scripts.drain_forensics` (US-262) is the CSV side.

Design notes
------------

* **Idempotent writer.**  ``startup_log.boot_id`` is the PK and the writer
  uses ``INSERT OR IGNORE``.  Calling :func:`recordBootReason` more than
  once during the same boot -- e.g. an orchestrator restart, a deploy
  hook re-run -- never produces duplicate rows.

* **Dependency injection at the I/O boundary.**  :func:`detectBootReason`
  takes ``bootIdReader`` and ``journalctlRunner`` providers as keyword
  arguments.  Production wires :func:`readCurrentBootId` and
  :func:`runJournalctl`; tests inject canned values without patching
  ``subprocess.run``.

* **Best-effort.**  Per the story invariant "If journalctl is unavailable
  or returns malformed output -- log error and skip; do NOT crash
  startup": detection failures degrade gracefully.  ``priorBootClean``
  is ``None`` when the prior-boot journal cannot be probed; the row is
  still written so the boot_id appears in ``startup_log`` for forward
  cross-reference (the missing classification is itself diagnostic).

* **No wiring in this story.**  The story scope deliberately omits the
  startup callsite that invokes :func:`recordBootReason`.  The story
  ``stopConditions`` permit deferring the integration call to a separate
  follow-up if it would create an ordering dependency with the sync /
  capture loop.  This module exposes the function so the wiring is a
  one-liner when the follow-up lands.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.common.time.helper import utcIsoNow

__all__ = [
    'BOOT_ID_PATH',
    'BootListEntry',
    'BootReasonReport',
    'JOURNALCTL_TIMEOUT_SECONDS',
    'LADDER_GRACEFUL_GREP_PATTERN',
    'LADDER_GRACEFUL_PROBE_LIMIT',
    'LIST_BOOTS_RETRY_ATTEMPTS',
    'LIST_BOOTS_RETRY_SLEEP_SECONDS',
    'PRIOR_BOOT_TAIL_LINES',
    'SHUTDOWN_MARKERS',
    '_probeLadderGraceful',
    '_readBootList',
    'detectBootReason',
    'parseListBoots',
    'readCurrentBootId',
    'recordBootReason',
    'runJournalctl',
    'writeStartupLog',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

#: Linux kernel boot id surface.  32 hex characters with dashes (UUID form).
BOOT_ID_PATH = '/proc/sys/kernel/random/boot_id'

#: Subprocess timeout for journalctl invocations.  10s is generous; on a
#: healthy Pi5 ``--list-boots`` returns in under a second.  Hard cap so a
#: hung journald cannot block startup forever.
JOURNALCTL_TIMEOUT_SECONDS = 10.0

#: How many tail lines of the prior boot's journal to scan for shutdown
#: markers.  systemd emits the canonical ``Reached target Shutdown`` line
#: within the last ~30 entries of a graceful poweroff, so 100 gives a
#: comfortable margin while keeping the subprocess output bounded.
PRIOR_BOOT_TAIL_LINES = 100

#: Case-insensitive substrings that classify a prior boot as cleanly shut
#: down.  Sourced from systemd's standard shutdown / reboot / halt
#: targets and the ``systemd-shutdown`` binary's banner.  Any single
#: match is sufficient -- we treat presence as the positive signal.
SHUTDOWN_MARKERS: tuple[str, ...] = (
    'reached target shutdown',
    'reached target power-off',
    'reached target poweroff',
    'reached target reboot',
    'systemd-shutdown',
    'system is powering down',
    'powering off',
    'halting system',
    'shutdown started',
)

#: ``journalctl --grep`` pattern that catches the **successful** poweroff
#: marker emitted by ``ShutdownHandler._executeShutdown`` after
#: ``subprocess.run(['systemctl','poweroff'])`` returns 0.  V0.27.11 US-342
#: repointed this from the orchestrator's pre-call INTENT marker
#: ("PowerDownOrchestrator: TRIGGER at ...") to the post-call SUCCESS
#: marker, because Drain 22 (2026-05-15) showed the INTENT marker is in
#: the journal even when poweroff FAILS (I-036 PolicyKit denial fired
#: between TRIGGER log and the subprocess.run -- the marker was a
#: shutdown-attempt signal, not a shutdown-success signal).  Drift here =
#: silently broken detection: keep this in lockstep with
#: :data:`src.pi.hardware.shutdown_handler.SHUTDOWN_SUCCESS_MARKER`.
#: The runtime contract test in
#: ``tests/pi/diagnostics/test_boot_reason_canary.py`` enforces it.
LADDER_GRACEFUL_GREP_PATTERN = (
    'PowerDownOrchestrator: poweroff accepted by systemd'
)

#: How many lines to pull from the ladder grep probe.  The marker fires
#: at most once per drain test (one row in ``power_log`` ``stage_trigger``
#: per drain), so 5 is comfortable headroom for the multi-drain case
#: where a boot saw NORMAL -> WARNING -> NORMAL -> WARNING -> TRIGGER
#: re-entries.  Bounded subprocess output keeps the probe cheap.
LADDER_GRACEFUL_PROBE_LIMIT = 5

#: How many times to call ``journalctl --list-boots`` before giving up
#: (US-330 / I-030).  A boot-time I/O storm -- the leading suspect being
#: the V0.27.6 US-322 ``orphan-cleanup.timer`` ``Persistent=true``
#: catch-up DELETE on ``realtime_data`` that now fires at boot and
#: contends with the concurrently-launching orchestrator on the Pi 5's
#: SD card -- can push the ``--list-boots`` subprocess past its
#: ``JOURNALCTL_TIMEOUT_SECONDS`` cap, surfacing as ``runJournalctl``
#: returning ``None``.  Without a retry that transient failure
#: permanently strands the ``startup_log`` row at NULL ``prior_boot_clean``
#: (the I-030 symptom).  3 attempts (= 1 + 2 retries) is plenty for a
#: storm that subsides in seconds; the happy path returns on attempt 1
#: with zero added latency.
LIST_BOOTS_RETRY_ATTEMPTS = 3

#: Backoff between ``journalctl --list-boots`` attempts (US-330 / I-030).
#: Long enough for a short SD-card DELETE storm to drain, short enough
#: that the worst-case boot-time penalty -- only ever paid on the
#: anomalous path -- is a handful of seconds.  DI'd through
#: :func:`detectBootReason`'s ``sleeper`` kwarg so the test suite passes
#: a no-op and never actually blocks.
LIST_BOOTS_RETRY_SLEEP_SECONDS = 2.0

# Regex to extract (idx, boot_id, rest) from a single ``--list-boots``
# data line.  ``boot_id`` is matched as either the dashless 32-hex form
# (older systemd) or the UUID dashed form (systemd 250+); both are
# normalized downstream by :func:`_normalizeBootId`.
_LIST_BOOTS_LINE = re.compile(
    r'^\s*'
    r'(-?\d+)'                                  # idx (may be negative)
    r'\s+'
    r'([0-9a-fA-F]{32}|[0-9a-fA-F-]{36})'       # boot_id (raw form)
    r'\s+'
    r'(.+?)'                                    # remainder (timestamps)
    r'\s*$'
)


# ================================================================================
# Data Model
# ================================================================================

@dataclass(slots=True, frozen=True)
class BootListEntry:
    """One parsed line from ``journalctl --list-boots``.

    Attributes:
        idx: Index relative to the current boot.  ``0`` is the current
            boot, ``-1`` is the immediately prior boot, etc.
        bootId: Normalized 32-char lowercase hex (no dashes).
        firstEntry: First-entry timestamp string as journald renders it.
        lastEntry: Last-entry timestamp string as journald renders it.
    """
    idx: int
    bootId: str
    firstEntry: str
    lastEntry: str


@dataclass(slots=True, frozen=True)
class BootReasonReport:
    """Detection result for one Pi boot.

    Attributes:
        currentBootId: Normalized boot id of the current Pi boot.
        priorBootId: Normalized boot id of the immediately prior boot,
            or ``None`` when no prior boot is visible (fresh Pi or
            journal pruned).
        priorBootClean: ``True`` if the prior boot's tail journal
            contained a shutdown marker, ``False`` if it did not, or
            ``None`` when the classification could not be made
            (journalctl unavailable, no prior boot, journal pruned).
        priorLastEntryTs: Last-entry timestamp from the prior boot, or
            ``None`` when prior boot is unknown.
        currentBootFirstEntryTs: First-entry timestamp of the current
            boot, or ``None`` when ``--list-boots`` did not include it
            (e.g. journald only just came up).
    """
    currentBootId: str
    priorBootId: str | None
    priorBootClean: bool | None
    priorLastEntryTs: str | None
    currentBootFirstEntryTs: str | None


# ================================================================================
# I/O Boundary (DI'd into detectBootReason)
# ================================================================================

def readCurrentBootId(path: str = BOOT_ID_PATH) -> str | None:
    """Read the current Pi's boot id from the kernel surface.

    Args:
        path: Filesystem path of the boot-id surface.  Tests override
            with a tmp file; production uses the default.

    Returns:
        Normalized 32-char lowercase hex string (no dashes), or
        ``None`` if the surface is unreadable (logs the error).
    """
    try:
        with open(path, encoding='ascii') as fh:
            raw = fh.read()
    except OSError as exc:
        logger.error("Cannot read boot_id from %s: %s", path, exc)
        return None
    normalized = _normalizeBootId(raw)
    if not normalized:
        logger.error("boot_id surface %s returned empty / malformed value", path)
        return None
    return normalized


def runJournalctl(
    args: list[str],
    timeoutSeconds: float = JOURNALCTL_TIMEOUT_SECONDS,
) -> str | None:
    """Invoke ``journalctl <args>`` and return stdout, or ``None`` on failure.

    Always passes ``--no-pager`` so journalctl never tries to spawn a
    pager in the non-interactive context.  Returns ``None`` rather than
    raising so the caller can degrade gracefully (per the story
    invariant: detection failures must not crash startup).

    Args:
        args: Argument list to pass after ``journalctl --no-pager``.
        timeoutSeconds: Hard subprocess timeout.

    Returns:
        Stdout text on success, ``None`` on FileNotFoundError (no
        journalctl on PATH), TimeoutExpired, or other OS errors.  On
        non-zero exit code returns whatever stdout was captured (still
        useful when journalctl emits warnings about pruned boots).
    """
    cmd = ['journalctl', '--no-pager', *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeoutSeconds,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.error("journalctl invocation failed (%s): %s", ' '.join(cmd), exc)
        return None
    if result.returncode != 0 and not result.stdout:
        logger.warning(
            "journalctl returned code %d with empty stdout: %s",
            result.returncode,
            result.stderr.strip(),
        )
    return result.stdout


# ================================================================================
# Pure Helpers
# ================================================================================

def _normalizeBootId(raw: str) -> str:
    """Lowercase + strip whitespace + strip dashes.

    journalctl --list-boots returns 32-char dashless hex on older
    systemd and the dashed UUID form on systemd 250+; the kernel
    surface returns the dashed form.  Normalizing to dashless lowercase
    gives us a stable equality key across both surfaces.
    """
    return raw.strip().lower().replace('-', '')


def parseListBoots(output: str) -> list[BootListEntry]:
    """Parse ``journalctl --list-boots`` text into typed entries.

    Skips header / dashed-rule lines.  Tolerates extra columns
    (different systemd versions add a CONTAINER column etc.) by greedy
    timestamp extraction: each timestamp is "Day YYYY-MM-DD HH:MM:SS
    TZ" = 4 whitespace-separated tokens; the first 4 after the boot id
    are the first-entry timestamp, the next 4 are the last-entry
    timestamp.  Lines that don't match the expected shape are silently
    dropped (logs at debug level so a malformed surface doesn't
    spam stderr at startup).

    Args:
        output: Raw stdout from ``journalctl --no-pager --list-boots``.

    Returns:
        List of :class:`BootListEntry`, in the same order as the input.
    """
    entries: list[BootListEntry] = []
    for line in output.splitlines():
        match = _LIST_BOOTS_LINE.match(line)
        if not match:
            continue
        idxStr, bootIdRaw, rest = match.group(1), match.group(2), match.group(3)
        tokens = rest.split()
        if len(tokens) < 8:
            logger.debug("Skipping --list-boots line with too few tokens: %r", line)
            continue
        try:
            idx = int(idxStr)
        except ValueError:
            continue
        firstEntry = ' '.join(tokens[:4])
        lastEntry = ' '.join(tokens[4:8])
        entries.append(BootListEntry(
            idx=idx,
            bootId=_normalizeBootId(bootIdRaw),
            firstEntry=firstEntry,
            lastEntry=lastEntry,
        ))
    return entries


def _hasShutdownMarker(journalText: str) -> bool:
    """True if any canonical shutdown marker appears in the text."""
    lower = journalText.lower()
    return any(marker in lower for marker in SHUTDOWN_MARKERS)


def _probeLadderGraceful(
    journalctlRunner: Callable[[list[str]], str | None],
    priorBootId: str,
) -> bool | None:
    """Probe the prior boot for the V0.24.1 ladder TRIGGER marker.

    Issues ``journalctl -b <priorBootId> -g LADDER_GRACEFUL_GREP_PATTERN
    -n LADDER_GRACEFUL_PROBE_LIMIT`` via the runner and inspects stdout.
    The narrow ``-g`` query searches the entire prior-boot journal (not
    just the tail) so a buried application marker is reachable even when
    the orchestrator + drain_forensics + obd.obd log storm pushed the
    100-line tail past the marker line by ~700 entries (the empirical
    chi-eclipse-01 / 2026-05-09 case).

    Returns:
        ``True`` if the runner returned non-empty stdout (one or more
        matching lines -- the ladder fired).  ``False`` if the runner
        returned an empty string (probe ran cleanly, found no match --
        legitimate "no graceful ladder evidence").  ``None`` if the
        runner returned ``None`` (subprocess failure / journalctl
        unavailable / older systemd without ``-g`` support); the caller
        treats this as UNKNOWN and degrades safely instead of guessing.
    """
    output = journalctlRunner([
        '-b', priorBootId,
        '-g', LADDER_GRACEFUL_GREP_PATTERN,
        '-n', str(LADDER_GRACEFUL_PROBE_LIMIT),
    ])
    if output is None:
        return None
    return bool(output.strip())


# ================================================================================
# Core Detection
# ================================================================================

def _readBootList(
    journalctlRunner: Callable[[list[str]], str | None],
    sleeper: Callable[[float], None],
) -> list[BootListEntry]:
    """Run ``journalctl --list-boots`` with retry-on-subprocess-failure.

    US-330 / I-030: a boot-time I/O storm -- the leading suspect being
    the V0.27.6 US-322 ``orphan-cleanup.timer`` (``Persistent=true``,
    so it fires at boot to catch up the missed nightly run) running its
    ``realtime_data`` DELETE on the Pi 5's SD card while the orchestrator
    is launching -- can push the ``journalctl --list-boots`` subprocess
    past its :data:`JOURNALCTL_TIMEOUT_SECONDS` cap, which
    :func:`runJournalctl` surfaces as ``None``.  Pre-fix the caller made
    the call exactly once and, on ``None``, wrote a ``startup_log`` row
    with ``prior_boot_clean`` / ``prior_last_entry_ts`` both NULL -- the
    transient failure permanently lost the prior-boot classification (the
    I-030 symptom on the V0.27.6 post-Drain-17 boot).

    This helper retries the call up to :data:`LIST_BOOTS_RETRY_ATTEMPTS`
    times with a :data:`LIST_BOOTS_RETRY_SLEEP_SECONDS` backoff so a
    storm that drains in seconds doesn't strand the row.  The happy path
    (``--list-boots`` works on the first call) returns immediately with
    zero backoff -- the retry cost is only ever paid on the anomalous
    path.  A non-``None`` result is parsed and returned as-is even if it
    yields no usable boots: that is a real result (a genuinely fresh Pi
    or a pruned journal legitimately shows only the current boot), not a
    transient failure, so it is NOT retried.  When *every* attempt
    returns ``None`` we log loudly (the I-030 row was written silently --
    no silent failures, per the V0.24.1 anti-pattern lesson) and return
    an empty list so the caller degrades to the best-effort NULL row.

    Args:
        journalctlRunner: ``journalctl <args>`` provider returning stdout
            or ``None`` on subprocess failure.
        sleeper: Backoff sleep function (``time.sleep`` in production; a
            no-op in tests so the suite never blocks).

    Returns:
        Parsed :class:`BootListEntry` list from the first attempt that
        produced non-``None`` output, or ``[]`` if all attempts failed.
    """
    for attempt in range(1, LIST_BOOTS_RETRY_ATTEMPTS + 1):
        listOutput = journalctlRunner(['--list-boots'])
        if listOutput is not None:
            if attempt > 1:
                logger.info(
                    "journalctl --list-boots succeeded on attempt %d/%d "
                    "(earlier attempts returned no output -- transient boot-time "
                    "I/O contention; see US-330 / I-030)",
                    attempt,
                    LIST_BOOTS_RETRY_ATTEMPTS,
                )
            return parseListBoots(listOutput)
        if attempt < LIST_BOOTS_RETRY_ATTEMPTS:
            logger.warning(
                "journalctl --list-boots returned no output on attempt %d/%d -- "
                "retrying in %.1fs (boot-time I/O contention can time the "
                "subprocess out; see US-330 / I-030)",
                attempt,
                LIST_BOOTS_RETRY_ATTEMPTS,
                LIST_BOOTS_RETRY_SLEEP_SECONDS,
            )
            sleeper(LIST_BOOTS_RETRY_SLEEP_SECONDS)
    logger.warning(
        "journalctl --list-boots unavailable after %d attempts -- the "
        "startup_log row will record prior_boot_clean=NULL (prior-boot "
        "disposition unknown). If this recurs, check boot-time I/O contention "
        "(US-322 orphan-cleanup.timer) and journald persistence (/var/log/journal).",
        LIST_BOOTS_RETRY_ATTEMPTS,
    )
    return []


def detectBootReason(
    *,
    bootIdReader: Callable[[], str | None] = readCurrentBootId,
    journalctlRunner: Callable[[list[str]], str | None] = runJournalctl,
    sleeper: Callable[[float], None] = time.sleep,
) -> BootReasonReport | None:
    """Build a :class:`BootReasonReport` for the current boot.

    Args:
        bootIdReader: Provider returning the current boot id, or
            ``None`` if the kernel surface is unreadable.  Default
            wires :func:`readCurrentBootId`.
        journalctlRunner: Provider that runs ``journalctl <args>`` and
            returns stdout (or ``None`` on failure).  Default wires
            :func:`runJournalctl`.
        sleeper: Backoff sleep used by the ``journalctl --list-boots``
            retry (US-330 / I-030).  Default :func:`time.sleep`; tests
            inject a no-op so the suite never blocks.

    Returns:
        :class:`BootReasonReport` for the current boot, or ``None`` if
        the current boot id itself cannot be read (no point writing a
        row keyed on a missing PK).  Detection failures *after* the
        boot id is read are encoded as ``None`` fields on the report
        (e.g. ``priorBootClean=None`` when journalctl is unavailable).
    """
    currentBootId = bootIdReader()
    if currentBootId is None:
        return None

    # US-330 / I-030: retry the --list-boots lookup so a transient
    # boot-time storm doesn't permanently strand the row at NULL.
    boots = _readBootList(journalctlRunner, sleeper)
    currentEntry = next((b for b in boots if b.bootId == currentBootId), None)
    currentFirstTs = currentEntry.firstEntry if currentEntry else None

    # Prior boot = the entry with the largest negative idx (closest to 0).
    priorEntry = max(
        (b for b in boots if b.idx < 0),
        key=lambda b: b.idx,
        default=None,
    )
    if priorEntry is None:
        # Either --list-boots was unavailable after all retries (logged
        # in _readBootList) or this is a genuine fresh-Pi / pruned-journal
        # boot -- either way the prior-boot disposition is unknown.
        return BootReasonReport(
            currentBootId=currentBootId,
            priorBootId=None,
            priorBootClean=None,
            priorLastEntryTs=None,
            currentBootFirstEntryTs=currentFirstTs,
        )

    priorJournal = journalctlRunner([
        '-b', priorEntry.bootId,
        '-n', str(PRIOR_BOOT_TAIL_LINES),
        '--reverse',
    ])
    priorClean: bool | None
    if priorJournal is None:
        priorClean = None
    else:
        priorClean = _hasShutdownMarker(priorJournal)

    # US-308: V0.24.1 ladder graceful shutdown probe.  Tail-based scan
    # above misses the V0.24.1 case (systemd markers don't survive the
    # log-storm + abrupt halt) -- this second narrow probe catches the
    # application-emitted ``_enterTrigger`` line via journalctl --grep.
    # A positive ladder hit is a STRICTLY ADDITIVE positive signal: it
    # only promotes UNKNOWN/False -> True; never demotes True to False.
    # If the probe itself fails (journalctl unavailable / older systemd
    # without ``-g``) the tail-based answer stands.
    if priorClean is not True:
        ladderHit = _probeLadderGraceful(journalctlRunner, priorEntry.bootId)
        if ladderHit:
            priorClean = True

    return BootReasonReport(
        currentBootId=currentBootId,
        priorBootId=priorEntry.bootId,
        priorBootClean=priorClean,
        priorLastEntryTs=priorEntry.lastEntry,
        currentBootFirstEntryTs=currentFirstTs,
    )


# ================================================================================
# DB Writer
# ================================================================================

def writeStartupLog(database: Any | None, report: BootReasonReport) -> bool:
    """Write the startup_log row idempotently.

    Uses ``INSERT OR IGNORE`` so re-invocation with the same
    ``boot_id`` is a no-op (returns ``False``); the PK constraint is
    the idempotency key per the story invariant "Idempotent: rerunning
    boot_reason for the same boot_id MUST NOT insert a duplicate row".

    Args:
        database: ObdDatabase-shaped object with ``connect()``
            context manager, or ``None`` for a no-op.
        report: Detection result to persist.

    Returns:
        ``True`` if a new row was inserted, ``False`` if the row
        already existed (idempotent skip), or on database error
        (logged at ERROR; never re-raised so startup is not crashed).
    """
    if database is None:
        return False
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO startup_log
                (boot_id, prior_boot_clean, prior_last_entry_ts,
                 current_boot_first_entry_ts, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    report.currentBootId,
                    None if report.priorBootClean is None else int(report.priorBootClean),
                    report.priorLastEntryTs,
                    report.currentBootFirstEntryTs,
                    utcIsoNow(),
                ),
            )
            inserted = cursor.rowcount > 0
            if inserted:
                logger.info(
                    "startup_log row written | boot=%s prior_clean=%s",
                    report.currentBootId[:8],
                    report.priorBootClean,
                )
            else:
                logger.debug(
                    "startup_log row already exists for boot=%s -- idempotent skip",
                    report.currentBootId[:8],
                )
            return inserted
    except sqlite3.Error as exc:
        logger.error("Failed to write startup_log row: %s", exc)
        return False


# ================================================================================
# Top-Level Entry Point
# ================================================================================

def recordBootReason(
    database: Any | None,
    *,
    bootIdReader: Callable[[], str | None] = readCurrentBootId,
    journalctlRunner: Callable[[list[str]], str | None] = runJournalctl,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Detect prior-boot disposition and write the startup_log row.

    This is the wiring point for the eventual startup-callsite story.
    Idempotent by construction: invoking twice on the same boot
    inserts at most one row.

    Args:
        database: ObdDatabase instance (or ``None`` for dry-run).
        bootIdReader: DI override; default :func:`readCurrentBootId`.
        journalctlRunner: DI override; default :func:`runJournalctl`.
        sleeper: DI override for the ``--list-boots`` retry backoff
            (US-330 / I-030); default :func:`time.sleep`.

    Returns:
        ``True`` if a new row was inserted, ``False`` otherwise
        (detection failed, row already existed, or database error).
    """
    report = detectBootReason(
        bootIdReader=bootIdReader,
        journalctlRunner=journalctlRunner,
        sleeper=sleeper,
    )
    if report is None:
        logger.warning("Boot-reason detection skipped: current boot_id unavailable")
        return False
    return writeStartupLog(database, report)
