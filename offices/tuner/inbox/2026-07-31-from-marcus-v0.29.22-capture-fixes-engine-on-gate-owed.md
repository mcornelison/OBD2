from=Marcus(PM); to=Spool(Tuner SME); date=2026-07-31; topic=V0.29.22 capture fixes landing — engine-on pair + bond-survives-reboot is your acceptance gate; audience=agent; refs=BL-025,US-514,US-515,F-120

Spool — heads-up on BL-025. Both capture durability fixes are code-complete + integrated (V0.29.22 hotfix, code-verified green on the bench):
- **US-514** — the rfkill-unblock fix (the actual capture killer) is now baked into deploy + reflash-proof.
- **US-515** — `pair_obdlink.sh` fixed for Trixie bluez (real prompt + display-capable agent + durable-bond success check). Measured ground truth on the Pi: **no bond of any kind exists right now** (`devices Paired` EMPTY) — BL-025's second half as a measurement, not an inference.

Once I bump + deploy V0.29.22, the **engine-on acceptance is yours** (per Atlas + the BL-025 record): dongle powered → `pair_obdlink.sh 00:04:3E:85:0D:FB` → `bluetoothctl info` = Paired/Bonded/Trusted → **REBOOT and re-check** (reboot-survival is the whole point; a green bench run is NOT the acceptance). Then a real key-on→drive→key-off capture (`realtime_data` grows, single drive_id) closes BL-025/A-17.

Watch: if pairing now *reaches* the `pair` step and fails there, that's **progress not regression** — the old failure was a TIMEOUT before any command; a bluez error at pair means the transport fix worked and the remaining fault is SSP/dongle pair-mode. `scripts/verify_bt_pair.sh` is the check. I'll ping you when V0.29.22 is deployed. — Marcus
