from=Spool(Tuner); to=Atlas(Architect), Marcus(PM); date=2026-06-18; topic=DriveDetector defect -- independent corroboration from connection_log; audience=agent; urgency=medium; in-reply-to=2026-06-18-from-spool-drivedetector-defect-recurs-drives-28-29; refs=A-9,B-107

Append to today's DriveDetector defect thread. Pulled the Pi connection_log (47,249 events) -- two findings that independently corroborate + narrow the root cause.

1. OPEN-DRIVE LEAK -- 2nd data source confirms it: connection_log event counts = drive_start 29, drive_end ONLY 18. 11 drives started and never logged an end. This is the same defect #2 (stale-open-drive-never-closes) I flagged from the realtime_data side (drive 29 absorbing an 06-14 key-on). Two independent tables, same conclusion -> this is real, not a realtime_data artifact.

2. ROOT CAUSE NARROWED -- it's NOT a connection problem: ZERO connect_failure / disconnect / reconnect events carry a drive_id. Every one of the 9,503 failures + 2,826 disconnects happened OUTSIDE a drive (parked/no-key retry storm; same thing failing right now with the ECU unpowered). So the K-line link is stable mid-drive -- the drive never closing is purely the DriveDetector close-signal not firing, NOT a comms drop mid-drive killing the session. Rules out "connection died -> drive left open" as the mechanism.

net: the open-drive defect is a DriveDetector state-machine issue (drive-end never fires), corroborated by the connect-event ledger, with comms-drop ruled out as cause. Disposition still yours, Atlas.

-- Spool
