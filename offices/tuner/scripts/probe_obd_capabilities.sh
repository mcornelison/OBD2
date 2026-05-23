#!/usr/bin/env bash
# probe_obd_capabilities.sh -- probe what the ECU exposes via OBD-II.
#
# Use case: any time the ECU changes (swap, EPROM update, calibration change),
# run this to enumerate what the new ECU advertises beyond the standard 16 Mode 01
# PIDs we routinely poll. Looks for:
#
#   1. Mode 01 supported-PID bitmap (PID 0x00 / 0x20 / 0x40 / 0x60 chains)
#      -- the full standard-namespace surface, named where python-obd knows the name
#   2. Mode 09 (vehicle info) -- VIN, calibration ID, ECU name, CVN
#      -- reveals the modified EPROM signature if it identifies itself
#   3. Speculative Mode 22 enhanced-diagnostic probes
#      -- vendor-specific extended PIDs. Stock 2G usually doesn't respond; modified
#         EPROMs sometimes do. Worth a 30-second poke.
#
# Cost: pauses eclipse-obd for ~60 seconds. Live telemetry drops during that window;
# DriveDetector may end the current drive_id and start a new one when service restarts.
# Do NOT run mid-WOT. Idle or engine-off only.
#
# Usage:
#   ./probe_obd_capabilities.sh                       # prints to stdout
#   ./probe_obd_capabilities.sh > /tmp/probe.txt      # save to file
#
# Authority: Spool (Tuner SME). Lives in offices/tuner/scripts/ because it's a
# tuning-surface diagnostic, not a sprint-shipped feature.

set -uo pipefail

REMOTE="${REMOTE:-chi-eclipse-01}"
VENV_PY="${VENV_PY:-/home/mcornelison/obd2-venv/bin/python}"
WORKDIR="${WORKDIR:-/home/mcornelison/Projects/Eclipse-01}"

echo "===== OBD CAPABILITY PROBE $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
echo "remote=$REMOTE  venv=$VENV_PY  workdir=$WORKDIR"
echo

ssh "$REMOTE" bash -s <<REMOTE_SCRIPT
set -uo pipefail

echo "--- pausing eclipse-obd ---"
sudo -n systemctl stop eclipse-obd
sleep 3

echo "--- running probe ---"
cd "$WORKDIR"
"$VENV_PY" - <<'PYEOF' 2>&1
import obd
import time
from obd import OBDCommand, OBDStatus
from obd.protocols import ECU
from obd.decoders import raw_string, encoded_string, count

print()
print("=== 1. Connection ===")
o = obd.OBD(fast=False, timeout=10)
print(f"status:   {o.status()}")
print(f"port:     {o.port_name()}")
print(f"protocol: {o.protocol_name()} (id={o.protocol_id()})")
if o.status() != OBDStatus.CAR_CONNECTED:
    print("ECU NOT CONNECTED -- abort probe")
    raise SystemExit(2)

print()
print("=== 2. Mode 01 -- supported standard PIDs ===")
print(f"discovered_count: {len(o.supported_commands)}")
print()
print(f"{'PID':<8} {'NAME':<32} {'DESCRIPTION'}")
print("-" * 80)
for cmd in sorted(o.supported_commands, key=lambda c: (c.command or b'').decode(errors='replace')):
    code = (cmd.command or b'').decode(errors='replace')
    print(f"{code:<8} {cmd.name:<32} {cmd.desc}")

print()
print("=== 3. Mode 09 -- vehicle info / calibration identity ===")
# python-obd has a few Mode 09 commands; query the most useful ones manually.
mode09_probes = [
    ("0900", "Supported Mode 09 PIDs bitmap", count),
    ("0902", "VIN",                            encoded_string(17)),
    ("0904", "Calibration ID",                 raw_string),
    ("0906", "Calibration Verification Number (CVN)", raw_string),
    ("090A", "ECU Name",                       raw_string),
]
for cmd_hex, label, decoder in mode09_probes:
    custom = OBDCommand(label, label, bytes.fromhex(cmd_hex), 32, decoder, ECU.ENGINE, False)
    try:
        resp = o.query(custom, force=True)
        if resp.is_null():
            print(f"  {cmd_hex}  {label:<48} -> NO RESPONSE")
        else:
            print(f"  {cmd_hex}  {label:<48} -> {resp.value!r}")
    except Exception as e:
        print(f"  {cmd_hex}  {label:<48} -> ERR: {e}")
    time.sleep(0.3)

print()
print("=== 4. Mode 22 -- vendor enhanced diagnostic (speculative) ===")
# Mode 22 takes a 16-bit PID. Probe a few common Mitsubishi/DSM addresses.
# If ANY of these come back non-null, the ECU implements Mode 22.
mode22_probes = [
    "2202", "2204", "2210", "2220",
    "2240", "2280", "22F101", "22F190",
]
mode22_found = False
for cmd_hex in mode22_probes:
    custom = OBDCommand(f"Mode22_{cmd_hex}", f"Mode22 PID {cmd_hex[2:]}",
                        bytes.fromhex(cmd_hex), 32, raw_string, ECU.ENGINE, False)
    try:
        resp = o.query(custom, force=True)
        if resp.is_null():
            print(f"  {cmd_hex:<10} -> NO RESPONSE (NORMAL for stock ECU)")
        else:
            print(f"  {cmd_hex:<10} -> {resp.value!r}  <-- ECU RESPONDED")
            mode22_found = True
    except Exception as e:
        print(f"  {cmd_hex:<10} -> ERR: {e}")
    time.sleep(0.3)

print()
if mode22_found:
    print(">>> Mode 22 SUPPORTED -- enhanced diagnostic surface available <<<")
else:
    print(">>> Mode 22 not advertising on common addresses (stock-2G typical) <<<")

print()
print("=== 5. Adapter / ELM info ===")
# Use python-obd interface for raw AT commands to OBDLink.
try:
    iface = o.interface
    for at_cmd in [b"ATI", b"ATRV", b"AT@1", b"AT@2", b"STDI"]:
        try:
            r = iface.send_and_parse(at_cmd)
            val = r[0].raw() if r else None
            print(f"  {at_cmd.decode():<8} -> {val!r}")
        except Exception as e:
            print(f"  {at_cmd.decode():<8} -> ERR: {e}")
        time.sleep(0.2)
except Exception as e:
    print(f"  iface access ERR: {e}")

print()
o.close()
print("=== probe complete ===")
PYEOF
PROBE_EXIT=\$?

echo "--- restarting eclipse-obd ---"
sudo -n systemctl start eclipse-obd
sleep 2
sudo -n systemctl is-active eclipse-obd

echo "--- probe exit: \$PROBE_EXIT ---"
exit \$PROBE_EXIT
REMOTE_SCRIPT
