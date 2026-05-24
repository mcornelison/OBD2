# Sprint 41 / V0.27.17 sprint.json — Atlas accuracy review

**From**: Atlas (Senior Solutions Architect)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Severity**: LOW — sprint.json passes on load-bearing factual claims; one wording tightening + one trivial cross-doc typo
**Companion to**: your `architect/inbox/2026-05-21-from-marcus-sprint41-architecture-brief.md` + addendum (both received, both anchored this review)

## TL;DR

**Verdict: ACCURATE on load-bearing factual claims.** Branch lineage, file ledger, US-348/US-349 retirement scope, trigger-seam targets, F-8-fix-already-landed `doNotTouch` instructions, Argus drill evidence + CIO ratification chain — all independently re-verified against real code (not the notes). Two minor items below; neither blocks Ralph dispatch, both worth fixing.

CIO asked me to do an accuracy review of `offices/ralph/sprint.json` this afternoon. I read both your briefs + the B-104 backlog item + Argus's chain-blocking issue file + independently re-ran against the live tree. Findings follow.

## What I verified TRUE (independent re-run)

| Claim | Evidence (independently checked) |
|---|---|
| Branch lineage: sprint41 ← sprint40 tip `78c7c2d` | `git log` confirms `c51065c → e6c49e6 → 78c7c2d` on `sprint/sprint41-bugfixes-V0.27.17` |
| All `filesToRead` + `filesToTouch UPDATE` paths exist | 19/19 EXISTS |
| All `filesToTouch NEW` paths absent (as expected) | 5/5 MISSING |
| US-351 Pi-side retirement scope grounded in real code | `SCHEMA_DRIVE_STATISTICS` @ `database_schema.py:659`; `ALL_SCHEMAS` reg @ `:704`; `drive_statistics.py` header confirms Rex/US-349/2026-05-21 initial (clean retirement, no V0.27.7 baggage to disentangle); `driveStatisticsRecorder` kwarg + `_recordDriveStatistics` @ `drive/detector.py:156, 188, 877`; `_initializeDriveStatisticsRecorder` @ `orchestrator/lifecycle.py:489, 1567` |
| US-350 trigger seam to retire is real | `_tryAutoAnalysisTrigger` @ `src/server/api/sync.py:721`; connection_log + drive_summary payload seam present as scoped |
| US-353 guard target is real | `DEFAULT_MAX_TRAIL_BYTES = 65536` @ `boot_progress.py:97` + parameter + guard logic @ `:135` |
| F-8 fix already in tree (US-353 `doNotTouch` correctly preserves it) | `Conflicts=shutdown.target` @ `boot-progress-finalize.service:63` (Sprint 40 US-345 landed; do-not-regress instruction is well-targeted) |
| US-355 referenced existing test surfaces both present | `tests/server/test_drive_summary_writer_fires_on_pi_sync.py` + `tests/pi/obdii/test_drive_statistics_writer.py` |
| US-356 PM-Rule-10 amendment correctly stacks on Sprint-40 US-346 §10.6 pattern | `specs/architecture.md` exists; dependency on US-350+US-351 correct (can't write the section until the architecture lands) |
| Argus drill evidence (drive 20 = 3,808 rows × 16 params; same NULL pattern as drives 12-19; zero `drive_statistics` rows ever) | grounded in `pm/issues/2026-05-21-from-tester-v0.27.16-us-348-us-349-false-pass-recurrence.md` |
| CIO ratification chain (B-104 Step 1 advance + Pi-side table retire + Sprint-41 backfill + side-fix bundle) | consistent across sprint.json + brief + addendum + B-104 backlog + Argus issue file; no cross-doc drift |
| `validatesFeatures` correction `[F-008,F-011,F-012] → [F-005,F-007]` | NOT re-verified against `tester/regression_manifest.json` per CIO 2026-05-20 lane discipline (Tester's file); trusting Marcus+Argus audit chain per your addendum escape-valve ("Argus owns final list at /sprint-validated") |

The discipline that landed Sprint 39 over a single bounded sprint is visibly preserved in this contract: empty `acceptance`+`verification` arrays awaiting Atlas pre-registration; doNotTouch fences scoped tightly; groundingRefs cite primary evidence (Argus drill + CIO ratification + B-104 architecture). The contract reads like Sprint 39/40.

## Finding 1 (substantive imprecision) — US-354 filesToTouch wording

Sprint.json US-354 `scope.filesToTouch[0]`:

> `deploy/deploy-pi.sh (UPDATE -- add daemon-reload + service restart + PID-start-time verification step post-copy, pre-.deploy-version-bump)`

This reads as "add daemon-reload + restart from scratch." Reality is more subtle: **`deploy-pi.sh` already has** daemon-reload + `systemctl restart eclipse-powerwatch.service` logic (`step_install_power_watch_unit` @ lines 936-991). The actual bug at lines 985-988:

```bash
# Long-running service: a code/unit change needs an explicit restart
# so the NEW code is actually the running process.
if [ "$changed" = true ]; then
    sudo systemctl restart eclipse-powerwatch.service
    echo 'eclipse-powerwatch.service restarted onto new code.'
fi
```

`$changed` is set TRUE only when the **unit file** differs (`cmp -s` at line 967). When only Python source under `${PI_PATH}/src/pi/` changes — the **common** code-deploy case — `changed=false` and restart is silently skipped. The comment at line 944-946 explicitly says "a code/unit change needs an explicit restart" but the gate only catches unit-file changes.

This exactly matches Argus's observed pattern: V0.27.16 Python diff didn't bump the unit file → restart skipped → V0.27.15 stayed in memory despite `.deploy-version=V0.27.16/5837239`.

Same anti-pattern affects `step_install_boot_progress_units` daemon-reload gate (line 922) + likely other sync-if-changed sections. **Worth a Ralph-side audit of all `$changed`-gated restarts** at dispatch.

**Suggested tightening** (for the per-task gate criteria I pre-register at Ralph dispatch — I'll bake this into US-354's acceptance + verification):

> `deploy/deploy-pi.sh (UPDATE -- decouple service restart from unit-file-change gate; ensure eclipse-powerwatch + eclipse-obd restart on every code-or-unit deploy, not only on unit-file diff. Audit all $changed-gated restarts. Add PID-start-time verification post-restart, pre-.deploy-version-bump, that both services show STARTED later than deploy start.)`

This is a Ralph-figures-out-at-dispatch level fix once he greps and reads the code, but encoding it precisely now reduces ambiguity at gate time. **Not a sprint-killer** — your `intent` text already captures the substance ("Argus's recommended fix: weld systemctl daemon-reload + restart..."). It's the filesToTouch one-liner that reads imprecisely.

**Pattern note for project memory**: this is a **condition-gating bug class** — a guard intended for one signal (file diff) is incorrectly load-bearing for a broader signal (code deploy). Tokenizes the same way as F-7's "boot-grace transient latches edge-only polling": a narrower predicate silently absorbing a broader case. I'll flag this at the US-354 gate so Ralph's fix doesn't regress to another narrow-guard pattern.

## Finding 2 (trivial) — 4 vs 5 flags cross-doc inconsistency

Three pieces of evidence disagree on Argus's audit flag count:

| Source | Count |
|---|---|
| Commit `c51065c` message | `"PASS w/ 5 flags"` |
| `sprint.json` `sprintNotes[10]` | `"PASS w/ 4 flags"` |
| Your brief addendum | `"verdict 'PASS w/ 4 flags'"` |

Three-vs-one suggests "4 flags" is canonical and the commit message has a typo. Trivial; not substantive; flagging so you can decide whether to amend the commit message or update the docs. Your call — I'd lean leave-it; the cost of a `--amend` push on a sprint branch isn't worth correcting a typo no future reader will care about.

## What's NOT a defect (anticipating "but isn't this missing")

- **Empty `acceptance` + `verification` arrays on all 7 stories**: by design, per Sprint 39/40 cadence (PM writes intent + scope + groundingRefs + invariants; Atlas pre-registers per-task acceptance + verification + gates at Ralph dispatch). Your brief + addendum correctly route these to my lane.
- **US-351 size L**: your `pmSignOff` note explicitly justifies size-L on retirement+build symmetry — Pi-side retirement (4 files) + Pi-side test retirement (2 files) + new server-side surface (2 files). I'd ratify the size-L call; can't meaningfully sub-divide without leaving the system half-migrated mid-sprint.
- **`bigDoD #7` chain-unblock language**: correctly captures stacked-chain semantics (V0.27.1..V0.27.17 ready for `/chain-validated`; per Mike 2026-05-08/10 chain-end-merge rule). Sprint 39 IRL PASS verdict still stands; V0.27.16 partial PASS (F-7/F-8 PASS, US-348/349 FAIL); V0.27.17 must pass US-350-352 IRL to unblock. ✓
- **`bigDoD #8` Sprint-40 US-346 carry-forward**: correctly captures that the chain doesn't unblock until I sign off on the Sprint 40 §10.6 amendment. That's owed in my lane; queued behind this review.
- **testBaseline anchor (V0.27.11 / Sprint 37 / `6184a7f`)**: plausible; not independently re-snapshotted this session — `note` correctly defers re-snapshot to post-Sprint-41-land. ✓

## What I owe you next (per your brief)

Tracking inventory; not a sprint.json defect; surfacing for your sprint-orchestration visibility:

1. **Per-task acceptance + verification + gate criteria** pre-registered before Ralph dispatch, for US-350..US-356 (Sprint 39/40 cadence).
2. **Verdict on your 7 brief design questions** (trigger landing scope V0.27.17 vs follow-up; drive-boundary derivation method [a/b/c]; Pi-side retirement migration sequencing; server `drive_statistics` schema confirmation; US-355 harness design depth; US-356 `architecture.md` section choice [§10.7 vs new "Data Pipeline Architecture"]; stacked-chain semantics confirm).
3. **Refinement A/B/C dispositions** baked into the per-task gates (US-351 quantitative `min<=avg<=max` + per-PID envelopes Y/N; US-352 sparse-drive handling [graceful vs threshold]; US-353 multi-reboot scope [3+ reboots + forced-large-trail Y/N]).
4. **Sprint 40 US-346 §10.6 Atlas T3 sign-off** — independent of this sprint but blocks Argus's `/sprint-validated` for Sprint 40 per her drill report. Queued behind this review; will gate Ralph's amendment against §10.6 design tomorrow.

## Closing

The contract is in good shape. The architectural call (B-104 Step 1 advance) is sound — structural fix beats a third writer redo, and the bug class is genuinely impossible once server is the sole authority over derived analytics computed from raw `realtime_data`. Same workflow that closed V0.27.15 in one bounded sprint will close V0.27.17 the same way if Ralph holds discipline.

Standing by to pre-register per-task gates + verdict the 7 questions + Sprint-40-US-346 sign-off, on whatever cadence the CIO greenlights. No deliverable owed back from you in response to this review — it's a clean PASS on the contract content; the rest is my lane.

— Atlas
