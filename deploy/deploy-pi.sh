#!/usr/bin/env bash
################################################################################
# deploy-pi.sh — Deploy/update the OBD2v2 Pi tier on chi-eclipse-01 (10.27.27.28)
#
# Usage:
#   bash deploy/deploy-pi.sh                # Default: rsync code + venv deps + restart service
#   bash deploy/deploy-pi.sh --init         # First-time setup: wipe legacy ~/Projects,
#                                           #   create dirs, fresh venv, system deps, hostname
#   bash deploy/deploy-pi.sh --restart      # Just restart the systemd service (no code/deps)
#   bash deploy/deploy-pi.sh --dry-run      # Print what would be done, do nothing on Pi
#   bash deploy/deploy-pi.sh --help         # Show this usage
#
# Configuration (deploy/deploy.conf overrides defaults — gitignored, copy from .example):
#   PI_HOST  - Pi IP or hostname               (default: 10.27.27.28)
#   PI_USER  - SSH user on the Pi              (default: mcornelison)
#   PI_PATH  - Project path on the Pi          (default: /home/mcornelison/Projects/Eclipse-01)
#   PI_PORT  - SSH port                        (default: 22)
#
# Prerequisites:
#   - Key-based SSH from this Windows git-bash to mcornelison@10.27.27.28 already works
#   - rsync available in git-bash AND on the Pi (rsync ships with Raspberry Pi OS)
#   - Local Windows tree at the project root is the source of truth
#
# What this script does:
#   Default mode:
#     1. rsync the working tree to PI_PATH on the Pi (excludes .git/, .venv/, data/, etc.)
#     2. Update venv deps from requirements.txt + requirements-pi.txt at ~/obd2-venv
#     3. Restart eclipse-obd systemd service if installed (warn-only if absent)
#
#   --init mode (additionally):
#     1. Verify SSH gate (ssh PI_USER@PI_HOST hostname) before doing anything
#     2. Wipe pre-sprint ~/Projects/ tree (CIO confirmed safe — verified empty/git-only)
#     3. mkdir -p PI_PATH
#     4. apt install system deps (python3-venv, i2c-tools, pygame/pillow build deps,
#        bluetooth, smbus2 deps)
#     5. Create fresh venv at ~/obd2-venv
#     6. Set hostname to chi-eclipse-01 via hostnamectl + /etc/hosts loopback fix
#     7. Then run the default-mode steps
#
#   --restart mode:
#     1. systemctl restart eclipse-obd (or print clear notice if not installed)
################################################################################

set -e
set -o pipefail

################################################################################
# Defaults (overridable via deploy/deploy.conf)
################################################################################

PI_HOST="10.27.27.28"
PI_USER="mcornelison"
PI_PATH="/home/mcornelison/Projects/Eclipse-01"
PI_PORT="22"

# Always relative to repo root regardless of CWD
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$SCRIPT_DIR/deploy.conf"

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

# Pi-side venv lives in $HOME on the Pi (NOT on a NAS mount).
# Mirrors the server's ~/obd2-server-venv pattern. Resolved over SSH so $HOME
# is the Pi user's home, not the operator's.
REMOTE_VENV='$HOME/obd2-venv'

SERVICE_NAME="eclipse-obd"

################################################################################
# Flag parsing
################################################################################

show_help() {
    cat <<'EOF'
Usage: bash deploy/deploy-pi.sh [MODE]

Modes (mutually exclusive):
  (no flag)   Default: rsync code + venv deps + restart service
  --init      First-time setup: wipe legacy ~/Projects, create dirs, fresh venv,
              system deps (apt), hostname rename to chi-eclipse-01, then default body
  --restart   Just restart the eclipse-obd systemd service (no code/deps changes)
  --dry-run   Print what would be done; perform no changes on the Pi
  --help, -h  Show this help and exit

Configuration (deploy/deploy.conf overrides defaults — gitignored):
  PI_HOST   default: 10.27.27.28
  PI_USER   default: mcornelison
  PI_PATH   default: /home/mcornelison/Projects/Eclipse-01
  PI_PORT   default: 22

Examples:
  bash deploy/deploy-pi.sh --help
  bash deploy/deploy-pi.sh --dry-run         # preview what default mode would do
  bash deploy/deploy-pi.sh --init            # first-time Pi setup
  bash deploy/deploy-pi.sh                   # routine re-deploy
  bash deploy/deploy-pi.sh --restart         # bounce the service after a config edit
EOF
}

INIT=false
RESTART_ONLY=false
DRY_RUN=false

for arg in "$@"; do
    case $arg in
        --init)     INIT=true ;;
        --restart)  RESTART_ONLY=true ;;
        --dry-run)  DRY_RUN=true ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Run 'bash deploy/deploy-pi.sh --help' for usage." >&2
            exit 2
            ;;
    esac
done

if $INIT && $RESTART_ONLY; then
    echo "ERROR: --init and --restart are mutually exclusive." >&2
    exit 2
fi

################################################################################
# Helpers
################################################################################

