# V0.27.7 addendum — Drive-12-independent work + US-321 validated, US-320 needs Mike pip install
**Date**: 2026-05-12
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — companion to tonight's two prior notes (Drive 11 chain validation + MAP PID request)

## Context

Mike asked whether any bugs/fixes I'd found tonight could land in V0.27.7 without waiting on Drive 12 IRL validation. Answer: yes. This note adds 2 small candidates plus a non-sprint hygiene list. Companion to:
- `2026-05-12-from-spool-drive-11-v027-chain-validation-and-v0276-failures.md` (Stories X/Y/Z/W)
- `2026-05-12-from-spool-add-map-pid-to-default-poll-list.md` (MAP feature add)

## New V0.27.6 validations (no Ralph work needed)

- **US-321 (phantom sqlite fallback removed) — CONFIRMED PASSING IRL.** Invoked `scripts/report.py --calibrate --device chi-eclipse-01` from Mike's Windows shell with DATABASE_URL unset; got clean exit code 2 with `report.py: error: DATABASE_URL not set; pass --db-url or export DATABASE_URL`. Exact Option A behavior. Update `regression_manifest.json` accordingly.

- **US-320 (pymysql in requirements) — FULLY VALIDATED IRL** (updated 2026-05-12 post-Mike-pip-install). `requirements-server.txt` has `pymysql>=1.1.0` ✓; Mike ran `pip install` on his dev box; ran `python scripts/report.py --calibrate --device chi-eclipse-01` against chi-srv-01 production MariaDB and got the expected clean banner `Need 5 more real drives before calibration is meaningful` with exit code 0. **Mark VALIDATED in regression_manifest.json.** First end-to-end success of the original I-022 use case.

## Two additional V0.27.7 candidates — both Drive-12-independent

### Story E (P3, S) — Pi-side historical drain backfill (drain_event_id=1 and =9)

**Scope**: One-off SQL OR script under `scripts/`. Pi-side `battery_health_log`.

**Repro**: `SELECT drain_event_id, start_timestamp, end_timestamp FROM battery_health_log WHERE end_timestamp IS NULL` on Pi-side returns 2 historical rows:
- `drain_event_id=1, start_timestamp=2026-05-04T13:21:08Z, end_timestamp=NULL`
- `drain_event_id=9, start_timestamp=2026-05-09T01:47:10Z, end_timestamp=NULL`

Per MEMORY.md: drain 9 specifically — "Pi died mid-drain and the close-event didn't write before `systemctl poweroff` triggered." Pre-V0.27.2 root cause; the V0.27.2 fix prevents this from recurring but doesn't backfill these two rows. Drain 1 close-time reconstructable from `power_log` `stage_trigger` row at 2026-05-04T13:34:09Z (per MEMORY Drain Test 10 record).

**Acceptance**:
1. Pi-side rows for `drain_event_id IN (1, 9)` have populated `end_timestamp`, `end_soc`, `runtime_seconds` derived from contemporaneous `power_log` `stage_trigger` rows (timing-truth source).
2. Server-side rows for same `source_id IN (1, 9)` get updated via the (now-working) US-315 sync UPDATE path. **This is also a third orthogonal validation of US-315's drive-side AFTER Story X lands** — if the new fix works for forward drives, it should also propagate these historical close-event UPDATEs.
3. Mechanism is reusable, not a hand-edit (script under `scripts/`, idempotent guard).

**Why P3**: Two stranded rows aren't load-bearing for any current analytics, but they pollute lifetime drain-runtime trend data. Cheap to fix.

### Story F (P3, S) — Investigate the 199 leaked orphans (post-US-322)

**Scope**: data analysis + possible writer-guard patch.

**Repro**: After US-322's cleanup landed in V0.27.6, Pi-side `realtime_data` NULL-drive_id orphan count is 199 (down from 61,293 pre-cleanup — 99.7% reduction, US-322 working). The 199 leaked through.

**Hypothesis**: One of (a) writes that arrived during the cleanup-timer's transaction window, (b) reconnect-noise polls between the timer's firings, (c) a guard-pattern the timer doesn't cover (e.g., specific PIDs that always poll before DriveDetector engages).

**Acceptance**:
1. Cluster the 199 rows by timestamp + PID; identify the dominant pattern.
2. If pattern is "between-timer-firings noise": tighten the timer interval OR add a writer-side guard that drops engine-off polls before they hit realtime_data.
3. If pattern is "transaction-race during cleanup": fix the cleanup's transactional isolation OR add a final cleanup sweep.
4. Acceptance: after Drive 12, Pi-side orphan count stays ≤ 50 (further 75% reduction from current).

**Why P3**: US-322 is fundamentally working (99.7% reduction). This is "make a working solution even better," not "fix broken solution." Spool's analytics already filter on `drive_id IS NOT NULL`, so the 199 rows are inert noise, not data poison.

## Non-sprint hygiene (Spool / Marcus / Mike handle directly, no Ralph)

- **`offices/tuner/drain-test-procedure.md` schema drift** — Step 4 `startup_log` query references nonexistent `software_version` column. Spool is patching this directly when appending Drain Test 17 results. P3 procedure-doc fix, not a sprint story.
- **`regression_manifest.json` updates from tonight's findings** — Marcus's lane. Suggested updates:
  - F-007 (or whichever feature ID covers drive_summary writer + sync): US-310 / US-311 / US-317 first IRL pass on Drive 11; US-315 drive_summary side STILL REGRESSED (move to V0.27.7).
  - Feature for drain ladder + sync: US-315 battery_health side validated TWICE (drains 16 + 17). Drain Test 17 is first 5-of-5 PASS in project history.
  - US-321: VALIDATED tonight.
  - US-322: VALIDATED tonight.
  - US-320: code-shipped, dev-env install pending.
  - US-323 + US-324: REGRESSED, queued for V0.27.7.
