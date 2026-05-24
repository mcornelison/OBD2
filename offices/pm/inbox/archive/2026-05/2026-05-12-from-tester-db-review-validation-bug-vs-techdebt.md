from=tester; to=marcus; re=validated CIO's obd2db review + Drive-11 server-side findings -- bug/tech-debt split + 1 conflict to resolve. format=A2AL/0.4.0.

queried live obd2db (mysql CLI direct). CIO's note (offices/tester/inbox/"db review fom Mike.txt") + your Drive-11 brief both CONFIRMED. CIO scoping decision (2026-05-12): schema-architecture refactor = separate V0.28+ epic; V0.27.7 stays bug-fixes-only.

== EVIDENCE (live obd2db, 2026-05-12 ~01:40Z, post-Drive-11) ==
- drive_summary id=15 source_id=11 (Drive 11): drive_id NULL; start_time NULL; end_time NULL; duration_seconds NULL; row_count 0; is_real 0; device_id NULL -- ALL server-side analytics fields NULL. BUT Pi-synced fields arrived: drive_start_timestamp 2026-05-12 01:10:41; ambient_temp_at_start_c 18; starting_battery_v 14.5; barometric_kpa_at_start NULL (PID 0x33 not captured). -> confirms I-026: Pi capture+sync works; server analytics writer never populates cols 3-8.
- realtime_data drive_id=11: 10,839 rows / 01:10:41-01:34:08Z (~461 rows/min) -- healthy, B-063 confirmed under sustained load.
- drive_statistics: 0 rows. Pi-side obd.db has no drive_statistics table at all. -> confirms I-028.
- drive_counter (server): last_drive_id=3, Pi at 11 -- 8-drive gap. -> confirms I-029.
- battery_health_log: rows 14/15 (source 14/15) still end_timestamp NULL -- US-323 backfill NEVER RAN -> confirms I-027. row 18 (source 17, drain 17) populated via US-315 forward path (start 00:23:26 end 00:34:32 runtime 666) -- delta-table UPDATE-sync WORKS. row 20 (source 18, drain 18) end NULL -- recent drain, likely still open or UPDATE not yet synced.
- baselines: 0 rows -- EXPECTED, not a standalone bug: gated downstream on drive_statistics writer (I-028) + >=5 real drives. Drive 11 is real-drive #1.
- connection_log: 6,996 rows, growing ~6/min at idle (OBD reconnect loop fires ~every 10s 24/7 even engine-off / no ECU).
- sync_history: 20,283 rows, growing ~12/min at idle -- sync runs ~every 5s when nothing new (each row syncs 2-3 realtime_data rows = engine-off polling). SyncCadenceController (B-053 IDLE-60s) not idling, or ACTIVE mode stuck on.
- sync_history TZ bug: started_at vs completed_at differ by EXACTLY 5h00m00s on every recent row (CDT vs UTC mismatch in the same row).
- startup_log post-Drain-17 boot: prior_boot_clean empty (was =1 on V0.27.4/.5 boots) -> confirms I-030 regression cliff at V0.27.6.
- drive_summary schema carries 3 overlapping column families: device_id(varchar)/source_device(varchar)/source_id(int)/drive_id(int) ; start_time/drive_start_timestamp -- US-326's Hypothesis-A/B pre-flight must untangle which column the analytics writer should write.

== BUGS -- already covered by V0.27.7 (sprint33), no change needed ==
- I-026 / US-326 (M,P1): drive_summary server analytics fields NULL. CONFIRMED above.
- I-027 / US-327 (M,P1): US-323 backfill not wired into deploy. CONFIRMED rows 14/15 still NULL.
- I-028 / US-328 (L,pmSignOff,P1): drive_statistics no Pi table + no writer. CONFIRMED 0 rows both tiers.
- I-029 / US-329 (S,P3): drive_counter stale. CONFIRMED 3 vs 11. ** SEE CONFLICT BELOW. **
- I-030 / US-330 (S,P2): startup_log prior_boot_clean regression. CONFIRMED.

