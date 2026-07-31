# OBD-II connection — the working recipe (proven live 2026-07-31, engine idling)
**Date**: 2026-07-31
**From**: Spool (Tuning SME)
**To**: Atlas (Architect)
**Priority**: Important (BL-025 — the reference implementation for the service connect path)
**Refs**: BL-025, `offices/tuner/scripts/probe_obd_capabilities.sh`, `src/pi/obdii/obd_connection.py`

CIO asked me to hand you the recipe that actually establishes a live OBD connection. I ran my capability probe against the Pi (`mcornelison@10.27.27.100`) with the engine idling today and got a **full live connection + the service then captured real data**. Here is exactly what worked, reproducible.

## Live proof (today, engine on)
```
status:   Car Connected
port:     /dev/rfcomm0
protocol: ISO 9141-2 (id=3)
Mode 01 supported PIDs discovered: 38 (RPM, COOLANT_TEMP, MAF, O2, trims, TIMING_ADVANCE, ...)
```
Immediately after, `eclipse-obd` captured live `realtime_data`: **RPM 780, BATTERY_V 13.4, SPEED 0.0**, and `connect_success` + `drive_start`/`drive_end` fired. So the recipe works for BOTH the raw path and the service.

## THE RECIPE

### 1. Bluetooth-layer preconditions (must all be true before python-obd opens the port)
```bash
# device must be paired AND trusted AND connected. Trusted is what lets BlueZ
# AUTO-RECONNECT after a reboot/power-cycle -- without it the link stays down
# and every read EOFs ("device reports readiness to read but returned no data").
bluetoothctl trust 00:04:3E:85:0D:FB      # <-- I set this today; it was Paired:yes / Trusted:NO
# bind the SPP channel to a tty node:
rfcomm bind 0 00:04:3E:85:0D:FB 1          # -> /dev/rfcomm0  (channel 1 = OBDLink LX SPP)
```
Verify before connecting:
```bash
bluetoothctl info 00:04:3E:85:0D:FB | grep -E 'Paired|Trusted|Connected'
#   Paired: yes / Trusted: yes / Connected: yes   <-- all yes, or the connect will fail
rfcomm -a        #   rfcomm0: ...:FB channel 1  (must NOT say "closed")
```

### 2. python-obd connection (the exact call that connected)
```python
import obd
# what the probe uses -- auto-detect finds /dev/rfcomm0:
o = obd.OBD(fast=False, timeout=10)
# equivalently, forcing the port (what the service does) also works when the BT link is live:
o = obd.OBD(portstr="/dev/rfcomm0", fast=False, timeout=10)

assert o.status() == obd.OBDStatus.CAR_CONNECTED     # "Car Connected"
# protocol auto-negotiates to ISO 9141-2 (id=3) -- do NOT force a protocol
```

### 3. The parameters that matter (and why)
- **`fast=False`** — REQUIRED for this DSM K-line. Fast mode's optimistic ELM timing does not survive ISO 9141-2's slow 5-baud init.
- **`timeout` ≥ 10s** — the K-line is 10,400 bps; short timeouts abort mid-handshake.
- **No forced protocol** — python-obd auto-detects ISO 9141-2 (id=3) correctly. Forcing is unnecessary and brittle.
- **rfcomm channel 1** — the OBDLink LX SPP channel (confirmed via `sdptool browse`, Session 23).
- **Trusted: yes** — the durability piece. A paired-but-untrusted device does not auto-reconnect after the Pi power-cycles (which it does every car-powered drive).

## Reference implementation
`offices/tuner/scripts/probe_obd_capabilities.sh` is the literal code that connected today — the `obd.OBD(fast=False, timeout=10)` block in step 1 of the probe. Use it as the golden path; run it any time to confirm a live connection independent of the service.

## Note on my earlier note (2026-07-27, US-441/US-432 blame) — SUPERSEDED
That note theorized a service-code regression. Today's live run disproves it: my **raw** recipe (none of the US-441/US-432 code) behaved **identically** to the service — it failed when the BT link/trust was absent and succeeded the instant it was present. So the connect path itself is sound; the failure mode is BT-link/trust establishment, not the `_ioLock`/epoch-fence/PID-probe logic. Don't spend the bisect there.

## What I can still do
I own the engine-data verification. Once your durable connect fix is in (I'd anchor it on: **pairing must set `trust`**, and the boot sequence must confirm `Connected: yes` before binding rfcomm), tell me and I'll re-run the probe + confirm a clean captured drive against `realtime_data`/`connection_log`.

— Spool
