# Specs Updated from Session 23 Real Data + DTC Retrieval Gap Flag
**Date**: 2026-04-19
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine (FYI + one small gap to address)

## Context

Two items while we wait on Sprint 14:

1. **I've updated `specs/grounded-knowledge.md`, `specs/obd2-research.md`, and my own `offices/tuner/knowledge.md`** with Session 23 empirical facts. Shared-team reference now has authoritative real-car data instead of theoretical baselines.
2. **One story gap I want to surface before Sprint 14 closes**: DTC retrieval (Mode 03/07 + `dtc_log` table) isn't visible in Sprint 14. Flagging now so it doesn't slip.

CIO authorized me to update specs/ with knowledge that should be shared across the team, so these changes crossed my normal lane boundary with permission.

---

## Changes Made to Shared Specs

### `specs/grounded-knowledge.md` — expanded

New top-level section **"Real Vehicle Data"** (between community-sourced ranges and Usage Rules). Authoritative empirical observations from Session 23. Key tables:

- **PID support empirically confirmed** — which PIDs responded (11 PIDs ✅) vs. confirmed unsupported (0x0A, 0x0B, 0x42 ❌)
- **Battery Voltage alternate path** — PID 0x42 is dead; use ELM327 `ATRV` / python-obd `ELM_VOLTAGE`
- **Real-world K-line throughput** — 6.4 rows/sec measured, matches theoretical 6-8 PIDs/sec prediction
- **Warm-idle fingerprint** — the specific numbers for this specific car (LTFT 0.00% flat, RPM 761-852, coolant 73-74°C, timing 5-9° BTDC, etc.) as authoritative baseline for fixture validation, range-check tests, regression data, and AI prompt grounding

**PM impact**: When you write story acceptance criteria for anything that touches OBD values, this is now your source for "what does 'normal' mean on this specific car." PM Rule 7 (grounded facts) now has real empirical backing, not just community consensus.

### `specs/obd2-research.md` — expanded

- Added **Session 23 empirical column** to Tier 1 and Tier 2 PID support tables (✅ / ❌ / pending-Sprint-14 for every PID Ralph will consider polling)
- PID 0x0B caveat **strengthened**: was "may report MDP, unreliable for boost"; now **"does not respond at all on this ECU"** — live-car fact, stronger than research inference
- New **PID 0x42 caveat section** with the ELM_VOLTAGE workaround path for Ralph's code and Tester's fixtures
- New **"Session 23 Empirical Measurement"** subsection under Protocol & Throughput Constraints, proving theoretical numbers hold on the real car
- Added **Sprint 14 polling-design implication** — adding 6 new PIDs (US-199) brings concurrent PID count to ~17; per-PID rate drops to ~0.3-0.4 Hz if flat-polled; tiered polling (Section 5) becomes essential. Included my recommendation for which tier each new PID belongs in (e.g. fuel system status → fast-poll, barometric → slow-poll).

**PM impact**: When Ralph implements US-199, this section tells him exactly how to slot each new PID into the existing tiered-polling design.

### `offices/tuner/knowledge.md` — expanded (my own file, FYI)

New top-level section **"This Car's Empirical Baseline"** with the full interpretation layer (not just facts — what each observed value means, what a drift from it would indicate). Deeper than the specs/ version; the specs/ version has the numbers, this has the clinical read.

Also fixed PID support table to reflect Session 23 empirical truth, and documented the battery voltage / ELM_VOLTAGE alternate path (CR #3 from my review note — homework done).

### Session log entry added to `knowledge.md` for the 2026-04-19 update

---

## Small Gap I Want to Flag in Sprint 14

### Missing: DTC retrieval (Mode 03/07) + `dtc_log` table

When I reviewed Sprint 14's loaded stories via `sprint.json`, I confirmed you've queued all my priority CRs — excellent. US-193 (TD-023), US-195 (data_source), US-199 (6 new PIDs), US-200 (drive_id). That covers Priority 1-7 from my data-collection-gaps note.

**Except for one piece**: US-199 captures the **MIL bit** (PID 0x01 — "is the light on?"), but I don't see DTC retrieval anywhere. DTC retrieval needs:

- **Mode 03** — retrieve stored DTC codes when MIL is illuminated
- **Mode 07** — retrieve pending DTCs (sub-threshold, not yet illuminated). May not be supported on 2G — Ralph probes.
- **`dtc_log` table** — new schema, one row per DTC occurrence, keyed to `drive_id`. Columns: dtc_code, description, status (stored/pending/cleared), first_seen_timestamp, last_seen_timestamp, drive_id.

In my original data-collection-gaps note, I called this "Spool Data v2 Story 3" at L-size. It's a new capability (not just a PID addition), which is why it's bigger.

**Why it matters**: If a 4G63 stores P0300 (random misfire) — a classic crankwalk early indicator — we'd see the MIL bit but not the code. I couldn't diagnose what's actually wrong without running OBD-II readout manually via a separate tool. That defeats the point of the Pi collector.

### What I'm asking for

- **Option A (preferred)**: Add DTC retrieval as a new story in Sprint 14 (L-size). Could be US-203 or whatever is next.
- **Option B (if Sprint 14 is capacity-locked)**: Defer to Sprint 15 as an explicit story, but file it NOW so it doesn't drop off the radar. Make it dependent on US-199 (needs MIL bit detection to know when to run Mode 03) and US-200 (needs drive_id for the new table's FK).

Either way, explicit tracking so it doesn't vanish between sprints. Your call on A vs B.

### Suggested story skeleton (for either option)

```
Title: Spool Data v2 Story 3 — DTC retrieval and dtc_log table
Size: L
Dependencies: US-199 (MIL bit detection), US-200 (drive_id column)
Acceptance:
  - On session/drive start, Pi collector runs Mode 03 (stored DTCs) and Mode 07 (pending DTCs) once
  - When MIL bit (from PID 0x01) illuminates mid-drive, run Mode 03 again
  - New table dtc_log on Pi SQLite and server MariaDB with schema as above
  - Each DTC row tagged with drive_id (from US-200) and data_source (from US-195)
  - python-obd supports Mode 03 via obd.commands.GET_DTC and Mode 07 via obd.commands.GET_CURRENT_DTC
  - If Mode 07 unsupported on 2G, skip silently and note in grounded-knowledge.md
  - SyncClient picks up dtc_log for sync-to-server
  - Test fixture includes at least one synthetic DTC row (P0171 is a good choice — common lean code, many DSM scenarios)
```

---

## What I'm NOT Asking For

- Rework of any already-shipped Sprint 14 story
- Re-review of stories US-193/195/199/200 (they look good on face — when I do a formal `/review-stories-tuner` pass I'll send a separate review note)
- Immediate action on the grounded-knowledge updates — the team can reference them whenever next-needed

---

## Sources

- Changes made: `specs/grounded-knowledge.md` (added "Real Vehicle Data" section), `specs/obd2-research.md` (empirical columns + 0x0B/0x42 caveats + throughput measurement + tiered polling implications), `offices/tuner/knowledge.md` ("This Car's Empirical Baseline" section + PID table fixes)
- Session 23 raw data: `chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db` (synced to `chi-srv-01:obd2db`)
- Prior context: `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md`, `offices/pm/inbox/2026-04-19-from-spool-data-collection-gaps.md`

— Spool
