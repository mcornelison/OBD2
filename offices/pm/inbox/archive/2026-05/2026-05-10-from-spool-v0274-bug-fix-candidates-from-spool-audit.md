# V0.27.4 bug-fix candidates from Spool audit pass
**Date**: 2026-05-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — 5 bugs/findings + 1 meta-observation, all from a Spool-side audit pass while waiting on B-063

## Context

CIO asked me to honestly review what else needs filing while waiting on B-063 fuse-box wiring. I did 5 quick audits (data + code) and surfaced material findings worth V0.27.4 grooming. Sorted by impact.

---

## Item 1 — B-065 root cause CONFIRMED in code (P1 candidate, your call on priority)

**Location**: `src/pi/data/sync_log.py:250-296` — `getDeltaRows()` function.

**Finding**: The Pi sync client is **PK-monotone INSERT-only by design, not by bug**. The delta query is:
```python
SELECT * FROM <table> WHERE <pk_column> > ? ORDER BY <pk_column> ASC LIMIT ?
```

Once a row has been synced (its PK is ≤ `last_synced_id`), it is **NEVER re-fetched**. UPDATEs to existing rows on Pi-side don't trigger re-sync because the PK doesn't advance.

**Implication for fix shape**: B-065 is NOT a one-line cursor-advance bug. It's a design change. Three possible architectures:
1. **Add a `modified_at` column** to delta-eligible tables; sync also pulls `WHERE modified_at > last_modified_synced`.
2. **Separate UPDATE log** that sync client reads alongside delta rows.
3. **Periodic full-state snapshots** for rows with mutable fields (battery_health_log close fields, drive_summary analytics fields).

(1) is least invasive and matches typical CDC patterns. (2) is most flexible. (3) is wasteful but simplest.

**Tables affected** (rows that may be modified post-INSERT):
- `battery_health_log` — close fields update on drain end (current bug, 6/6 reproducible)
- `drive_summary` — analytics fields update post drive_end (will be the next bug once V0.27.3 US-310 + Drive 11+ start producing rows)
- `connection_log` — drive_id update on drive_start/drive_end (per US-200, may be affected)
- `dtc_log` — last_seen_timestamp updates on repeat DTC sightings

**Recommendation**: P1 in V0.27.4 grooming. The 30-min audit Marcus suggested is now done; result is "design change required," scope it accordingly. **Worth investigating before B-063 lands** — when Drive 11+ produces real drive_summary analytics, B-065 will start corrupting analytics-table sync the same way it's corrupting battery_health_log sync today.

---

## Item 2 — US-310 drive_summary writer is correctly implemented BUT design-coupled to Ollama auto-analysis (P1 candidate)

**Location**: `src/server/services/analysis.py:1025-1069` — `enqueueAutoAnalysisForSync()`.

**Finding**: V0.27.3 US-310 satisfies the Spec 3 12-field contract correctly in `_ensureDriveSummary()` (analysis.py line 879). However, **`_ensureDriveSummary` is called from `enqueueAutoAnalysisForSync` which short-circuits if Ollama is unreachable**:

```python
if not await pingOllama(ollamaBaseUrl):
    logger.warning("Auto-analysis skipped: Ollama unreachable...")
    return False  # <-- _ensureDriveSummary never called
```

If Ollama is down (or transiently unreachable) at sync time, drive_summary rows are **never created or updated**, regardless of US-310's correctness. The two responsibilities — populate drive_summary, and run AI analysis — are bundled.

**Current observable impact**: Server-side drive_summary table still only has 3 rows (drives 3, 4, 5) post-V0.27.3 deploy. Drives 6, 7, 8, 9, 10 have NO drive_summary row at all. Either Ollama was down during one or more sync cycles, OR the trigger logic isn't firing for some other reason — but the design is fragile regardless.

**Recommendation**: P1 in V0.27.4. **Separate `_ensureDriveSummary` from the Ollama auto-analysis trigger** so drive_summary always writes, and AI analysis runs only when Ollama is up. Two-line code change in `enqueueAutoAnalysisForSync` — call `_ensureDriveSummary` first, then check Ollama for the analysis step.

**Bonus finding while auditing**: `scripts/backfill_drive_summary_analytics_fields.py` (the V0.27.3-shipped backfill tool) **filters on `drive_id IS NOT NULL`**, which excludes drives 3-5 (legacy NULL drive_id rows on server) AND won't INSERT new rows for drives 6-10 (which have no drive_summary row at all). So historical drives can't be backfilled by the existing script. Worth extending the script to handle both cases — small companion task.

---

