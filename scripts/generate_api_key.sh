#!/usr/bin/env bash
################################################################################
# generate_api_key.sh -- Emit a fresh 64-hex API key for Pi<->server auth.
#
# Wraps `openssl rand -hex 32`. The output (64 hex characters + newline) is
# printed to stdout so callers can redirect, pipe, or capture via $().
#
# Usage:
#   bash scripts/generate_api_key.sh              # 64-hex to stdout
#   bash scripts/generate_api_key.sh --help       # usage
#
# Consumed by:
#   deploy/deploy-pi.sh --init     (writes to Pi .env as COMPANION_API_KEY)
#   deploy/deploy-server.sh --init (writes to server .env as API_KEY)
#
# Security notes:
#   - 32 bytes of randomness (256 bits) via openssl -- sufficient for any
#     bearer-token scenario short of threat models requiring HSM-backed keys.
#   - Output is NEVER echoed to the terminal when captured via $() -- the
#     calling deploy script is responsible for writing it straight to a .env
#     file with 600 perms, never logging the value.
#
# Exit codes:
#   0 -- key emitted successfully
#   1 -- openssl not available OR rand failed
#   2 -- misuse (unknown argument)
################################################################################

set -e
set -o pipefail

show_help() {
    cat <<'EOF'
Usage: bash scripts/generate_api_key.sh [--help]

Prints a freshly generated 64-hex API key to stdout (nothing else).

Example:
  bash scripts/generate_api_key.sh
    -> ae4c8f...  (64 hex chars)

  bash scripts/generate_api_key.sh > /tmp/key
    -> captured in a file for downstream consumption

No clipboard integration is provided: cross-platform clipboard tools
(xclip, pbcopy, clip.exe) vary too much to standardize, and the usual
flow is "capture via $() in a deploy script that writes it straight
to .env". See deploy/deploy-pi.sh --init and deploy/deploy-server.sh
--init.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $arg" >&2
            show_help >&2
            exit 2
            ;;
    esac
done

if ! command -v openssl >/dev/null 2>&1; then
    echo "ERROR: openssl not found in PATH. Install openssl or use a different" >&2
    echo "       random-source (e.g. 'python -c \"import secrets; print(secrets.token_hex(32))\"')." >&2
    exit 1
fi

openssl rand -hex 32
