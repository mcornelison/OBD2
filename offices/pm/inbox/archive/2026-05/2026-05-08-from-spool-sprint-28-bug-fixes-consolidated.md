# Sprint 28 bug-fixes consolidated — 4 bugs from today's validation session
**Date**: 2026-05-08
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (Mike asked for these consolidated for sprint grooming)

## TL;DR

Today's session validated Sprint 27 V0.27.1 IRL (Drive 6 + Drive 7 + drain test 8 all GREEN). In doing so, surfaced **4 sibling bugs** that need Sprint 28 grooming. **None are safety-critical** — V0.24.1 ladder + V0.27.1 reconnect path + engine telemetry capture all work correctly. These are data-hygiene + observability issues behind the now-working primary functionality.

| # | Bug | Severity | Effort | Subsystem |
|---|---|---|---|---|
| 1 | `drive_summary` writer regression | **P2** | M | Drive metadata |
| 2 | `battery_health_log` legacy columns hold VCELL voltage | P3 | S | Schema cleanup |
| 3 | `drain_event` close not written before poweroff | P3 | S | Drain logging race |
| 4 | `startup_log.prior_boot_clean=0` on graceful shutdown | P3 | S | Boot detection heuristic |

**Total estimate**: 1M + 3S = 4 size-points. Reasonable Sprint 28 inclusion alongside whatever else is on the docket.

---

## Bug 1 — `drive_summary` writer regression (P2, M)

**What**: Drive 6 + Drive 7 today produced `drive_end` events in `connection_log` but NO `drive_summary` rows. Last `drive_summary` row written is `drive_id=5` from 2026-04-29.

**Evidence**:
```
$ sqlite3 ~/Projects/Eclipse-01/data/obd.db \
    "SELECT MAX(drive_id) FROM drive_summary;"
5

$ sqlite3 ~/Projects/Eclipse-01/data/obd.db \
    "SELECT timestamp, event_type FROM connection_log WHERE event_type LIKE 'drive%' ORDER BY timestamp DESC LIMIT 4;"
01:47:12Z drive_end
01:37:27Z drive_start
00:57:32Z drive_end
00:41:54Z drive_start
```

`realtime_data` capture is fine (7,085 rows for drive_id=6, ~3,000+ for drive_id=7); only the summary roll-up is missing.

**Why P2 not P0/P1**: Realtime data + connection_log are both clean, so we have full visibility on what happened during the drives. The summary roll-up is an analytics-layer convenience, not a data-integrity gap. Engine grades + tuning analysis can be done from realtime_data directly (which is what I did today for Drive 6 + 7 grades).

**Why this is a regression**: This bug class hit us hard before — Drives 3+4+5 all had the same symptom (4 occurrences before US-237 reconciler shipped Sprint 19). Reappearance on a fresh deploy means either US-237 reconciler isn't firing OR US-236's defer-INSERT path has a regression introduced in Sprint 25/26/27.

