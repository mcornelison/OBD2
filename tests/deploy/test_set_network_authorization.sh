#!/usr/bin/env bash
################################################################################
# tests/deploy/test_set_network_authorization.sh — ARCH-004 acceptance gate
#
# Verifies deploy/set-network-authorization.sh against synthetic netplan and
# NetworkManager fixtures. Runs entirely on the dev workstation -- no Pi, no
# root, no real network config touched. $NETPLAN_DIR / $NM_CONN_DIR / $NMCLI_BIN
# are the test seams (mirrors $PI_CONFIG_TXT in set-gpu-cma.sh).
#
# Fixture fidelity: scenario 1 reproduces the LIVE Pi's actual state measured
# 2026-08-28 -- home netplan-managed with a networkmanager: block and NO
# priority key, plus an NM-native head-unit profile, BOTH at the default
# priority 0. That tie is the defect; anything less faithful would not exercise
# it.
#
# The PSK in these fixtures is a fake literal. The production script never
# reads, prints or copies a real one, and test 6 pins that.
#
# Usage:
#   bash tests/deploy/test_set_network_authorization.sh
################################################################################
set -uo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/deploy/set-network-authorization.sh"
pass=0; fail=0

ok()   { echo "  PASS: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }
check(){ if [ "$1" = "0" ]; then ok "$2"; else bad "$2"; fi; }

newFixture() {
    FIX="$(mktemp -d)"
    mkdir -p "$FIX/netplan" "$FIX/nm"
    cat > "$FIX/netplan/90-NM-ad591fdd.yaml" <<'YAML'
network:
  version: 2
  wifis:
    wlan0:
      renderer: NetworkManager
      access-points:
        "DeathstarWifi":
          band: "2.4GHz"
          auth:
            key-management: "psk"
            password: "FAKE-NOT-A-REAL-PSK"
          networkmanager:
            name: "netplan-wlan0-DeathstarWifi"
YAML
    cat > "$FIX/nm/DMH-W2770NEX_04A5.nmconnection" <<'CONN'
[connection]
id=DMH-W2770NEX_04A5
type=wifi
autoconnect=true
[wifi]
ssid=DMH-W2770NEX_04A5
[wifi-security]
key-mgmt=wpa-psk
psk-flags=1
CONN
    cat > "$FIX/nm/home.nmconnection" <<'CONN'
[connection]
id=netplan-wlan0-DeathstarWifi
type=wifi
[wifi]
ssid=DeathstarWifi
[wifi-security]
key-mgmt=wpa-psk
psk-flags=1
CONN
    cat > "$FIX/nm/eth0-static.nmconnection" <<'CONN'
[connection]
id=eth0-static
type=ethernet
CONN
}

run() { NETPLAN_DIR="$FIX/netplan" NM_CONN_DIR="$FIX/nm" NMCLI_BIN=true bash "$SCRIPT" >/dev/null 2>&1; }

echo "=== ARCH-004: network authorization ==="

# --- A: home wins -------------------------------------------------------------
echo "[A] home gets a winning autoconnect-priority"
newFixture; run
grep -qE 'connection\.autoconnect-priority: "100"' "$FIX/netplan/90-NM-ad591fdd.yaml"
check $? "priority written into the NETPLAN source (not nmcli, which netplan would revert)"
grep -q 'password: "FAKE-NOT-A-REAL-PSK"' "$FIX/netplan/90-NM-ad591fdd.yaml"
check $? "the auth stanza is untouched -- the PSK survives verbatim"
rm -rf "$FIX"

# --- B: allowlist -------------------------------------------------------------
echo "[B] unauthorized wifi profiles are removed"
newFixture; run
[ ! -e "$FIX/nm/DMH-W2770NEX_04A5.nmconnection" ]
check $? "the head-unit profile is REMOVED (not on the allowlist)"
[ -e "$FIX/nm/home.nmconnection" ]
check $? "the authorized home profile is KEPT"
[ -e "$FIX/nm/eth0-static.nmconnection" ]
check $? "ethernet is untouched -- you cannot roam onto a cable"
rm -rf "$FIX"

# --- C: nothing may prompt ----------------------------------------------------
echo "[C] no wifi profile can require an interactive agent"
newFixture; run
grep -qE '^psk-flags=0$' "$FIX/nm/home.nmconnection"
check $? "home secrets are system-owned -- NM never asks an agent, so no modal"
rm -rf "$FIX"

# --- idempotence --------------------------------------------------------------
echo "[idempotence] safe to re-run on every deploy"
newFixture; run; before="$(cat "$FIX/netplan/90-NM-ad591fdd.yaml")"; run
[ "$before" = "$(cat "$FIX/netplan/90-NM-ad591fdd.yaml")" ]
check $? "a second run changes nothing (drift self-heals without churn)"
n=$(grep -cE 'connection\.autoconnect-priority' "$FIX/netplan/90-NM-ad591fdd.yaml")
[ "$n" = "1" ]
check $? "the priority key appears exactly once after two runs (no duplication)"
rm -rf "$FIX"

# --- drift correction ---------------------------------------------------------
echo "[drift] a wrong pre-existing value is corrected, not duplicated"
newFixture
sed -i 's|            name: "netplan-wlan0-DeathstarWifi"|            passthrough:\n              connection.autoconnect-priority: "0"|' "$FIX/netplan/90-NM-ad591fdd.yaml"
run
grep -qE 'connection\.autoconnect-priority: "100"' "$FIX/netplan/90-NM-ad591fdd.yaml"
check $? "a stale priority 0 -- the live tie -- is corrected to 100"
rm -rf "$FIX"

# --- the script never leaks a secret ------------------------------------------
echo "[security] the script never reads or prints a PSK"
newFixture
out="$(NETPLAN_DIR="$FIX/netplan" NM_CONN_DIR="$FIX/nm" NMCLI_BIN=true bash "$SCRIPT" 2>&1)"
! echo "$out" | grep -q "FAKE-NOT-A-REAL-PSK"
check $? "no passphrase appears anywhere in the script's output"
rm -rf "$FIX"

echo
echo "=== $pass passed, $fail failed ==="
[ "$fail" = "0" ]
