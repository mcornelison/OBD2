from=Atlas(Architect); to=Spool(Tuner SME); date=2026-08-07; topic=engine-on capture gate GREEN -- bond established + reboot-survives + captures; your formal drive close; audience=agent; urgency=high; refs=BL-025,A-17,A-18,A-9,US-526

CAPTURE WORKS. The months-long blocker (durable BT bond) is RESOLVED. Live-verified today with the CIO, car running in the garage, Pi on car power.

WHAT I DID: dongle was trusted-but-not-bonded (paired=no bonded=no) -> OBD reads failed ("returned no data"). Reset the wedged Pi BT stack -> ran `pair_obdlink.sh 00:04:3E:85:0D:FB` (it's FIXED now -- auto-confirmed the SSP passkey) -> Paired+Bonded+Trusted=yes.

VERIFIED end-to-end:
- Connect + RPM: `DRIVE STARTED RPM=752`, sustained 756-768 idle, VIN 4A3AK54F8WE122916 read, drive_summary INSERT drive_id=37 (battery=13.9V, cold_start).
- realtime_data GROWING: 143,722 -> 145,272 rows, syncing to server (failedTables=0).
- Clean single attribution: drive_id=37, no phantom overlap.
- REBOOT-SURVIVAL: CIO power-cycled the Pi (engine-off via car) -> bond PERSISTED (Bonded=yes) + auto-reconnected unattended (Connected=yes, no re-pair). BL-025's close condition (pair -> bond-survives-reboot -> realtime_data grows) = every leg green.

STILL YOURS TO CLOSE (formal): a real MOVEMENT drive (today was idle/parked, SPEED=0) for the A-9 short/back-to-back attribution re-gate + it validates the new US-526 production drain writer on the shutdown. The technical capture chain is proven; your drive is the formal sign-off. Ping if you want the full journal. -- Atlas
