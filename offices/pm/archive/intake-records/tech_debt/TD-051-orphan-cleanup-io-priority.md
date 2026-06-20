# TD-051: orphan-cleanup.service runs unthrottled at boot, contending with the orchestrator

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | infrastructure            |
| Affected     | `deploy/orphan-cleanup.service`, `deploy/orphan-cleanup.timer` (V0.27.6 US-322 / B-072) |
| Introduced   | V0.27.6 / Sprint 32 US-322 -- the `Persistent=true` timer fires at boot to catch up the missed nightly 03:00 run; the service has `MemoryMax=128M` + `CPUQuota=20%` but no I/O throttle |
| Created      | 2026-05-12 (during US-330 / I-030) |

## Description

`orphan-cleanup.timer` has `Persistent=true` and `OnCalendar=*-*-* 03:00:00`,
so on a Pi that's powered off overnight (the normal key-off case) the missed
03:00 fire is caught up **at boot** -- `orphan-cleanup.service` runs its
`cleanup_orphan_realtime_data.py --execute` DELETE against `data/obd.db` on
the SD card while `eclipse-obd.service` is concurrently launching the
orchestrator. The service caps RAM (`MemoryMax=128M`) and CPU
(`CPUQuota=20%`) but does **not** lower its I/O priority, so the DELETE can
saturate the SD card's I/O bandwidth.

This is the leading suspect for I-030: the orchestrator's
`_recordStartupLog` -> `recordBootReason` runs early in `_initializeAllComponents`
(right after `_initializeDatabase`), and its first action is a
`journalctl --list-boots` subprocess. Under SD-card I/O starvation that
subprocess can exceed its 10 s timeout, `runJournalctl` returns `None`, and
(pre-US-330) `detectBootReason` immediately gave up and wrote a `startup_log`
row with NULL `prior_boot_clean` / `prior_last_entry_ts` -- the exact symptom
the PM observed on the V0.27.6 post-Drain-17 boot.

## Why It Was Accepted

US-330's `scope.filesToTouch` is `src/pi/diagnostics/boot_reason.py` + the new
test; `deploy/orphan-cleanup.service` is out of scope, and the story's
`doNotTouch` explicitly says not to touch the orphan-cleanup unit unless
"Hypothesis A confirmed AND fix requires unit reordering". The chosen fix is
the in-scope "race-guard" path (US-330 makes `detectBootReason` retry the
`--list-boots` lookup so a transient storm doesn't strand the row), which is
sufficient on its own. This TD records the complementary infrastructure-side
hardening for whoever next touches the deploy units.

## Risk If Not Addressed

Low. The US-330 race-guard already absorbs the symptom. Residual risk: the
boot-time orphan-cleanup DELETE can still slow *other* startup work (OBD
connect, DriveDetector spin-up) on the Pi 5's SD card for a few seconds on
boots that follow an overnight power-off. Likelihood: every cold boot where
a nightly 03:00 fire was missed. Impact: a few seconds of extra startup
latency; no data loss.

## Remediation Plan

In `deploy/orphan-cleanup.service`, add `IOSchedulingClass=idle` (and/or
`Nice=10`) so the catch-up DELETE yields the SD card to the orchestrator,
and/or add `After=eclipse-obd.service` to the `[Unit]` section so the cleanup
runs only once the orchestrator has finished its startup I/O. ~2-4 lines in
the unit file + a `bash -n` sanity check; install path is already idempotent
(`step_install_orphan_cleanup_unit` in `deploy/deploy-pi.sh` is
sync-if-changed + daemon-reload-on-change). Bundle into the next deploy/infra
touch; no B- item filed -- US-330's race-guard makes this non-urgent.
