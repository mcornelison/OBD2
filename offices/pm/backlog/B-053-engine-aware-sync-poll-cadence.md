# B-053: Engine-aware sync-poll cadence (replace constant 5/sec polling)

| Field      | Value                              |
|------------|------------------------------------|
| Status     | Pending PRD grooming               |
| Priority   | Medium (P2 -- not engine-telemetry-broken; just wasteful) |
| Filed By   | Marcus (PM), 2026-05-05 from CIO observation |
| Filed Date | 2026-05-05                         |
| Sprint     | Sprint 26+ candidate (post engine-telemetry restore) |

## Why

CIO 2026-05-05 inspection of `sync_log` on chi-srv-01: **100,000+ rows; sync attempts firing ~5/sec**. The current poll-driven sync runs constantly regardless of whether there's anything to sync. CIO's correct observation: **between key-on and key-off events, the data-capture layer is dormant** — no new `drive_summary` rows, no `realtime_data` accumulation, no `connection_log` events. The 5/sec polling is meaningful work ~5% of the time and noise the other 95%.

Compounding effects:
- `sync_log` table bloat (100k+ rows; analytics queries slow down; backup cost up)
- Pi CPU + network thrash during idle (battery drain on UPS during long-engine-off windows)
- Server-side cost: each empty sync still incurs API auth + DB read on chi-srv-01
- Once Pi is wired to ignition (CIO car-wiring task), the whole "engine off → Pi off" pattern means the wasted polls happen during the brief UPS-only window before graceful shutdown — even more wasteful

## Design space considered (CIO 2026-05-05 brainstorm)

### Option 1: Event-driven only (sync on drive_start + drive_end only)
- Pro: cleanest; minimal sync_log noise; no wasted polls
- Con: realtime_data accumulates DURING a drive (5-60 min); waiting until drive_end means chi-srv-01 sees the data 5+ min late; loses live-stream-during-drive value
- **NOT RECOMMENDED**

### Option 2: Engine-aware hybrid (RECOMMENDED)
- Idle (engine off): 1 poll/min heartbeat (catches stragglers + connectivity check)
- drive_start event: switch to active polling (1-5/sec; tunable)
- drive_end event: final flush sync + return to heartbeat cadence
- Pro: matches actual workload; preserves live-stream-during-drive; ~99% reduction in idle polls; failure mode parallel to B-047 D7 cooldown pattern
- Con: more complex state machine (idle / active / draining transitions)
- **RECOMMENDED**

### Option 3: Empty-sync exponential backoff
- Stays at 5/sec when active; after N empty syncs → 1s → 2s → 4s → 60s cap; reset on non-empty sync OR drive event
- Pro: simple change; ~95% reduction in idle work
- Con: still polls during idle (just less); doesn't fully match workload

### Option 4: Gate sync_log row insert on actual data movement
- Trivial 1-line fix; underlying poll cadence unchanged
- Pro: cheapest; fixes the table-bloat symptom
- Con: doesn't address wasted CPU/network; only fixes the visible symptom

## Recommended scope (Sprint 26+ candidate)

Implement **Option 2 (engine-aware hybrid)**. Decompose into ~3 user stories:

### Story 1 (M, P2): Sync-state state machine
- New `SyncCadenceController` class in `src/pi/obdii/sync/` with three states: IDLE / ACTIVE / DRAINING
- Listens to drive_start / drive_end events (US-200 engine_state pattern)
- IDLE = 1 poll/min; ACTIVE = configurable cadence (default 1/sec? 5/sec? PRD Q); DRAINING = single final flush sync at drive_end
- Persists last-sync-attempt + last-non-empty-sync timestamps for D7-style cooldown semantics
- Tests: parametrized state-transition fixture covering missed-drive-start fallback (any non-empty heartbeat auto-switches to ACTIVE)

