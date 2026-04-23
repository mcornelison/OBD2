# Sprint 16 Release Readiness — Spool's Pre-Deploy Tuning Review

**Date:** 2026-04-22
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Routine — informational, pre-deploy

## Summary

Paper review of Sprint 16 stories that touch my domain (simulate removal, BT resilience, data_source taxonomy, battery_health_log, post-drive review ritual). **Grade: GREEN on 4 of 5, YELLOW on 1 (US-211).** Nothing blocks deploy. Two minor suggestions filed below for follow-up stories.

Live validation (key-on/off, engine-on/off) deferred to tomorrow per CIO.

## Per-story grades

### US-210 Pi collector hotfix — GREEN

Matches CIO Session 6 directive 1 exactly.

- `eclipse-obd.service`: `--simulate` removed from ExecStart ✓, `Restart=always` + `RestartSec=5` ✓, `StartLimitBurst=10` over `StartLimitIntervalSec=300` ✓ (10 flaps/5min cap before systemd quarantines)
- US-192 DISPLAY/XAUTHORITY/SDL_VIDEODRIVER env preserved ✓
- `rfcomm-bind.service` untouched ✓
- `journald-persistent.conf` drop-in with `Storage=persistent`, content-compare idempotent install ✓
- `SIMULATE MODE -- NOT FOR PRODUCTION` stdout sentinel + test lock ✓ (catches accidental manual --simulate runs in journalctl output)

Verified `deploy/eclipse-obd.service` post-US-210 state directly during power audit. Matches Ralph's claim.

### US-211 BT-resilient collector — YELLOW (2 minor concerns)

Three-bucket classifier (ADAPTER_UNREACHABLE / ECU_SILENT / FATAL), reset-on-success, canonical event_types — all shipped correctly. But:

**Concern 1 — integration gap (more important):** Ralph's note §"What I did NOT do" flags that `BtResilienceMixin.handleCaptureError` is **not yet wired into the actual capture loop**. The classifier and reconnect loop exist and are tested; no code calls them. This means:
- US-208's "no rows" failure mode may still bite us on BT flap during a real drive
- The US-210 `Restart=always` is still doing all the resilience work today
- The downstream unblock claims in Ralph's note ("US-208 can now validate", "continuous capture") are **aspirational until the integration wiring lands**

Recommend: file a follow-on story (S, high priority) to wire `handleCaptureError()` into `data_logger.py`'s capture loop before the next live drive attempt. Otherwise tomorrow's key-on/off tests won't actually exercise the resilience path.

**Concern 2 — backoff spec drift (minor):** My Session 6 spec said `1/5/30/60s cap` (4 steps). Ralph shipped `(1, 5, 10, 30, 60)` — 5 steps with an added 10s intermediate. Gentler ramp, functionally fine, but spec drift worth noting per `feedback_spool_spec_discipline.md` (DO NOT CHANGE markers). Going forward, I'll add the marker when spec values are load-bearing; Ralph's addition here was a judgment call on a value I didn't flag as locked.

Neither blocks deploy. Flagging Concern 1 because it affects tomorrow's drill expectations.

### US-212 data_source hygiene — GREEN

Every seed-script INSERT tagged explicitly. `real/replay/physics_sim/fixture` enum preserved on the CHECK constraint. DEFAULT stays `'real'` as a narrow safety net for the live-OBD writer only. The AST audit test (`TestSeedScriptHygiene`) catches regressions at PR time — that's the right enforcement mechanism. Simulator's class-level `isSimulated=True` sentinel on `SimulatedObdConnection` is a clean auto-derivation hook.

Follow-up mentioned by Ralph (connection_log writers still use DEFAULT `'real'` and could misfire if someone runs --simulate with a real BT adapter attached) is real but low-risk — production service no longer runs `--simulate` so this is a developer-laptop-only concern. Defer unless we see it bite.

### US-217 battery_health_log schema — GREEN (with 1 small UX suggestion)

Schema matches my Session 6 grounding refs exactly:
- `drain_event_id` PK, `start_timestamp` / `end_timestamp` ISO-8601 UTC ✓
- `start_soc` / `end_soc` 0–100, `runtime_seconds` computed at close ✓
- `ambient_temp_c` (Celsius, matches canonical units) ✓
- `load_class` CHECK enum `production/test/sim` ✓
- `data_source` column present and constrained ✓
- Close-once idempotent semantic on `endDrainEvent` ✓ (correct for US-216 crash-safety)

**Suggestion:** `scripts/record_drain_test.py` defaults `--load-class` to `production`. This is backwards for the CLI's actual use case:
- Manual CLI invocation is almost always a CIO-driven scheduled drill → `test`
- `production` rows should come from US-216's orchestrator auto-writing them on real power loss, not from a human typing a command

Recommend flipping CLI default to `test` so the CIO doesn't accidentally pollute the production-baseline series by forgetting the flag during monthly drills. S-size follow-up, or roll into US-216.

### US-219 drive review ritual — GREEN

Exactly the wiring job I scoped. No new analytics, no new prompt content, no new thresholds:
- `system_message.txt` + `user_message.jinja` untouched ✓
- `drive-review-checklist.md` passed through with `cat` ✓
- Shares `_buildAnalyticsContext()` with auto-analysis endpoint → byte-identical prompts ✓ (no drift between manual and auto review paths)
- Ollama config sourced from `config.json`, not hardcoded ✓
- Graceful degradation (empty DB, Ollama down, empty recommendations) all exit 0 so Steps 3+4 always emit ✓

One follow-up CIO should be aware of: the `--drive-id latest` path depends on `drive_summary` having rows. Until US-214's dual-writer reconciliation settles + a real drive lands, `latest` may be ambiguous. Not a bug, just a calibration note for tomorrow's drills.

## What I checked but isn't in my lane

Didn't review:
- US-213 migration gate (infra/deploy — Ralph+Marcus lane)
- US-214 US-206 dual-writer reconciliation (code architecture — Ralph's lane, though I'd read any tuning-value impact)
- US-215 TD audit (PM lane)
- US-218 I-017 specs↔agent.md dedup (PM/docs lane)

If any of those touched tuning-domain values (thresholds, PID handling, drive detection, alert logic), flag and I'll loop back.

## Deploy posture from the tuning seat

Given US-211's integration gap, the FIRST real-drive test after deploy will stress the US-210 `Restart=always` path, not the BT-resilience path. That's acceptable — it's what we'd run today anyway — but expect the systemd-level process-bounce signature in the journal, not the in-process recovery signature US-211 ultimately promises. Save the latter for after the wiring story lands.

Tomorrow's key-on/off, engine-on/off tests should focus on:
1. Does the collector actually capture rows during the connected window (post-US-210 real mode)?
2. Do we see `data_source='real'` tagged on those rows (post-US-212)?
3. Does the drive_id lifecycle behave across KEY_OFF/KEY_ON boundaries?

BT-flap resilience should NOT be the focus until the US-211 integration lands — otherwise we'll be testing a code path that isn't yet connected.

## Filed follow-ups (Sprint 17 candidates)

1. **US-211 integration wiring** — wire `handleCaptureError()` into `data_logger.py` capture loop. S, high priority before next real drive. **Concern 1 above.**
2. **record_drain_test CLI default flip** — `--load-class test` default. S, low priority.
3. **connection_log DEFAULT hardening** — tag explicit per-writer. S, defer unless it bites.

## Bottom line

5 stories reviewed, 4 green, 1 yellow (integration gap, not a defect). No reason to hold the deploy on tuning grounds. Flag US-211's integration gap to Ralph before live drills, and the drills will produce clean data.

— Spool
