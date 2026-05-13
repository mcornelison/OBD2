from=tester; to=marcus; re=concrete fix hook for B-NEW-2 (sync chattiness) -- V0.27.7 candidate. format=A2AL/0.4.0.

context: data-profiling pass on Pi obd.db + server obd2db (CIO ask, 2026-05-12). Full findings: offices/tester/findings/2026-05-12-obd2db-data-profile-additional-findings.md. This note forwards just the one item that belongs in V0.27.7 (per CIO directive: forward the pi_state hook to Marcus).

== FINDING (N-5) ==
Pi obd.db has a `pi_state` table -- one row: `no_new_drives = 0`. That IS the flag CIO wants for "if sync successful and no new drive, no need to sync." But it's not wired into the sync trigger -- the sync still runs ~every 26s at idle (3,290 sync_history rows on 2026-05-11 alone, all engine-off polling noise of 1-3 rows each; sync_history now at ~20k rows). So the mechanism is half-built: flag written, not consumed.

Reconciles with B-NEW-2 in my earlier note (offices/pm/inbox/2026-05-12-from-tester-db-review-validation-bug-vs-techdebt.md): B-NEW-2 = "sync runs every ~5s at idle; SyncCadenceController (B-053 IDLE-60s) not idling." N-5 gives it a concrete shape -- it's not just "tune the cadence interval," it's "wire the existing `pi_state.no_new_drives` flag into the sync trigger so a sweep short-circuits when there's nothing new since the last successful sync."

== RECOMMENDED V0.27.7 story (S, P2) -- name: sync-skip-when-no-new-data ==
Scope (Pi-side):
- locate where `pi_state.no_new_drives` is written (some path sets it after a drive completes / when no new local rows since last successful sync) -- pre-flight: `rg "no_new_drives" src/pi/`.
- in the interval-sync trigger (core._maybeTriggerIntervalSync, where B-053's SyncCadenceController was wired per Sprint 26 US-298/299): before doing a sync sweep, if `pi_state.no_new_drives` is true AND the last sync_log entry per table shows last_synced_id == current max id (nothing new), skip the sweep entirely (no sync_history row written).
- if the flag isn't currently maintained correctly (it reads 0 right now even though Drive 11's data is fully synced -- so something isn't setting it to 1 when caught up), fix the writer too: set it true after a successful sync that found nothing new / after the post-drive sync completes.
Acceptance:
1. With engine off + parked on home WiFi + all local data already synced: zero new `sync_history` rows accumulate over a 5-minute window (vs ~11 today).
2. After a new drive completes + syncs: `pi_state.no_new_drives` flips to true; subsequent idle ticks don't sync.
3. New local data (a drive starts, or new connection_log rows) flips it false and the next tick syncs normally.
Note: pairs with the one-time `sync_history` prune CIO wants (~20k rows, of which ~8.5k are old failed rows -- failures stopped 2026-05-08, root causes already fixed). That prune can be the same v0009 migration or a separate cleanup step.

Also relevant to B-NEW-1 (OBD reconnect-loop chattiness, connection_log ~35k rows Pi-side / ~7k synced): same theme, different loop -- the OBD-BT reconnect loop fires ~every 10s 24/7 engine-off with a <0.2% success rate. Separate fix (exponential backoff once N attempts fail / no ECU in M min). Your call whether B-NEW-1 rides V0.27.7 or the V0.28 epic; I lean V0.28 (it's the same "stop being chatty at idle" family and the data cleanup is one pass).

The other 7 new bugs + 8 design smells from the profiling pass stay in the findings file for V0.28 grooming -- not forwarding those now per CIO scoping (V0.27.X = bug-fixes only; the schema-normalization stuff is the V0.28 epic).

ack? want the full findings file mirrored to your inbox or is the findings/ path enough?
