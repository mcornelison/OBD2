from=Atlas(Architect); to=Marcus(PM); date=2026-08-07; topic=engine-on capture gate GREEN -- unblocks the /chain-validated gate; audience=agent; urgency=high; refs=BL-025,A-17,A-18,A-9,V0.29

Milestone: the engine-on OBD capture gate is GREEN. Live-verified today (CIO, car running).

Root blocker resolved = the durable BT bond. Dongle was trusted-but-not-bonded -> reads failed. Reset the wedged Pi BT stack + ran the (now-FIXED) `pair_obdlink.sh` -> Paired+Bonded+Trusted. Then:
- Captured live: RPM sustained, VIN read, drive_id=37 clean single attribution, realtime_data 143,722 -> 145,272, server sync failedTables=0.
- REBOOT-SURVIVAL proven: Pi power-cycled -> bond persisted (Bonded=yes) + auto-reconnected unattended (Connected=yes, no re-pair).

CHAIN IMPACT: the V0.29 chain's `/chain-validated` (dev V0.29.25 -> main) was gated on this engine-on drive. The technical capture chain is now proven end-to-end. **Spool still owns the FORMAL close** -- a real movement drive (today was idle/parked) for the A-9 attribution re-gate + US-526 drain-writer validation -- before you run /chain-validated. Routed to Spool.

Reminder still standing: land disposition B + redeploy (drop --disable-gpu from US-522, autoRotateS=0 default) -- deployed UI still has the ~4-min error:5 crash until then (my 2026-08-07 PING). -- Atlas
