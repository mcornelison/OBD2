#!/usr/bin/env bash
################################################################################
# set-network-authorization.sh — ARCH-004: which networks this Pi may join
#
# THE REQUIREMENT (CIO, 2026-08-28), stated as he stated it:
#   "As I pull into the garage, the auto connection should connect to the home
#    WiFi and sync up before the whole system shuts down. That is the perfect
#    solution. So I would almost prefer us disabling the ... auto connect to
#    networks that are not pre-authorized."
#
# THE RESEARCH THAT CHANGED THE FIX. The obvious lever -- turn autoconnect off
# -- is WRONG, and the CIO caught it before it was built. NetworkManager does
# not roam onto unknown APs: it only auto-joins a network it holds a saved
# PROFILE for. **The allowlist already exists; it is the saved-profile list.**
#
# So the Pi was not "searching". It joined the car stereo because a profile for
# the stereo had been saved, and because -- measured on the live Pi 2026-08-28:
#
#   netplan-wlan0-DeathstarWifi   autoconnect yes   priority 0
#   DMH-W2770NEX_04A5             autoconnect yes   priority 0   <-- a TIE
#
# Both at priority 0. Pulling into the garage with the head unit powered, BOTH
# APs are in range and which one wins is not deterministic. That -- not a
# connection failure -- is why garage sync was unreliable.
#
# Hence three changes, which are one solution:
#
#   A. HOME WINS. Give the home profile a high autoconnect-priority. POSITIVE
#      control (prefer home) rather than negative control (block the stereo):
#      it keeps working when a future profile is added, which a blocklist would
#      not. This is the change that actually delivers the garage requirement.
#
#   B. THE STEREO IS NOT AN AUTHORIZED NETWORK. Its AP offers no route to the
#      server, so there is nothing on it we want. Removing the profile removes
#      it from the allowlist.
#
#   C. NOTHING MAY EVER ASK A QUESTION. An unattended device has nobody to
#      answer a credential prompt, so a prompt is a hang that presents to the
#      driver as a crash -- and it lands on top of the dashboard. Marking every
#      authorized secret SYSTEM-OWNED means NetworkManager never needs an agent
#      and therefore never raises a dialog.
#
# WHY ALL THREE. A alone leaves the Pi joining the stereo when home is out of
# range. B alone is whack-a-mole -- the next saved network re-creates the tie.
# C alone leaves the wrong network winning silently. Together: home always wins
# in the garage, unauthorized networks are never joined, and no dialog can ever
# cover the instrument.
#
# WHY netplan FOR (A) AND nmcli FOR (B). They are stored in different places,
# and using the wrong tool means the change is silently reverted:
#   - home  = NETPLAN-managed (/etc/netplan/90-NM-<uuid>.yaml, renderer
#             NetworkManager). An `nmcli` edit here is regenerated away on the
#             next `netplan apply`. Same class as the A-18 lesson, where a live
#             fix that was not repo-managed would have been lost to a reflash.
#   - stereo = NM-NATIVE (/etc/NetworkManager/system-connections/*.nmconnection),
#             created interactively. netplan does not know about it; nmcli owns
#             it outright.
#
# SECURITY NOTE, deliberate: this script NEVER reads, prints, copies or logs a
# PSK. The home passphrase lives in the netplan YAML (root-only 0600, which is
# normal) and stays there. `autoconnect-priority` is written via the netplan
# networkmanager.passthrough block WITHOUT touching the auth stanza.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/set-network-authorization.sh
#
# Test seam: $NETPLAN_DIR, $NM_CONN_DIR and $NMCLI_BIN may be overridden so the
# whole script runs against fixtures on a dev workstation with no Pi and no
# root (mirrors $PI_CONFIG_TXT in set-gpu-cma.sh, $RPI_EEPROM_CONFIG in US-253).
#
# Idempotent: safe to re-run on every deploy, which is the point -- an OS
# upgrade, a `netplan apply`, or someone tapping an SSID from the desktop can
# all re-introduce drift, and the next deploy heals it.
################################################################################
set -uo pipefail

# --- test seams ---------------------------------------------------------------
NETPLAN_DIR="${NETPLAN_DIR:-/etc/netplan}"
NM_CONN_DIR="${NM_CONN_DIR:-/etc/NetworkManager/system-connections}"
NMCLI_BIN="${NMCLI_BIN:-nmcli}"

# --- policy -------------------------------------------------------------------
# THE ALLOWLIST. A wifi profile whose SSID is not named here is not authorized
# and is removed. Adding an SSID to this list IS the act of authorizing a
# network -- there is no other way in, and that is deliberate.
AUTHORIZED_SSIDS="${AUTHORIZED_SSIDS:-DeathstarWifi}"

# Home must outrank anything that could be added later. NM treats higher as
# stronger; 0 is the default every profile gets, which is how the tie arose.
HOME_PRIORITY="${HOME_PRIORITY:-100}"

changed=0

log()  { echo "[net-auth] $*"; }
warn() { echo "[net-auth] WARNING: $*" >&2; }

isAuthorized() {
    local ssid="$1" allowed
    for allowed in $AUTHORIZED_SSIDS; do
        [ "$ssid" = "$allowed" ] && return 0
    done
    return 1
}

