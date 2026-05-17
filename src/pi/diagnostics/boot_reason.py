################################################################################
# File Name: boot_reason.py
# Purpose/Description: Boot-id helpers for the honest boot-progress instrument.
#                      Reads the current Pi boot id from
#                      ``/proc/sys/kernel/random/boot_id`` and normalizes it to
#                      a stable dashless-lowercase key.  Consumed by
#                      ``src/pi/diagnostics/boot_progress.py`` (via
#                      ``readBootId``) and the orchestrator / shutdown_handler
#                      that reuse it.  The legacy journal-scan canary
#                      (``journalctl --list-boots`` prior-boot disposition
#                      detector + in-process ``startup_log`` writer) was
#                      DELETED in the T10 cutover -- it is fully replaced by
#                      ``src/pi/diagnostics/boot_progress.py`` (honest
#                      instrument, spec 2026-05-15) whose
#                      ``boot-progress-arm.service`` unit is now the sole
#                      ``startup_log`` writer.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-15    | Plan (T10)   | I-037: journal-scan canary deleted -- fully
#               |              | replaced by src/pi/diagnostics/boot_progress.py.
#               |              | Boot-id helpers retained (consumed by
#               |              | boot_progress.readBootId).
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

"""Boot-id helpers for the honest boot-progress instrument.

This module formerly housed the journal-scan boot-reason canary (a
``journalctl --list-boots`` prior-boot disposition detector plus an
in-process ``startup_log`` writer).  That canary was the source of
I-037 -- its ladder-probe pattern matched the orchestrator INTENT
marker that fires *before* the failing poweroff subprocess, so it
classified hard crashes as clean shutdowns.  The T10 cutover deleted
the canary outright: ``startup_log`` is now written by the honest
instrument :mod:`src.pi.diagnostics.boot_progress` (spec 2026-05-15),
whose ``boot-progress-arm.service`` unit is the single authoritative
writer.

What survives here is the boot-id surface only:

* :func:`readCurrentBootId` -- read the Linux kernel boot id from
  ``/proc/sys/kernel/random/boot_id`` and normalize it.
* :func:`_normalizeBootId` -- the dashless-lowercase normalizer that
  gives a stable equality key across kernel/journald boot-id forms.
* :data:`BOOT_ID_PATH` -- the kernel surface path constant.

These are consumed by :func:`src.pi.diagnostics.boot_progress.readBootId`
(and, transitively, the orchestrator + shutdown_handler that reuse it).
"""

from __future__ import annotations

import logging

__all__ = [
    'BOOT_ID_PATH',
    'readCurrentBootId',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

#: Linux kernel boot id surface.  32 hex characters with dashes (UUID form).
BOOT_ID_PATH = '/proc/sys/kernel/random/boot_id'


# ================================================================================
# Boot-id Surface
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


# ================================================================================
# Pure Helpers
# ================================================================================

def _normalizeBootId(raw: str) -> str:
    """Lowercase + strip whitespace + strip dashes.

    The kernel ``/proc/sys/kernel/random/boot_id`` surface returns the
    dashed UUID form; journald historically rendered either the 32-char
    dashless hex (older systemd) or the dashed form (systemd 250+).
    Normalizing to dashless lowercase gives a stable equality key across
    every surface that exposes the boot id.
    """
    return raw.strip().lower().replace('-', '')
