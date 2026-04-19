# TD-023: OBD connection layer treats `macAddress` as a serial-port path

| Field        | Value                                                |
|--------------|------------------------------------------------------|
| Severity     | High (production blocker for first-deploy clean Pi)  |
| Status       | Open                                                 |
| Filed By     | Marcus (PM), Session 23, 2026-04-19                  |
| Surfaced In  | Sprint 13 PM+CIO live drill (US-167 / US-168)        |
| Blocking     | First-time Pi → ECU connection for any user out of the box; partially blocks any future B-043 / US-170 work that runs production main.py |

## Problem

`src/pi/obdii/obd_connection.py:285` constructs the python-OBD client by
passing the **Bluetooth MAC address** straight into `obd.OBD()` as the
serial-port `port` argument:

```python
self.obd = self._obdFactory(self.macAddress, self.connectionTimeout)
```

`obd.OBD(port=...)` expects a serial device path like `/dev/rfcomm0`, NOT
a Bluetooth MAC. python-OBD does not perform BT discovery / rfcomm bind
itself. With a MAC string passed as `port`, pyserial tries to open
`/dev/00:04:3E:85:0D:FB` and fails with `ENOENT`.

Observed in Session 23 drill (full retry chain on cold connection):

```
[obd.elm327] [Errno 2] could not open port 00:04:3E:85:0D:FB: [Errno 2] No such file or directory: '00:04:3E:85:0D:FB'
... (6 attempts, exponential backoff 1s..16s) ...
ERROR pi.obdii.obd_connection | connect | Failed to connect after 6 attempts | mac=00:04:3E:85:0D:FB
ERROR pi.obdii.orchestrator | start | Failed to start orchestrator: OBD-II connection failed after all retry attempts
```

## Workaround Used (Session 23)

CIO/PM drill sidestepped this by:
1. Manually `sudo rfcomm bind 0 00:04:3E:85:0D:FB 1` to expose the SPP as `/dev/rfcomm0`
2. Editing `~/Projects/Eclipse-01/.env` to **lie**: `OBD_BT_MAC=/dev/rfcomm0`
3. Running `python src/pi/main.py` — now `self.macAddress = "/dev/rfcomm0"` flows through unchanged and pyserial opens the path correctly

After the drill, `.env` was restored to the actual MAC `00:04:3E:85:0D:FB`. The Pi is now in a "documented broken" state — production main.py will fail until this TD is addressed.

## Proper Fix (Ralph)

`obd_connection.py.connect()` (or a thin layer above it) should:
1. Detect that `self.macAddress` looks like a MAC (regex `^[0-9A-F]{2}(:[0-9A-F]{2}){5}$`)
2. Verify pairing exists (`bluetoothctl info <MAC> | grep "Paired: yes"`)
3. Idempotently `sudo rfcomm bind 0 <MAC> <channel>` if `/dev/rfcomm0` not already bound
4. Pass `/dev/rfcomm0` (not the MAC) to `obd.OBD(port=...)`
5. On `disconnect()`, `sudo rfcomm release 0` for cleanliness

Or split into two config keys: `pi.bluetooth.macAddress` (BT layer) + `pi.bluetooth.serialPort` (resolved/derived path) so the connection layer cleanly receives a path, with the BT bind step in a separate concern (a startup hook in `eclipse-obd.service` or in `bin/connect_obdlink.sh`).

The latter is closer to what `scripts/connect_obdlink.sh` (saved on Pi during Session 23 drill) does — Ralph can lift that pattern into the production code path.

## Acceptance for Fix

- Fresh-Pi smoke: with only the BT MAC in `.env`, `python src/pi/main.py` connects to a paired LX without manual `rfcomm bind`
- Mocked test in `tests/pi/obdii/test_obd_connection_bt.py` covers the MAC → path resolution
- Idempotent: re-running main.py after a connection drop doesn't fail on "rfcomm0 already bound"
- specs/architecture.md Bluetooth section reflects the actual flow

## Related

- Sprint 13 closeout: `offices/pm/blockers/BL-006.md`
- Pi-side helper: `~/Projects/Eclipse-01/scripts/connect_obdlink.sh` (uncommitted; Ralph to lift to repo)
- TD-024 (sibling Sprint 13 finding): pi.hardware.status_display GL BadAccess
- US-167 carryforward (engineering deliverables to Sprint 14)
