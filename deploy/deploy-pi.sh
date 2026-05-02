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
#     2. Install/refresh systemd-journald persistent-storage drop-in (US-210, idempotent)
#     3. Enforce POWER_OFF_ON_HALT=0 in Pi 5 EEPROM (US-253, wake-on-power, idempotent)
#     4. Update venv deps from requirements.txt + requirements-pi.txt at ~/obd2-venv
#     5. Restart eclipse-obd systemd service if installed (warn-only if absent)
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
#
# B-044: infrastructure addresses are sourced from deploy/addresses.sh
# (the bash-side mirror of config.json pi.network.*). deploy.conf is
# sourced after, letting per-operator overrides win.
################################################################################

# Always relative to repo root regardless of CWD
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$SCRIPT_DIR/deploy.conf"

# shellcheck source=addresses.sh
. "$SCRIPT_DIR/addresses.sh"

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
    # Defaults shown here come from deploy/addresses.sh via the sourced
    # environment; no literals in heredoc (B-044).
    cat <<EOF
Usage: bash deploy/deploy-pi.sh [MODE]

Modes (mutually exclusive):
  (no flag)   Default: rsync code + venv deps + restart service
  --init      First-time setup: wipe legacy ~/Projects, create dirs, fresh venv,
              system deps (apt), hostname rename to \$PI_HOSTNAME, then default body
  --restart   Just restart the eclipse-obd systemd service (no code/deps changes)
  --dry-run   Print what would be done; perform no changes on the Pi
  --help, -h  Show this help and exit

Configuration (deploy/deploy.conf overrides defaults from deploy/addresses.sh):
  PI_HOST   current: $PI_HOST
  PI_USER   current: $PI_USER
  PI_PATH   current: $PI_PATH
  PI_PORT   current: $PI_PORT

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

# Sync the local tree to the Pi.
# Primary: rsync -az --delete (fast incremental, byte-level idempotent).
# Fallback: tar-over-ssh when rsync isn't installed locally (e.g. vanilla
# Windows git-bash). Spec 1.1 says "rsync or git-based sync" — tar matches
# the same semantics (full content convergence, same excludes). Trade-off:
# fallback re-sends every file on every run (no byte-level incremental).
sync_tree() {
    if $DRY_RUN; then
        local mode='rsync'
        command -v rsync >/dev/null 2>&1 || mode='tar'
        echo "DRY-RUN $mode from $REPO_ROOT/ to ${PI_USER}@${PI_HOST}:${PI_PATH}/"
        return 0
    fi
    if command -v rsync >/dev/null 2>&1; then
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
    else
        echo "NOTE: rsync not installed locally — using tar-over-ssh fallback."
        echo "      Install rsync for faster incremental sync (see deploy/README.md)."
        # Stream a gzipped tarball of the source tree over SSH, then on the Pi:
        # wipe top-level contents except runtime state dirs (data, exports, logs,
        # .env), then extract the tar. Mirrors rsync --delete but at tar granularity.
        ( cd "$REPO_ROOT" && tar -cz \
            --exclude='./.git' \
            --exclude='./.venv' \
            --exclude='./__pycache__' \
            --exclude='*.pyc' \
            --exclude='./.pytest_cache' \
            --exclude='./.mypy_cache' \
            --exclude='./.ruff_cache' \
            --exclude='./htmlcov' \
            --exclude='./.coverage' \
            --exclude='./node_modules' \
            --exclude='./data/obd.db' \
            --exclude='./data/obd.db-shm' \
            --exclude='./data/obd.db-wal' \
            --exclude='./data/regression' \
            --exclude='./exports' \
            --exclude='./logs' \
            --exclude='./.env' \
            --exclude='./deploy/deploy.conf' \
            -f - . ) | \
          ssh -p "${PI_PORT}" "${PI_USER}@${PI_HOST}" "
            set -e
            mkdir -p '${PI_PATH}'
            cd '${PI_PATH}'
            find . -mindepth 1 -maxdepth 1 \
                ! -name 'data' ! -name 'exports' ! -name 'logs' ! -name '.env' \
                -exec rm -rf {} +
            tar -xzf -
          "
    fi
}

