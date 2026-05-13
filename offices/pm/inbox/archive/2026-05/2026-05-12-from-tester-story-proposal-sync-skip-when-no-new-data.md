from=tester; to=marcus; re=story proposal -- sync-skip-when-no-new-data (V0.27.7 candidate). format=A2AL/0.4.0.

(standalone copy of the story I recommended in offices/pm/inbox/2026-05-12-from-tester-pi-state-hook-for-sync-chattiness.md -- drop straight into the V0.27.7 sprint if you take it.)

== STORY: sync-skip-when-no-new-data ==
id: US-NEW (yours to assign) | size: S | priority: P2 | closes: B-NEW-2 (sync chattiness; also folds the data-flow half of CIO's "sync_history has too many rows" note)

intent:
At idle (engine off, parked on home WiFi, all local data already synced) the Pi runs a sync sweep ~every 26s -- 3,290 sync_history rows on 2026-05-11 alone, each carrying 1-3 rows of engine-off polling noise; sync_history is now ~20k rows. The Pi already has the gate state: pi_state.no_new_drives (one row, currently 0). It's written but not consumed by the sync trigger. Wire it in so a sweep short-circuits when there's nothing new since the last successful sync; fix the writer if it isn't being set true when caught up (it reads 0 right now even though Drive 11's data is fully synced).

pre-flight (run during grooming, per feedback_pm_run_pre_flight_during_grooming):
- rg "no_new_drives" src/pi/  -- locate the pi_state writer + any existing reader.
- rg "_maybeTriggerIntervalSync|SyncCadenceController" src/pi/  -- confirm where B-053's controller (Sprint 26 US-298/299) is wired; that's the insertion point.
- confirm sync_log.{table}.last_synced_id == current MAX(id) is the cheap "nothing new" check (it is, per the 2026-05-12 profiling pass).

scope.filesToTouch (expect):
- src/pi/ -- the interval-sync trigger (core._maybeTriggerIntervalSync or equivalent): before a sweep, if pi_state.no_new_drives is true AND every synced table's last_synced_id == current max id, skip the sweep entirely (write NO sync_history row).
- src/pi/ -- the pi_state.no_new_drives writer: set true after a successful sync that found nothing new / after the post-drive sync completes; set false when new local data appears (drive starts, new connection_log rows).
- tests: a Pi integration test -- seed a DB with all-synced state + no_new_drives=true, run the trigger, assert no sync_history row + no outbound POST; then add a new realtime_data row, assert the next tick syncs.
doNotTouch: the SyncCadenceController's IDLE/ACTIVE intervals themselves (B-053) -- this is an orthogonal short-circuit on top; the OBD-BT reconnect loop (separate chattiness, B-NEW-1, lean V0.28).

acceptance:
1. engine off + home WiFi + all local data already synced -> zero new sync_history rows over a 5-minute window (vs ~11 today).
2. a new drive completes + syncs -> pi_state.no_new_drives flips true; subsequent idle ticks don't sync.
3. new local data (drive start, or new connection_log rows) flips it false; the next tick syncs normally; sync_history gets exactly one row for that sweep.
4. mod-history comment on touched files cites US-NEW.

pairs with: the one-time sync_history prune CIO wants (~20k rows; ~8.5k are old failed rows -- failures stopped 2026-05-08, root causes already fixed by migration 0006 + a resolved realtime_data optimistic-lock race). Same v0009 migration, or a separate cleanup step -- your call.

sizing note: S, not M -- it's a guard + a flag-writer fix + one test; the mechanism (pi_state.no_new_drives) already exists. The "investigation" is just confirming why the flag currently reads 0 when caught up.

ack? this + the broader N-5 note are the only two V0.27.7-relevant items from the 2026-05-12 profiling pass; the rest (7 more bugs + 8 design smells) are in offices/tester/findings/2026-05-12-obd2db-data-profile-additional-findings.md for V0.28 grooming.
