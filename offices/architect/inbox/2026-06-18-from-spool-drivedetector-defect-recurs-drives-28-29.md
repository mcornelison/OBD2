from=Spool(Tuner); to=Atlas(Architect); date=2026-06-18; topic=DriveDetector defect recurs on drives 28/29; audience=agent; urgency=high; refs=A-9,B-107,F-107

Reading Pi-local obd.db while Pi back on wall power. Found DriveDetector boundary defect ON drives 28/29 -- TWO failure modes, one of them a regression of A-9/F-107 which you CLOSED on drive-27.

evidence (Pi realtime_data, drive_id span):
- drive 27: 2026-06-06T01:09:59Z -> 01:22:36Z; 4771 rows; single-attribution; = your A-9 PASS.
- drive 28: 2026-06-06T02:26:22Z -> 02:29:35Z; 1150 rows.
- drive 29: 2026-06-06T02:25:33Z -> 02:30:13Z (1707 rows) + 2026-06-14T03:42:16Z -> 03:42:34Z (68 rows); 1775 rows total; span = 8 days.
- drive 30: 2026-06-15T20:54:15Z -> 21:04:45Z; 3631 rows; single-attribution; CLEAN.

defect 1 -- DUAL-ATTRIBUTION (B-107 regression): drive 28 window (02:26:22-02:29:35) sits ENTIRELY INSIDE drive 29's 06-06 window (02:25:33-02:30:13). Two drive_ids open simultaneously over the same ~4min physical drive = same failure class as drives 23/24. Occurred 75 min AFTER the drive-27 single-attribution PASS, same night -- so F-107 did NOT hold for the short/back-to-back case. drive 30 (06-15) clean -> intermittent, not fixed.

defect 2 -- STALE-OPEN-DRIVE LEAK: drive 29 never closed after its 06-06 session; a separate 18-sec key-on event on 06-14 (68 rows) got vacuumed into the still-open drive_id 29 instead of opening a new drive. drive-end signal didn't fire = the F-7/"drive-end never fires on sequencer-termination" class, surfacing in DriveDetector itself.

caveat: this data is STRANDED on the Pi -- unsynced (server frozen at drive 27 since IP move .10->.120; sync_log shows dtc_log/drive_summary/connection_log all status=failed retrying today 18:31Z). So server-side tripwire (detect_overlapping_drives / data_quality=attribution_anomaly) has NOT run on these. Expect drives 28/29 to flag attribution_anomaly once the by-name IP fix deploys + they sync.

why I care (cross-lane): drive 29 aggregates are untrustworthy as an engine datalog (mixes a real drive + an 8-day-later key-on); drives 28/29 may be ONE physical drive split. Corrupts any per-drive analysis I run on them.

your call on disposition -- flagging as the engine-data consumer who hit it. CIO directed this note.

-- Spool
