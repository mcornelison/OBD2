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

# US-354: capture deploy start as epoch BEFORE any step runs. The restart-
# verification step compares each long-running service's
# ExecMainStartTimestamp against this value; a service whose
# ExecMainStartTimestamp is earlier was NOT restarted by this deploy (the
# V0.27.16 dead-code-in-memory bug Argus caught 2026-05-21).
DEPLOY_START_EPOCH="$(date +%s)"

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

step_assert_single_instance_matched_pair() {
    # US-389 (F-107 Root 1 closure, Atlas C-5): the single-instance guard config
    # flag (pi.runtime.singleInstanceGuard.enabled) and the systemd
    # RuntimeDirectory=eclipse-obd are a MATCHED PAIR -- neither may ship without
    # the other.  Enabling the guard WITHOUT RuntimeDirectory makes the non-root
    # orchestrator hit EPERM on mkdir(/run/eclipse-obd) and crash-loop on boot;
    # shipping RuntimeDirectory WITHOUT the guard leaves the Root-1 dual-process
    # attribution defect un-prevented.  This gate FAILS THE DEPLOY before it
    # touches the Pi if either half is missing.
    #
    # Reads LOCAL files only (the source-of-truth config.json + the unit that
    # gets synced), so it runs for real even under --dry-run -- a violation
    # should surface in preview, not on the Pi.
    #
    # Missing-file gate mirrors step_write_deploy_version: if the helper,
    # config.json, or the unit isn't present relative to $REPO_ROOT (test
    # harness, partial sync, hand-extracted tarball), warn + skip rather than
    # abort, so the offline smoke test (deploy/ only) stays green.
    echo "--- Step: Asserting single-instance matched pair (US-389, Atlas C-5) ---"
    local helper="$REPO_ROOT/scripts/deploy_invariants.py"
    local configFile="$REPO_ROOT/config.json"
    local unitFile="$REPO_ROOT/deploy/${SERVICE_NAME}.service"
    if [ ! -f "$helper" ] || [ ! -f "$configFile" ] || [ ! -f "$unitFile" ]; then
        echo "WARN: skipping matched-pair invariant -- missing $(
            [ ! -f "$helper" ] && echo scripts/deploy_invariants.py
            [ ! -f "$configFile" ] && echo config.json
            [ ! -f "$unitFile" ] && echo deploy/${SERVICE_NAME}.service
        ) at $REPO_ROOT"
        return 0
    fi
    if ! python "$helper" check-pair --config "$configFile" --unit "$unitFile"; then
        echo "ERROR: single-instance matched-pair invariant FAILED -- aborting deploy (US-389)." >&2
        exit 10
    fi
}

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

step_install_polkit_poweroff() {
    # US-341 / I-036: install polkit rule granting mcornelison the
    # org.freedesktop.login1.power-off action without interactive auth.
    # Without this rule eclipse-obd.service (running as User=mcornelison)
    # cannot invoke `systemctl poweroff`; the V0.24.1 graceful-shutdown
    # ladder fires TRIGGER, the subprocess returns code=1 with
    # "Interactive authentication required.", and the Pi hard-crashes
    # at buck-dropout floor (~3.30V). Latent since V0.24.1 deploy
    # 2026-05-04 -- every drain 10-22 hard-crashed (Drain 22 forensic,
    # 2026-05-15).
    #
    # Idempotent sync-if-changed mirroring step_install_journald_persistent:
    # cmp -s the rsynced source against the installed copy; install only
    # when the content actually differs. PolicyKit auto-reloads on file
    # change, so no daemon-reload is required.
    echo "--- Step: Installing polkit rule for systemctl poweroff (US-341, I-036) ---"
    local sourceFile="deploy/polkit-rules/50-eclipse-obd-poweroff.rules"
    local targetPath="/etc/polkit-1/rules.d/50-eclipse-obd-poweroff.rules"

    if $DRY_RUN; then
        echo "DRY-RUN would install ${PI_PATH}/${sourceFile} -> ${targetPath}"
        echo "DRY-RUN would: polkit auto-reloads on file change (no daemon-reload)"
        return 0
    fi

    remote "
        set -e
        sudo mkdir -p /etc/polkit-1/rules.d
        if sudo test -f '${targetPath}' && sudo cmp -s '${PI_PATH}/${sourceFile}' '${targetPath}'; then
            echo 'polkit poweroff rule already current at ${targetPath} (no change).'
        else
            sudo install -m 644 '${PI_PATH}/${sourceFile}' '${targetPath}'
            echo 'polkit poweroff rule installed: ${targetPath}'
        fi
    "
}

step_install_polkit_service_control() {
    # US-403 / A-7: install the net-new polkit rule granting mcornelison
    # org.freedesktop.systemd1.manage-units, scoped to a fixed allow-list of
    # eclipse-* units + verbs (eclipse-obd / eclipse-sync / eclipse-dashboard
    # start/stop/restart; eclipse-powerwatch RESTART-ONLY -- stop DENIED at the
    # rule). Lets the unprivileged chromium dashboard kiosk's System Setup menu
    # control services without sudo/root. SIBLING to the 50- poweroff rule (NOT
    # a widening of it -- that rule grants only login1.power-off). Same idempotent
    # sync-if-changed pattern; PolicyKit auto-reloads on file change, so no
    # daemon-reload is required.
    echo "--- Step: Installing polkit rule for systemctl service control (US-403, A-7) ---"
    local sourceFile="deploy/polkit-rules/51-eclipse-service-control.rules"
    local targetPath="/etc/polkit-1/rules.d/51-eclipse-service-control.rules"

    if $DRY_RUN; then
        echo "DRY-RUN would install ${PI_PATH}/${sourceFile} -> ${targetPath}"
        echo "DRY-RUN would: polkit auto-reloads on file change (no daemon-reload)"
        return 0
    fi

    remote "
        set -e
        sudo mkdir -p /etc/polkit-1/rules.d
        if sudo test -f '${targetPath}' && sudo cmp -s '${PI_PATH}/${sourceFile}' '${targetPath}'; then
            echo 'polkit service-control rule already current at ${targetPath} (no change).'
        else
            sudo install -m 644 '${PI_PATH}/${sourceFile}' '${targetPath}'
            echo 'polkit service-control rule installed: ${targetPath}'
        fi
    "
}

