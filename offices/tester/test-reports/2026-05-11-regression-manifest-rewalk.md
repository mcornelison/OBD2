# Test Report: Regression Manifest Re-Walk (F-001 … F-014)

**Date**: 2026-05-11
**Tester**: Tester agent
**Scope**: Walk every feature in `offices/pm/regression_manifest.json`, confirm or challenge its `lastValidated` claim against current evidence (live Pi/server inspection + DB queries this session).
**Result**: Manifest is broadly accurate. **3 power-management features (F-008, F-011, F-012) are under-rated** — they have fresher real evidence (Drain Test 16, 2026-05-10) than the manifest records (Drain 8, 2026-05-08); recommend bumping. F-005 stays REGRESSED (confirmed live). F-007 is technically working as a mechanism but the manifest's preferred validation (a post-fix drive round-trip) is still outstanding — leave null, refresh the wording. Everything else stands.

`pm_regression_status.py` summary as run today: **10 OK, 0 STALE, 4 NEVER** (F-005, F-007, F-013, F-014).

---

## Feature-by-feature

### F-001 — Pi boots + `eclipse-obd.service` active  →  **CONFIRMED (fresher evidence available)**
- Manifest: `lastValidated 2026-05-08` (deploy-pi.sh health check, V0.27.0), automatic, stale-threshold 7 d.
- Now: live this session — Pi up (`uptime` 3h38m, booted 2026-05-11 07:32 CDT), `systemctl show eclipse-obd.service` → `ActiveState=active SubState=running`, deployed version V0.27.5 (`bb744d1`). `startup_log` has a fresh row for the 07:27 CDT boot, `prior_boot_clean=1`.
- Verdict: **OK** — feature works; manifest could refresh `lastValidated` to 2026-05-11 (V0.27.5 deploy + observed running). Not stale either way.

### F-002 — OBD-II handshake when adapter+ECU available (engine on)  →  **STANDS (awaiting Drive 11 for re-confirm)**
- Manifest: `2026-05-08` (Drive 6 + Drive 7, 3 engine-on cycles), real_engine_on_test, stale-threshold 30 d.
- Now: can't re-test without an engine. Pi journal this session shows the OBD connect path *attempting* and failing as expected with the engine off (`device reports readiness to read but returned no data` — the ELM with no ECU). Connect machinery is alive (`connect_attempt` count climbing).
- Verdict: **OK** — 3 days old, not stale. Drive 11 re-confirms. No change.

### F-003 — RPM samples flow during engine-on  →  **STANDS (awaiting Drive 11)**
- Manifest: `2026-05-08` (Drive 6+7, 12,658 RPM samples).
- Now: Pi `realtime_data` retains the per-drive evidence — drives 6/7/8 = 7085/4222/8268 rows; no fresh engine-on since. (Drives 9/10 = 1095/572 rows — the brownout-degraded ones, held out of the baseline shelf.)
- Verdict: **OK** — not stale. Drive 11 re-confirms. No change.

### F-004 — `drive_start` fires (RPM > 500 for 10 s)  →  **STANDS (awaiting Drive 11)**
- Manifest: `2026-05-08` (drive_id=6 + drive_id=7 both fired).
- Now: `connection_log` has `drive_start`=9 / `drive_end`=8 events; `drive_counter.last_drive_id`=10 on the Pi. Detector hasn't fired since (no engine).
- Verdict: **OK** — not stale. Drive 11 re-confirms (and exercises the I-019/US-311 warm-restart path). No change.

### F-005 — `drive_summary` INSERT fires on `drive_end`  →  **STILL REGRESSED — confirmed live**
- Manifest: `lastValidated: null`, "REGRESSED 2026-05-08 (Drives 6+7 produced 0 drive_summary rows despite drive_end events). Targeted in V0.27.2."
- Now: Pi `drive_summary` has rows for `drive_id` **2, 3, 4, 5 only** — drives 6, 7, 8, 9, 10 are still missing despite their `drive_end` events. (And all 4 existing rows have `ambient_temp_at_start_c` / `starting_battery_v` / `barometric_kpa_at_start` = NULL — the 12-field metadata was never populated either.) Server-side `drive_summary` = the 3 stale ghost shells (id 12/13/14, NULL `drive_id`, `is_real=0`).
- The fixes (V0.27.2 US-304, V0.27.3 US-310 12-field) are **deployed on the Pi but have never been exercised by a real `drive_end`** — no clean drive since deploy. So the regression is unconfirmed-fixed.
- Verdict: **REGRESSED, accurately recorded.** Drive 11 is the test. If `drive_summary.drive_id=11` doesn't appear within ~30 s of `drive_end` with non-NULL metadata → the fix didn't hold → V0.27.7 bug-fix sprint. No manifest change; this is the headline item the chain merge waits on.