### Story 2 (S, P2): Wire SyncCadenceController into existing sync loop
- Replace existing constant-cadence poll wrapper with controller-driven cadence
- Preserve existing sync_now.py functional behavior (push delta) -- only changes WHEN it fires
- Tests: integration test asserting idle workload < 100 sync attempts/hour vs current ~18,000/hour

### Story 3 (S, P2): Sync-log retention + cleanup migration
- One-shot SQL migration: prune sync_log rows older than configured retention (default 30 days?) PRD Q
- Idempotent; safe to re-run
- Standing rule: future sync_log rows are bounded by Story 1 + 2 cadence reduction (no further bloat)

## Open design questions (PRD grooming)

1. **ACTIVE cadence**: 1/sec? 5/sec? same as current 5/sec? Spool may have an opinion (live-stream visibility for AI analysis vs Pi battery drain during drive).

2. **DRAINING semantics**: single final flush on drive_end is enough? Or do we want a 2-second post-drive-end window to catch any straggler writes that landed between detect-end and flush-fire?

3. **IDLE cadence floor**: 1/min is a heartbeat. Could be 1/5min. CIO's risk-tolerance for "miss a drive_start event for up to 5 min." Tradeoff: lower idle cadence saves more battery; misses a real-drive's first 5 min of data if drive_start event itself fails to fire (would happen on a BT-flake at engine startup).

4. **Failure handoff**: if home WiFi unreachable during a drive, Pi accumulates locally as today. After drive_end + WiFi back: SyncCadenceController in DRAINING mode fires the deferred batch. Test scenario: drive happens away from home → arrive home → DRAINING fires.

5. **sync_log retention**: 30 days? 90 days? cap by row count instead (e.g., last 10k rows)?

6. **Cooldown if server unreachable**: parallel to B-047 D7? After N consecutive failed sync attempts (network/auth error), back off polling. Resume on next drive_start event. Avoids retry-spam if home WiFi is flaky.

## Operator-action gates (action items, NOT sprint stories)

- CIO observes sync_log row-count over a few days post-deploy, confirms cadence change took effect (post-Sprint action: query `SELECT COUNT(*) FROM sync_log WHERE timestamp > date('now', '-1 day')` before/after)
- CIO accepts the live-stream-during-drive cadence (1 vs 5 /sec) chosen during PRD grooming

## Sprint sizing

- Story 1 (state machine) — M
- Story 2 (wire-in) — S
- Story 3 (retention migration) — S

Whole feature: ~5 size-points across 3 stories. Single-sprint-fit.

## Related

- US-242 (Sprint 20 idle-poll → active-poll escalation in DriveDetector) — parallel pattern; the data-capture side already has engine-state-aware cadence; this story brings the SAME pattern to the sync side
- US-200 (Sprint 14 drive_id + engine_state) — provides the drive_start / drive_end events SyncCadenceController consumes
- US-188 (Sprint 13 home-net detection) — orthogonal; separate concern (where to sync, not when)
- B-043 (Pi auto-sync + conditional shutdown) — once car-wiring lands, the engine-off path needs sync_log-cadence reduction more urgently (UPS battery limited)
- B-047 D7 (24-hour cooldown after Pi self-update check) — analogous failure-mode handling; SyncCadenceController could mirror that pattern

## Honest gap (PM Rule 7)

Need to verify CIO's "100,000+ rows / 5 sec cadence" observation against actual sync_log production data. Could be:
- 5/sec average over hours of idle (most likely per CIO observation)
- 5/sec burst during sync attempt → quiet → burst (less likely)
- Per-table sync log + 8 tables = 8/cycle but appears as ~5/sec in casual `tail -f` reading

Pre-flight audit at PRD grooming time should query actual cadence:
```sql
SELECT date(timestamp), COUNT(*) FROM sync_log
GROUP BY date(timestamp) ORDER BY 1 DESC LIMIT 7;
```
to confirm the 5/sec rate before committing to design choices.
