# B-078: sync runs every ~26-40s at idle -- sync_history grows ~1.5 rows/min; engine-off poll loop drives the chatter (V0.28+ design story)

| Field | Value |
|---|---|
| Priority | Medium (P2 -- 20k+ rows in a few weeks is unsustainable; CIO/tester both want this fixed before V0.28+ feature work piles on top) |
| Status | Pending (V0.28+ candidate; V0.27.8 attempt deferred via BL-017 -- the patch-sprint framing was wrong) |
| Category | sync / cadence / data-hygiene |
| Size | M (design story -- two coordinated changes; see "The real fix") |
| Related | Sprint 26 US-298 (SyncCadenceController state machine IDLE-60s / ACTIVE-5s / DRAINING) + US-299 (wired into `core._maybeTriggerIntervalSync`); B-053 (the cadence-controller epic); B-076 (the one-time `sync_history` prune is part of that epic's cleanup step); B-077 (connection_log idle chatter -- same "stop being chatty at idle" family); BL-017 (the failed V0.27.8 attempt + the correct framing); US-225 / TD-034 (`pi_state.no_new_drives` -- the drain-WARNING gate; do NOT repurpose for sync) |
| Created | 2026-05-12 |
| Updated | 2026-05-13 -- framing corrected per BL-017 / Ralph Session 196 pre-flight |

## Description

Tester 2026-05-12 + PM 2026-05-12 live obd2db queries: `sync_history` has 20,381 rows (since 2026-04-16, ~27 days) and growing ~1.5 rows/min idle (15 rows in a 10-min sample) = one sync every ~26-40s. The Sprint 26 `SyncCadenceController` (US-298) was supposed to drop to IDLE-60s when no new local rows since the last successful sync; US-299 wired it into `core._maybeTriggerIntervalSync` (confirmed live, NOT a phantom-path).

**Why IDLE doesn't engage**: the engine-off OBD polling still writes `realtime_data` rows every ~2-3s. So "new local rows since last sync" is *always true* at idle → the controller stays ACTIVE → 5s cadence (or close to it, given throttle). The chatter is not a cadence-controller bug; it's a *system-level* effect of the engine-off poll loop being fast + sync treating every new row as worth a push.

## What V0.27.8 attempted -- and why it was wrong (BL-017)

The V0.27.8 attempt (US-332, the tester's N-5 proposal) was to wire the existing `pi_state.no_new_drives` flag into the sync trigger as a sync-skip gate. **Ralph's pre-flight found this is unusable**:

- `pi_state.no_new_drives` is the **US-225 / TD-034 drain-WARNING drive-id-mint gate** (set true at WARNING@3.70V, used by `DriveDetector._openDriveId` to suppress drive_id minting at CRANKING during a power-down). It is *already consumed*, just not by sync. Repurposing it would regress drive_id minting (NULL drive_id at CRANKING during idle-and-caught-up -- the exact bug class US-326/US-328 just fixed this chain) AND directly contradict its existing "true ⇒ flush sync NOW before poweroff" semantics. One flag cannot carry both meanings.
- Even a *correctly built* sync-skip wouldn't reduce the observed chatter: `SyncClient.pushDelta` already returns `EMPTY` without any POST when the table has no rows past its high-water mark; a truly-idle Pi already writes zero `sync_history` rows. **The rows come from the engine-off poll writing `realtime_data` every 2-3s -- which is the actual driver.**

So a real fix has to touch the engine-off poll loop AND/OR add a dedicated sync-state flag (separate from `no_new_drives`). Both are bigger than a patch-sprint story.

## The real fix (V0.28+ design)

Two coordinated halves, both needed:

1. **Slow/batch the engine-off `realtime_data` poll loop.** When no drive is in progress, either (a) poll less often (e.g., 10-30s instead of 2-3s) -- this is the cleanest; the engine-off polls aren't a tuning data source, they're a connectivity-keepalive + dashboard-display feed and can update at human-perceivable rates; OR (b) batch them locally and only flush to `realtime_data` every N seconds; OR (c) write them to a separate ephemeral table that doesn't sync. Pairs with **B-077 (connection_log idle chatter, ~1.5/min from the OBD-BT reconnect loop)** -- same "stop being chatty at idle" family, related but a different loop.
2. **Add a dedicated sync-state flag** (e.g., `pi_state.sync_idle` -- a NEW column, NOT `no_new_drives`) + a proper writer + a guard in `_maybeTriggerIntervalSync`. Writer: set true after a sweep that pushed 0 rows AND every HWM == MAX(pk); set false when a drive starts OR a non-poll row is written. Guard: skip the sweep entirely when true. (BL-017 Option C.) This piece is only needed if (1) leaves a residue worth short-circuiting; if (1) cuts the poll loop hard enough, the existing `pushDelta` EMPTY short-circuit may already do the job.

Plus (rides B-076's cleanup step, not this story): a one-time prune of the ~20k historical `sync_history` rows (~8.5k of which are old failed rows pre-2026-05-08; the rest are the idle-chatter accumulation).

## What this story is NOT

- Not "make SyncCadenceController IDLE-60s engage" -- it already does what it's specified to do; the spec's "new local rows since last sync" check fires for every poll row.
- Not "wire `pi_state.no_new_drives` into the sync trigger" -- per BL-017, that flag is the drain gate; repurposing it is a regression.
- Not a 1-file fix -- this is at least a poll-loop change + a sync-state design + tests.

## Acceptance Criteria (when groomed for V0.28+)

- [ ] Pre-flight: read the engine-off poll loop (likely in `src/pi/obdii/` collector or data_logger code) + confirm its current cadence + identify which approach (slow vs batch vs ephemeral) fits the existing architecture; decide whether the dedicated sync-state flag is needed in addition to the poll-loop change
- [ ] Engine-off poll cadence reduced (e.g., 10-30s) OR batched, without regressing dashboard / connectivity / `DriveDetector` engage timing
- [ ] If a dedicated `pi_state.sync_idle` is added: it's a NEW column (not `no_new_drives`); writer sets it true after a sweep with 0 rows pushed AND all HWMs == MAX(pk); writer sets it false on drive_start or a non-poll write; guard in `_maybeTriggerIntervalSync`
- [ ] Real-world gate: post-fix deploy, leave the Pi engine-off + parked on home WiFi for 30 min -> `sync_history` grows <= ~1 row/min (down from ~1.5/min); during a drive, sync still fires at the configured ACTIVE cadence (no regression on Drive 12+ data freshness)
- [ ] `pi_state.no_new_drives` byte-untouched (US-225/TD-034 drain gate preserved)
- [ ] One-time prune of historical `sync_history` rides B-076

## Source

- Tester 2026-05-12 db-review note (B-NEW-2) + 2026-05-12 pi-state-hook + sync-skip story-proposal notes (the original N-5 finding -- correct *symptom* identification; *fix* premise was wrong, see BL-017)
- BL-017 resolution 2026-05-13 -- Ralph Session 196 pre-flight that surfaced the `pi_state.no_new_drives` misuse + the engine-off poll being the real driver
- CIO directive 2026-05-12 (one-time `sync_history` prune)
- PM 2026-05-12 live re-query (20,381 rows / 15 in 10 min idle)