# Verify we have SOME way to sync. rsync is preferred; tar+ssh is the fallback.
require_sync_tool() {
    if ! command -v rsync >/dev/null 2>&1 && ! command -v tar >/dev/null 2>&1; then
        echo "ERROR: neither rsync nor tar is installed in this shell." >&2
        echo "  Install one to proceed (rsync preferred for incremental sync)." >&2
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
            swig liblgpio-dev \
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
    # Target hostname flows from addresses.sh ($PI_HOSTNAME). The list of
    # ACCEPTABLE pre-rename states is intentionally hardcoded to
    # legacy/factory names -- those are historical artifacts, not
    # infrastructure addresses, and B-044 does not govern them.
    echo "--- Step: Renaming Pi hostname to ${PI_HOSTNAME} ---"
    remote "
        current=\$(hostname)
        lower=\$(echo \"\$current\" | tr '[:upper:]' '[:lower:]')
        echo \"Current hostname: \$current (normalized: \$lower)\"
        case \"\$lower\" in
            ${PI_HOSTNAME})
                echo 'Hostname already ${PI_HOSTNAME}, skipping rename.'
                ;;
            raspberrypi|chi-eclipse-tuner|chi-eclips-tuner)  # b044-exempt: legacy hostname whitelist for rename step
                echo \"Renaming \$current -> ${PI_HOSTNAME}\"
                sudo hostnamectl set-hostname ${PI_HOSTNAME}
                # Update /etc/hosts loopback so 'sudo' doesn't complain about
                # not being able to resolve the hostname. Match the literal
                # current hostname (preserves case) when sedding.
                if grep -q \"127.0.1.1.*\$current\" /etc/hosts; then
                    sudo sed -i \"s/127.0.1.1.*\$current.*/127.0.1.1\t${PI_HOSTNAME}/\" /etc/hosts
                elif ! grep -q '127.0.1.1' /etc/hosts; then
                    echo -e '127.0.1.1\t${PI_HOSTNAME}' | sudo tee -a /etc/hosts >/dev/null
                fi
                echo 'Hostname rename complete (full effect after next reboot).'
                ;;
            *)
                echo \"REFUSING to rename: unexpected current hostname '\$current'.\"
                echo 'Expected raspberrypi, chi-eclipse-tuner (any case), chi-eclips-tuner (any case), or ${PI_HOSTNAME}.'  # b044-exempt: legacy hostname whitelist
                echo 'Resolve manually, then re-run --init.'
                exit 6
                ;;
        esac
    "
}

step_setup_api_key() {
    # US-201: ensure Pi .env has COMPANION_API_KEY. Idempotent: if already
    # set, no-op (so re-running --init never rotates the key and breaks the
    # already-paired server). When missing, offers two modes:
    #   1. Auto-generate (openssl rand -hex 32) via scripts/generate_api_key.sh
    #   2. Paste an existing value (when pairing with a pre-configured server)
    #
    # The key is written with chmod 600 and NEVER echoed to the terminal
    # in plaintext during the generate path.
    echo "--- Step: Ensuring Pi .env has COMPANION_API_KEY (US-201) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would check/write \$PI_PATH/.env:COMPANION_API_KEY=<64-hex>"
        return 0
    fi

    local keyPresent
    keyPresent=$(ssh -p "$PI_PORT" "${PI_USER}@${PI_HOST}" \
        "grep -E '^COMPANION_API_KEY=.+' '${PI_PATH}/.env' >/dev/null 2>&1 && echo yes || echo no")

    if [ "$keyPresent" = "yes" ]; then
        echo "COMPANION_API_KEY already present in Pi .env -- no change (idempotent)."
        return 0
    fi

    echo "COMPANION_API_KEY missing or empty in Pi .env."
    echo "Choose:"
    echo "  [g] Generate a fresh 64-hex key (recommended for first-time setup)"
    echo "  [p] Paste an existing key (use when pairing with a pre-configured server)"
    echo "  [s] Skip (configure manually later)"
    local choice=""
    read -r -p "Choice [g/p/s]: " choice
    local newKey=""
    case "$choice" in
        g|G)
            newKey=$(bash "$REPO_ROOT/scripts/generate_api_key.sh")
            echo "Generated fresh key (not echoed). Writing to Pi .env..."
            ;;
        p|P)
            read -r -s -p "Paste API key (input hidden, press Enter when done): " newKey
            echo ""
            if [ -z "$newKey" ]; then
                echo "Empty paste -- aborting."
                return 1
            fi
            ;;
        *)
            echo "Skipped. Wire COMPANION_API_KEY into ${PI_PATH}/.env manually later."
            return 0
            ;;
    esac

    # Write via SSH without ever echoing the key to the terminal.
    # Uses `printf '%s\n'` over SSH stdin so the value never appears in
    # `ps` output (which would leak if we passed it as a shell argument).
    printf 'COMPANION_API_KEY=%s\n' "$newKey" | \
        ssh -p "$PI_PORT" "${PI_USER}@${PI_HOST}" \
            "cat >> '${PI_PATH}/.env' && chmod 600 '${PI_PATH}/.env'"
    echo "COMPANION_API_KEY written to ${PI_PATH}/.env (chmod 600)."
}

