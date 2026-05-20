---
name: PM bumps deploy/RELEASE_VERSION as part of every sprint closeout
description: At sprint close (after Ralph commits + before/with merge to main), PM bumps deploy/RELEASE_VERSION per SemVer V<major>.<minor>.<patch>. New functionality -> minor; bug fixes only -> patch. Pre-stable until V1.0.0 (CIO drain-test gates).
type: feedback
originSessionId: c18b7094-bf20-456a-a0e5-9bcc3073010d
---
CIO directive 2026-04-30 at Sprint 19 close: "remember to log the version info as part of the sprint closeout process".

**Rule:** at every sprint close, PM:

1. Reads `deploy/RELEASE_VERSION` for the prior version string
2. Decides bump kind based on what shipped:
   - **major** (V1.x.0 -> V2.0.0): backwards-incompatible architecture change. Won't happen often pre-V1.0.
   - **minor** (V0.18.0 -> V0.19.0): new functionality, backward-compat (new tables, new orchestrator behaviors, new CLIs, new sub-systems). MOST sprints will be minor bumps.
   - **patch** (V0.18.0 -> V0.18.1): pure bug fixes, no new tables/CLIs/behaviors. Fix-only sprints land here.
3. Writes the new version string + a one-line description (max 400 chars per `DESCRIPTION_MAX_LEN` in `scripts/version_helpers.py`) to `deploy/RELEASE_VERSION`
4. Commits as `chore(release): bump V<old> -> V<new> (Sprint NN close)` with a 2-3 line body summarizing reasons
5. Pushes the commit (typically straight to main as part of sprint-close merge sequence; or on the sprint branch if not yet merged)

**Why:** the deploy scripts (`deploy-pi.sh`, `deploy-server.sh`) read this file at deploy time and stamp the current version into each tier's `.deploy-version` file (with fresh UTC timestamp + git hash). Without a version bump, post-sprint deploys would advertise the old version on the new code — confusing for ops debugging.

**How to apply:** sprint-close protocol becomes:
1. Commit Ralph's work on sprint branch
2. Push sprint branch
3. Merge sprint branch -> main (PM-owned per `feedback_ralph_no_git_commands.md`)
4. **Bump `deploy/RELEASE_VERSION` (this rule)**
5. Commit version bump as separate `chore(release):` commit
6. Push main

**Pre-V1.0.0 stability rule (CIO 2026-04-29):** stay pre-stable until "a few more drain tests" pass cleanly. V1.0.0 is reserved for the moment US-216 staged shutdown actually fires in production AND drive_summary metadata reliably populates AND power_log writes are wired. Until then, every sprint stays in V0.x.

**Bump kind decision examples (calibrate from):**
- Sprint 18 (Ops-Hardening 8/8: sync restore, truncate, drive_summary fix, ELM_VOLTAGE filter, journald, server systemd, SIGTERM, orphan backfill) → would have been V0.17.0 → V0.18.0 (minor — new behaviors)
- Sprint 19 (Runtime Fixes 8/8: SOC->VCELL, BATTERY-detection rebuild, defer-INSERT, v0004 migration, v0005 dtc_log, connection_log path-b investigation, orphan backfill script, versioning system) → V0.18.0 → V0.19.0 (minor — new migrations + new versioning subsystem)
- Hypothetical sprint that ONLY fixes bugs (no new tables, no new orchestrator behaviors) → V0.X.0 → V0.X.1 (patch)

**Important:** do NOT bump version in the Ralph-execution commit. Version bump is a SEPARATE PM commit with its own message, post-merge-to-main. Keeps the version-history grep-able.
