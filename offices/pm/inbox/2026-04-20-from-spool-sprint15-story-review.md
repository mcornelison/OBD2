# Sprint 15 Tuning-Domain Story Review — APPROVED (retroactive, no corrections)

**Date**: 2026-04-20
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine

## Review Scope

Retroactive `/review-stories-tuner` pass on the three **pending** tuning-domain stories in Sprint 15:

- **US-204** — Spool Data v2 Story 3: DTC retrieval Mode 03/07 + `dtc_log` table + server mirror
- **US-206** — Spool Data v2 Story 4: drive-metadata capture (ambient IAT, starting battery, barometric)
- **US-208** — B-037 Pi Sprint kickoff: first-drive validation + post-drive analytics smoke test

US-205 (Session 23 truncate) and US-207 (TD cleanup bundle) skipped — the former is my own request being groomed, the latter is already passed + not a tuning-domain story. US-209 (server schema catch-up) is ops/schema, no tuning values touched.

## Result: APPROVED — no corrections needed

All three stories preserve tuning specification intent faithfully. Spec values match my Priority 3 / Priority 5 / Priority 7 language in `2026-04-19-from-spool-data-collection-gaps.md`, Session 23 empirical fingerprint in `specs/grounded-knowledge.md`, and I-016 disposition criterion.

## Detailed findings

### US-204 — DTC retrieval — ✅ approved

Matches my Priority 2 spec exactly:

| Spec element | Story implementation | Verdict |
|-------------|----------------------|---------|
| Mode 03 at session start | `DtcLogger.logSessionStartDtcs(driveId)` | ✅ |
| Mode 03 on MIL illumination mid-drive | MIL rising-edge (0→1) from US-199 decoder triggers `logMilEventDtcs(driveId)` | ✅ |
| Mode 07 probe-first, skip silently on unsupported | Probe once per session; cache on `ObdConnection`, record to `grounded-knowledge.md` if unsupported | ✅ |
| `dtc_log` schema (7 columns incl. drive_id) | Exact match: dtc_code / description / status CHECK / first_seen / last_seen / drive_id / data_source | ✅ |
| Drive_id inheritance from US-200 context | `setCurrentDriveId` context, NULL drive_id flagged as bug | ✅ |
| Event-driven, NOT tier-scheduled | Invariant #1 explicitly prohibits adding dtc_log to pollingTiers | ✅ |
| Duplicate code handling | Update `last_seen_timestamp` on re-observation, new codes INSERT | ✅ |
| Fixture DTCs | P0171 + P0420 | ✅ matches my spec |

**Bonus discipline** I didn't explicitly require but the story added correctly:
- *"DTC descriptions come from python-obd DTC_MAP; fall through to empty string if unknown. Do NOT invent descriptions — that's specs/ territory."* → excellent. This is exactly the right rule. Mitsubishi P1XXX codes specifically need the DSM cheat sheet I owe you (blocked on first real DTC capture).
- Stop condition on unknown DSM codes → inbox note to me for cheat sheet seeding → correct flow.

**No safety concerns.** DTC retrieval is read-only and cannot change engine behavior.

### US-206 — drive-metadata capture — ✅ approved

Matches my Priority 5 + Priority 7 spec:

| Spec element | Story implementation | Verdict |
|-------------|----------------------|---------|
| Ambient-via-IAT at key-on (cold start only) | `ambient_temp_at_start_c` from `INTAKE_TEMP` cache snapshot only on UNKNOWN/KEY_OFF → CRANKING | ✅ matches intent |
| Warm-restart ambient = unknown | NULL (explicitly called out in invariant as "semantically important") | ✅ **cleaner than my original proposal** |
| Starting battery at key-on | `starting_battery_v` from ELM_VOLTAGE | ✅ |
| Barometric at drive-start (static for drive) | `barometric_kpa_at_start` from PID 0x33 at `_startDrive` | ✅ |
| One row per drive, keyed to drive_id | drive_id as PK FK to drive_counter | ✅ |
| No new polling (consume cached values) | Invariant explicitly prohibits new Mode 01 polls | ✅ |

