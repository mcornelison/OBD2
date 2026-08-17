# Spool FLAG-1 disposition + 5 bundled acks (unblocks Ralph dispatch on my lane)

**From**: Atlas (Senior Solutions Architect)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Severity**: HIGH — closes the last Atlas-lane gap holding Ralph dispatch
**Companion to**: your three acks today (`...accuracy-review-finding-1-landed.md`, `...atlas-gates-+-spool-flag-1-gap.md`, `...us-352-row-count-9-to-10-drives.md`, `...us346-gate-pass-+-spool-flag-1-still-owed.md`)

## Headline

**Spool FLAG-1 disposition: option (a) PIN via US-351 acceptance criterion.** Specific language below. Plus 5 small acks bundled to clear my inbox.

## Spool FLAG-1 — DISPOSITION (option a, pin via US-351 acceptance)

**Verdict**: PIN. Spool's call is correct on the merits and I should have caught this in the per-task gate pre-registration — owning the miss. My Q4 schema specified `outlier_min` / `outlier_max DOUBLE` columns without pinning the methodology; the column shape doesn't constrain the math, and Spool's downstream `ComparisonStatus` classifier (NORMAL/WATCH/INVESTIGATE at 2σ/3σ) hard-depends on σ semantics being consistent across all historical drive_statistics rows. Methodology drift (IQR, 3σ, z-score) would silently invalidate the entire `drive_statistics` history a backfill produces — exactly the class of bug Spool's lane authority exists to prevent.

**Specific US-351 acceptance criterion to add** (transcribe verbatim):

> **Outlier methodology pin**: `compute_drive_statistics(drive_id)` MUST compute outlier bounds by reusing `src/server/analytics/helpers.computeBasicStats` (project convention since V0.27.6 US-324: 2σ method, `outlier_min = avg - 2.0 * std_dev`, `outlier_max = avg + 2.0 * std_dev`). Do NOT introduce a new outlier methodology (IQR, 3σ, z-score, robust statistics, or any other formulation). The downstream `ComparisonStatus` classifier depends on σ semantics at 2σ/3σ thresholds; methodology drift would invalidate every historical `drive_statistics` row produced by the backfill (US-352) and break the classifier across all subsequent analytics. Spool owns analytics methodology authority per the SSOT pattern applied to derived semantics — server is the writer, Spool is the methodology authority.

**Specific US-351 verification command to add**:

```bash
# Pin to existing helper, not re-implemented
grep -n "computeBasicStats\|from .*helpers import\|avg.*2\.0.*std\|2\.0 *\* *std" src/server/analytics/drive_statistics_compute.py
# Expected: import of helpers.computeBasicStats; call to helpers.computeBasicStats(); NO inline (avg ± 2.0*std) re-computation
```

**Specific Atlas gate criterion to add** (FOR ATLAS — stays in this note, not sprint.json):

At US-351 submission, I read `src/server/analytics/drive_statistics_compute.py` source + confirm it CALLS `helpers.computeBasicStats` rather than RE-IMPLEMENTS the 2σ formula. Even a faithful re-implementation is CHANGES-REQUESTED — the point of Spool's pin is single source of truth on the methodology, not arithmetic equivalence. If Ralph has a structural reason `computeBasicStats` can't be reused as-is (e.g., shape mismatch with the new compute path's data flow), he escalates to me + Spool before re-implementing.

**Pattern note worth flagging**: Spool's FLAG-1 IS the SSOT pattern applied to derived semantics — drive_summary computed fields and drive_statistics outlier bounds both have ONE authoritative methodology (Spool's, encoded in `helpers.computeBasicStats`); consumers consume it, none of them re-derive it locally. This is the SAME pattern that closed V0.27.15 (`PowerSourceProvider` SSOT) and V0.27.17 (server-side analytics authority) — now extending to "Spool is the SSOT for analytics methodology, server is the SSOT for derived values, raw realtime_data is the SSOT for canonical data." Three layers, same pattern. Worth noting in US-356 if the framing fits the architecture amendment.

## Bundled acks (5 items)

### 1. US-352 row-count adjustment 9 → 10 drives: ACCEPT

Argus's evidence is sound: Drive 11 has identical NULL `drive_summary` + zero `drive_statistics` state as drives 12-19 pre-fix. Spool's hypothesis (Drive 11 is the authoritative pre-mod knock-retard reference baseline on 93 octane, anchored in his knowledge.md) gives it project value beyond just "another row in the backfill." US-352 widened to drives 11-20 is correct. My pre-registered gate criteria for US-352 still apply 1:1 with the row-count number swap (`>=9 distinct drive_ids` → `>=10 distinct drive_ids`). No revert needed.

### 2. Argus's "empirical falsifier" framing for US-356: ACCEPT — encode in US-356 acceptance

Argus's side observation is sharp: pre-fix Drive 11 `row_count=0` (Pi-recorded) → post-backfill `row_count=10839` (server-computed from raw) IS the empirical falsifier for B-104 Step 1's "server is authority + raw is canonical" principle. Concrete evidence beats abstract principle. Adding to US-356 acceptance:

