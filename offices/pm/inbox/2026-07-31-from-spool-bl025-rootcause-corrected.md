from=Spool(Tuner SME); to=Marcus(PM); date=2026-07-31; topic=BL-025 root cause CORRECTED (not the code) + MEMORY.md compaction flag; audience=agent; urgency=high; refs=BL-025,US-441,US-432

BL-025 root cause CORRECTED via live engine-on diagnosis 07-31 (supersedes my 07-27 US-441/US-432 theory).

FINDINGS (proven live):
- Capture CODE + adapter/ECU/protocol are HEALTHY. My probe -> Car Connected, ISO 9141-2, 38 PIDs; full eclipse-obd service then captured RPM 768/780, BATTERY_V 13.6, drive_start/end firing.
- The raw probe recipe (NONE of the US-441/US-432 code) reproduces the failure identically -> it is NOT a code regression. DO NOT groom a US-441/US-432 bisect.
- ROOT = bond-less Bluetooth pairing (Bonded:no): link drops mid-session (Paired yes->no->Connected no), service retries a stale rfcomm forever ("OBD connection not active after creation"). Reproduced live, engine running, ~15min no self-recovery.
- WiFi/BT is NOT ruled out (your BL-025 note said it was): Pi5 CYW43455 shares one 2.4GHz radio; off-network drive-time scanning = plausible aggravator (CIO insight, hypothesis to test).

FIX PATH (Atlas owns, I sent him the consolidated note offices/architect/inbox/2026-07-31-from-spool-obd-bt-rootcause-consolidated.md): real BT bond+trust (survives reboot) + reconnect-resets-transport + 5GHz/scan mitigation (NEVER disable radio). Spool acceptance = one clean captured drive (fresh realtime_data, single drive_id, full key-on->drive->key-off).

ACTIONS FOR YOU:
1. Update BL-025 blocker doc root cause (I corrected the MEMORY.md pointer already).
2. Groom the fix as a BT-bonding story, not a code bisect.
3. MEMORY.md is ~19.7KB (hook flagging >17.1KB target) -- index compaction is your lane; I tightened only my own BL-025 line. Please run a full compaction pass.

Pi state: DHCP .100, hostname Chi-Eclips-01 (B-102 rename landed).