## Item 3 — start_soc/end_soc still hold VCELL volts (P3, V0.27.2 carryover)

**Evidence from Drain Test 15**:
```
drain_event_id | start_soc | end_soc
15             | 3.93875   | 3.445
```

Schema documentation in `battery_health_log` SQL:
```sql
-- SOC at event open. Range: 0..100 (MAX17048 integer % scale).
start_soc REAL NOT NULL,
```

Documentation says 0-100% SOC scale; writer writes voltage. Per MEMORY.md the rename is mid-flight: US-289 (V0.27.2) shipped Step 1 (SocPct seam writer-side); **B-060 (UpsMonitor SOC% wire-through, Step 2) and B-061 (drop legacy columns, Step 3) are still pending**.

**Recommendation**: confirm B-060 + B-061 are on the V0.27.4 backlog. They were already P3 candidates pre-Sprint-29 grooming; just verify they survived the V0.27.4 candidate winnowing. If they did → no new action. If they got dropped, re-add.

---

## Item 4 — Connection_log noise unchanged post-V0.27.2/V0.27.3 (P3, observation)

**Re-profile result** (compared to the Apr 24-28 ~2,640/day baseline I cited earlier):

| Day | connect_attempt | connect_failure | connect_success |
|---|---:|---:|---:|
| 2026-05-09 | 2,472 | 411 | 3 |
| 2026-05-10 (partial) | 1,130 | 185 | 2 |

5/10 partial-day projects to ~1,920/day at current rate. **Noise didn't materially change** between V0.27.1 and V0.27.3. The 10s heartbeat hotfix was supposed to reduce reconnect spam; it didn't (or its effect is dwarfed by other reconnect attempts).

**Recommendation**: Sprint 30+ candidate to investigate reconnect spam reduction. Not urgent — it's bench-running noise, doesn't affect engine telemetry capture. But worth knowing the prior fix didn't move the needle.

---

## Item 5 — Drive 9 brownout hypothesis CONFIRMED (informational, B-063 already gates fix)

**Evidence**: power_log + drain_forensics CSV during Drive 9 window (00:16-00:46 UTC 2026-05-10):
- `battery_power` event logged at 00:19:02Z (2 min into Drive 9)
- `stage_warning` fired at 00:46:12Z (3 sec after drive_end)
- Drive 9 was on battery for ~27 min, NOT continuous flicker
- During the battery period: forensic CSV showed 92/97 rows with **non-zero `throttled_hex`** = heavy CPU throttling

**Different shape than I originally hypothesized** (I said "continuous flicker"; actual was "single USB-C disconnect at 2-min mark, sustained battery for 27 min"). End result is the same — Pi was on degraded battery power for nearly the entire drive, brownout-throttling kicked in, data logger captured at 36 rows/min instead of 459.

**No new bug to file** — root cause is B-063 hardware blocker (USB-C undersized). Once fuse-box wiring is in place, Pi stays on stable 5A AC → no UPS handoff during drive → no brownout-throttling → data capture stays at 459 rows/min. Just adding empirical confirmation to the case for B-063.

---

## Meta — Validation queue is still stacking; today's audits reduced two unknowns

**Status before today's audits**:
- V0.27.2: 2/5 contracts validated (drain close + startup_log via Drains 14, 15)
- V0.27.3: 1/4 validated (US-312 calibration.py)
- 5 outstanding contracts gate on B-063 + Drive 11+

**After today's audits** — three items moved from "unknown" to "known":
- **US-310 (drive_summary writer)**: code is CORRECT; ships gated by Ollama coupling design issue. Drive 11+ won't trip on US-310 itself, just on the Ollama-coupling.
- **B-065 (sync UPDATE gap)**: design-rooted, not a quick fix. V0.27.4 P1 with right fix-shape.
- **Drive 9 brownout**: confirmed B-063-rooted.

**What still needs Drive 11+** to validate:
- US-311 (DriveDetector warm-restart-cranking fix) — only validates with key-on-key-off-key-on cycle
- US-314 (drive_counter sync gap) — only propagates with new drive_id mint

**Other follow-ups** for Sprint 30+ that surfaced:
- Backfill script extension (for historical drives without drive_summary rows)
- Ollama-decoupling refactor (post-V0.27.4 if not folded into US-310 fix above)

— Spool

PS: All audits done while CIO was actively waiting; everything took <30 min total. The discipline of pre-flight audits (`feedback_pm_run_pre_flight_during_grooming.md`) extends naturally to "Spool-side audits while waiting on hardware" — willing to keep doing this when Drive 11+ is hours/days away.