# Echo + run an SSH command on the Pi (or print only if --dry-run).
remote() {
    local cmd="$1"
    if $DRY_RUN; then
        echo "DRY-RUN ssh ${PI_USER}@${PI_HOST}: ${cmd}"
    else
        ssh -p "$PI_PORT" "${PI_USER}@${PI_HOST}" "$cmd"
    fi
}

# Echo + run rsync to the Pi (or print only if --dry-run).
sync_tree() {
    if $DRY_RUN; then
        echo "DRY-RUN rsync from $REPO_ROOT/ to ${PI_USER}@${PI_HOST}:${PI_PATH}/"
        return 0
    fi
    rsync \
        -az \
        --delete \
        --exclude='.git/' \
        --exclude='.venv/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache/' \
        --exclude='.mypy_cache/' \
        --exclude='.ruff_cache/' \
        --exclude='htmlcov/' \
        --exclude='.coverage' \
        --exclude='node_modules/' \
        --exclude='data/obd.db' \
        --exclude='data/obd.db-shm' \
        --exclude='data/obd.db-wal' \
        --exclude='data/regression/' \
        --exclude='exports/' \
        --exclude='logs/' \
        --exclude='.env' \
        --exclude='deploy/deploy.conf' \
        -e "ssh -p ${PI_PORT}" \
        "$REPO_ROOT/" "${PI_USER}@${PI_HOST}:${PI_PATH}/"
}

# Verify rsync is available locally — fail fast on Windows git-bash without it.
require_rsync() {
    if ! command -v rsync >/dev/null 2>&1; then
        echo "ERROR: rsync is not installed in this shell." >&2
        echo "  On Windows git-bash, install via: pacman -S rsync (in MSYS2)" >&2
        echo "  Or add it to your git-bash environment another way." >&2
        exit 3
    fi
}

# Verify SSH to the Pi works, OR fail with a clear message.
# This is the explicit STOP condition from US-176.
require_ssh() {
    echo "--- SSH gate: verifying ${PI_USER}@${PI_HOST} reachable ---"
    if $DRY_RUN; then
        echo "DRY-RUN ssh check skipped"
        return 0
    fi
    local got
    if ! got=$(ssh -p "$PI_PORT" -o ConnectTimeout=10 -o BatchMode=yes \
                   "${PI_USER}@${PI_HOST}" hostname 2>&1); then
        echo "ERROR: SSH to ${PI_USER}@${PI_HOST} failed:" >&2
        echo "$got" >&2
        echo "Aborting. Resolve SSH access (key auth, network, host key) before retrying." >&2
        exit 4
    fi
    echo "SSH OK. Pi reports hostname: $got"
}

################################################################################
# Step routines (each idempotent)
################################################################################

