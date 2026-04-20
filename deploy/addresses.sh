#!/usr/bin/env bash
################################################################################
# addresses.sh -- Canonical bash-side infrastructure addresses (B-044).
#
# This file is the SINGLE SOURCE OF TRUTH for IPs, hostnames, ports, users,
# paths, and the OBDLink MAC as they appear in shell scripts. It mirrors
# config.json's pi.network.* and server.network.* sections -- updating one
# without the other is drift.
#
# Shell scripts source this file and use the exported variables. Callers
# may override any value by pre-setting it in the environment OR in
# deploy/deploy.conf (which is sourced AFTER this file when present and
# takes precedence via the :- fallback pattern).
#
# Usage in a script:
#     SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#     . "$SCRIPT_DIR/../deploy/addresses.sh"
#     # Now $PI_HOST, $SERVER_HOST, etc. are available.
#
# b044-exempt: canonical bash-side mirror of config.json pi.network.* /
# server.network.* / pi.bluetooth.macAddress. Every literal in this file
# must also appear (or be authoritatively set) in config.json. This is the
# analogue of config.json for bash-land consumers and is explicitly
# exempt from the audit_config_literals.py lint.
################################################################################

# ----------------------------------------------------------------------------
# Pi tier (chi-eclipse-01) -- mirrors config.json pi.network.*
# ----------------------------------------------------------------------------
PI_HOST="${PI_HOST:-10.27.27.28}"
PI_USER="${PI_USER:-mcornelison}"
PI_PATH="${PI_PATH:-/home/mcornelison/Projects/Eclipse-01}"
PI_PORT="${PI_PORT:-22}"
PI_HOSTNAME="${PI_HOSTNAME:-chi-eclipse-01}"
PI_DEVICE_ID="${PI_DEVICE_ID:-chi-eclipse-01}"

# ----------------------------------------------------------------------------
# Server tier (chi-srv-01) -- mirrors config.json server.network.*
# ----------------------------------------------------------------------------
SERVER_HOST="${SERVER_HOST:-10.27.27.10}"
SERVER_USER="${SERVER_USER:-mcornelison}"
SERVER_PORT="${SERVER_PORT:-8000}"
SERVER_HOSTNAME="${SERVER_HOSTNAME:-chi-srv-01}"
SERVER_PROJECT_PATH="${SERVER_PROJECT_PATH:-/mnt/projects/O/OBD2v2}"
SERVER_BASE_URL="${SERVER_BASE_URL:-http://${SERVER_HOST}:${SERVER_PORT}}"

# ----------------------------------------------------------------------------
# OBDLink LX Bluetooth MAC -- mirrors config.json pi.bluetooth.macAddress
# ----------------------------------------------------------------------------
OBD_BT_MAC="${OBD_BT_MAC:-00:04:3E:85:0D:FB}"

export PI_HOST PI_USER PI_PATH PI_PORT PI_HOSTNAME PI_DEVICE_ID
export SERVER_HOST SERVER_USER SERVER_PORT SERVER_HOSTNAME SERVER_PROJECT_PATH SERVER_BASE_URL
export OBD_BT_MAC
