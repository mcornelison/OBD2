# Tuning research items + feature candidates for backlog
**Date**: 2026-05-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — file for backlog grooming, not urgent for V0.27.4

## Context

CIO asked me what tuning gaps / new features I want to pursue. None of these are V0.27.4 work — they're future-sprint candidates and forward-looking research. Filing for backlog so they don't get forgotten.

---

## Item A — Sustained WOT capture protocol (DRIVE-PLAN, not a code story)

**Gap**: Drive 7 hit 100% engine load momentarily. **N=1 for under-load data**, and the WOT was incidental, not sustained. **Sustained WOT (5-10+ sec at full boost) is the single most valuable missing tuning data point.**

**What sustained WOT tells us that incidental WOT doesn't**:
- Thermal margin under sustained load (coolant + IAT trend over 10+ sec at full WOT)
- MAF saturation behavior (does MAF flatten / clip near 158 g/s peak, or stay linear?)
- Timing-pull behavior (does ECU pull timing under sustained load even without knock-pull DTCs?)
- Stock fuel system delivery limits (LTFT/STFT trends at 100% load show injector duty saturation)
- Closed-loop O2 behavior post-WOT-enrichment (how fast does B1S1 return to switching after WOT exit?)

None of these are answerable from Drive 7's momentary WOT.

**Drive plan recommendation** (post-B-063, future drive 11/12/13):
1. Empty stretch of road, 3rd or 4th gear pull
2. Accelerator floored, hold for **5-10 sec at full WOT**
3. Repeat 2-3 times with 30-sec cooldown between
4. Tag drive intent as `datalog_pull` (per `drive_annotations` schema spec)
5. Pre-drive checklist: tank ≥3/4, ambient temp logged, weather noted, no anomalies

**Action for backlog**: file as research/drive-plan item **B-066 sustained-WOT-capture-drive-plan**. Sprint 30+ depending on Drive 11 cadence. CIO approval needed before any deliberate WOT pull.

---

## Item B — Cross-drive comparison tool (FEATURE)

**Gap**: With drives 3-8 on the pre-mod baseline shelf, querying "show me LTFT trend across all healthy idle drives" or "show me coolant warm-up curves across cold-start drives" is currently a **manual SQL exercise** every time. Spool ends up writing one-off queries.

**Proposed feature**: a small CLI / skill that takes a parameter name + a filter (mod_state, cold/warm-start, idle-only/under-load) and produces an aggregated comparison across drives matching the filter.

**Example use cases**:
- `/spool-compare LTFT_1 mod_state=premod is_actual_drive=true` — LTFT trend across drives 6-8
- `/spool-compare COOLANT_TEMP cold_start=true` — warm-up curves across drives 3, 4, 5, 6, 8 (skip 7 which was warm-restart)
- `/spool-compare TIMING_ADVANCE engine_load=>80` — timing-under-load across all drives with peak engine_load > 80%

**Implementation approach**: probably a Python script in `offices/tuner/` reading `obd2db` directly. ~100 LOC. Alternative: SQL view templates Spool can copy-paste.

**Action for backlog**: file as **B-067 cross-drive-comparison-tool**. Sprint 30+ low-priority. Mostly Spool-side ergonomics; not load-bearing for project goals.

---

## Item C — Real-time telemetry monitor (DEFERRED — too speculative, file as research)

**Gap**: Currently Spool only sees data POST-drive (after sync completes). A live "Spool watching the drive" mode would let Spool catch knock-pull events, thermal runaway, or unusual fueling in the moment instead of post-hoc.

**Why deferred**: we're K-line constrained at ~5 PIDs/sec. Real-time monitoring is feasible but:
- Requires server-side streaming (Pi → server push every N rows, not just at sync)
- Requires alert mechanism (Spool can't watch dashboards 24/7)
- Marginal value vs post-drive analysis until drives become more frequent / risk increases (e.g., post-ECMLink, real WOT pulls)
- Probably wasteful pre-ECMLink (knock pulls aren't directly observable on stock OBD-II anyway)

**Action for backlog**: file as **research-only** in tech_debt or backlog as **TD-049 real-time-telemetry-monitor-research**. Revisit when ECMLink lands + actual knock data is available. Not a pre-mod priority.

---

## Item D — Reminder: weather API for drive context + PID 0x2F probe (already filed)

These were filed earlier today/yesterday in PM notes. Not duplicating here, just reminding they're still on the candidate queue for Sprint 30+:

- **Weather API integration** (PM note `2026-05-09-from-spool-feature-idea-weather-api-for-drive-context.md`) — auto-populate ambient_temp + weather at drive_end via Open-Meteo or NWS. Pairs with `drive_annotations` schema.
- **PID 0x2F probe** (PM note `2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` Item 4) — probe fuel level PID, add to poll set if supported. Removes manual fuel_level_at_start interview.

Both pair naturally with `drive_annotations` table (Spec 2 from yesterday's bundle). When Ralph builds the table, both auto-populate paths can be wired up at the same time.

---

## Recommended sprint-grooming buckets

| Priority | Item | Effort | Trigger |
|---|---|---|---|
| Sprint 30 candidate | A — Sustained WOT capture drive plan | S (operator-only, no code) | Post-B-063, after Drive 11 baseline |
| Sprint 30+ low-pri | B — Cross-drive comparison tool | M (~100 LOC + SQL views) | Spool ergonomics improvement |
| Tech debt | C — Real-time telemetry monitor | M-L (server streaming + alerts) | Revisit post-ECMLink |
| Sprint 30+ | Weather API (already filed) | S | Pairs with drive_annotations |
| Sprint 30+ | PID 0x2F probe (already filed) | XS | Pairs with drive_annotations |

None of these compete with V0.27.4 bug-fix work. They're all post-bug-fix-stability candidates.

— Spool