step_wipe_legacy_projects() {
    # CIO Session 16: confirmed safe to wipe ~/Projects/ leftover content.
    # This routine ONLY runs in --init. Safety verification:
    #   1. List ~/Projects/ entries
    #   2. For each entry that's not the new Eclipse-01 path, confirm it's either:
    #      a git-clone (has .git/) OR an empty dir. Refuse to wipe if anything
    #      else is in there.
    echo "--- Step: Verifying + wiping legacy ~/Projects content ---"
    remote "
        set -e
        cd \$HOME/Projects 2>/dev/null || { echo 'No ~/Projects dir, nothing to wipe.'; exit 0; }
        for entry in * .[!.]*; do
            [ -e \"\$entry\" ] || continue
            target=\$(basename \"\$entry\")
            if [ \"\$target\" = 'Eclipse-01' ]; then
                continue
            fi
            full=\"\$HOME/Projects/\$target\"
            if [ -d \"\$full/.git\" ]; then
                echo \"Removing legacy git clone: \$full\"
                rm -rf \"\$full\"
            elif [ -z \"\$(ls -A \"\$full\" 2>/dev/null)\" ]; then
                echo \"Removing empty legacy dir: \$full\"
                rmdir \"\$full\"
            else
                echo \"REFUSING to remove non-git, non-empty: \$full\"
                echo \"Move or back up its contents first, then re-run --init.\"
                exit 5
            fi
        done
        echo 'Legacy ~/Projects wipe complete.'
    "
}

step_make_project_dir() {
    echo "--- Step: Ensuring ${PI_PATH} exists ---"
    remote "mkdir -p '${PI_PATH}'"
}

step_install_system_deps() {
    echo "--- Step: Installing system packages (apt) ---"
    # Exhaustive list captured during pre-flight audit:
    #   python3-venv, python3-dev          - Python venv + compiled wheels
    #   i2c-tools                          - i2cdetect for X1209 UPS HAT
    #   bluetooth bluez bluez-tools        - OBD-II Bluetooth dongle (future)
    #   libbluetooth-dev                   - Bluetooth Python bindings (future)
    #   libsdl2-* libfreetype6-dev         - pygame on the OSOYOO HDMI display
    #     libjpeg-dev libportmidi-dev
    #   zlib1g-dev                         - Pillow image processing
    #   sqlite3                            - on-Pi DB integrity checks
    #   rsync                              - for self-deploy tooling parity
    remote "
        sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            python3-venv python3-dev \
            i2c-tools \
            bluetooth bluez bluez-tools libbluetooth-dev \
            libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev \
            libfreetype6-dev libjpeg-dev libportmidi-dev \
            zlib1g-dev \
            sqlite3 \
            rsync
    "
}

step_create_venv() {
    echo "--- Step: Creating venv at ${REMOTE_VENV} ---"
    # Idempotent: only create if not already present.
    remote "
        if [ ! -f ${REMOTE_VENV}/bin/python3 ]; then
            python3 -m venv ${REMOTE_VENV}
            echo 'venv created.'
        else
            echo 'venv already exists, skipping creation.'
        fi
        ${REMOTE_VENV}/bin/pip install -q --upgrade pip
    "
}

step_install_python_deps() {
    echo "--- Step: Installing Python deps from requirements.txt + requirements-pi.txt ---"
    remote "
        cd '${PI_PATH}'
        ${REMOTE_VENV}/bin/pip install -q -r requirements.txt -r requirements-pi.txt
        echo 'pip install complete.'
    "
}

step_set_hostname() {
    echo "--- Step: Renaming Pi hostname to chi-eclipse-01 ---"
    # STOP condition from sprint contract: refuse if current hostname is
    # something unexpected (not the documented states). Only proceed for
    # 'raspberrypi' (factory default), 'chi-eclipse-tuner' (prior name), or
    # 'chi-eclipse-01' (already done — no-op).
    remote "
        current=\$(hostname)
        echo \"Current hostname: \$current\"
        case \"\$current\" in
            chi-eclipse-01)
                echo 'Hostname already chi-eclipse-01, skipping rename.'
                ;;
            raspberrypi|chi-eclipse-tuner)
                echo \"Renaming \$current -> chi-eclipse-01\"
                sudo hostnamectl set-hostname chi-eclipse-01
                # Update /etc/hosts loopback so 'sudo' doesn't complain about
                # not being able to resolve the hostname.
                if grep -q \"127.0.1.1.*\$current\" /etc/hosts; then
                    sudo sed -i \"s/127.0.1.1.*\$current.*/127.0.1.1\tchi-eclipse-01/\" /etc/hosts
                elif ! grep -q '127.0.1.1' /etc/hosts; then
                    echo -e '127.0.1.1\tchi-eclipse-01' | sudo tee -a /etc/hosts >/dev/null
                fi
                echo 'Hostname rename complete (full effect after next reboot).'
                ;;
            *)
                echo \"REFUSING to rename: unexpected current hostname '\$current'.\"
                echo 'Expected raspberrypi, chi-eclipse-tuner, or chi-eclipse-01.'
                echo 'Resolve manually, then re-run --init.'
                exit 6
                ;;
        esac
    "
}

step_restart_service() {
    echo "--- Step: Restarting ${SERVICE_NAME} systemd service ---"
    # If service isn't installed yet (US-179 hasn't run), this is a warn, not a fail.
    remote "
        if systemctl list-unit-files | grep -q '${SERVICE_NAME}.service'; then
            sudo systemctl restart ${SERVICE_NAME}
            sleep 1
            sudo systemctl is-active ${SERVICE_NAME} && echo 'Service active.' || echo 'WARN: service not active after restart — check journalctl -u ${SERVICE_NAME}'
        else
            echo 'WARN: ${SERVICE_NAME}.service not installed yet. Skipping restart.'
            echo '       (Install via deploy/install-service.sh — see US-179 in Sprint 10.)'
        fi
    "
}

################################################################################
# Mode dispatch
################################################################################

echo "=== OBD2v2 Pi Deployment ==="
echo "Target:    ${PI_USER}@${PI_HOST}:${PI_PATH}"
echo "Mode:      $($INIT && echo --init || ($RESTART_ONLY && echo --restart || echo default))$($DRY_RUN && echo ' (dry-run)')"
echo "Local:     ${REPO_ROOT}"
echo "Remote venv: ${REMOTE_VENV}"
echo ""

if $RESTART_ONLY; then
    if ! $DRY_RUN; then require_ssh; fi
    step_restart_service
    echo ""
    echo "Deploy OK: $(date -Iseconds) restart-only to ${PI_USER}@${PI_HOST}"
    exit 0
fi

# Dry-run is a preview: don't require local rsync or live SSH. The point is to
# show what WOULD happen even on a workstation that can't actually do it.
if ! $DRY_RUN; then
    require_rsync
    require_ssh
fi

if $INIT; then
    step_wipe_legacy_projects
    step_make_project_dir
    step_install_system_deps
    step_create_venv
    step_set_hostname
fi

# Default-mode body (also runs after --init):
echo "--- Step: Syncing tree to ${PI_PATH} ---"
sync_tree

# venv may not exist on first non-init run on a fresh Pi — create lazily.
remote "
    if [ ! -f ${REMOTE_VENV}/bin/python3 ]; then
        echo 'No venv at ${REMOTE_VENV}; creating.'
        python3 -m venv ${REMOTE_VENV}
        ${REMOTE_VENV}/bin/pip install -q --upgrade pip
    fi
"
step_install_python_deps
step_restart_service

echo ""
echo "Deploy OK: $(date -Iseconds) to ${PI_USER}@${PI_HOST}"