step_install_journald_persistent() {
    # US-210: install systemd-journald drop-in that flips Storage=auto ->
    # Storage=persistent. Idempotent: re-running rewrites the same content
    # (deploy/journald-persistent.conf is the canonical source) and only
    # restarts systemd-journald when the installed drop-in actually changed.
    # Under --init AND default flow per story scope -- journald persistence
    # is required for every deploy, not just first-time setup.
    #
    # US-230: strengthen the post-check. Pre-US-230 this step only verified
    # `/var/log/journal` existed. Spool's 2026-04-23 post-deploy audit found
    # the parent dir present but EMPTY -- no machine-id subdir -- so logs
    # still flowed to tmpfs /run/log/journal. The US-230 post-check verifies
    # /var/log/journal/<machine-id>/ exists AND `journalctl --disk-usage`
    # reports > 0 bytes. On failure prints the 5 diagnostic outputs
    # (disk-usage, ls, --verify, conf.d contents, is-active) and exits
    # non-zero WITHOUT silently mkdir'ing the subdir (invariant #2).
    echo "--- Step: Installing systemd-journald persistent-storage drop-in (US-210, US-230) ---"
    local sourceFile="deploy/journald-persistent.conf"
    local targetPath="/etc/systemd/journald.conf.d/99-obd-persistent.conf"

    if $DRY_RUN; then
        echo "DRY-RUN would install ${PI_PATH}/${sourceFile} -> ${targetPath}"
        echo "DRY-RUN would: systemctl restart systemd-journald (only if content changed)"
        echo "DRY-RUN would verify: /var/log/journal/<machine-id>/ exists AND journalctl --disk-usage > 0 (US-230)"
        return 0
    fi

    # Install + restart journald only when content changed, so routine
    # re-deploys don't churn the service. The diff check uses `cmp -s`
    # (silent exit 0 = identical) which is the same idempotency trick
    # install-service.sh uses. The US-230 post-check runs unconditionally
    # so that every deploy re-asserts persistence, not just those that
    # triggered a restart (Spool's failure mode was a silent
    # already-installed drop-in on an empty /var/log/journal).
    remote "
        set -e
        sudo mkdir -p /etc/systemd/journald.conf.d
        restarted=false
        if sudo test -f '${targetPath}' && sudo cmp -s '${PI_PATH}/${sourceFile}' '${targetPath}'; then
            echo 'journald drop-in already current at ${targetPath} (no change).'
        else
            sudo install -m 644 '${PI_PATH}/${sourceFile}' '${targetPath}'
            echo 'journald drop-in installed: ${targetPath}'
            sudo systemctl restart systemd-journald
            echo 'systemd-journald restarted.'
            restarted=true
        fi

        # US-230 stopCondition #1: systemd-journald creates /var/log/journal/<machine-id>/
        # on restart when Storage=persistent is set, but may need a moment to write
        # the first log rotation. Seed a short sleep only when we just restarted so
        # subsequent routine deploys on a healthy Pi don't incur the delay.
        if [ \"\$restarted\" = true ]; then
            sleep 2
        fi

        # US-230 post-check: derive machine-id + verify subdir + non-zero disk usage.
        MACHINE_ID=\$(cat /etc/machine-id 2>/dev/null || true)
        if [ -z \"\$MACHINE_ID\" ]; then
            echo 'ERROR: /etc/machine-id missing or empty -- cannot verify persistent journal subdir (US-230).' >&2
            exit 7
        fi
        MACHINE_JOURNAL_DIR=\"/var/log/journal/\$MACHINE_ID\"

        # Single diagnostic bundle emitter; reused by both failure paths
        # (missing subdir, zero disk usage) to print the 5 US-230 AC #3 items.
        emit_journald_diagnostics() {
            echo '' >&2
            echo '--- US-230 journald persistence diagnostics ---' >&2
            echo 'journalctl --disk-usage:' >&2
            journalctl --disk-usage 2>&1 | sed 's/^/  /' >&2
            echo 'ls -la /var/log/journal/:' >&2
            (ls -la /var/log/journal/ 2>&1 || echo '(ls failed)') | sed 's/^/  /' >&2
            echo 'journalctl --verify (head 20):' >&2
            journalctl --verify 2>&1 | head -20 | sed 's/^/  /' >&2
            echo '/etc/systemd/journald.conf.d/ contents:' >&2
            for _f in /etc/systemd/journald.conf.d/*.conf; do
                [ -f \"\$_f\" ] || continue
                echo \"  --- \$_f ---\" >&2
                sed 's/^/    /' \"\$_f\" >&2
            done
            echo \"systemctl is-active systemd-journald: \$(systemctl is-active systemd-journald 2>&1)\" >&2
            echo '' >&2
            echo 'Per US-230 invariant #2: DO NOT silently mkdir /var/log/journal/<machine-id>/' >&2
            echo 'as recovery. Investigate root cause (tmpfs bind, disk-full, SELinux, journald' >&2
            echo 'failed to pick up Storage=persistent). File inbox note before any manual fix.' >&2
        }

        if [ ! -d \"\$MACHINE_JOURNAL_DIR\" ]; then
            echo '' >&2
            echo \"ERROR: persistent journal subdir missing: \$MACHINE_JOURNAL_DIR\" >&2
            echo '  Storage=persistent is set but systemd-journald has not created the' >&2
            echo '  machine-id subdir -- logs are still flowing to tmpfs /run/log/journal.' >&2
            emit_journald_diagnostics
            exit 7
        fi

        # Verify journalctl --disk-usage reports > 0. Output format:
        #   'Archived and active journals take up 24M in the file system.'
        # A just-restarted journald on a healthy Pi has 0B for a ~second or
        # two; we already slept 2s above on restart. A second retry covers
        # slow-disk edge cases before declaring failure.
        DISK_USAGE_OUT=\$(journalctl --disk-usage 2>&1 || true)
        if ! echo \"\$DISK_USAGE_OUT\" | grep -qE 'take up [1-9][0-9.]*[BKMGT]? in'; then
            sleep 3
            DISK_USAGE_OUT=\$(journalctl --disk-usage 2>&1 || true)
            if ! echo \"\$DISK_USAGE_OUT\" | grep -qE 'take up [1-9][0-9.]*[BKMGT]? in'; then
                echo '' >&2
                echo 'ERROR: journalctl --disk-usage reports zero bytes after restart + 3s retry (US-230).' >&2
                echo \"  Output: \$DISK_USAGE_OUT\" >&2
                echo '  Expected: non-zero -- logs are being written to persistent storage.' >&2
                emit_journald_diagnostics
                exit 7
            fi
        fi
        echo \"Persistent journal verified (US-230): \$MACHINE_JOURNAL_DIR present; \$DISK_USAGE_OUT\"
    "
}

step_enforce_eeprom_power_off_on_halt() {
    # US-253: enforce POWER_OFF_ON_HALT=0 in the Pi 5 bootloader EEPROM so that
    # `systemctl poweroff` halts the SoC but leaves the PMIC awake watching the
    # power rails. With 0, wall-power return auto-boots the Pi -- no operator
    # button press needed (the post-B-043 in-car drill: key-OFF -> US-216
    # graceful shutdown -> key-ON -> auto-boot).
    #
    # Idempotent. The standalone script logs no-op when the setting is already
    # 0 or absent (default), and rewrites only when it differs. Errors from
    # rpi-eeprom-config halt the deploy with a clear message rather than
    # silently shipping a broken wake-on-power config.
    echo "--- Step: Enforcing POWER_OFF_ON_HALT=0 in Pi 5 EEPROM (US-253) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/enforce-eeprom-power-off-on-halt.sh"
        echo "DRY-RUN would verify: rpi-eeprom-config exposes POWER_OFF_ON_HALT=0 (or unset = default 0)"
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/enforce-eeprom-power-off-on-halt.sh'"
}

step_install_rfcomm_bind() {
    # US-196: install rfcomm-bind.service so /dev/rfcomm0 is re-bound on every
    # boot. Idempotent — re-running re-writes /etc/default/obdlink with the
    # configured MAC and leaves the unit enabled.
    echo "--- Step: Installing rfcomm-bind systemd unit (US-196 reboot-survive) ---"
    local piEnvMac
    # Best-effort pull of the MAC already configured on the Pi (.env).
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/install-rfcomm-bind.sh \$OBD_BT_MAC"
        return 0
    fi
    piEnvMac=$(ssh -p "$PI_PORT" "${PI_USER}@${PI_HOST}" \
        "grep -E '^OBD_BT_MAC=' '${PI_PATH}/.env' 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\"'\"'\"'" \
        2>/dev/null || true)
    if [[ -z "$piEnvMac" ]]; then
        echo "WARN: OBD_BT_MAC not found in ${PI_PATH}/.env on the Pi — skipping rfcomm-bind install."
        echo "      Run manually later:  sudo bash ${PI_PATH}/deploy/install-rfcomm-bind.sh <MAC>"
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/install-rfcomm-bind.sh' '${piEnvMac}'"
}

step_install_eclipse_obd_unit() {
    # Install deploy/eclipse-obd.service into /etc/systemd/system/ whenever the
    # rsynced copy differs from the installed copy, then systemctl daemon-reload.
    # Idempotent via `cmp -s` -- no-op when content matches. Runs on every deploy
    # (not just --init) because the unit file changes per-sprint (US-192 X11 env,
    # US-198 display, US-210 drop --simulate + Restart=always, etc.) and the
    # rsync into ${PI_PATH}/deploy/ alone does NOT update the systemd-loaded copy.
    # Found during Sprint 16 deploy (2026-04-22): Pi was running with pre-US-210
    # unit (still --simulate, Restart=on-failure) despite deploy succeeding.
    echo "--- Step: Installing ${SERVICE_NAME} systemd unit (sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/${SERVICE_NAME}.service /etc/systemd/system/${SERVICE_NAME}.service || (install + daemon-reload)"
        return 0
    fi
    remote "
        SRC='${PI_PATH}/deploy/${SERVICE_NAME}.service'
        DST='/etc/systemd/system/${SERVICE_NAME}.service'
        if [ ! -f \"\$SRC\" ]; then
            echo 'WARN: \$SRC not present on Pi — skipping unit install.'
            exit 0
        fi
        if sudo test -f \"\$DST\" && sudo cmp -s \"\$SRC\" \"\$DST\"; then
            echo 'eclipse-obd.service already up-to-date; no install needed.'
        else
            echo 'Installing new eclipse-obd.service → /etc/systemd/system/'
            sudo install -m 644 \"\$SRC\" \"\$DST\"
            sudo systemctl daemon-reload
            echo 'Unit installed + daemon-reload complete.'
        fi
    "
}

step_write_deploy_version() {
    # US-241: stamp ${PI_PATH}/.deploy-version with the {version, releasedAt,
    # gitHash, description} record describing this deploy. Composed locally
    # by scripts/version_helpers.py compose-record so the JSON shape lives
    # in one Python module (testable) instead of duplicated bash heredocs.
    # Idempotent: re-running with the same RELEASE_VERSION + git hash
    # overwrites the tier file with a refreshed releasedAt timestamp (so the
    # tier always knows when it was LAST deployed) -- B-047 US-B/C/D consume
    # this ledger via readDeployVersion(); shape is stable from US-A onward.
    #
    # Missing-helper gate: if scripts/version_helpers.py or
    # deploy/RELEASE_VERSION isn't present relative to $REPO_ROOT (test
    # harness, partial sync, hand-extracted tarball), warn + skip rather
    # than abort the deploy. Real deploys always have both files; the gate
    # exists so test_deploy_pi.sh's offline-safe contract holds when only
    # deploy/ is present.
    echo "--- Step: Writing .deploy-version on Pi (US-241) ---"
    local helpersPath="$REPO_ROOT/scripts/version_helpers.py"
    local versionFile="$REPO_ROOT/deploy/RELEASE_VERSION"
    if [ ! -f "$helpersPath" ] || [ ! -f "$versionFile" ]; then
        echo "WARN: skipping .deploy-version step -- missing $(
            [ ! -f "$helpersPath" ] && echo scripts/version_helpers.py
            [ ! -f "$versionFile" ] && echo deploy/RELEASE_VERSION
        ) at $REPO_ROOT"
        return 0
    fi
    local gitHash
    if [ -d "$REPO_ROOT/.git" ]; then
        gitHash=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)
    else
        gitHash="unknown"
    fi
    local versionJson
    versionJson=$(python "$helpersPath" compose-record \
        --version-file "$versionFile" \
        --git-hash "$gitHash") || {
        echo "ERROR: failed to compose release record from $versionFile" >&2
        exit 8
    }
    if $DRY_RUN; then
        echo "DRY-RUN would write to ${PI_PATH}/.deploy-version: ${versionJson}"
        return 0
    fi
    printf '%s\n' "$versionJson" | \
        ssh -p "$PI_PORT" "${PI_USER}@${PI_HOST}" \
            "cat > '${PI_PATH}/.deploy-version'"
    echo "Wrote ${PI_PATH}/.deploy-version: ${versionJson}"
}

step_restart_service() {
    echo "--- Step: Restarting ${SERVICE_NAME} systemd service ---"
    # If service isn't installed yet (fresh Pi before first install), this is a warn, not a fail.
    remote "
        if systemctl list-unit-files | grep -q '${SERVICE_NAME}.service'; then
            sudo systemctl restart ${SERVICE_NAME}
            sleep 1
            sudo systemctl is-active ${SERVICE_NAME} && echo 'Service active.' || echo 'WARN: service not active after restart — check journalctl -u ${SERVICE_NAME}'
        else
            echo 'WARN: ${SERVICE_NAME}.service not installed yet. Skipping restart.'
            echo '       Run a default deploy (not --restart) to install via step_install_eclipse_obd_unit.'
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
    require_sync_tool
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

# US-210: journald persistent-storage drop-in install. Runs under --init AND
# default flow because a) it's idempotent (no-op when already current) and
# b) the drop-in is the canonical source of truth for journald storage, so
# every deploy should reassert it in case /etc/systemd/journald.conf.d/
# was trampled. Runs AFTER sync_tree so deploy/journald-persistent.conf
# exists on the Pi.
step_install_journald_persistent

# US-253: EEPROM POWER_OFF_ON_HALT=0 enforcement. Runs under --init AND default
# flow because the setting could be modified out-of-band on the Pi (any
# `sudo rpi-eeprom-config --edit` rewrites it) and a wrong value silently
# breaks the wake-on-power loop after the next graceful shutdown. The
# standalone script is idempotent -- no-op when already correct. Runs AFTER
# sync_tree so deploy/enforce-eeprom-power-off-on-halt.sh exists on the Pi.
step_enforce_eeprom_power_off_on_halt

# US-196: rfcomm-bind.service install needs to run AFTER sync_tree so
# deploy/install-rfcomm-bind.sh and deploy/rfcomm-bind.service exist on the
# Pi. Only in --init mode — routine re-deploys shouldn't re-toggle systemd.
if $INIT; then
    step_install_rfcomm_bind
    step_setup_api_key
fi

# venv may not exist on first non-init run on a fresh Pi — create lazily.
remote "
    if [ ! -f ${REMOTE_VENV}/bin/python3 ]; then
        echo 'No venv at ${REMOTE_VENV}; creating.'
        python3 -m venv ${REMOTE_VENV}
        ${REMOTE_VENV}/bin/pip install -q --upgrade pip
    fi
"
step_install_python_deps
step_install_eclipse_obd_unit
step_write_deploy_version
step_restart_service

echo ""
echo "Deploy OK: $(date -Iseconds) to ${PI_USER}@${PI_HOST}"