**Recommended fix approach**:
1. Diagnose: which path is failing — defer-INSERT (US-236) or reconciler (US-237) or both?
2. Add a runtime-validation INTEGRATION TEST that exercises the actual production flow: drive_start → 5 min realtime data → drive_end → assert `drive_summary` row exists with all required fields populated. Sprint 19 retro work (Spool/US-256) created this test pattern; this bug class shouldn't regress without test breakage.
3. Backfill drive_summary rows for drive_id=6 + drive_id=7 (one-time `scripts/repair_*.py` style script, similar to US-237's reconciler) so we don't lose the metadata for Drive 7 (the first under-load capture in project history).

**Acceptance criteria**:
- `drive_summary` row written within 30 seconds of every `drive_end` event
- Integration test exercises the production flow and asserts row presence + field population
- One-shot backfill script populates drive_id=6 and drive_id=7 from realtime_data + connection_log evidence

---

## Bug 2 — `battery_health_log` legacy columns still hold VCELL voltage (P3, S)

**What**: US-289 added `start_vcell_v` / `end_vcell_v` columns to `battery_health_log` and the writer NOW populates them correctly (validated today on drain 8). **But the original `start_soc` / `end_soc` columns still hold VCELL voltage values, NOT actual SOC percentages.** Writer is dual-populating both old and new columns with the SAME value.

**Evidence** — drain 8 row written today:
```
drain_event_id  start_soc  end_soc    start_vcell_v  end_vcell_v
8               4.17       3.42375    4.17           3.42375
```

`start_soc=4.17` is a VCELL voltage value (4.17V). A 4.17% SOC LiPo would be dead. The column is mis-named.

**Why this matters**: Anyone who queries `battery_health_log` and reads `start_soc` thinking "0-100% range" will get nonsensical results. This will bite analytics queries silently.

**Recommended fix approach** (per Spool's original Sprint 25 spec ask US-289):
- Option 1: Drop `start_soc` / `end_soc` columns entirely. Audit consumers first (analytics queries, sync mappings). If nothing reads them, just drop.
- Option 2: Migration to actually populate `start_soc` / `end_soc` with computed SOC% (using MAX17048 SOC reading at the same timestamp), with `start_vcell_v` / `end_vcell_v` holding the truth (VCELL voltage). Requires the SOC% reading to be available at write time, which it is.
- Option 1 is cleaner; Option 2 preserves backward compat.

**Acceptance criteria**:
- `battery_health_log.start_soc` (if kept) holds actual SOC% values 0-100, not voltage
- `battery_health_log.start_vcell_v` holds VCELL voltage as designed
- Schema migration runs cleanly on existing rows (or columns dropped if Option 1)

---

## Bug 3 — `drain_event` close not written before `systemctl poweroff` (P3, S)

**What**: Today's late-session drain test 9 OPENED at `2026-05-09T01:47:10Z` (stage_warning at VCELL 3.671V) but never CLOSED. `battery_health_log.drain_event_id=9` has `end_timestamp=NULL, runtime_seconds=NULL`. The Pi died mid-drain (uptime when checked = 5 min after a recent boot) and the close-event didn't write before `systemctl poweroff` triggered.

**Evidence**:
```
$ sqlite3 ~/Projects/Eclipse-01/data/obd.db \
    "SELECT drain_event_id, start_timestamp, end_timestamp, runtime_seconds FROM battery_health_log ORDER BY drain_event_id DESC LIMIT 2;"
9  2026-05-09T01:47:10Z  (NULL)  (NULL)
8  2026-05-09T01:24:04Z  2026-05-09T01:36:45Z  761
```

Drain 8 closed cleanly because Mike restored AC power BEFORE `systemctl poweroff` actually triggered (transition_to_ac at 01:36:59Z, 14s after stage_trigger at 01:36:45Z). Drain 9 went all the way to poweroff without AC restoration.

**Why this matters**: Every drain that goes ALL THE WAY to graceful poweroff (the load-bearing safety case) will leave an OPEN drain_event row. Long-term, this corrupts the analytics table — runtime trending, baseline aging detection, anything that joins on closed drain events will miss the most important rows (the actual poweroff cases).

**Recommended fix approach**:
- Hook `drain_event` close into `_enterStage(TRIGGER)` — write the close BEFORE `systemctl poweroff` is invoked (currently the close is presumably tied to `transition_to_ac` which obviously can't fire when the Pi is about to poweroff)
- `end_timestamp` = TRIGGER fire timestamp; `end_vcell_v` = VCELL at TRIGGER; `runtime_seconds` = TRIGGER timestamp - start_timestamp
- Reasonable: if AC IS restored later (drain 8 case), the existing `transition_to_ac` close path overrides with the actual restore timestamp. Two paths to close the row, last-write-wins.
- Backfill drain_event_id=9 manually using power_log evidence (stage_trigger timestamp + VCELL value)

**Acceptance criteria**:
- Drain events that go all the way to TRIGGER → poweroff have `end_timestamp` populated (not NULL) using TRIGGER firing timestamp
- Drain events that recover via AC restore continue to close with restore timestamp (existing path preserved)
- Regression test: simulate full drain through TRIGGER → assert `end_timestamp` populated within 5s of TRIGGER fire

---

## Bug 4 — `startup_log.prior_boot_clean=0` on graceful shutdown boots (P3, S)

**What**: `startup_log` writer reports `prior_boot_clean=0` (hard crash) for boots following Mike's "normal simulated power off" — even though the V0.24.1 ladder fired correctly and `systemctl poweroff` was invoked cleanly. The writer's "find graceful shutdown record in journal" heuristic isn't recognizing the ladder's shutdown sequence as graceful.

**Evidence**:
```
$ sqlite3 ~/Projects/Eclipse-01/data/obd.db \
    "SELECT recorded_at, prior_boot_clean, prior_last_entry_ts FROM startup_log ORDER BY recorded_at DESC LIMIT 3;"
2026-05-09T03:13:29Z  0  Fri 2026-05-08 22:14:40 CDT  ← post-graceful-shutdown but reported as crash
2026-05-09T01:36:18Z  0  Fri 2026-05-08 20:40:06 CDT
2026-05-08T03:52:38Z  0  Tue 2026-05-05 19:13:47 CDT
```

The 03:13:29Z boot follows drain 8's CLEAN graceful shutdown (V0.24.1 ladder hit TRIGGER at 3.424V, `systemctl poweroff` invoked). Yet `prior_boot_clean=0`. Either:
- The writer's regex/heuristic for detecting "graceful shutdown markers in journalctl" is too narrow (doesn't match the ladder's actual log lines)
- OR the journal entries from the ladder's shutdown sequence are getting truncated before persistence (journald buffer not flushed)

**Why this matters**: The whole POINT of `startup_log` (US-263/US-287) is to make "did the prior shutdown crash?" a queryable post-mortem signal. With this bug, EVERY graceful ladder-shutdown is reported as a hard crash — the signal is permanently lying. Crashes vs graceful-shutdowns become indistinguishable.

**Recommended fix approach**:
1. Capture the ACTUAL log lines emitted during a V0.24.1 ladder graceful shutdown (drain 8 today is a good source — `journalctl --boot=-1` should show them)
2. Update the writer's graceful-shutdown detection regex/heuristic to match those lines specifically
3. Add a unit test: feed a synthetic journal slice from a V0.24.1 ladder shutdown → assert `prior_boot_clean=1`
4. Regression: feed a hard-crash synthetic journal slice → assert `prior_boot_clean=0`

**Acceptance criteria**:
- Boots following a V0.24.1 ladder graceful shutdown report `prior_boot_clean=1`
- Boots following an actual hard crash (e.g., kill -9 the python process) report `prior_boot_clean=0`
- Test coverage for both paths

---

## Sprint 28 ask

Group all 4 bugs into Sprint 28. Suggested ordering:

1. **Bug 1 (drive_summary regression)** — P2, blocks tuning analytics for new drives. Highest impact even though not safety.
2. **Bug 3 (drain_event close-before-poweroff)** — P3 but easy fix; corrupts long-term drain analytics if ignored.
3. **Bug 4 (startup_log graceful detection)** — P3, lying observability signal; fix together with Bug 3 since both are observability-layer.
4. **Bug 2 (battery_health_log column cleanup)** — P3, schema hygiene; do last because depends on auditing consumers.

Estimate: 1M + 3S = **4 size-points** for Sprint 28.

Plus carryforwards from prior PM notes:
- Mirror Drive 7 baseline into `specs/grounded-knowledge.md` (Marcus-actionable, see prior note)
- DSM DTC interpretation cheat sheet (Spool deliverable, now unblocked since US-292 shipped)

---

## Cross-references

- Today's drive grades + drive_summary regression: `2026-05-08-from-spool-drive-6-7-grades-engine-healthy-under-wot.md`
- Drain test 8 + 9 evidence: `offices/tuner/sessions.md` Session 9 late-session amendment
- Memory snapshot: MEMORY.md "Current State" Sprint 27 paragraph + drain test amendment
- US-289 origin: Sprint 25 US-289 (Spool ask Session 8)
- US-263/US-287 origin: Sprint 22 US-263 (schema) + US-287 (writer, Sprint 25)

---

— Spool

PS: All 4 bugs surfaced from VALIDATION work today, not from new feature work. The pattern is healthy: Sprint 27 + V0.27.1 hotfix unblocked the primary mission (engine telemetry capture works again), and exercising that primary mission EXPOSED these data-hygiene gaps that were hiding behind the prior P0s. This is exactly what we want — bugs come out as soon as the feature is exercised in production. Sprint 28 should be a "polish + close gaps" sprint, not another "fix the primary mission" sprint.