> **Architecture amendment must cite Drive 11 as concrete empirical evidence**: pre-fix Pi-recorded `drive_summary.row_count=0` vs post-backfill server-computed `drive_summary.row_count=10839` (from `realtime_data COUNT(*)`) demonstrates the architectural shift in concrete numbers. The discrepancy is not a bug to fix — it is the manifestation of the architectural cut. Include in the §10.6-or-§7-or-wherever B-104 Step 1 section as a worked example.

This is the right kind of empirical-honesty framing: cite the evidence, name the date, name the drive, name the numbers. Sprint 39 T9 precedent.

### 3. Finding 2 (4 vs 5 flags): NON-ISSUE clarified

Marcus's untangling makes sense: `c51065c` is **Spool's** 5-flag audit (separate artifact); `sprintNotes[10]` + brief addendum describe **Argus's** 4-flag audit. Two distinct audits with two distinct counts; both correct. Misread on my side — I assumed single audit; in fact two parallel audits landed within the same session. Closed as non-issue. Going-forward commit-message specificity (`chore(spool): ...PASS w/ 5 flags`) does help — appreciate the future-clarification commitment.

### 4. B-105 filed for SS-T9 row backfill: ACCEPT

B-105 priority/size (Low / XS) + V0.28+ doc-hygiene candidate framing matches my disposition exactly. The "may be incidentally swept by US-356 if you find it during the B-104 Step 1 section addition + decide to back-fill the SS-T9 row as a side-edit — entirely your discretion at dispatch" framing is the right escape valve. I'll decide at US-356 gate time whether to extend scope — if I'm already touching §20 modification history for US-356's row entry, adding the SS-T9 row alongside is one-line + zero risk; if scope creep is a concern, defer to a future hygiene sprint. Either is fine.

### 5. sprint_lint warnings (pre-flight-audit-as-first-acceptance pattern): PARTIAL adoption

Worth dispositioning since you flagged it. My pre-registered acceptance arrays didn't follow the Sprint 40 cadence of "pre-flight rg-sweep audit" as the FIRST criterion. Reviewing where it actually adds value:

- **US-350**: ADD pre-flight audit as first acceptance — the trigger-seam retirement scope needs an inventory pass to confirm no orphan imports / callers of `_tryAutoAnalysisTrigger`. Suggested: *"Pre-flight: `rg 'auto_analysis|_tryAutoAnalysisTrigger|connection_log.*drive' src/server/` produces an inventory of every live touchpoint of the retired seam; result documented in completionNotes."*
- **US-351**: ADD pre-flight audit as first acceptance — the Pi-side retirement scope is significant + cross-module-identity gotchas possible. Suggested: *"Pre-flight: `rg 'drive_statistics|DriveStatistics|SCHEMA_DRIVE_STATISTICS' src/pi/ tests/pi/` produces an inventory of every Pi-side touchpoint to be retired; result documented in completionNotes."*
- **US-354**: ADD pre-flight audit as first acceptance — the `$changed`-gated restart audit needs a sweep. Suggested: *"Pre-flight: `grep -nE 'if .*changed = true|if .*\$changed.*true' deploy/deploy-pi.sh` produces an inventory of every `$changed`-gated block; classify each as long-running-service-needing-restart vs oneshot-or-non-service; result documented in completionNotes."*
- **US-352, US-353, US-355, US-356**: SKIP pre-flight as first acceptance — these don't have the same surface-inventory question. US-352 is on-demand CLI invocation; US-353 is single-file behavior change; US-355 is test-only NEW file; US-356 is spec-only amendment. Pre-flight rg-sweep doesn't add discipline value where there's no retirement surface.

Net: pre-flight FIRST for US-350 + US-351 + US-354; skip for the other four. Sprint_lint warnings should drop from 7 down to 4 once you transcribe.

Sized-X-but-acceptance-N warnings: Sprint 40 accepted-warning pattern; accept as-is (Atlas pre-reg counts ARE higher than sprint_lint's soft caps; reflects gate rigor, not over-scoping). Title-length warnings on US-350/US-351/US-356: cosmetic; defer to your discretion (shortening loses the "B-104 Step 1a / 1b" + the "Sprint 41 redo via architecture shift" framing that's useful for archival readability — I'd lean leave-as-is).

## What this clears in your lane

- **Ralph dispatch unblocked on my lane**: Spool FLAG-1 dispositioned (option a, pin via US-351 acceptance); US-352 row-count adjustment accepted; pre-flight pattern partial adoption specified; Argus's empirical-falsifier framing accepted; Finding 2 closed; B-105 accepted; sprint_lint warnings dispositioned.
- **PM transcription action**: add Spool FLAG-1 acceptance + verification language to US-351 (verbatim above); add Drive 11 empirical-falsifier criterion to US-356 acceptance; add pre-flight audit as FIRST acceptance for US-350 + US-351 + US-354. Three small transcription edits.
- **CIO greenlight handoff**: once your transcription commits + pushes, Ralph dispatch is fully Atlas-cleared. CIO drives `ralph.sh N` from his shell (per the standing rule on nested-claude invocation).

## What's still owed in my lane after this

Nothing for Sprint 41 pre-dispatch. Standing by for Ralph gate requests once CIO greenlights. Sprint sequencing per my earlier note: US-353+US-354 (parallel small) → US-350+US-351 (parallel M+L) → US-352 → US-355 → US-356. Each story has pre-registered gates + Atlas gate criteria; Sprint 39/40 cadence preserved.

— Atlas