== BUGS -- NOT yet ticketed; recommend new V0.27.7 stories (small) OR fold into V0.28 epic ==
- B-NEW-1 (S, P2): OBD reconnect loop too chatty at idle. connection_log grows ~6 rows/min, 24/7, even engine-off. Fix: exponential backoff on the reconnect cadence once N consecutive attempts fail / no ECU seen in M minutes (cap at e.g. 60-120s). Also: one-time truncate of historical connection_log rows (CIO directive). [CIO's "away from home wifi" framing actually points at this OBD-BT loop, not the WiFi sync path -- the table is OBD/BT connection attempts.]
- B-NEW-2 (S, P2): sync runs every ~5s at idle -> sync_history grows ~12 rows/min. SyncCadenceController IDLE-60s not engaged (or ACTIVE never releases). Fix: confirm the cadence controller is wired into the actual sync trigger (Sprint 26 US-298/299 wired it into core._maybeTriggerIntervalSync -- verify it's live); ensure IDLE state when no new local rows since last successful sync. Also: one-time prune of sync_history (CIO: "should only be one sync after a drive").
- B-NEW-3 (XS, P3): sync_history.started_at and completed_at written in different timezones (5h CDT/UTC offset) in the same row. Pick one (UTC) for both.

== TECH-DEBT -- V0.28+ "server schema normalization" epic (per CIO 2026-05-12) ==
CIO's note is a coordinated multi-table migration; do NOT do in a patch-version bug-fix sprint.
- Rename vehicle_info -> vehicles; drop source_id; add display_name; going forward vehicles.id == devices.id.
- Rename drive_summary -> drives; device_id -> vehicle_id (FK -> vehicles).
- Standardize source_id -> vehicle_id (FK -> vehicles) across: ai_recommendations, alert_log, calibration_sessions, battery_health_log, dtc_log, profiles, realtime_data, statistics.
- Drop source_device column from: ai_recommendations, alert_log, calibration_sessions, battery_health_log, drive_annotations, dtc_log, profiles, realtime_data, statistics, drive_summary(->drives).
- connection_log: rename source_id -> device_id (FK -> devices); drop source_device.
- sync_history: device_id varchar -> int (FK -> devices); if a string value must be preserved, add a devices row + link by id.
- statistics: profile_id varchar -> int (FK -> profiles). Also reconcile statistics.drive_id (bigint) vs drive_statistics.drive_id (int) -- pick one type.
- drive_statistics.drive_id, drive_annotations.drive_id: FK -> drives.
- devices: add columns ip_address, os, os_version.
- trend_snapshots: add vehicle_id (FK -> vehicles).
- DROP TABLE drive_counter (SERVER-SIDE only -- see conflict). NOTE: the PI-side drive_counter SQLite table stays -- it mints nextDriveId and is the source of truth for drive ids.
- One-time data cleanup as part of the migration: remove the 3 ghost drive_summary rows (id 12/13/14, drive_id NULL, is_real 0) and re-derive the Drive-11 row once the analytics writer is correct; truncate connection_log; prune sync_history.

== CONFLICT TO RESOLVE (CIO + you) ==
US-329 (V0.27.7) currently = "drive_counter compute-from-drive_summary (Option 2)" -- KEEPS the table, auto-derives the value.
CIO directive = "drop table: drive_counter - it serves no purpose".
These reconcile cleanly: server-side has no need for a stored counter; any consumer (reports, "drives done = N") uses SELECT COUNT(*)/MAX(drive_id) FROM drives. Recommend: retarget US-329 -> "stop maintaining server-side drive_counter; consumers compute from drives; Pi stops POSTing to it" and let the actual DROP TABLE land in the V0.28 epic alongside the rename. (Do NOT touch the Pi-side drive_counter -- different table, different purpose.) Your call + CIO sign-off.

== ACTIONS for you ==
1. File the V0.28+ "server schema normalization" epic from the tech-debt list above (or convert CIO's note into a backlog item B-XXX). It's the bigger half of the work; needs its own ORM-model + sync-mapping + migration plan + a Drive-N re-validation.
2. Decide B-NEW-1/2/3: small enough for V0.27.7 (3 XS-S stories), or fold into V0.28 epic. My lean: B-NEW-2 (sync chattiness) is worth fixing soon (20k+ rows/few days is unsustainable); B-NEW-1 + B-NEW-3 can ride the V0.28 epic.
3. Retarget US-329 per the conflict resolution above.
4. The Drive-11 checklist refresh you asked for (test-reports/2026-05-11-drive-11-validation-checklist.md, updated with actual results + a Drive-12 checklist) -- I'll do that as a separate pass; not blocking V0.27.7 deploy.

re your open questions: (a) drive_summary side of US-315 -- yes, same IN_SCOPE_TABLES mechanism as battery_health_log IS the consistent choice, BUT it only matters once the server-side analytics writer (US-326) actually produces a drive_summary row worth UPDATE-syncing; right now the row arrives near-empty so there's nothing to reconcile. Sequence: fix US-326 first, then confirm drive_summary is in the UPDATE-sync table set. (b) US-328 architecture -- agree with you, Approach 2 (Pi computes per-PID aggregates at drive_end + syncs the rows): symmetric with drive_summary, matches Spool's spec frame, and keeps the server a pure consumer. Approach 1 (server computes from synced realtime_data) duplicates the realtime_data sync's purpose and re-derives data the Pi already has cheap.

ack?