- **B-062 (drain_event close targeted fix) re-evaluation** — was bumped P3 → P2 because of unclosed drains. Drains 16/17/18 all closing correctly Pi-side (drain 17 also synced cleanly to server via US-315). Marcus's call: close as superseded by V0.27.2 + V0.27.4 + V0.27.6 carry-forwards, OR keep open until Drive 12's drain produces another clean close on both sides.

## ⚠ ADDED post-Pi-recovery: Bug 3 — US-308 REGRESSION in V0.27.6 (P1)

After filing the above, Pi came back online (post drain 18 + reboot). I pulled the latest `startup_log` rows. **`prior_boot_clean` is NULL on both post-V0.27.6 boot rows.**

```
boot_id                          | prior_boot_clean | recorded_at
af5f5785ee514dc1b5335128901161b0 |     NULL         | 2026-05-12T01:45:56Z   ← drain 18 post-boot
ca2f0f5b4f514a33b487f2c8b1f7699e |     NULL         | 2026-05-12T00:37:02Z   ← drain 17 post-boot (V0.27.6 deploy boot)
0dee6252a12d4b6490df7ab7df04ef59 |       1          | 2026-05-11T12:27:57Z   ← last pre-V0.27.6 boot
4f82c652a74c402d8ac17edb890d1bfd |       1          | 2026-05-10T20:00:14Z   ← drain 16 post-boot, V0.27.4
88c03212cbc5417aabb4c128814743f5 |       1          | 2026-05-10T14:13:19Z   ← drain 15 post-boot, V0.27.3
```

Three pre-V0.27.6 boots: `prior_boot_clean=1` ✓. Two post-V0.27.6 boots: `prior_boot_clean=NULL` ❌. Clean signal that **V0.27.6 introduced a regression in the startup_log writer's graceful-shutdown detection.** All three nullable companion columns (`prior_last_entry_ts`, `current_boot_first_entry_ts`) are also NULL on the post-V0.27.6 rows but populated on the pre-V0.27.6 rows.

### Story G (P1, S) — Restore US-308 startup_log prior_boot_clean detection

**Scope**: investigate which V0.27.6 change broke the journal-parsing logic in the startup_log writer. Suspects in order of likelihood:
1. **US-322** (orphan-cleanup systemd timer) — could be interfering with journal access OR competing with the journal-parse step on boot
2. **US-325** (BT reconnect exponential backoff + Pi rebuild durability) — touched boot sequence; could have shifted startup_log writer timing
3. Some inadvertent change to the journalctl invocation or its environment in V0.27.6

**Acceptance**:
1. After the next Pi reboot post-fix, `startup_log` row has `prior_boot_clean=1` and populated `prior_last_entry_ts` + `current_boot_first_entry_ts` columns.
2. Repeats correctly across 2 consecutive boot cycles.
3. **No drive needed** — pure boot-cycle validation. Mike can validate from his desk by unplugging+replugging.

**Why P1**: US-308 is the ONLY signal we have that distinguishes a graceful shutdown (V0.24.1 ladder fired correctly) from a hard crash (Pi died unexpectedly). Without it, drain forensics regress to the pre-Sprint-25 era. Spool's drain-test procedure depends on this signal for the "prior_boot_clean" pass/fail target.

**Note on Bug 4 (drain 18 unclear close)**: drain 18 has `end_timestamp=NULL` Pi-side. Could be (a) drain was interrupted by an AC restoration before TRIGGER fired (legitimate no-close scenario), (b) Pi clock jumped 23 hours forward post-reboot (RTC drift / NTP sync confusion — power_log timestamps after the boot show `2026-05-13` instead of `2026-05-12`), or (c) V0.27.6 close-event writer regression. **Not enough signal to file as a story tonight.** Recommend a deliberate bench-drain test on V0.27.7 to disambiguate. P2 follow-up, NOT a current sprint story.

**Note on Bug 5 (Pi clock drift)**: Post-reboot timestamps show 2026-05-13 — 23 hours forward of wall time. NTP eventually catches up but late. Could be Pi RTC battery dead OR systemd-timesyncd configuration issue. P3 observability item — file for V0.28+ if it recurs.

## Updated Summary for grooming

V0.27.7 candidate stack (6 total now):
- **P1**: Story X (US-315 drive_summary side), Story Y (server backfill 11-15), Story Z (drive_statistics writer + table), **Story G (US-308 prior_boot_clean regression)**
- **P3**: Story W (drive_counter sync), Story E (Pi-side drain 1+9 backfill), Story F (199 orphan leak investigation)

**3 of 7 candidates require Drive 12 IRL** (X, Z, W). The other 4 (Y, E, F, G) can be validated WITHOUT a drive — pure bench / boot-cycle / SQL work.

Plus optional V0.27.7 ride-along (per the other note): MAP PID add (XS-S).

Plus non-sprint hygiene: regression_manifest update, B-062 re-eval, procedure-doc patch (Spool handles).

— Spool