step_install_nm_wifi_powersave() {
    # US-325 / I-025: install the NetworkManager drop-in that disables WiFi
    # power-save on the Pi 5.  The BCM4345/6 WiFi+BT combo chip starves WiFi
    # when Bluetooth is busy (the eclipse-obd reconnect heartbeat) and
    # power_save is ON (the Pi 5 default) -- association breaks until a manual
    # reconnect.  CIO observed two WiFi drops in three hours on 2026-05-11;
    # this is Fix #1 (OS-side, Pi 5 best practice), and US-325's reconnect
    # exponential backoff is Fix #2 (reduce BT activity at the source).
    #
    # Idempotent sync-if-changed, mirroring step_install_journald_persistent:
    # cmp -s the rsynced source against the installed copy; install + restart
    # NetworkManager ONLY when the content actually differs, so routine
    # re-deploys don't bounce the network.  Runs under --init AND default flow
    # so a Pi rebuilt from scratch ends up power-save-disabled automatically
    # (CIO 2026-05-11 directive: document the Pi setup changes for a
    # from-scratch rebuild).  Runs AFTER sync_tree so the source file exists
    # on the Pi.
    echo "--- Step: Installing NetworkManager wifi.powersave=2 drop-in (US-325, sync-if-changed) ---"
    local sourceFile="deploy/nm-disable-wifi-powersave.conf"
    local targetPath="/etc/NetworkManager/conf.d/disable-wifi-powersave.conf"

    if $DRY_RUN; then
        echo "DRY-RUN would install ${PI_PATH}/${sourceFile} -> ${targetPath}"
        echo "DRY-RUN would: sudo systemctl restart NetworkManager (only if content changed)"
        return 0
    fi
    remote "
        set -e
        if [ ! -f '${PI_PATH}/${sourceFile}' ]; then
            echo 'WARN: ${sourceFile} not present on Pi -- skipping wifi.powersave drop-in install.' >&2
            exit 0
        fi
        sudo mkdir -p /etc/NetworkManager/conf.d
        if sudo test -f '${targetPath}' && sudo cmp -s '${PI_PATH}/${sourceFile}' '${targetPath}'; then
            echo 'wifi.powersave drop-in already current at ${targetPath} (no change).'
        else
            sudo install -m 644 '${PI_PATH}/${sourceFile}' '${targetPath}'
            echo 'wifi.powersave drop-in installed: ${targetPath}'
            sudo systemctl restart NetworkManager
            echo 'NetworkManager restarted (WiFi power-save now disabled).'
        fi
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

step_install_drain_forensics_unit() {
    # US-277: idempotent sync-if-changed install of drain-forensics.service +
    # drain-forensics.timer into /etc/systemd/system/.  Closes the Sprint 22
    # ship gap that left systemd install as a manual operator post-deploy
    # hook (Spool ran sudo cp + daemon-reload + enable mid-Drain-7).  Mirrors
    # the step_install_journald_persistent + step_install_eclipse_obd_unit
    # pattern: cmp -s on the rsynced source vs the installed copy, and only
    # daemon-reload when something actually changed.  `enable --now` runs
    # unconditionally because it is itself idempotent and ensures the timer
    # is on even if a prior deploy left it disabled.
    #
    # Runtime dirs (idempotent via install -d):
    #   /var/log/eclipse-obd  - drain_forensics.py CSV target (mcornelison)
    #   /var/run/eclipse-obd  - orchestrator-state.json target (mcornelison;
    #                           writer runs in eclipse-obd.service as
    #                           User=mcornelison so the dir owner has to
    #                           match -- root:root would block the write
    #                           and leave the logger CSV's pd_stage +
    #                           pd_tick_count columns at the same -1
    #                           sentinel that motivated US-276 + US-277
    #                           in the first place)
    #
    # /var/run is a tmpfs on Raspberry Pi OS and is wiped on every reboot.
    # This function recreates the dir on every deploy, which covers the
    # routine case (new deploy after CIO power-cycles the Pi).  Cross-boot
    # auto-recreate (without a fresh deploy) is a follow-up via
    # /etc/tmpfiles.d/eclipse-obd.conf; tracked separately per US-277
    # stop-condition #1.
    echo "--- Step: Installing drain-forensics systemd unit (US-277, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo install -d -o mcornelison -g mcornelison /var/log/eclipse-obd"
        echo "DRY-RUN would: sudo install -d -o mcornelison -g mcornelison /var/run/eclipse-obd"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/drain-forensics.service /etc/systemd/system/drain-forensics.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/drain-forensics.timer /etc/systemd/system/drain-forensics.timer || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now drain-forensics.timer"
        return 0
    fi
    remote "
        set -e
        SRC_SVC='${PI_PATH}/deploy/drain-forensics.service'
        DST_SVC='/etc/systemd/system/drain-forensics.service'
        SRC_TIM='${PI_PATH}/deploy/drain-forensics.timer'
        DST_TIM='/etc/systemd/system/drain-forensics.timer'

        if [ ! -f \"\$SRC_SVC\" ] || [ ! -f \"\$SRC_TIM\" ]; then
            echo 'WARN: drain-forensics unit files not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        # Provision runtime dirs unconditionally (install -d is idempotent).
        sudo install -d -o mcornelison -g mcornelison /var/log/eclipse-obd
        sudo install -d -o mcornelison -g mcornelison /var/run/eclipse-obd

        # Sync-if-changed install of the unit pair.  daemon-reload happens
        # only when at least one file actually changed to avoid pointless
        # systemd churn on routine no-op deploys.
        changed=false
        if sudo test -f \"\$DST_SVC\" && sudo cmp -s \"\$SRC_SVC\" \"\$DST_SVC\"; then
            echo 'drain-forensics.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_SVC\" \"\$DST_SVC\"
            echo 'drain-forensics.service installed.'
            changed=true
        fi
        if sudo test -f \"\$DST_TIM\" && sudo cmp -s \"\$SRC_TIM\" \"\$DST_TIM\"; then
            echo 'drain-forensics.timer already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_TIM\" \"\$DST_TIM\"
            echo 'drain-forensics.timer installed.'
            changed=true
        fi

        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload
            echo 'systemd daemon-reload complete.'
        fi

        # enable --now is idempotent: turns the timer on if disabled,
        # leaves it alone otherwise.  Re-asserting on every deploy is the
        # easiest way to recover from an out-of-band 'systemctl disable'.
        sudo systemctl enable --now drain-forensics.timer
        echo 'drain-forensics.timer enabled + active.'
    "
}

step_install_orphan_cleanup_unit() {
    # US-322 / B-072: idempotent sync-if-changed install of orphan-cleanup.service
    # + orphan-cleanup.timer into /etc/systemd/system/.  Closes the V0.27.6 ship
    # gap that would otherwise leave systemd install as a manual operator step.
    # Mirrors step_install_drain_forensics_unit byte-for-byte: cmp -s on the
    # rsynced source vs the installed copy, daemon-reload only when something
    # actually changed, enable --now is idempotent and re-asserted on every
    # deploy so the timer recovers from an out-of-band 'systemctl disable'.
    #
    # The cleanup script touches data/obd.db only -- no extra runtime dirs
    # are required.  Spool's grooming chose Approach 1 (script + nightly
    # timer) over Approach 2 (writer-side guard) for being simpler and
    # reversible: a future deploy can `systemctl disable orphan-cleanup.timer`
    # to revert with no code changes.
    echo "--- Step: Installing orphan-cleanup systemd unit (US-322 / B-072, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/orphan-cleanup.service /etc/systemd/system/orphan-cleanup.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/orphan-cleanup.timer /etc/systemd/system/orphan-cleanup.timer || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now orphan-cleanup.timer"
        return 0
    fi
    remote "
        set -e
        SRC_SVC='${PI_PATH}/deploy/orphan-cleanup.service'
        DST_SVC='/etc/systemd/system/orphan-cleanup.service'
        SRC_TIM='${PI_PATH}/deploy/orphan-cleanup.timer'
        DST_TIM='/etc/systemd/system/orphan-cleanup.timer'

        if [ ! -f \"\$SRC_SVC\" ] || [ ! -f \"\$SRC_TIM\" ]; then
            echo 'WARN: orphan-cleanup unit files not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        # Sync-if-changed install of the unit pair.  daemon-reload happens
        # only when at least one file actually changed to avoid pointless
        # systemd churn on routine no-op deploys.
        changed=false
        if sudo test -f \"\$DST_SVC\" && sudo cmp -s \"\$SRC_SVC\" \"\$DST_SVC\"; then
            echo 'orphan-cleanup.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_SVC\" \"\$DST_SVC\"
            echo 'orphan-cleanup.service installed.'
            changed=true
        fi
        if sudo test -f \"\$DST_TIM\" && sudo cmp -s \"\$SRC_TIM\" \"\$DST_TIM\"; then
            echo 'orphan-cleanup.timer already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_TIM\" \"\$DST_TIM\"
            echo 'orphan-cleanup.timer installed.'
            changed=true
        fi

        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload
            echo 'systemd daemon-reload complete.'
        fi

        # enable --now is idempotent: turns the timer on if disabled,
        # leaves it alone otherwise.  Re-asserting on every deploy is the
        # easiest way to recover from an out-of-band 'systemctl disable'.
        sudo systemctl enable --now orphan-cleanup.timer
        echo 'orphan-cleanup.timer enabled + active.'
    "
}

step_install_boot_progress_units() {
    # T11/T12: idempotent sync-if-changed install of boot-progress-finalize.service
    # + boot-progress-arm.service into /etc/systemd/system/.  Closes the ship gap
    # that would otherwise leave systemd install as a manual operator step.
    # Mirrors step_install_drain_forensics_unit / step_install_orphan_cleanup_unit
    # byte-for-byte: cmp -s on the rsynced source vs the installed copy,
    # daemon-reload only when something actually changed, enable --now is
    # idempotent and re-asserted on every deploy so the units recover from an
    # out-of-band 'systemctl disable'.  BOTH units are enabled: the arm unit
    # runs at boot, and the finalize unit must be "active" so its ExecStop
    # fires at shutdown.
    #
    # No extra runtime dirs are required -- the boot-progress writer targets
    # the existing data/ dir (already provisioned by the rsync of the repo
    # tree), so unlike step_install_drain_forensics_unit there is no
    # install -d step here.
    echo "--- Step: Installing boot-progress systemd units (T11/T12, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/boot-progress-finalize.service /etc/systemd/system/boot-progress-finalize.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/boot-progress-arm.service /etc/systemd/system/boot-progress-arm.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now boot-progress-finalize.service boot-progress-arm.service"
        return 0
    fi
    remote "
        set -e
        SRC_FIN='${PI_PATH}/deploy/boot-progress-finalize.service'
        DST_FIN='/etc/systemd/system/boot-progress-finalize.service'
        SRC_ARM='${PI_PATH}/deploy/boot-progress-arm.service'
        DST_ARM='/etc/systemd/system/boot-progress-arm.service'

        if [ ! -f \"\$SRC_FIN\" ] || [ ! -f \"\$SRC_ARM\" ]; then
            echo 'WARN: boot-progress unit files not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        # Sync-if-changed install of the unit pair.  daemon-reload happens
        # only when at least one file actually changed to avoid pointless
        # systemd churn on routine no-op deploys.
        changed=false
        if sudo test -f \"\$DST_FIN\" && sudo cmp -s \"\$SRC_FIN\" \"\$DST_FIN\"; then
            echo 'boot-progress-finalize.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_FIN\" \"\$DST_FIN\"
            echo 'boot-progress-finalize.service installed.'
            changed=true
        fi
        if sudo test -f \"\$DST_ARM\" && sudo cmp -s \"\$SRC_ARM\" \"\$DST_ARM\"; then
            echo 'boot-progress-arm.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_ARM\" \"\$DST_ARM\"
            echo 'boot-progress-arm.service installed.'
            changed=true
        fi

        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload
            echo 'systemd daemon-reload complete.'
        fi

        # enable --now is idempotent: turns the units on if disabled,
        # leaves them alone otherwise.  Re-asserting on every deploy is the
        # easiest way to recover from an out-of-band 'systemctl disable'.
        # BOTH units enabled so the arm unit runs at boot and the finalize
        # unit is 'active' so its ExecStop fires at shutdown.
        sudo systemctl enable --now boot-progress-finalize.service boot-progress-arm.service
        echo 'boot-progress units enabled + active.'
    "
}

step_install_power_watch_unit() {
    # Phase-2 T6: idempotent sync-if-changed install of eclipse-powerwatch.service
    # into /etc/systemd/system/.  Mirrors step_install_boot_progress_units:
    # cmp -s on the rsynced source vs the installed copy, daemon-reload only
    # when it changed, enable --now idempotently re-asserted every deploy so
    # the watcher recovers from an out-of-band 'systemctl disable'.
    #
    # Unlike the boot-progress units (oneshot/ExecStop), eclipse-powerwatch is
    # a long-running Type=simple service: on a code/unit change we must also
    # `systemctl restart` it -- daemon-reload + enable --now alone leave the
    # OLD process (old code) running, silently shipping nothing.
    #
    # No extra runtime dirs needed -- the outcome record targets the existing
    # data/ dir (already provisioned by the repo rsync).
    echo "--- Step: Installing eclipse-powerwatch systemd unit (Phase-2 T6, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-powerwatch.service /etc/systemd/system/eclipse-powerwatch.service || (install + daemon-reload + restart)"
        echo "DRY-RUN would: sudo systemctl enable --now eclipse-powerwatch.service"
        return 0
    fi
    remote "
        set -e
        SRC_PW='${PI_PATH}/deploy/eclipse-powerwatch.service'
        DST_PW='/etc/systemd/system/eclipse-powerwatch.service'

        if [ ! -f \"\$SRC_PW\" ]; then
            echo 'WARN: eclipse-powerwatch.service not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        changed=false
        if sudo test -f \"\$DST_PW\" && sudo cmp -s \"\$SRC_PW\" \"\$DST_PW\"; then
            echo 'eclipse-powerwatch.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_PW\" \"\$DST_PW\"
            echo 'eclipse-powerwatch.service installed.'
            changed=true
        fi

        # daemon-reload remains gated on \$changed -- it reloads systemd's
        # in-memory unit metadata, which is only meaningful when the unit
        # file actually differs (no-op churn otherwise).
        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload
            echo 'systemd daemon-reload complete.'
        fi

        # enable --now is idempotent (recovers from out-of-band disable).
        sudo systemctl enable --now eclipse-powerwatch.service

        # US-354 fix: long-running service must restart on EVERY deploy, not
        # just when the unit file changed. The Python source is rsynced
        # under \$PI_PATH on every deploy; without an unconditional restart
        # here, a Python-source-only change leaves the OLD interpreter
        # still memory-mapped on the OLD code (V0.27.16 dead-code-in-memory
        # bug -- Argus's 2026-05-21 finding). daemon-reload above stays
        # gated on \$changed; only the process replacement is decoupled.
        sudo systemctl restart eclipse-powerwatch.service
        echo 'eclipse-powerwatch.service restarted onto current code (US-354).'
        echo 'eclipse-powerwatch unit enabled + active.'
    "
}

step_install_states_tmpfiles() {
    # US-395 (F-103, Atlas C-5): install the tmpfiles.d entry that provisions
    # /run/eclipse-obd/states/ at EVERY boot, owned non-root (mcornelison),
    # INDEPENDENT of any unit start order.  /run is a tmpfs on Raspberry Pi OS
    # (wiped every reboot), so the old deploy-time `install -d` ran once and was
    # gone on the next boot; eclipse-obd.service creates only /run/eclipse-obd
    # (via RuntimeDirectory) on its OWN start and removes it on stop, and never
    # makes the states/ subdir.  A tmpfiles.d entry is run by
    # systemd-tmpfiles-setup early at boot, every boot -- the cold-reboot
    # invariant the bench drill proves (splash renders without eclipse-obd having
    # provisioned the dir).  This is AC#4: the boot-durable provisioning
    # mechanism, NOT install -d alone.
    #
    # Sync-if-changed mirrors step_install_journald_persistent (cmp -s the
    # rsynced source vs the installed copy).  After install we run
    # `systemd-tmpfiles --create` so the dir exists IMMEDIATELY (this deploy),
    # not only after the next reboot.  Missing-file gate (warn + skip) keeps the
    # offline smoke test green when only deploy/ is present.  Runs AFTER
    # sync_tree so deploy/eclipse-obd-states.conf exists on the Pi.
    echo "--- Step: Installing F-103 states-dir tmpfiles.d provisioning (US-395, Atlas C-5) ---"
    local sourceFile="deploy/eclipse-obd-states.conf"
    local targetPath="/etc/tmpfiles.d/eclipse-obd-states.conf"
    if $DRY_RUN; then
        echo "DRY-RUN would install ${PI_PATH}/${sourceFile} -> ${targetPath}"
        echo "DRY-RUN would: sudo systemd-tmpfiles --create ${targetPath} (so /run/eclipse-obd/states exists now, not just next boot)"
        return 0
    fi
    remote "
        set -e
        SRC='${PI_PATH}/${sourceFile}'
        DST='${targetPath}'
        if [ ! -f \"\$SRC\" ]; then
            echo 'WARN: ${sourceFile} not present on Pi -- skipping states-dir tmpfiles install.' >&2
            exit 0
        fi
        if sudo test -f \"\$DST\" && sudo cmp -s \"\$SRC\" \"\$DST\"; then
            echo 'states-dir tmpfiles entry already current at ${targetPath} (no change).'
        else
            sudo install -m 644 \"\$SRC\" \"\$DST\"
            echo 'states-dir tmpfiles entry installed: ${targetPath}'
        fi
        # Apply now so /run/eclipse-obd/states exists this deploy, not only after
        # the next reboot (tmpfiles is normally run by systemd-tmpfiles-setup at
        # boot).  Idempotent -- creates only what's absent.
        sudo systemd-tmpfiles --create \"\$DST\"
        echo '/run/eclipse-obd/states provisioned (systemd-tmpfiles --create).'
    "
}

step_install_splash_assets() {
    # US-395 (F-103, AC#2 + AC#3/A-9): install the splash kit assets the
    # eclipse-states-http.service serves to the chromium kiosk
    # (specs/UI/dist/splash-pi/) into /opt/splash, and write
    # /opt/splash/version.txt (the version chip boot-state-poll.js fetches as a
    # public static asset; malformed/absent -> the JS 'V?.?.?' fallback).
    #
    # A-9: if the splash kit is ABSENT this WARNs and lets the deploy CONTINUE --
    # it MUST NOT block.  A Pi deploy without the (UI-team) kit still ships the
    # rest of the tier.  The local-source guard returns 0; the remote
    # per-asset guard skips-with-warn any individual missing file.
    #
    # Scope seam: this installs the BACKEND-served assets (index.html, styles.css,
    # boot-state-poll.js) + version.txt.  The chromium kiosk UNIT
    # (splash-boot.service.{wayland,x11}) + the shutdown render assets are US-396
    # (render side), mirroring the US-394 producer/render seam.
    #
    # Runs AFTER sync_tree so ${PI_PATH}/specs/UI/dist/splash-pi/ exists on the Pi.
    echo "--- Step: Installing F-103 splash assets + version.txt to /opt/splash (US-395) ---"
    local assetSrc="$REPO_ROOT/specs/UI/dist/splash-pi"
    local installDir="/opt/splash"
    local assets="index.html styles.css boot-state-poll.js"
    if [ ! -d "$assetSrc" ]; then
        echo "WARN: splash assets not found at $assetSrc -- skipping splash asset install + version.txt; deploy continues (A-9)." >&2
        return 0
    fi
    # Derive the bare version string from deploy/RELEASE_VERSION (JSON {version}).
    # version.txt holds just the SemVer string the chip renders; a parse failure
    # falls back to the same 'V?.?.?' sentinel the kiosk JS uses.
    local splashVersion="V?.?.?"
    local versionFile="$REPO_ROOT/deploy/RELEASE_VERSION"
    if [ -f "$versionFile" ]; then
        splashVersion=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$versionFile" 2>/dev/null || echo "V?.?.?")
    fi
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo install -d ${installDir}"
        echo "DRY-RUN would: sudo install -m 0644 ${PI_PATH}/specs/UI/dist/splash-pi/{${assets}} ${installDir}/"
        echo "DRY-RUN would: write ${installDir}/version.txt = ${splashVersion}"
        return 0
    fi
    remote "
        set -e
        SRC='${PI_PATH}/specs/UI/dist/splash-pi'
        DST='${installDir}'
        if [ ! -d \"\$SRC\" ]; then
            echo 'WARN: splash assets not present on Pi at '\"\$SRC\"' -- skipping (A-9).' >&2
            exit 0
        fi
        sudo install -d -m 0755 \"\$DST\"
        for f in ${assets}; do
            if [ -f \"\$SRC/\$f\" ]; then
                sudo install -m 0644 \"\$SRC/\$f\" \"\$DST/\$f\"
                echo \"installed \$f -> \$DST/\"
            else
                echo \"WARN: splash asset \$f missing in \$SRC -- skipped (A-9).\" >&2
            fi
        done
        printf '%s\n' '${splashVersion}' | sudo tee \"\$DST/version.txt\" >/dev/null
        echo \"wrote \$DST/version.txt = ${splashVersion}\"
    "
}

step_install_dashboard_assets() {
    # US-399 (F-092, A-1/A-2): install the carousel dashboard kit assets the
    # eclipse-states-http.service serves to the chromium dashboard kiosk
    # (specs/UI/dist/dashboard-pi/) into /opt/dashboard. The server's
    # --assets-dir search path lists /opt/splash then /opt/dashboard, so the
    # dashboard is reached at /dashboard.html same-origin (token injected).
    #
    # A-9 posture (mirrors step_install_splash_assets): if the dashboard kit is
    # ABSENT this WARNs and the deploy CONTINUES -- a Pi without the (UI-team)
    # kit still ships the rest of the tier, and a /opt/dashboard that doesn't
    # exist is harmless to the server (the asset lookup just skips it).
    #
    # Scope seam: this installs the BACKEND-served assets only. The chromium
    # dashboard kiosk UNIT (eclipse-dashboard.service) is installed by the kit's
    # session-aware install.sh on the Pi (V-1/V-2 detection) -- the same seam as
    # the splash kiosk unit -- and is started by the splash OnSuccess= hand-off.
    #
    # Runs AFTER sync_tree so ${PI_PATH}/specs/UI/dist/dashboard-pi/ exists.
    echo "--- Step: Installing carousel dashboard assets to /opt/dashboard (US-399) ---"
    local assetSrc="$REPO_ROOT/specs/UI/dist/dashboard-pi"
    local installDir="/opt/dashboard"
    local assets="dashboard.html dashboard.css carousel.js"
    if [ ! -d "$assetSrc" ]; then
        echo "WARN: dashboard assets not found at $assetSrc -- skipping; deploy continues (A-9)." >&2
        return 0
    fi
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo install -d ${installDir}"
        echo "DRY-RUN would: sudo install -m 0644 ${PI_PATH}/specs/UI/dist/dashboard-pi/{${assets}} ${installDir}/"
        return 0
    fi
    remote "
        set -e
        SRC='${PI_PATH}/specs/UI/dist/dashboard-pi'
        DST='${installDir}'
        if [ ! -d \"\$SRC\" ]; then
            echo 'WARN: dashboard assets not present on Pi at '\"\$SRC\"' -- skipping (A-9).' >&2
            exit 0
        fi
        sudo install -d -m 0755 \"\$DST\"
        for f in ${assets}; do
            if [ -f \"\$SRC/\$f\" ]; then
                sudo install -m 0644 \"\$SRC/\$f\" \"\$DST/\$f\"
                echo \"installed \$f -> \$DST/\"
            else
                echo \"WARN: dashboard asset \$f missing in \$SRC -- skipped (A-9).\" >&2
            fi
        done
    "
}

step_install_ui_kiosk_units() {
    # BUG-FIX (Atlas 2026-07-01; finding
    # offices/architect/findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md).
    # The two ASSET steps above install what eclipse-states-http SERVES, but nothing
    # installed the chromium KIOSK UNITS that actually render it -- so every real
    # deploy left the backend serving to 127.0.0.1:9899 with no browser drawing it,
    # and pygame is sunset (statusDisplay.enabled=false) -> a blank 3.5" screen.
    # This step closes that seam by running the kit's own session-aware installers:
    #   specs/UI/dist/splash-pi/install.sh     -> splash-boot + splash-grace units
    #   specs/UI/dist/dashboard-pi/install.sh  -> eclipse-dashboard unit
    #
    # Two things the first on-hardware run proved necessary (do NOT drop them):
    #  (1) SESSION DETECTION over SSH.  The installers' own V-2 check reads the
    #      CALLING session's type; over SSH that is 'tty', so the installer aborts
    #      ("cannot determine session type") rather than guess X11-vs-Wayland -- a
    #      wrong guess is the D-3 black-screen bug.  We detect the type from the Pi's
    #      ACTIVE graphical seat0 session and pass it via {SPLASH,DASHBOARD}_FORCE_SESSION.
    #      If it genuinely can't be determined we WARN + skip -- we never guess.
    #  (2) chromium BINARY name.  The unit templates hardcode
    #      ExecStart=/usr/bin/chromium-browser, but current Raspberry Pi OS (Trixie)
    #      ships /usr/bin/chromium -> the unit dies with 203/EXEC.  We add the compat
    #      symlink when chromium-browser is absent but chromium exists.  (The ideal
    #      long-term fix is a kit-installer V-3 binary check that substitutes the real
    #      path into the unit, like it substitutes User= -- flagged to the UI kit;
    #      this keeps the DEPLOY self-sufficient meanwhile.)
    #
    # Idempotent (the installers are idempotent; `ln -sf` is idempotent).  A-9
    # posture: absent kit/installer -> WARN + skip, deploy continues.  This installs +
    # ENABLES the units; the splash renders at the NEXT boot (WantedBy=graphical.target),
    # so the step does not thrash the live screen mid-deploy.  Runs AFTER the asset +
    # state-server steps so the served assets + backend are already in place.
    echo "--- Step: Installing F-103/F-092 chromium kiosk units (splash + dashboard) ---"
    local splashKit="specs/UI/dist/splash-pi/install.sh"
    local dashKit="specs/UI/dist/dashboard-pi/install.sh"
    if [ ! -f "$REPO_ROOT/$splashKit" ] && [ ! -f "$REPO_ROOT/$dashKit" ]; then
        echo "WARN: UI kit installers not found under $REPO_ROOT/specs/UI/dist -- skipping kiosk-unit install (A-9)." >&2
        return 0
    fi
    if $DRY_RUN; then
        echo "DRY-RUN would: detect the Pi's ACTIVE graphical seat0 session type (x11|wayland)"
        echo "DRY-RUN would: ensure /usr/bin/chromium-browser (symlink -> chromium if absent)"
        echo "DRY-RUN would: sudo {SPLASH,DASHBOARD}_FORCE_SESSION=<type> _FORCE_USER=${PI_USER} bash ${PI_PATH}/{${splashKit},${dashKit}}"
        return 0
    fi
    remote "
        # (1) Detect the graphical session type from the ACTIVE seat0 session (an
        #     SSH session reads as 'tty' and would make the installer abort).
        SESS=''
        for s in \$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print \$1}'); do
            seat=\$(loginctl show-session \"\$s\" -p Seat --value 2>/dev/null || true)
            typ=\$(loginctl show-session \"\$s\" -p Type --value 2>/dev/null || true)
            act=\$(loginctl show-session \"\$s\" -p Active --value 2>/dev/null || true)
            if [ \"\$seat\" = 'seat0' ] && [ \"\$act\" = 'yes' ] && { [ \"\$typ\" = 'x11' ] || [ \"\$typ\" = 'wayland' ]; }; then
                SESS=\"\$typ\"; break
            fi
        done
        if [ -z \"\$SESS\" ]; then
            if pgrep -x Xorg >/dev/null 2>&1; then SESS=x11
            elif ls /run/user/*/wayland-0 >/dev/null 2>&1; then SESS=wayland
            fi
        fi
        if [ -z \"\$SESS\" ]; then
            echo 'WARN: could not determine the Pi graphical session type (no active x11/wayland seat0 session) -- skipping kiosk-unit install; NOT guessing (D-3 black-screen risk). Re-run deploy from a booted graphical session.' >&2
            exit 0
        fi
        echo \"graphical session type: \$SESS\"

        # (2) chromium binary compat: units call /usr/bin/chromium-browser; Trixie
        #     ships /usr/bin/chromium.  Symlink when the browser name is absent.
        if ! command -v chromium-browser >/dev/null 2>&1; then
            if command -v chromium >/dev/null 2>&1; then
                sudo ln -sf \"\$(command -v chromium)\" /usr/bin/chromium-browser
                echo \"linked /usr/bin/chromium-browser -> \$(command -v chromium)\"
            else
                echo 'WARN: neither chromium-browser nor chromium on the Pi -- kiosk will not launch; install chromium.' >&2
            fi
        fi

        # (2b) Disable X screen blanking / DPMS so the panel never sleeps and shows
        #      'no input' (Bug 4).  Install the persistent xorg.conf.d drop-in (takes
        #      effect at the next X start) AND apply it live via xset now (best-effort)
        #      so this deploy needs no X restart.
        XCONF_SRC='${PI_PATH}/deploy/eclipse-kiosk-no-blank.conf'
        XCONF_DST='/etc/X11/xorg.conf.d/10-eclipse-kiosk-no-blank.conf'
        if [ -f \"\$XCONF_SRC\" ]; then
            if sudo test -f \"\$XCONF_DST\" && sudo cmp -s \"\$XCONF_SRC\" \"\$XCONF_DST\"; then
                echo 'kiosk no-blank xorg drop-in already current (no change).'
            else
                sudo install -d -m 0755 /etc/X11/xorg.conf.d
                sudo install -m 0644 \"\$XCONF_SRC\" \"\$XCONF_DST\"
                echo \"installed xorg no-blank drop-in -> \$XCONF_DST\"
            fi
        else
            echo 'WARN: deploy/eclipse-kiosk-no-blank.conf absent on Pi -- screen may blank after 10min (A-9).' >&2
        fi
        # Apply live now (best-effort; harmless if no X session is active).
        if sudo -u ${PI_USER} DISPLAY=:0 XAUTHORITY=/home/${PI_USER}/.Xauthority xset s off -dpms s noblank >/dev/null 2>&1; then
            echo 'screen blanking/DPMS disabled live on :0.'
        else
            echo 'note: could not apply xset live (no active X session?) -- the xorg drop-in covers the next boot.'
        fi

        # (3) Run the kit's session-aware installers, forcing the detected session +
        #     the deploy user (env set INSIDE the root shell so sudo does not strip it).
        SPK='${PI_PATH}/${splashKit}'
        DSK='${PI_PATH}/${dashKit}'
        if [ -f \"\$SPK\" ]; then
            sudo bash -c \"SPLASH_FORCE_SESSION=\$SESS SPLASH_FORCE_USER=${PI_USER} bash '\$SPK'\" \
                && echo 'splash kiosk units installed + enabled.' \
                || echo 'WARN: splash-pi/install.sh failed -- deploy continues (A-9); check the Pi session/binary.' >&2
        else
            echo 'WARN: splash-pi/install.sh absent on Pi -- skipped (A-9).' >&2
        fi
        if [ -f \"\$DSK\" ]; then
            sudo bash -c \"DASHBOARD_FORCE_SESSION=\$SESS DASHBOARD_FORCE_USER=${PI_USER} bash '\$DSK'\" \
                && echo 'dashboard kiosk unit installed.' \
                || echo 'WARN: dashboard-pi/install.sh failed -- deploy continues (A-9).' >&2
        else
            echo 'WARN: dashboard-pi/install.sh absent on Pi -- skipped (A-9).' >&2
        fi
        echo 'Kiosk units in place; the splash renders at the next boot (WantedBy=graphical.target).'
    "
}

step_install_state_server_units() {
    # US-395 (F-103, AC#1): idempotent sync-if-changed install of the two F-103
    # state-server units -- eclipse-boot-state.service (the [A-1] boot-state
    # emitter) + eclipse-states-http.service (the [A-4] localhost token-gated
    # state server the kiosk fetch()es).  Mirrors step_install_boot_progress_units
    # byte-for-byte: cmp -s on the rsynced source vs the installed copy,
    # daemon-reload only when something actually changed, enable --now idempotent
    # and re-asserted every deploy so the units recover from an out-of-band
    # 'systemctl disable'.
    #
    # Unlike the boot-progress units (oneshot), BOTH of these are long-running
    # Type=simple services -- so, like step_install_power_watch_unit, they must
    # also `systemctl restart` on EVERY deploy: daemon-reload + enable --now
    # alone leave the OLD interpreter on the OLD rsynced code (the V0.27.16
    # dead-code-in-memory bug, US-354).  Restart the HTTP server FIRST so the
    # emitter's first write lands after the server is listening.
    #
    # Runs AFTER sync_tree so deploy/eclipse-{boot-state,states-http}.service
    # exist on the Pi.  Missing-file gate (warn + skip) keeps the offline smoke
    # test green when only deploy/ is present.
    echo "--- Step: Installing F-103 state-server units (US-395, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-boot-state.service /etc/systemd/system/eclipse-boot-state.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-states-http.service /etc/systemd/system/eclipse-states-http.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now eclipse-boot-state.service eclipse-states-http.service"
        echo "DRY-RUN would: sudo systemctl restart eclipse-states-http.service eclipse-boot-state.service (long-running Type=simple, US-354)"
        return 0
    fi
    remote "
        set -e
        SRC_BS='${PI_PATH}/deploy/eclipse-boot-state.service'
        DST_BS='/etc/systemd/system/eclipse-boot-state.service'
        SRC_HTTP='${PI_PATH}/deploy/eclipse-states-http.service'
        DST_HTTP='/etc/systemd/system/eclipse-states-http.service'

        if [ ! -f \"\$SRC_BS\" ] || [ ! -f \"\$SRC_HTTP\" ]; then
            echo 'WARN: F-103 state-server unit files not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        # Sync-if-changed install of the unit pair.  daemon-reload happens only
        # when at least one file actually changed to avoid pointless systemd
        # churn on routine no-op deploys.
        changed=false
        if sudo test -f \"\$DST_BS\" && sudo cmp -s \"\$SRC_BS\" \"\$DST_BS\"; then
            echo 'eclipse-boot-state.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_BS\" \"\$DST_BS\"
            echo 'eclipse-boot-state.service installed.'
            changed=true
        fi
        if sudo test -f \"\$DST_HTTP\" && sudo cmp -s \"\$SRC_HTTP\" \"\$DST_HTTP\"; then
            echo 'eclipse-states-http.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_HTTP\" \"\$DST_HTTP\"
            echo 'eclipse-states-http.service installed.'
            changed=true
        fi

        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload
            echo 'systemd daemon-reload complete.'
        fi

        # enable --now is idempotent (recovers from an out-of-band disable).
        sudo systemctl enable --now eclipse-boot-state.service eclipse-states-http.service

        # US-354: long-running Type=simple services must restart on EVERY deploy
        # so rsynced source changes actually run (not just on a unit-file diff).
        # HTTP server first so the emitter's first write lands after it listens.
        sudo systemctl restart eclipse-states-http.service eclipse-boot-state.service
        echo 'F-103 state-server units enabled + restarted onto current code (US-354).'
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
    # US-389: capture the single-instance matched-pair state so .deploy-version
    # records {guardEnabled, runtimeDirectory} rather than being silent on top
    # of the prior (V0.28.2) stamp.  Best-effort: a summarize failure (missing
    # helper / files) just omits the field -- it must NEVER abort the version
    # write (the matched-pair gate already hard-failed the deploy earlier if the
    # pair was actually broken).
    local invariantsHelper="$REPO_ROOT/scripts/deploy_invariants.py"
    local configFile="$REPO_ROOT/config.json"
    local unitFile="$REPO_ROOT/deploy/${SERVICE_NAME}.service"
    local siJson=""
    if [ -f "$invariantsHelper" ] && [ -f "$configFile" ] && [ -f "$unitFile" ]; then
        siJson=$(python "$invariantsHelper" summarize \
            --config "$configFile" --unit "$unitFile" 2>/dev/null || echo "")
    fi
    local -a siArgs=()
    if [ -n "$siJson" ]; then
        siArgs=(--single-instance "$siJson")
    fi
    local versionJson
    versionJson=$(python "$helpersPath" compose-record \
        --version-file "$versionFile" \
        --git-hash "$gitHash" \
        "${siArgs[@]}") || {
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
    # US-389 + US-354 deploy-hygiene class: STOP before START (not a bare
    # `systemctl restart`) so the outgoing orchestrator fully exits and RELEASES
    # the single-instance pidfile (/run/eclipse-obd/orchestrator.lock) before the
    # incoming process ACQUIREs it.  A bare restart can let the new instance's
    # guard observe the still-dying old pid and refuse to start; the explicit
    # stop -> settle -> start enforces the release-then-acquire ordering that
    # architecture.md §10.7.1 gates the guard's production-enable on (Atlas).
    # If the service isn't installed yet (fresh Pi before first install), this
    # is a warn, not a fail.
    remote "
        if systemctl list-unit-files | grep -q '${SERVICE_NAME}.service'; then
            sudo systemctl stop ${SERVICE_NAME} || true
            sleep 1
            sudo systemctl start ${SERVICE_NAME}
            sleep 1
            sudo systemctl is-active ${SERVICE_NAME} && echo 'Service active.' || echo 'WARN: service not active after restart — check journalctl -u ${SERVICE_NAME}'
        else
            echo 'WARN: ${SERVICE_NAME}.service not installed yet. Skipping restart.'
            echo '       Run a default deploy (not --restart) to install via step_install_eclipse_obd_unit.'
        fi
    "
}

step_verify_service_restarts() {
    # US-354: assert eclipse-powerwatch + eclipse-obd PIDs both started AFTER
    # this deploy began. Catches the V0.27.16 dead-code-in-memory bug where
    # `.deploy-version` was bumped while the long-running services still ran
    # the prior release's code in memory (restart was gated on unit-file diff;
    # a Python-source-only deploy left $changed=false and skipped the restart).
    #
    # The verification compares each service's ExecMainStartTimestamp (parsed
    # via `date -d`) against the local-side DEPLOY_START_EPOCH captured at
    # script entry. Either service starting BEFORE the deploy began means the
    # restart didn't actually replace the process -- abort the deploy with a
    # clear error rather than silently bumping .deploy-version on top of a
    # dead-code Pi.
    #
    # Services not installed yet (fresh Pi before first install) are WARN, not
    # FAIL -- mirrors step_restart_service's pattern.
    echo "--- Step: Verifying eclipse-powerwatch + eclipse-obd restarted (US-354) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would verify ExecMainStartTimestamp of eclipse-powerwatch.service >= DEPLOY_START_EPOCH"
        echo "DRY-RUN would verify ExecMainStartTimestamp of eclipse-obd.service >= DEPLOY_START_EPOCH"
        return 0
    fi

    # Pass the local-side DEPLOY_START_EPOCH into the remote shell. Captured
    # at script entry (before any step ran), so any restart fired during this
    # deploy yields a service-start later than this value.
    local deployStartEpoch="${DEPLOY_START_EPOCH:-0}"

    remote "
        set -e
        DEPLOY_START_EPOCH='${deployStartEpoch}'
        if [ -z \"\$DEPLOY_START_EPOCH\" ] || [ \"\$DEPLOY_START_EPOCH\" = 0 ]; then
            echo 'ERROR: DEPLOY_START_EPOCH not set on remote -- cannot verify restart (US-354).' >&2
            exit 9
        fi

        verify_one_service() {
            local svc=\"\$1\"
            if ! systemctl list-unit-files | grep -q \"\$svc\"; then
                echo \"WARN: \$svc not installed -- skipping restart verification (fresh Pi).\"
                return 0
            fi
            local ts
            ts=\$(systemctl show -p ExecMainStartTimestamp --value \"\$svc\" 2>/dev/null || true)
            if [ -z \"\$ts\" ]; then
                echo \"ERROR: \$svc has no ExecMainStartTimestamp -- service not running? (US-354).\" >&2
                systemctl status \"\$svc\" --no-pager 2>&1 | sed 's/^/  /' >&2 || true
                return 1
            fi
            local epoch
            epoch=\$(date -d \"\$ts\" +%s 2>/dev/null || echo 0)
            if [ \"\$epoch\" -eq 0 ]; then
                echo \"ERROR: failed to parse \$svc start timestamp: \$ts (US-354).\" >&2
                return 1
            fi
            if [ \"\$epoch\" -lt \"\$DEPLOY_START_EPOCH\" ]; then
                echo \"ERROR: \$svc start time (\$ts / epoch \$epoch) is BEFORE deploy start (epoch \$DEPLOY_START_EPOCH).\" >&2
                echo \"       The service was NOT restarted by this deploy -- it is still running prior-release code in memory.\" >&2
                echo \"       This is the V0.27.16 dead-code-in-memory bug (US-354).\" >&2
                return 1
            fi
            echo \"OK: \$svc restarted at \$ts (epoch \$epoch >= deploy-start \$DEPLOY_START_EPOCH).\"
            return 0
        }

        rc=0
        verify_one_service 'eclipse-powerwatch.service' || rc=1
        verify_one_service 'eclipse-obd.service' || rc=1
        if [ \"\$rc\" -ne 0 ]; then
            echo '' >&2
            echo 'US-354 restart verification FAILED. .deploy-version will NOT be bumped.' >&2
            echo 'Investigate the failing service(s) above before re-running the deploy.' >&2
            exit 9
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

# US-389 (F-107 Root 1): assert the single-instance guard / RuntimeDirectory
# matched pair BEFORE anything is synced or restarted -- a broken pair must
# abort the deploy on the workstation, never reach the Pi.  Runs in every mode
# that ships code (default + --init); the local read-only check is cheap and
# valuable even in --dry-run preview.
step_assert_single_instance_matched_pair

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

# US-341 / I-036: polkit rule granting mcornelison the
# org.freedesktop.login1.power-off action.  Without this rule
# eclipse-obd.service (User=mcornelison) cannot invoke `systemctl poweroff`
# at TRIGGER and the Pi hard-crashes at buck-dropout floor.  Same
# idempotent canonical-source-of-truth pattern as the journald drop-in.
# Runs AFTER sync_tree so deploy/polkit-rules/ exists on the Pi.
step_install_polkit_poweroff

# US-403 / A-7: net-new polkit rule granting mcornelison scoped systemd
# manage-units (the install-fixed eclipse-* allow-list) so the unprivileged
# dashboard kiosk's System Setup menu can restart/stop services without root.
# Sibling to the 50- poweroff rule (different action: manage-units). Runs AFTER
# sync_tree so deploy/polkit-rules/ exists on the Pi.
step_install_polkit_service_control

# US-325 / I-025: NetworkManager wifi.powersave=2 drop-in. Same rationale as
# the journald drop-in -- idempotent, canonical-source-of-truth OS config that
# every deploy reasserts (so a Pi rebuilt from scratch via --init lands
# power-save-disabled). Runs AFTER sync_tree so deploy/nm-disable-wifi-
# powersave.conf exists on the Pi.
step_install_nm_wifi_powersave

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
# US-277: install drain-forensics .service + .timer alongside the main
# eclipse-obd unit so a fresh deploy is enough to start the forensic
# logger.  Runs on every deploy (not just --init) because /var/run is a
# tmpfs and the runtime-dirs need to be re-provisioned after every reboot,
# and the unit files themselves change per-sprint as instrumentation
# evolves.  Idempotent: no-op when files match + dirs already exist.
step_install_drain_forensics_unit

# US-322 / B-072: nightly orphan-cleanup timer for NULL-drive_id realtime_data
# rows.  Same install posture as drain-forensics -- the unit pair lives in the
# repo, deploy syncs them sync-if-changed, daemon-reload only on real change,
# enable --now is idempotent.  No extra runtime dirs needed (script touches
# data/obd.db only).
step_install_orphan_cleanup_unit

# T11/T12: install boot-progress-finalize.service + boot-progress-arm.service
# alongside the other systemd units.  Same install posture as drain-forensics /
# orphan-cleanup -- the unit pair lives in the repo, deploy syncs them
# sync-if-changed, daemon-reload only on real change, enable --now is
# idempotent (BOTH units enabled: arm runs at boot, finalize active so its
# ExecStop fires at shutdown).  No extra runtime dirs needed (the existing
# data/ dir is the boot-progress target).
step_install_boot_progress_units

# Phase-2 T6: install eclipse-powerwatch.service (the bounded pre-shutdown
# pipeline / graceful-poweroff watcher). Same sync-if-changed posture as the
# other units; additionally restarts the long-running service on change so the
# new code actually runs. No extra runtime dirs (outcome record -> data/).
step_install_power_watch_unit

# US-395: F-103 boot/shutdown splash deploy integration.  Order matters at
# RUNTIME, so provision in dependency order:
#   1. states-dir tmpfiles.d (the dir the emitter + server write/read; created at
#      EVERY boot independent of eclipse-obd -- Atlas C-5 / AC#4),
#   2. splash assets + version.txt to /opt/splash (WARN-not-BLOCK if the kit is
#      absent -- A-9 / AC#2-3),
#   3. the two state-server units (enable + restart; AC#1).
# All three run AFTER sync_tree so deploy/*.service, deploy/eclipse-obd-states.conf,
# and specs/UI/dist/splash-pi/ exist on the Pi.  Same sync-if-changed posture as
# the other unit installers; the two state units are long-running Type=simple so
# they also restart every deploy (US-354).
step_install_states_tmpfiles
step_install_splash_assets
# US-399 (F-092): carousel dashboard served assets -> /opt/dashboard (the
# eclipse-states-http server's 2nd --assets-dir). WARN-not-BLOCK if absent (A-9).
# Runs before the state-server restart so the server picks up the assets it now
# serves at /dashboard.html. The kiosk UNIT is installed by the kit's install.sh.
step_install_dashboard_assets
step_install_state_server_units
# Atlas 2026-07-01 BUG-FIX: install the chromium KIOSK UNITS (splash + dashboard).
# The asset + backend steps above only install what the state server SERVES; without
# this the kiosk is never installed and the 3.5" screen stays blank (pygame sunset).
# Runs after the state server is up so the served surface + backend are in place.
step_install_ui_kiosk_units

# US-354 reordering: restart first, then verify both long-running services
# came back with start times AFTER DEPLOY_START_EPOCH, THEN bump
# .deploy-version. The prior order wrote .deploy-version before the
# eclipse-obd restart -- a failed restart left the version bumped on a Pi
# still running old code (the V0.27.16 dead-code-in-memory bug).
# step_install_power_watch_unit above also restarts unconditionally now
# (decoupled from the unit-file-change gate per US-354).
step_restart_service
step_verify_service_restarts
step_write_deploy_version

echo ""
echo "Deploy OK: $(date -Iseconds) to ${PI_USER}@${PI_HOST}"