### F-006 — `realtime_data` accumulates during drive  →  **STANDS (and corroborated from data)**
- Manifest: `2026-05-08` (12,658 rows).
- Now: Pi `realtime_data` = 102,816 rows total; per-drive 6/7/8/9/10 = 7085/4222/8268/1095/572. (Plus 61,293 NULL-`drive_id` orphan rows — engine-off polling — Sprint 32 US-322 cleans these; they're noise, not poison.) Server `realtime_data` = 41,682 (drives 3-10 + ~2k recent NULLs).
- Verdict: **OK** — not stale; the data path is demonstrably accumulating. No change.

### F-007 — Sync to chi-srv-01 on home WiFi (delta push)  →  **MECHANISM WORKS; manifest's preferred validation still outstanding**
- Manifest: `lastValidated: null`, "NOT VALIDATED … re-validation requires next Drive N → home WiFi sync round-trip → assert chi-srv-01 received the delta + sync_history row written."
- Now (observed live):
  - Pi `sync_log.connection_log.last_synced_at = 2026-05-11T16:06:07Z` — i.e. the Pi **pushed a delta to the server during this session**. Server `sync_history` = 17,097 rows.
  - Server `realtime_data` holds drives 3-10 → those drives' realtime data **did** round-trip historically.
  - Server `battery_health_log` row 16 got its close via the **US-315 UPDATE-sync** path (`synced_at` 2026-05-10 19:47:17, `end_timestamp` 2026-05-10 20:00:46 — arrived as INSERT, updated later); Pi `sync_log.battery_health_log.last_synced_modified_at` is populated (dual-cursor live). Pi journal this session shows `FORENSIC sync_push_table_entry`/`_table_advance` lines firing.
- So the **delta-push feature itself is observably working right now.** What's *not* validated is (a) a fresh drive's data round-tripping post-V0.27.4, and (b) the V0.27.4 drive_summary-metadata + drive_counter UPDATE-sync fixes (US-314/US-315) on a real drive — and (b) is partly blocked upstream because F-005 means there's no drive_summary row to sync in the first place.
- Verdict: **Leave `lastValidated` null** (conservative, and the drive_summary side genuinely is unvalidated), **but recommend refreshing `validatedBy`** so it stops reading like the sync pipeline is dead. Suggested text below. Drive 11 closes it fully.

### F-008 — PowerDownOrchestrator fires staged shutdown (VCELL ladder)  →  **UNDER-RATED — fresher real evidence exists**
- Manifest: `2026-05-08` (in-vehicle Drain 8 — ladder fired warning→imminent→trigger→graceful poweroff), real_drain_test, stale-threshold 60 d.
- Now: **Drain Tests 11-16 all post-date Drain 8.** Pi `power_log` shows complete `stage_warning → stage_imminent → stage_trigger` cycles for the recent drains, e.g. Drain 16 (2026-05-10): `stage_warning` 19:47:15Z @ VCELL 3.696, `stage_imminent` 19:56:20Z @ 3.541, `stage_trigger` 20:00:46Z @ 3.44 → `battery_health_log` row 16 closed at 20:00:46Z runtime=811s → next boot `startup_log.prior_boot_clean=1`. The full ladder→poweroff→clean-reboot chain, 2 days more recent than the manifest's evidence.
- Verdict: **OK, but recommend bumping** `lastValidated → 2026-05-10`, `validatedBy → "Drain Test 16 (full ladder → graceful poweroff → prior_boot_clean=1 on reboot)"`.

### F-009 — Reconnect path tolerates BT drop + recovers  →  **STANDS (and the heartbeat is alive now)**
- Manifest: `2026-05-08` (Drive 6 → Drive 7 reconnect, 38 s automatic recovery; V0.27.1 hotfix).
- Now: Pi journal this session — `RECONNECT HEARTBEAT | ticks=1044 | last_attempt_seconds_ago=10.0 | last_attempt_outcome=already_in_flight` (US-301 heartbeat running). `connection_log` shows `connect_attempt`=25,293 / `connect_failure`=4,200 / `connect_success`=13 / `disconnect`=2,793 across history — the loop is durably cycling and has recovered to `connect_success` 13 times.
- Verdict: **OK** — not stale; the reconnect machinery is demonstrably alive. Drive 11 gives another natural test (engine-off stops). No change needed.

### F-010 — DTC retrieval at drive_start + drive_end (Mode 03/07 + dtc_log writes)  →  **STANDS (awaiting Drive 11)**
- Manifest: `2026-05-08` (Drive 6+7, Mode 03 probe ran on drive_start; clean ECU → 0 codes per Mike's lower-bar).
- Now: `dtc_log` = 0 rows on both Pi and server — consistent with a clean ECU returning no codes. Can't re-test without an engine (and the lower-bar is "the probe runs," which only shows in a journal during a drive).
- Verdict: **OK** — not stale. Drive 11's journal should show the Mode 03 probe. No change.

### F-011 — Stage state-machine latching (monotonic WARNING/IMMINENT/TRIGGER)  →  **UNDER-RATED — fresher evidence**
- Manifest: `2026-05-08` (Drain 8 — monotonic NORMAL→WARNING→IMMINENT→TRIGGER in power_log), real_drain_test, stale-threshold 60 d.
- Now: Pi `power_log` event-type counts = `stage_warning` 16, `stage_imminent` 14, `stage_trigger` 12 — i.e. each drain produces *at most one* of each stage event (latching holds; no flapping back-and-forth), and the recent drains (13/14/15/16) each show a clean monotonic warning→imminent→trigger triple at the expected VCELL thresholds (~3.70 → ~3.54 → ~3.41-3.45 V).
- Verdict: **OK, but recommend bumping** `lastValidated → 2026-05-10`, `validatedBy → "Drain Test 16 (one stage_warning/imminent/trigger each, monotonic; no flapping across drains 13-16)"`.

### F-012 — `battery_health_log` writes `start_vcell_v` / `end_vcell_v`  →  **UNDER-RATED — fresher evidence**
- Manifest: `2026-05-08` (Drain 8 — row 8 closed: start_vcell=4.17V end_vcell=3.42V runtime=761s), real_drain_test, stale-threshold 60 d.
- Now: Pi `battery_health_log` rows 11-16 all have `start_vcell_v` / `end_vcell_v` populated (e.g. row 16: start 3.889 V, end 3.44 V, runtime 811 s) and `end_timestamp` non-NULL (the V0.27.2 drain-close fix). 14 of 16 rows closed cleanly (rows 1 and 9 are the known historical OPEN ones).
- Verdict: **OK, but recommend bumping** `lastValidated → 2026-05-10`, `validatedBy → "Drain Test 16 (row 16 closed: start_vcell 3.889V / end_vcell 3.44V / runtime 811s; rows 11-16 all closed)"`.

### F-013 — Pi self-update applies cleanly  →  **SYNTHETIC ONLY (accurate)**
- Manifest: `lastValidated: null`, "synthetic only (US-258, US-293 tests); never IRL", manual_attestation, stale-threshold 90 d.
- Now: nothing has exercised the real self-update path. Gated on **B-066** (the B-047 self-update IRL drill — CIO + PM cooperative). Note: per the post-B-063 plan in MEMORY.md, *every key-on becomes a Pi power-on*, so the B-047 "power-on" update trigger will fire on every car start once the fuse-box feed lands — the safety preconditions (engine-off / sync-caught-up / no-DTC) become load-bearing.
- Verdict: **NEVER, accurately recorded.** No change. Recommend B-066 be scheduled alongside / soon after B-063.

### F-014 — Auto-rollback on broken release (service-fails-to-start within 60 s)  →  **SYNTHETIC ONLY (accurate)**
- Manifest: `lastValidated: null`, "synthetic only (US-294 test); never IRL", manual_attestation, stale-threshold 90 d.
- Now: same as F-013 — only exercised in synthetic tests. Part of the B-066 drill.
- Verdict: **NEVER, accurately recorded.** No change.

---

## Recommended manifest edits (for the PM — I did not edit `regression_manifest.json`)

```
F-008  lastValidated: "2026-05-08" -> "2026-05-10"
       validatedBy:   "...Drain 8..." -> "Drain Test 16 (2026-05-10): full VCELL ladder stage_warning@3.696V -> stage_imminent@3.541V -> stage_trigger@3.44V -> graceful poweroff -> prior_boot_clean=1 on reboot"
F-011  lastValidated: "2026-05-08" -> "2026-05-10"
       validatedBy:   "...Drain 8..." -> "Drain Test 16 (2026-05-10): exactly one stage_warning/imminent/trigger per drain, monotonic; no flapping across drains 13-16"
F-012  lastValidated: "2026-05-08" -> "2026-05-10"
       validatedBy:   "...Drain 8 row 8..." -> "Drain Test 16 (2026-05-10): row 16 closed start_vcell 3.889V / end_vcell 3.44V / runtime 811s; rows 11-16 all closed with end_timestamp non-NULL (V0.27.2 drain-close fix)"
F-007  lastValidated: stays null
       validatedBy:   refresh to: "Sync delta-push MECHANISM confirmed working live 2026-05-11 (Pi pushed connection_log delta to chi-srv-01 16:06:07Z; battery_health_log row 16 closed on server via US-315 UPDATE-sync; dual-cursor populated). NOT YET validated: a fresh post-V0.27.4 drive's data round-trip + the drive_summary-metadata/drive_counter UPDATE-sync fixes (US-314/US-315) on a real drive -- gated on Drive 11, which is itself gated on F-005 (no drive_summary row exists to sync)."
F-001  optional: bump lastValidated 2026-05-08 -> 2026-05-11, validatedBy "observed eclipse-obd.service active running V0.27.5 (bb744d1), uptime 3h+, startup_log fresh row prior_boot_clean=1"
```

No other changes. F-005 stays REGRESSED; F-013/F-014 stay synthetic-only; F-002/F-003/F-004/F-006/F-009/F-010 stay OK (not stale, re-confirmed by Drive 11).

## Side note (not a manifest item): B-063 is still active
Pi `power_log` shows `transition_to_ac`/`transition_to_battery` events at ~70/day on 2026-05-10 and already ~23 on 2026-05-11 — vs. ~10-15/day on calmer days. The Pi's power source is still flickering, i.e. **B-063 is not yet resolved** ("fix is imminent" = not done). This doesn't affect any manifest feature directly, but it's the gate on F-005's re-validation and on the whole V0.27 chain merge.