# ------------------------------------------------------------------------------
# A. Home wins: set autoconnect-priority in the NETPLAN source of truth.
# ------------------------------------------------------------------------------
applyHomePriority() {
    local f found=0
    for f in "$NETPLAN_DIR"/*.yaml; do
        [ -e "$f" ] || continue
        grep -q "networkmanager:" "$f" 2>/dev/null || continue
        found=1

        if grep -qE "^\s*connection\.autoconnect-priority:" "$f"; then
            # Present already -- correct it in place if it drifted.
            if grep -qE "^\s*connection\.autoconnect-priority:\s*\"?${HOME_PRIORITY}\"?\s*$" "$f"; then
                log "A: autoconnect-priority already ${HOME_PRIORITY} in $(basename "$f")"
            else
                sed -i -E "s|^(\s*)connection\.autoconnect-priority:.*|\1connection.autoconnect-priority: \"${HOME_PRIORITY}\"|" "$f"
                log "A: corrected autoconnect-priority -> ${HOME_PRIORITY} in $(basename "$f")"
                changed=1
            fi
            continue
        fi

        # Absent -- add it under a passthrough block, creating the block if
        # needed. Anchored on the `networkmanager:` key so the auth stanza
        # (which holds the PSK) is never touched.
        if grep -qE "^\s*passthrough:" "$f"; then
            sed -i -E "0,/^(\s*)passthrough:/s||\1passthrough:\n\1  connection.autoconnect-priority: \"${HOME_PRIORITY}\"|" "$f"
        else
            sed -i -E "0,/^(\s*)networkmanager:/s||\1networkmanager:\n\1  passthrough:\n\1    connection.autoconnect-priority: \"${HOME_PRIORITY}\"|" "$f"
        fi
        log "A: added autoconnect-priority ${HOME_PRIORITY} to $(basename "$f")"
        changed=1
    done
    [ "$found" = "1" ] || warn "A: no netplan file with a networkmanager: block found in $NETPLAN_DIR"
}

# ------------------------------------------------------------------------------
# B. Remove wifi profiles whose SSID is not on the allowlist.
# ------------------------------------------------------------------------------
removeUnauthorizedProfiles() {
    local f base ssid
    for f in "$NM_CONN_DIR"/*.nmconnection; do
        [ -e "$f" ] || continue
        # Only wifi profiles are subject to the allowlist. Ethernet is physical:
        # you cannot roam onto a cable by accident, so it is out of scope here.
        grep -qE "^type=(wifi|802-11-wireless)" "$f" 2>/dev/null || continue

        ssid="$(sed -n 's/^ssid=//p' "$f" | head -n1)"
        base="$(basename "$f")"
        [ -n "$ssid" ] || { warn "B: $base has no ssid= line; leaving it alone"; continue; }

        if isAuthorized "$ssid"; then
            log "B: keeping authorized wifi profile '$ssid'"
        else
            rm -f "$f"
            log "B: REMOVED unauthorized wifi profile '$ssid' ($base)"
            changed=1
        fi
    done
}

# ------------------------------------------------------------------------------
# C. No profile may ever require an interactive agent.
# ------------------------------------------------------------------------------
# psk-flags=0 means "system owned": NetworkManager stores the secret itself and
# never asks an agent for it. Any other value can raise the dialog that was
# photographed sitting on top of the driver's instrument on 2026-08-28.
#
# This is the half of the fix that does NOT depend on getting the network policy
# right: even if an unauthorized profile somehow returns, it cannot put a modal
# over the dashboard.
enforceSystemOwnedSecrets() {
    local f base
    for f in "$NM_CONN_DIR"/*.nmconnection; do
        [ -e "$f" ] || continue
        grep -qE "^type=(wifi|802-11-wireless)" "$f" 2>/dev/null || continue
        base="$(basename "$f")"

        if grep -qE "^psk-flags=" "$f"; then
            if grep -qE "^psk-flags=0\s*$" "$f"; then
                log "C: '$base' secrets already system-owned"
            else
                sed -i -E "s|^psk-flags=.*|psk-flags=0|" "$f"
                log "C: '$base' secrets -> system-owned (was agent-owned: could prompt)"
                changed=1
            fi
        elif grep -qE "^\[wifi-security\]" "$f"; then
            sed -i -E "0,/^\[wifi-security\]/s||[wifi-security]\npsk-flags=0|" "$f"
            log "C: '$base' pinned secrets to system-owned"
            changed=1
        fi
    done
}

# ------------------------------------------------------------------------------
main() {
    log "ARCH-004 network authorization -- allowlist: ${AUTHORIZED_SSIDS}"
    applyHomePriority
    removeUnauthorizedProfiles
    enforceSystemOwnedSecrets

    if [ "$changed" = "1" ]; then
        log "changes applied; reloading NetworkManager connections"
        # Best-effort: on a workstation running the tests these do not exist,
        # and a reload failure must not fail the deploy step.
        command -v netplan >/dev/null 2>&1 && netplan generate >/dev/null 2>&1
        "$NMCLI_BIN" connection reload >/dev/null 2>&1 || true
        log "NOTE: the priority change takes effect on the next association."
    else
        log "no changes needed -- already conformant"
    fi
    return 0
}

main "$@"
