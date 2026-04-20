#!/usr/bin/env bash
################################################################################
# audit_config_literals.sh -- B-044 standing-rule audit wrapper.
#
# Delegates to scripts/audit_config_literals.py (portable Python, stdlib only)
# so the logic is identical whether run from make, a pytest fast-suite lint,
# Windows git-bash, Linux, or the Pi.
#
# Usage:
#   bash scripts/audit_config_literals.sh           # clean report or exit 1
#   bash scripts/audit_config_literals.sh -v        # verbose per-finding listing
#   bash scripts/audit_config_literals.sh --help    # argparse help
#
# Exit codes:
#   0 -- no findings (clean)
#   1 -- one or more hardcoded infrastructure addresses detected
#   2 -- argparse / Python error
################################################################################

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON="${PYTHON:-python}"

exec "$PYTHON" "$SCRIPT_DIR/audit_config_literals.py" --root "$REPO_ROOT" "$@"
