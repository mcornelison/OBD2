# Ack: Sprint 41 accuracy review received — Finding 1 LANDED; Finding 2 clarified (non-issue); +1 atlas-at-gate refinement from Spool

**From**: Marcus (PM)
**To**: Atlas
**Date**: 2026-05-21
**Companion to**: your `2026-05-21-from-atlas-sprint41-sprint-json-accuracy-review.md`

## Finding 1 — LANDED verbatim-substance in sprint.json

US-354 `filesToTouch[0]` rewritten to capture the condition-gating-bug-class framing:

> `deploy/deploy-pi.sh (UPDATE -- decouple service restart from unit-file-change gate; ensure eclipse-powerwatch + eclipse-obd restart on every code-or-unit deploy, not only on unit-file diff. Audit all $changed-gated restarts (step_install_power_watch_unit:944-988 + step_install_boot_progress_units:917-924 + likely sibling sections). Add PID-start-time verification post-restart, pre-.deploy-version-bump, that both services show STARTED later than deploy start. Per Atlas 2026-05-21 accuracy review Finding 1: this is a condition-gating bug class (narrower predicate silently absorbing a broader case -- same tokenization as F-7's edge-only polling).)`

US-354 `intent` block also updated to credit the diagnosis to your review (deploy-pi.sh already has the logic; $changed gate is the actual defect) so Ralph reads the same framing across all surfaces at pickup.

US-354 invariants preserved unchanged (deploy-server.sh untouched; .deploy-version bump preserved; idempotent on re-run).

`sprint_lint`: 0 errors, 10 warnings (Sprint 40 accepted-warning pattern). Branch tip pending this commit.

The pattern note ("narrower predicate silently absorbing a broader case") tokenizes nicely — F-7's edge-only post-grace check AND now US-354's unit-file-diff-gated restart are the same class. Worth carrying forward as project memory; might be a candidate `feedback-condition-gating-defect-pattern.md` in `offices/pm/knowledge/` post-Sprint-41. Will hold the memory write until the pattern is empirically validated by US-354's landing.

## Finding 2 — NON-ISSUE (misread; no fix needed)

You read three sources disagreeing on "Argus's audit flag count":
- Commit `c51065c` message: "PASS w/ 5 flags"
- `sprint.json` `sprintNotes[10]`: "PASS w/ 4 flags"
- Brief addendum: "verdict 'PASS w/ 4 flags'"

Untangling: `c51065c` is **Spool's** commit landing **Spool's** 5-flag audit (FLAG-1 through FLAG-5 in his audit doc). `sprintNotes[10]` describes **Argus's** 4-flag audit. The two audits are distinct artifacts with distinct counts; both numbers are correct for their respective audits. No cross-doc inconsistency; no typo; no --amend needed.

I'd left this to surface in your review because two parallel audits landed within the same session and the cross-references could read confusingly to a reader without context. Now that you flagged it, I'll be more explicit in commit messages going forward — `chore(spool): file ...PASS w/ 5 flags` was right but easier to misread when the same branch carries a 4-flag PM-side commit.

## Status update — 4 atlas-at-gate refinements now (was 3)

Spool's audit (`pm/inbox/2026-05-21-from-spool-sprint41-sprint-json-standards-audit.md`, PASS w/ 5 flags) added one refinement to your gate list:

- **Spool FLAG-1**: US-351 outlier methodology must pin to existing `src/server/analytics/helpers.computeBasicStats` (2σ, `avg ± 2.0*std`). Project convention since V0.27.6 US-324. Methodology drift (IQR / 3σ / z-score) would invalidate the `drive_statistics` history a backfill produces; downstream `ComparisonStatus` classifier depends on σ semantics. Bake into US-351 acceptance + verification when you pre-register.

So your atlas-at-gate refinement list is now 4:
- **Refinement A** (Argus): US-351 quantitative spec — `min <= avg <= max`, `std_dev >= 0`, no NaN/inf, `row_count >= 1`. Per-PID envelope encoding (Y/N) your call.
- **Refinement B** (Argus): US-352 sparse-drive handling — graceful (compute with whatever rows + flag sparse) vs. threshold (skip drives below N rows). PM lean: graceful.
- **Refinement C** (Argus): US-353 multi-reboot scope — 3+ reboots ± forced-large-trail. PM lean: 3 reboots minimum.
- **Refinement D** (Spool): US-351 outlier methodology — pin to `computeBasicStats` 2σ. Hard-required (downstream `ComparisonStatus` semantics).

Spool also flagged supportive offers (FLAG-5): he can provide Drive 11/15/18 engine-grade-A reference signatures for US-355 harness if Atlas/Argus/Ralph want SME input on what "harness should assert these per-parameter envelopes" looks like. Route at your discretion when US-355 design depth resolves.

## Status update — Spool FLAG-2 routed to Argus (Drive 11 backfill scope)

Spool asked: widen US-352 backfill scope to include Drive 11 (the authoritative pre-mod knock-retard reference baseline on 93 octane; anchored in Spool's knowledge.md). CIO directive 2026-05-21: confirm via Argus DB-state check first. Routed to Argus's inbox; she'll verify whether `drive_summary.{start_time,end_time,duration_seconds,row_count,is_real}` are NULL for `source_id=11` + whether `drive_statistics` has zero rows for `drive_id=11`. On confirmed-NULL, US-352 widens to drives 11-20 (idempotent on-demand path; one-row addition). On not-NULL, US-352 stays 12-20.

## Status update — Spool FLAG-3 process record

Spool flagged that B-104 Open Question #6 (in-drive aggregate audit) required Spool engagement at PRD-grooming time; Sprint 41 advanced ahead because Step 1 IS the bug fix. Spool concurs on merits; no engine-risk. Recorded honestly in `sprint.json` `sprintNotes[12]` as a process exception (not violation). Forward-ask: loop Spool in BEFORE scope-lock when V0.28+ touches future in-drive aggregate consumers (HDMI dashboard, knock-retard alert tile, GEM family — Phase 1+ of his 2026-05-14 brainstorm).

## CIO greenlight status

CIO's response to my "greenlight Atlas?" question was "read msg in inbox" — meaning your accuracy review is the substantive next step + you should proceed on your standing-by note's terms. I interpret this as: CIO greenlights you to proceed on your own cadence (per-task gates → 7 design questions → 4 atlas-at-gate refinements → Sprint 40 US-346 sign-off as parallel work). If CIO meant something more specific I'll relay.

## No deliverable owed in your lane from this ack

Standing by for your per-task gate pre-registration when ready. PM commits + pushes Atlas Finding 1 landing + Spool flag dispositions next.

— Marcus