**Design improvement over my original spec**: I suggested a "confidence flag" for ambient-via-IAT reliability. The story uses NULL semantic instead, with analytics treating NULL as "ambient unknown." This is simpler and more robust than a separate flag — I endorse the refinement.

**Storage unit note**: `ambient_temp_at_start_c REAL NULL` stores Celsius. That's correct — raw PID values are stored native (°C for temps, kPa for pressures) and converted at display layer. Consistent with how `realtime_data` stores COOLANT_TEMP / INTAKE_TEMP. No change needed.

**No safety concerns.** Pure metadata capture, no control path.

### US-208 — first-drive validation + 15-min sustained warmup — ✅ approved

This one deserves more scrutiny because it's the first story to encode my thermostat disposition criterion into executable acceptance. Verified the numbers:

| Criterion | Source | Verdict |
|-----------|--------|---------|
| **180°F (82°C) sustained coolant threshold** | `I-016` disposition + my `specs/grounded-knowledge.md` Session 23 fingerprint flag ("below 180°F after sustained warmup, investigate thermostat") | ✅ correct — this is the thermostat-open temp for a stock 4G63, and the binary "thermostat functional" gate |
| **≥15 minutes continuous sustained idle** | Ralph's review note + I-016 three-hypothesis framing | ✅ adequate for Chicago April ambient (~50-65°F); 15 min at idle-only should reach 180°F if thermostat is functional |
| **"No connection churn"** | TD-023 post-fix stability requirement | ✅ Sprint 14 rfcomm-bind.service makes continuous capture achievable |
| **drive_id = 1 expected (post-US-205 truncate)** | US-205 acceptance #6 | ✅ consistent |

**Critical tuning nuance I want on the record**: the **180°F threshold is a binary "thermostat opened" gate**, not a "full op temp" gate. A truly healthy 4G63 at sustained idle should reach 190-200°F (full op temp). If the drill shows coolant climbing to 180-185°F and plateauing (not reaching 190-200°F), that's *still* a pass for I-016's thermostat-functional disposition, but a flag worth noting for a future drill under load (not just idle). I'll grade accordingly when data comes in.

**AI prompt output grading expectation**: US-208 accepts "insufficient data" as valid output from the Spool AI prompts. For a 15+ min **idle-only** drill (no driving, no load variance), "insufficient data" is the LIKELY correct output — the DESIGN_NOTE.md gates I wrote in Session 4 require trend/correlation data the idle drill won't provide. So "insufficient data" here is the right answer, not a failure. The story correctly anticipates this.

**No safety concerns.** Validator is read-only.

## Recommendations

1. **None blocking — all three stories ship as written.**

2. **Minor drill-protocol suggestion for US-208 execution** (not a story correction, just an observation for when CIO runs the drill): capture an IAT reading BEFORE engine crank during the drill, if the Pi is already running. This nails down the "ambient-via-IAT cold-start" path for US-206 testing simultaneously. CIO's noted that Pi currently runs on wall power (not ignition-switched), so the Pi is already up when he walks up to the car — perfect condition for pre-crank IAT capture.

3. **Bundled drill opportunity** (reinforcing #2): CIO mentioned wanting to also test the "engine restart with Pi still running" scenario. The drill Marcus laid into US-208 already covers this if structured as: **(a)** Pi up, engine off → **(b)** start engine → first drive_id minted → **(c)** run for ≥15 min sustained idle → **(d)** engine off, wait ≥30s → **(e)** restart → new drive_id should mint. That validates the state-machine edge case AND the coolant disposition. One drill, two purposes.

## Sources

- Original spec: `offices/pm/inbox/2026-04-19-from-spool-data-collection-gaps.md` (Priorities 2, 5, 7)
- Session 23 fingerprint: `specs/grounded-knowledge.md` "Real Vehicle Data" section + "Measured Eclipse 4G63 Idle Values"
- I-016 disposition: `offices/pm/issues/I-016-coolant-below-op-temp-session23.md`
- Engine state machine: `src/pi/obdii/engine_state.py` + `specs/architecture.md` §5 Drive Lifecycle

## Approved stories

- US-204 — ready for execution (scheduler gated on US-205 per story dependencies)
- US-206 — ready for execution (gated on US-204)
- US-208 — ready for execution (gated on US-204/205/206)

— Spool
