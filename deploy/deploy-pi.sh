#!/usr/bin/env bash
################################################################################
# deploy-pi.sh — Deploy/update the Pi tier on chi-eclipse-01 (addressed BY HOSTNAME;
#                 wlan0 is 10.27.27.124 -- see deploy/addresses.sh, the SSOT)
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
#   PI_HOST  - Pi IP or hostname               (default: chi-eclipse-01, by NAME)
#   PI_USER  - SSH user on the Pi              (default: mcornelison)
#   PI_PATH  - Project path on the Pi          (default: /home/mcornelison/Projects/Eclipse-01)
#   PI_PORT  - SSH port                        (default: 22)
#
# Prerequisites:
#   - Key-based SSH from this Windows git-bash to mcornelison@chi-eclipse-01 already works
#   - rsync available in git-bash AND on the Pi (rsync ships with Raspberry Pi OS)
#   - Local Windows tree at the project root is the source of truth
#
# What this script does:
#   Default mode:
#     1. rsync the working tree to PI_PATH on the Pi (excludes .git/, .venv/, data/, etc.)
#     2. Install/refresh systemd-journald persistent-storage drop-in (US-210, idempotent)
#     3. Enforce POWER_OFF_ON_HALT=0 in Pi 5 EEPROM (US-253, wake-on-power, idempotent)
#     4. Set GPU CMA to 256M in /boot/firmware/config.txt (US-524, idempotent,
#        takes effect on next reboot)
#     5. Update venv deps from requirements.txt + requirements-pi.txt at ~/obd2-venv
#     6. Restart eclipse-obd systemd service if installed (warn-only if absent)
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
        # WHITELIST, not a blacklist (2026-08-25). The Pi is a production
        # appliance: it carries the code that runs the car and nothing else.
        # Everything else in this repo -- tests, specs, docs, tools, the server
        # tier, CI config, agent slash commands -- is WORKSHOP. It stays in git
        # (tests are gates and must be version-locked to the commit they
        # validate) but it does not ship.
        #
        # An include-list is used deliberately: with a blacklist, every new
        # top-level directory silently ships until somebody notices. That is how
        # a 17.7 MB 3D-printer manual ended up on the car.
        #
        # rsync include rules: parent dirs must be included before their
        # contents, and the final --exclude=* drops everything not named.
        rsync \
            -az \
            --delete \
            --prune-empty-dirs \
            --exclude=__pycache__/ \
            --exclude=*.pyc \
            --include=config.json \
            --include=requirements.txt \
            --include=requirements-pi.txt \
            --include=.deploy-version \
            --include=src/ \
            --include=src/__init__.py \
            --include=src/pi/*** \
            --include=src/common/*** \
            --include=scripts/*** \
            --include=deploy/ \
            --include=deploy/*.sh \
            --include=deploy/boot-progress-*.service \
            --include=deploy/drain-forensics.* \
            --include=deploy/eclipse-*.service \
            --include=deploy/eclipse-*.timer \
            --include=deploy/eclipse-*.conf \
            --include=deploy/orphan-cleanup.* \
            --include=deploy/rfcomm-bind.service \
            --include=deploy/journald-persistent.conf \
            --include=deploy/nm-disable-wifi-powersave.conf \
            --include=deploy/RELEASE_VERSION \
            --include=deploy/polkit-rules/ \
            --include=deploy/polkit-rules/*.rules \
            --exclude=deploy/obd-server.service \
            --exclude=deploy/obd2-server.service \
            --exclude=deploy/server-analytics-batch.* \
            --exclude=deploy/deploy.conf \
            --exclude=* \
            -e "ssh -p ${PI_PORT}" \
            "$REPO_ROOT/" "${PI_USER}@${PI_HOST}:${PI_PATH}/"
    else
        echo "NOTE: rsync not installed locally — using tar-over-ssh fallback."
        echo "      Install rsync for faster incremental sync (see deploy/README.md)."
        # Stream a gzipped tarball of the source tree over SSH, then on the Pi:
        # wipe top-level contents except runtime state dirs (data, exports, logs,
        # .env, config.local.json), then extract the tar. Mirrors rsync --delete
        # but at tar granularity. NOTE: excluding a file from the TARBALL alone is
        # not enough -- the wipe runs first, so every preserved path needs a
        # matching `! -name` below or the operator's settings are deleted (US-530).
        # tar path: an explicit FILE LIST, mirroring the rsync whitelist above.
        # Both paths must ship the SAME tree -- if they diverge, which one ran
        # (rsync present or not) silently changes what is on the car.
        ( cd "$REPO_ROOT" && tar -cz \
            --exclude="__pycache__" \
            --exclude="*.pyc" \
            --exclude="./deploy/deploy.conf" \
            --exclude="./deploy/obd-server.service" \
            --exclude="./deploy/obd2-server.service" \
            --exclude="./deploy/server-analytics-batch.service" \
            --exclude="./deploy/server-analytics-batch.timer" \
            --exclude="./deploy/README.md" \
            --exclude="./deploy/deploy.conf.example" \
            --exclude="./deploy/sudoers.d" \
            -f - \
            ./config.json ./requirements.txt ./requirements-pi.txt ./.deploy-version \
            ./src/__init__.py ./src/pi ./src/common ./scripts ./deploy ) | \
          ssh -p "${PI_PORT}" "${PI_USER}@${PI_HOST}" "
            set -e
            mkdir -p '${PI_PATH}'
            cd '${PI_PATH}'
            find . -mindepth 1 -maxdepth 1 \
                ! -name 'data' ! -name 'exports' ! -name 'logs' ! -name '.env' \
                ! -name 'config.local.json' \
                -exec rm -rf {} +
            tar -xzf -
          "
    fi
}

# Purge stale Python bytecode on the Pi (US-553).
#
# WHY THE --exclude RULES ABOVE ARE NOT THIS FIX. Excluding __pycache__/ and
# *.pyc stops stale bytecode being SENT; it does nothing about what is already
# ON the car. Worse: rsync PROTECTS excluded files from --delete. Measured
# 2026-08-28 -- a --delete run that correctly removed a module deleted upstream
# left BOTH `pkg/__pycache__/mod.cpython-311.pyc` AND a bare `pkg/ghost.pyc`
# in place. Orphaned bytecode therefore accumulates on the Pi forever.
#
# WHY THAT IS DANGEROUS -- the two cases that actually bite, both measured
# rather than assumed (an ordinary edit, which changes mtime or size, is
# invalidated correctly; the folklore "stale .pyc masks any fix" is FALSE):
#   1. GHOST MODULE. A bare `foo.pyc` sitting where `foo.py` used to be is
#      importable with NO source present -- CPython still registers
#      SourcelessFileLoader for .pyc on the path hooks. Delete a module
#      upstream and the Pi can keep importing last month's copy indefinitely.
#   2. (mtime, size) COLLISION. __pycache__ entries are validated against the
#      source's (mtime, size) PAIR, not a hash. An edit preserving both is
#      masked -- the fixed .py is on disk and the old bytecode still executes.
#      rsync -a and the tar fallback BOTH preserve mtime, so the deploy itself
#      is what makes this reachable.
# This is the factor that made the first redeploy of the 2026-08-11 P0 fix
# (`from common.config.overlay` -> relative, commit d6517429) still come up on
# the old code.
#
# WHY NOT `--delete-excluded`, the obvious one-flag fix: the whitelist above
# ends in `--exclude=*`, so --delete-excluded would treat EVERY non-whitelisted
# path on the Pi as deletable -- data/, logs/, exports/, .env,
# config.local.json. That is the car's recorded drive history. Never add it.
#
# Scoped to the two directories that carry shipped Python. The venv lives at
# $HOME/obd2-venv, OUTSIDE PI_PATH, so site-packages bytecode is untouched and
# dependency import cost is unchanged. Reports a count: a silent purge is an
# unverifiable one.
step_purge_stale_bytecode() {
    echo "--- Step: Purging stale bytecode under ${PI_PATH} ---"
    remote "
        set -e
        purged=0
        for d in '${PI_PATH}/src' '${PI_PATH}/scripts'; do
            [ -d \"\$d\" ] || continue
            n=\$(find \"\$d\" \\( -type d -name '__pycache__' -o -type f -name '*.pyc' \\) -print | wc -l)
            purged=\$((purged + n))
            find \"\$d\" -type d -name '__pycache__' -prune -exec rm -rf {} +
            find \"\$d\" -type f -name '*.pyc' -delete
        done
        echo \"Stale bytecode purged: \$purged path(s) removed under src/ + scripts/.\"
    "
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
    # US-435: 'chi-eclips-01' is the CIO's manual `hostnamectl` rename (dropped
    # the 'e' vs the canonical 'chi-eclipse-01'); accepting it here lets --init
    # converge the Pi to $PI_HOSTNAME rather than refusing on an unknown name.
    echo "--- Step: Renaming Pi hostname to ${PI_HOSTNAME} ---"
    remote "
        current=\$(hostname)
        lower=\$(echo \"\$current\" | tr '[:upper:]' '[:lower:]')
        echo \"Current hostname: \$current (normalized: \$lower)\"
        case \"\$lower\" in
            ${PI_HOSTNAME})
                echo 'Hostname already ${PI_HOSTNAME}, skipping rename.'
                ;;
            raspberrypi|chi-eclipse-tuner|chi-eclips-tuner|chi-eclips-01)  # b044-exempt: legacy hostname whitelist for rename step
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
                echo 'Expected raspberrypi, chi-eclipse-tuner (any case), chi-eclips-tuner (any case), chi-eclips-01 (any case), or ${PI_HOSTNAME}.'  # b044-exempt: legacy hostname whitelist
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

step_install_obdctl() {
    # US-492 / F-122: put the `obdctl` operator CLI on the Pi's PATH. The tool
    # itself is plain source in the synced tree (src/pi/ops/obdctl.py); what is
    # installed here is a 3-line wrapper at /usr/local/bin/obdctl so the CIO can
    # type `obdctl status all` from any directory without remembering a path.
    #
    # SYSTEM python3 on purpose, NOT ${REMOTE_VENV}: obdctl is the tool you
    # reach for when the Pi is misbehaving, and a broken/half-installed venv is
    # one of the things it has to survive. obdctl imports stdlib + its own unit
    # manifest only, so system python3 is sufficient (a test pins both facts).
    #
    # Same idempotent sync-if-changed posture as the polkit rules: write the
    # wrapper to a temp file, compare, install only on change.
    echo "--- Step: Installing obdctl operator CLI (US-492, F-122) ---"
    local targetPath="/usr/local/bin/obdctl"
    local entryPoint="${PI_PATH}/src/pi/ops/obdctl.py"

    if $DRY_RUN; then
        echo "DRY-RUN would install wrapper -> ${targetPath} (mode 755)"
        echo "DRY-RUN would point it at /usr/bin/python3 ${entryPoint}"
        return 0
    fi

    remote "
        set -e
        TMP_WRAPPER=\$(mktemp)
        cat > \"\$TMP_WRAPPER\" <<'OBDCTL_WRAPPER'
#!/bin/sh
# US-492 obdctl launcher (installed by deploy-pi.sh -- do not edit by hand).
exec /usr/bin/python3 ${entryPoint} \"\$@\"
OBDCTL_WRAPPER
        if sudo test -f '${targetPath}' && sudo cmp -s \"\$TMP_WRAPPER\" '${targetPath}'; then
            echo 'obdctl already current at ${targetPath} (no change).'
        else
            sudo install -m 755 \"\$TMP_WRAPPER\" '${targetPath}'
            echo 'obdctl installed: ${targetPath}'
        fi
        rm -f \"\$TMP_WRAPPER\"
        if [ ! -f '${entryPoint}' ]; then
            echo 'WARN: ${entryPoint} missing -- obdctl will not run until the tree syncs.' >&2
        fi
        obdctl --help >/dev/null 2>&1 && echo 'obdctl on PATH and runnable.' || echo 'WARN: obdctl installed but not runnable -- check /usr/bin/python3.' >&2
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

step_set_gpu_cma() {
    # US-524 / F-124: raise the GPU CMA pool from the Pi 5's 64 MiB device-tree
    # default to 256 MiB, via the vc4-kms-v3d overlay's `cma-256` param in
    # /boot/firmware/config.txt. Headroom that COMPLEMENTS US-522's
    # --disable-gpu; explicitly not a standalone fix for the freeze class.
    #
    # Same posture as step_enforce_eeprom_power_off_on_halt above: a standalone
    # idempotent script, run with sudo, re-asserted on EVERY deploy so a Pi
    # rebuilt via --init (or a config.txt rewritten by an OS image update)
    # lands back on the intended value instead of silently reverting to 64 MiB.
    # Runs AFTER sync_tree so deploy/set-gpu-cma.sh exists on the Pi.
    #
    # NOT cmdline.txt: the live Pi's /proc/cmdline carries no `cma=` arg (the
    # 64 MiB pool comes from the device tree), and a malformed cmdline.txt can
    # break `root=` on a headless box, whereas a bad overlay param only makes
    # the firmware skip the overlay -- dark display, SSH still reachable.
    #
    # BOOT-CONFIG SURFACE (deploy-contract blind spot, same class as the
    # /etc/chromium.d note in US-522): /boot/firmware/config.txt is OS-shipped
    # and can be rewritten out-of-band by `rpi-update`, an OS image upgrade, or
    # raspi-config. The script is idempotent and re-run on every deploy
    # precisely so that drift self-heals.
    #
    # The change takes effect on the NEXT BOOT only. This step deliberately
    # does not reboot the Pi -- an unattended reboot mid-deploy would race the
    # service restarts below. The script prints REBOOT REQUIRED; CmaTotal stays
    # at the old value until then.
    echo "--- Step: Setting GPU CMA to 256M in boot config (US-524 / F-124) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/set-gpu-cma.sh"
        echo "DRY-RUN would verify: /boot/firmware/config.txt vc4-kms-v3d overlay carries cma-256"
        echo "DRY-RUN note: takes effect on next reboot; confirm with grep CmaTotal /proc/meminfo"
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/set-gpu-cma.sh'"
}

step_set_network_authorization() {
    # ARCH-004: which networks this Pi may join.
    #
    # THE DEFECT, measured on the live Pi 2026-08-28: the home profile and a
    # saved profile for the car's Pioneer head unit were BOTH autoconnect with
    # BOTH at priority 0. Pulling into the garage, both APs are in range and
    # which one wins is not deterministic -- so garage sync was unreliable, and
    # 35 minutes of a drive sat unsynced on the Pi through a CLEAN shutdown.
    #
    # THE FIX IS NOT "disable autoconnect" -- the CIO caught that before it was
    # built, and he was right. NetworkManager never roams onto unknown APs; it
    # only joins networks it holds a saved profile for, so the allowlist already
    # existed and the stereo was simply ON it. The script instead makes home
    # OUTRANK everything (positive control, survives future profiles), drops
    # profiles not on the allowlist, and marks every secret system-owned so no
    # credential dialog can ever cover the driver's instrument.
    #
    # Re-asserted on EVERY deploy on purpose: tapping an SSID from the desktop
    # re-authorizes a network, and an OS upgrade can regenerate netplan output.
    # This step is how that drift self-heals.
    #
    # Takes effect on the NEXT ASSOCIATION, not the next reboot -- unlike the
    # two boot-config steps above. The script says so rather than letting the
    # deploy imply the Pi has already moved to the new policy.
    echo "--- Step: Re-asserting network authorization (ARCH-004) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/set-network-authorization.sh"
        echo "DRY-RUN would verify: home profile carries connection.autoconnect-priority"
        echo "DRY-RUN would verify: no wifi profile outside the allowlist remains"
        echo "DRY-RUN note: takes effect on next association; confirm with nmcli con show"
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/set-network-authorization.sh'"
}

step_set_display_mode() {
    # US-552 / F-127 (Atlas A-16 display-pipeline fidelity): pin the KMS output
    # mode to the panel's native 480x320 via a `video=<connector>:480x320` token
    # in /boot/firmware/cmdline.txt. Unpinned, the Pi scans out whatever EDID
    # negotiation lands on -- likely 1080p, which the 3.5" panel then
    # downsamples, softening every glyph and raising the legibility floor the
    # US-540 type scale was set against.
    #
    # Same posture as step_set_gpu_cma above: an idempotent standalone script,
    # run with sudo, re-asserted on EVERY deploy so a Pi rebuilt via --init (or
    # a cmdline.txt rewritten by an OS image update) lands back on the intended
    # mode. Runs AFTER sync_tree so deploy/set-display-mode.sh exists on the Pi.
    #
    # YES, cmdline.txt -- the surface step_set_gpu_cma deliberately refuses. On a
    # Pi 5 there is no alternative: the legacy config.txt hdmi_group/hdmi_mode
    # settings are a Pi 4-and-earlier firmware path. The script bounds the risk
    # instead: it discovers the connector from /sys/class/drm rather than
    # assuming one, writes NOTHING unless exactly one connector is connected and
    # the panel itself advertises the target mode, and verifies the composed
    # line (one line, root= and every original token intact) before installing
    # it -- restoring the pristine backup if the post-write read disagrees.
    #
    # It exits 0 on every "did not pin" path (no panel on a bench deploy, an
    # ambiguous two-panel setup, an operator-set video= left alone) so a bench
    # deploy cannot be halted by a display that is not plugged in. Non-zero
    # means a genuinely malformed boot cmdline or a failed write -- both of
    # which MUST stop the deploy before anyone reboots this Pi.
    #
    # The change takes effect on the NEXT BOOT only; the script says so rather
    # than letting the deploy imply the panel is already rendering 1:1.
    echo "--- Step: Pinning HDMI/KMS output to the panel-native mode (US-552 / F-127) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/set-display-mode.sh"
        echo "DRY-RUN would verify: /boot/firmware/cmdline.txt carries video=<connector>:480x320"
        echo "DRY-RUN note: takes effect on next reboot; confirm with cat /sys/class/graphics/fb0/virtual_size"
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/set-display-mode.sh'"
}

step_install_rfkill_unblock() {
    # BL-025 P0 (V0.29.22 hotfix, CIO-directed): make the boot-time radio
    # unblock REPO-MANAGED so a reflash or `--init` cannot lose it.
    #
    # systemd-rfkill restores a SAVED Bluetooth soft-block
    # (/var/lib/systemd/rfkill/*:bluetooth = [1]) on every boot -> BT comes up
    # blocked -> eclipse-obd never reaches the OBDLink LX -> zero capture. That
    # is the "dead since ~07-03" root cause, found live 2026-07-31. The unit
    # runs After=systemd-rfkill.service and unblocks all radios.
    #
    # Same sync-if-changed posture as step_install_orphan_cleanup_unit /
    # step_install_drain_forensics_unit: cmp -s guard, daemon-reload only on a
    # real change, `enable --now` re-asserted every deploy so an out-of-band
    # `systemctl disable` self-heals.
    #
    # The extra half the sibling steps do not have: the unit fixes every boot
    # FROM NOW ON, but a stale [1] is still sitting in /var/lib/systemd/rfkill
    # right now. Zeroing the saved state closes the window between this deploy
    # and the next reboot -- and removes the artifact instead of permanently
    # papering over it.
    echo "--- Step: Installing eclipse-rfkill-unblock systemd unit (BL-025, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-rfkill-unblock.service /etc/systemd/system/eclipse-rfkill-unblock.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now eclipse-rfkill-unblock.service"
        echo "DRY-RUN would: sudo rfkill unblock all + zero any saved block under /var/lib/systemd/rfkill/*bluetooth*"
        return 0
    fi
    remote "
        set -e
        SRC='${PI_PATH}/deploy/eclipse-rfkill-unblock.service'
        DST='/etc/systemd/system/eclipse-rfkill-unblock.service'

        if [ ! -f \"\$SRC\" ]; then
            echo 'WARN: eclipse-rfkill-unblock.service not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        if sudo test -f \"\$DST\" && sudo cmp -s \"\$SRC\" \"\$DST\"; then
            echo 'eclipse-rfkill-unblock.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC\" \"\$DST\"
            sudo systemctl daemon-reload
            echo 'eclipse-rfkill-unblock.service installed + daemon-reload complete.'
        fi

        sudo systemctl enable --now eclipse-rfkill-unblock.service
        echo 'eclipse-rfkill-unblock.service enabled + active.'

        # Belt-and-suspenders: clear the LIVE block and neutralize the SAVED
        # one, so this deploy does not leave a blocked radio waiting on a
        # reboot. Failures here are reported, not fatal -- the unit above is
        # the durable fix and a missing rfkill binary must not abort a deploy.
        if sudo rfkill unblock all; then
            echo 'rfkill: all radios unblocked.'
        else
            echo 'WARN: rfkill unblock all failed (is the rfkill package installed?).' >&2
        fi
        for f in /var/lib/systemd/rfkill/*bluetooth*; do
            [ -e \"\$f\" ] || continue
            if [ \"\$(sudo cat \"\$f\" 2>/dev/null)\" = '0' ]; then
                echo \"rfkill saved state already clear: \$f\"
            else
                echo '0' | sudo tee \"\$f\" >/dev/null && echo \"rfkill saved block CLEARED: \$f\"
            fi
        done
    "
}

step_install_bond_selfheal_unit() {
    # US-545 / A-18: install eclipse-bond-selfheal.service -- the BT bond
    # self-heal. Same sync-if-changed posture as the sibling unit steps.
    #
    # `enable` WITHOUT `--now`, deliberately. `--now` would run a full self-heal
    # in the middle of a deploy: stop capture, cycle the radio and try to pair,
    # on a box the operator is actively deploying to, for a bond that is
    # probably fine. The unit's job is the NEXT boot (it is ordered
    # Before=eclipse-obd.service); a deploy-time heal is the operator's explicit
    # call -- `systemctl start eclipse-bond-selfheal` with the engine on.
    echo "--- Step: Installing eclipse-bond-selfheal systemd unit (US-545, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-bond-selfheal.service /etc/systemd/system/eclipse-bond-selfheal.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable eclipse-bond-selfheal.service"
        return 0
    fi
    remote "
        set -e
        SRC='${PI_PATH}/deploy/eclipse-bond-selfheal.service'
        DST='/etc/systemd/system/eclipse-bond-selfheal.service'

        if [ ! -f \"\$SRC\" ]; then
            echo 'WARN: eclipse-bond-selfheal.service not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        if sudo test -f \"\$DST\" && sudo cmp -s \"\$SRC\" \"\$DST\"; then
            echo 'eclipse-bond-selfheal.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC\" \"\$DST\"
            sudo systemctl daemon-reload
            echo 'eclipse-bond-selfheal.service installed + daemon-reload complete.'
        fi

        sudo systemctl enable eclipse-bond-selfheal.service \
            && echo 'eclipse-bond-selfheal.service enabled (runs on the NEXT boot, before eclipse-obd).' \
            || echo 'WARN: failed to enable eclipse-bond-selfheal.service -- a lost BT bond will NOT self-heal at boot.' >&2
    "
}

step_install_rfcomm_bind() {
    # US-196: install rfcomm-bind.service so /dev/rfcomm0 is re-bound on every
    # boot. Idempotent — re-running re-writes /etc/default/obdlink with the
    # configured MAC and leaves the unit enabled.
    #
    # US-477 / F-120: the bind MAC is now the repo-canonical $OBD_BT_MAC (SSOT in
    # deploy/addresses.sh), NOT a best-effort ssh-pull from the Pi's own .env.
    # Trusting the Pi's .env is exactly how the 2026-07-17 phantom MAC
    # (00:04:3C:84:15:6B, a mis-identified device) propagated into the rfcomm
    # bind -> bound a nonexistent device -> zero capture. Binding the canonical
    # MAC makes the initial install self-correct too, in lockstep with the
    # every-deploy step_reassert_obd_mac.
    echo "--- Step: Installing rfcomm-bind systemd unit (US-196 reboot-survive) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/install-rfcomm-bind.sh ${OBD_BT_MAC}"
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/install-rfcomm-bind.sh' '${OBD_BT_MAC}'"
}

step_reassert_obd_mac() {
    # US-477 / F-120: self-heal the OBDLink LX MAC on the Pi's /etc/default/obdlink.
    # Runs on EVERY deploy (not just --init) with the same rationale as the EEPROM
    # enforcement step: the env file can be modified out-of-band on the Pi, and a
    # wrong MAC silently binds a dead device (the 2026-07-17 phantom incident that
    # captured zero rows for a weekend). Re-asserts the repo-canonical $OBD_BT_MAC
    # (SSOT deploy/addresses.sh). SURGICAL: corrects only the OBD_BT_MAC line and
    # preserves OBD_BT_CHANNEL. Idempotent -- no-op when already canonical.
    #
    # $OBDLINK_ENV_FILE overrides the target path; used by the --dry-run bench
    # path (US-477 validationCriterion 2) to demonstrate the self-heal against a
    # fixture without touching a real /etc/default/obdlink.
    local envFile="${OBDLINK_ENV_FILE:-/etc/default/obdlink}"
    echo "--- Step: Re-asserting canonical OBDLink MAC ${OBD_BT_MAC} into ${envFile} (US-477 self-heal) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would run: sudo bash ${PI_PATH}/deploy/reassert-obd-mac.sh --mac ${OBD_BT_MAC} --env-file ${envFile}"
        # When a local fixture env file is present (bench / VC2), show the actual
        # self-heal decision. The helper's --dry-run only REPORTS -- it never
        # writes -- so this stays dry-run-safe.
        if [[ -f "$envFile" ]]; then
            bash "${SCRIPT_DIR}/reassert-obd-mac.sh" --mac "$OBD_BT_MAC" --env-file "$envFile" --dry-run || true
        fi
        return 0
    fi
    remote "sudo bash '${PI_PATH}/deploy/reassert-obd-mac.sh' --mac '${OBD_BT_MAC}' --env-file '${envFile}'"
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
    #
    # US-480-b: also `systemctl enable` the orchestrator so a fresh --init Pi +
    # reboot AUTO-STARTS it -- and with it the in-process F-092/097/111 card-state
    # emitters (system-status / battery-health / dtc), which US-480-a wired to run
    # inside THIS process via CardStateEmitterMixin (Atlas Q-1: the OBD emitters
    # are orchestrator-invoked, never standalone units -- a standalone unit would
    # open a 2nd connection to the non-thread-safe OBD port and re-introduce the
    # A-17 race). Without the enable the unit installs but never boot-starts, so
    # /run/eclipse-obd/states/ stays empty and the carousel cards render the NA
    # wall -- the exact "code merged but never deploy-installed" gap that shipped
    # the emitters dark. `enable` (NOT `enable --now`): step_restart_service owns
    # the actual start via an explicit stop->start (US-389 release-then-acquire; a
    # --now here would race it). Re-asserted every deploy, OUTSIDE the cmp -s
    # change gate, so a Pi installed-but-never-enabled (or disabled out-of-band)
    # self-heals on a routine re-deploy.
    echo "--- Step: Installing ${SERVICE_NAME} systemd unit (sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/${SERVICE_NAME}.service /etc/systemd/system/${SERVICE_NAME}.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable ${SERVICE_NAME} (US-480-b boot-persistence for the in-process emitters; NOT --now -- step_restart_service owns the start)"
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
        # US-480-b: enable (boot-persistence) -- unconditional + idempotent, so a
        # Pi installed pre-US-480-b (or disabled out-of-band) self-heals. NOT
        # --now: step_restart_service owns the start (US-389 stop->start).
        sudo systemctl enable ${SERVICE_NAME} && echo '${SERVICE_NAME} enabled (boot-persistent; in-process emitters auto-start on reboot -- US-480-b).' || echo 'WARN: failed to enable ${SERVICE_NAME} -- reboot will NOT auto-start the emitters. Investigate before relying on the carousel.'
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

step_install_kiosk_watchdog_unit() {
    # US-523 / F-124: idempotent sync-if-changed install of
    # eclipse-kiosk-watchdog.service + .timer.  Same posture as
    # step_install_orphan_cleanup_unit: cmp -s the rsynced source against the
    # installed copy, daemon-reload only on real change, `enable --now` on every
    # deploy so the timer recovers from an out-of-band `systemctl disable`.
    #
    # The watchdog restarts eclipse-dashboard when chromium's renderer wedges
    # (GPU command-buffer hot-loop -- see the unit header + Atlas's RCA).  It is
    # defense-in-depth behind US-522's `--disable-gpu`, so a restart appearing
    # in its journal means that fix did NOT hold.
    #
    # No `install -d` here: the ledger dir is provisioned by the unit's own
    # RuntimeDirectory= (deliberately its OWN dir, not /run/eclipse-obd, which a
    # oneshot would delete on exit -- taking the live states/ with it).
    #
    # The restart itself rides the EXISTING polkit grant in
    # deploy/polkit-rules/51-eclipse-service-control.rules (restart verb on
    # eclipse-dashboard.service for the Pi user), so no new privilege is added.
    echo "--- Step: Installing kiosk-watchdog systemd unit (US-523 / F-124, sync-if-changed) ---"
    if $DRY_RUN; then
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-kiosk-watchdog.service /etc/systemd/system/eclipse-kiosk-watchdog.service || (install + daemon-reload)"
        echo "DRY-RUN would: sudo cmp -s ${PI_PATH}/deploy/eclipse-kiosk-watchdog.timer /etc/systemd/system/eclipse-kiosk-watchdog.timer || (install + daemon-reload)"
        echo "DRY-RUN would: sudo systemctl enable --now eclipse-kiosk-watchdog.timer"
        return 0
    fi
    remote "
        set -e
        SRC_SVC='${PI_PATH}/deploy/eclipse-kiosk-watchdog.service'
        DST_SVC='/etc/systemd/system/eclipse-kiosk-watchdog.service'
        SRC_TIM='${PI_PATH}/deploy/eclipse-kiosk-watchdog.timer'
        DST_TIM='/etc/systemd/system/eclipse-kiosk-watchdog.timer'

        if [ ! -f \"\$SRC_SVC\" ] || [ ! -f \"\$SRC_TIM\" ]; then
            echo 'WARN: eclipse-kiosk-watchdog unit files not present in deploy/ on the Pi -- skipping install.' >&2
            exit 0
        fi

        changed=false
        if sudo test -f \"\$DST_SVC\" && sudo cmp -s \"\$SRC_SVC\" \"\$DST_SVC\"; then
            echo 'eclipse-kiosk-watchdog.service already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_SVC\" \"\$DST_SVC\"
            echo 'eclipse-kiosk-watchdog.service installed.'
            changed=true
        fi
        if sudo test -f \"\$DST_TIM\" && sudo cmp -s \"\$SRC_TIM\" \"\$DST_TIM\"; then
            echo 'eclipse-kiosk-watchdog.timer already up-to-date.'
        else
            sudo install -m 644 \"\$SRC_TIM\" \"\$DST_TIM\"
            echo 'eclipse-kiosk-watchdog.timer installed.'
            changed=true
        fi

        if [ \"\$changed\" = true ]; then
            sudo systemctl daemon-reload
            echo 'systemd daemon-reload complete.'
        fi

        sudo systemctl enable --now eclipse-kiosk-watchdog.timer
        echo 'eclipse-kiosk-watchdog.timer enabled + active.'
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
    # (src/pi/ui/splash/) into /opt/splash, and write
    # /opt/splash/version.txt (the version chip boot-state-poll.js fetches as a
    # public static asset; malformed/absent -> the JS 'V?.?.?' fallback).
    #
    # A-9: if the splash kit is ABSENT this WARNs and lets the deploy CONTINUE --
    # it MUST NOT block.  A Pi deploy without the (UI-team) kit still ships the
    # rest of the tier.  The local-source guard returns 0; the remote
    # per-asset guard skips-with-warn any individual missing file.
    #
    # US-495 (S2/F-111): the install is a FORCE-REFRESH via
    # deploy/asset-refresh.sh -- install the manifest, PRUNE everything the
    # repo does not vouch for, then verify the bytes landed. /opt was previously
    # only ever written to, never pruned, so retired kit generations accumulated
    # there and (because /opt/splash is the FIRST --assets-dir) shadowed the real
    # assets forever.
    #
    # US-498 (S5/F-103): the manifest now covers the WHOLE served surface --
    # boot AND closeout (shutdown.html, shutdown-state-poll.js) plus both SVGs.
    # They were previously keep-listed as "the kit's install.sh owns those", but
    # a keep-listed asset is never installed, never pruned and never verified
    # here; its only refresh path was the kiosk-unit step, which is an A-9 step
    # allowed to WARN and skip (install.sh aborts outright if it cannot detect
    # the session type or the chromium binary). So the stale-asset hole US-495
    # closed for the boot surface was still wide open for the shutdown one --
    # and a stale closeout surface only shows itself during a shutdown, with
    # nobody watching. Both installers copy the same bytes from the same synced
    # kit dir, so owning them here costs nothing and buys the byte-verify.
    # `keepAssets` is now version.txt alone: the deploy GENERATES it from
    # deploy/RELEASE_VERSION below (not a kit file), so the refresh must not
    # prune it in the window before it is rewritten.
    #
    # Runs AFTER sync_tree so ${PI_PATH}/src/pi/ui/splash/ exists on the Pi.
    echo "--- Step: Installing F-103 splash assets + version.txt to /opt/splash (US-395) ---"
    local assetSrc="$REPO_ROOT/src/pi/ui/splash"
    local installDir="/opt/splash"
    local assets="index.html styles.css boot-state-poll.js shutdown.html shutdown-state-poll.js splash.svg splash-shutdown.svg"
    local keepAssets="version.txt"
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
        echo "DRY-RUN would: source ${PI_PATH}/deploy/asset-refresh.sh"
        echo "DRY-RUN would: refresh_asset_dir ${PI_PATH}/src/pi/ui/splash ${installDir} '${assets}' '${keepAssets}'"
        echo "DRY-RUN would:   (install + PRUNE unvouched files + verify bytes)"
        echo "DRY-RUN would: write ${installDir}/version.txt = ${splashVersion}"
        return 0
    fi
    remote "
        set -e
        . '${PI_PATH}/deploy/asset-refresh.sh'
        refresh_asset_dir '${PI_PATH}/src/pi/ui/splash' '${installDir}' \
                          '${assets}' '${keepAssets}'
        printf '%s\n' '${splashVersion}' | sudo tee '${installDir}/version.txt' >/dev/null
        echo 'wrote ${installDir}/version.txt = ${splashVersion}'
    "
}

step_install_dashboard_assets() {
    # US-399 (F-092, A-1/A-2): install the carousel dashboard kit assets the
    # eclipse-states-http.service serves to the chromium dashboard kiosk
    # (src/pi/ui/dashboard/) into /opt/dashboard. The server's
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
    # US-495 (S2/F-111): force-refresh via deploy/asset-refresh.sh, same as
    # the splash step. NO keep-list here -- /opt/dashboard has exactly one
    # installer (this step and the kit's install.sh ship the identical three
    # files), so anything else in there is a retired generation and gets pruned.
    #
    # Runs AFTER sync_tree so ${PI_PATH}/src/pi/ui/dashboard/ exists.
    echo "--- Step: Installing carousel dashboard assets to /opt/dashboard (US-399) ---"
    local assetSrc="$REPO_ROOT/src/pi/ui/dashboard"
    local installDir="/opt/dashboard"
    # OFL.txt (BL-027): the Oswald brand face ships INSIDE dashboard.css as an
    # inlined data: URI, and SIL OFL 1.1 requires the licence to travel with the
    # font. It must be VOUCHED here or refresh_asset_dir prunes it from
    # /opt/dashboard -- i.e. the repo would look compliant while the deployed
    # artifact shipped the face bare.
    local assets="dashboard.html dashboard.css carousel.js OFL.txt"
    if [ ! -d "$assetSrc" ]; then
        echo "WARN: dashboard assets not found at $assetSrc -- skipping; deploy continues (A-9)." >&2
        return 0
    fi
    if $DRY_RUN; then
        echo "DRY-RUN would: source ${PI_PATH}/deploy/asset-refresh.sh"
        echo "DRY-RUN would: refresh_asset_dir ${PI_PATH}/src/pi/ui/dashboard ${installDir} '${assets}'"
        echo "DRY-RUN would:   (install + PRUNE unvouched files + verify bytes)"
        return 0
    fi
    remote "
        set -e
        . '${PI_PATH}/deploy/asset-refresh.sh'
        refresh_asset_dir '${PI_PATH}/src/pi/ui/dashboard' '${installDir}' '${assets}'
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
    #   src/pi/ui/splash/install.sh     -> splash-boot + splash-grace units
    #   src/pi/ui/dashboard/install.sh  -> eclipse-dashboard unit
    #
    # Two things the first on-hardware run proved necessary (do NOT drop them):
    #  (1) SESSION DETECTION over SSH.  The installers' own V-2 check reads the
    #      CALLING session's type; over SSH that is 'tty', so the installer aborts
    #      ("cannot determine session type") rather than guess X11-vs-Wayland -- a
    #      wrong guess is the D-3 black-screen bug.  We detect the type from the Pi's
    #      ACTIVE graphical seat0 session and pass it via {SPLASH,DASHBOARD}_FORCE_SESSION.
    #      If it genuinely can't be determined we WARN + skip -- we never guess.
    #  (2) chromium BINARY name (US-428 -- Bug 2 proper fix).  The unit templates
    #      parameterize the browser as ExecStart=__CHROMIUM_BIN__; the kit installers'
    #      V-3 check detects the real path (chromium-browser OR chromium -- Trixie
    #      ships /usr/bin/chromium) and substitutes it into ExecStart, exactly like
    #      V-1 substitutes User=.  The old /usr/bin/chromium-browser symlink shim is
    #      RETIRED: an absent chromium now makes the installer fail loudly (its exit is
    #      wrapped WARN-not-BLOCK below, A-9), never a silent 203/EXEC unit.
    #
    # UNMANAGED FLAG SURFACE -- /etc/chromium.d/ (US-522, A-16 deploy-contract blind
    #   spot).  chromium's BASE flags are NOT in this repo: the Debian/RPi-OS
    #   `/usr/bin/chromium` wrapper sources every file in /etc/chromium.d/ into
    #   $CHROMIUM_FLAGS and then runs `exec .../chromium $CHROMIUM_FLAGS "$@"`, so the
    #   OS-shipped flags precede the unit's own argv.  That is where
    #   `--enable-gpu-rasterization` came from -- the flag that froze the kiosk
    #   (AllocateRingBuffer hot-loop; Atlas RCA 2026-08-02) and that a repo grep can
    #   never find.  The dashboard unit now overrides it with `--disable-gpu` in
    #   ExecStart (the only repo-managed lever), but the OS side stays UNMANAGED: a
    #   chromium PACKAGE UPGRADE can re-introduce GPU raster or add new flags with no
    #   repo change at all.  If the kiosk freeze class ever returns, diff
    #   /etc/chromium.d/default-flags and the live `pgrep -a chromium` cmdline FIRST.
    #
    # Idempotent (the installers are idempotent; the V-3 chromium substitution is
    # deterministic).  A-9
    # posture: absent kit/installer -> WARN + skip, deploy continues.  This installs +
    # ENABLES the units; the splash renders at the NEXT boot (WantedBy=graphical.target),
    # so the step does not thrash the live screen mid-deploy.  Runs AFTER the asset +
    # state-server steps so the served assets + backend are already in place.
    echo "--- Step: Installing F-103/F-092 chromium kiosk units (splash + dashboard) ---"
    local splashKit="src/pi/ui/splash/install.sh"
    local dashKit="src/pi/ui/dashboard/install.sh"
    if [ ! -f "$REPO_ROOT/$splashKit" ] && [ ! -f "$REPO_ROOT/$dashKit" ]; then
        echo "WARN: UI kit installers not found under $REPO_ROOT/src/pi/ui -- skipping kiosk-unit install (A-9)." >&2
        return 0
    fi
    if $DRY_RUN; then
        echo "DRY-RUN would: detect the Pi's ACTIVE graphical seat0 session type (x11|wayland)"
        echo "DRY-RUN would: (kit installers' V-3 check substitutes the real chromium path into ExecStart -- no symlink shim; US-428)"
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

        # (2) chromium binary (US-428 -- Bug 2 proper fix): NO symlink shim here.
        #     The kit installers' V-3 check detects the real chromium path
        #     (chromium-browser OR chromium) and substitutes it into the unit
        #     ExecStart (like User=, V-1), so /usr/bin/chromium-browser need not
        #     exist.  An absent chromium makes the installer fail loudly below,
        #     wrapped WARN-not-BLOCK (A-9) -- never a 203/EXEC unit.

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
    # NOT `[ -d .git ]`: trunk\ is a git WORKTREE, where .git is a FILE holding
    # "gitdir: ...", not a directory. That check silently failed after the v3
    # move and every deploy since has stamped gitHash "unknown" -- so nobody
    # could tell what code was on the car. rev-parse works in both layouts.
    if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
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

# US-553: clear stale bytecode IMMEDIATELY after the sync and long before the
# service restart, so the interpreter that starts at the end of this deploy can
# only load bytecode compiled from the source this deploy just shipped. Must
# run AFTER sync_tree -- purging first would just be re-orphaned by the sync.
step_purge_stale_bytecode

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

# US-524 / F-124: GPU CMA headroom (64 MiB device-tree default -> 256 MiB via
# the vc4-kms-v3d overlay's cma-256 param). Ordered directly after the EEPROM
# step because both are idempotent BOX-level boot/firmware config re-asserted
# on every deploy, and both must run AFTER sync_tree so their standalone
# scripts exist on the Pi. Takes effect on the next reboot; the script says so
# rather than letting the deploy imply the pool was raised immediately.
step_set_gpu_cma

# US-552 / F-127: pin the HDMI/KMS output mode to the panel-native 480x320.
# Ordered directly after step_set_gpu_cma because it is the same class of step
# -- an idempotent BOX-level boot-config re-assertion that needs sync_tree to
# have put its standalone script on the Pi, and that takes effect on the next
# reboot. Both touch the display pipeline, so keeping them adjacent keeps the
# "what did the deploy change about the screen" answer in one place.
step_set_display_mode

# ARCH-004: re-assert WHICH NETWORKS this Pi may join. Same class as the two
# steps above -- an idempotent BOX-level re-assertion that needs sync_tree to
# have put its standalone script on the Pi -- but NOT a boot-config step: it
# takes effect on the next association, not the next reboot.
#
# Ordered last in this block because it is the member of the family most likely
# to drift: tapping an SSID from the desktop is enough to re-authorize a
# network, and an OS upgrade can regenerate netplan output.
step_set_network_authorization

# US-477 / F-120: re-assert the canonical OBDLink MAC into /etc/default/obdlink
# on EVERY deploy so a drifted Pi (like the 2026-07-17 phantom that captured
# zero rows) self-heals on the next routine re-deploy -- NOT gated behind
# --init. Same posture as step_enforce_eeprom_power_off_on_halt: idempotent,
# reasserts canonical OS-side config, runs AFTER sync_tree so
# deploy/reassert-obd-mac.sh exists on the Pi.
step_reassert_obd_mac

# BL-025 P0: install + enable the boot-time radio unblock. Runs on EVERY deploy
# (not gated behind --init) for the same reason as step_reassert_obd_mac above:
# a radio soft-block can be re-saved at any shutdown, so the safety net has to be
# re-asserted routinely, and a Pi that has drifted must self-heal on the next
# ordinary re-deploy rather than waiting for a rebuild. Ordered BEFORE
# step_install_rfcomm_bind because binding /dev/rfcomm0 to a soft-blocked
# adapter is precisely the failure this unit exists to prevent. Runs AFTER
# sync_tree so deploy/eclipse-rfkill-unblock.service exists on the Pi.
step_install_rfkill_unblock

# US-545 / A-18: bond self-heal. Ordered right after the rfkill unblock for the
# same reason the UNIT declares After=eclipse-rfkill-unblock.service -- a bond
# check on a soft-blocked adapter reports "dongle not discoverable", which is a
# confident wrong answer that sends the operator after the wrong fault. Runs
# AFTER sync_tree so deploy/eclipse-bond-selfheal.service exists on the Pi.
step_install_bond_selfheal_unit

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
# US-492: obdctl operator CLI. Runs AFTER the tree sync (the wrapper execs the
# synced src/pi/ops/obdctl.py) and BEFORE the unit installs, so that if a later
# step leaves a unit in a bad state the operator already has the tool to fix it.
step_install_obdctl
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
# and src/pi/ui/splash/ exist on the Pi.  Same sync-if-changed posture as
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
# US-523 (F-124): the kiosk WATCHDOG -- restarts eclipse-dashboard when
# chromium's renderer wedges.  Installed AFTER the kiosk units it guards so the
# unit it restarts already exists on the box when the timer's first tick lands.
step_install_kiosk_watchdog_unit

# ================================================================================
# Post-deploy prune (2026-08-26) -- the Pi is an appliance, not a workshop
# ================================================================================
#
# Runs ONLY after every deploy step above has succeeded, because it deletes: a
# half-finished deploy plus a prune is the one combination that could remove
# something the deploy had not yet replaced.
#
# Two jobs:
#
# 1. DB backups. cleanup_orphan_realtime_data.py copies the whole DB to
#    <name>.bak-us322-<ts> before --execute, and orphan-cleanup.timer fires
#    NIGHTLY with Persistent=true. Nothing pruned them: 5 copies / 11 GB had
#    accumulated on the car with roughly five weeks of SD card left. The script
#    now retains 2 itself; this step also clears any pre-existing pile-up, and
#    keeps working if an older script is ever on the box.
#
# 2. The workshop. The rsync whitelist stops NEW workshop files shipping, but
#    --delete deliberately spares excluded files -- that is exactly why data/ and
#    .env survive a deploy. The consequence is that offices/, specs/, tests/ and
#    tools/ (~119 MB) stay forever once present. Removing them takes an explicit
#    delete.
#
# SAFETY: this is an explicit REMOVE list, not "delete anything not in a keep
# list". A keep-list omission would delete drive data; a remove-list omission
# only leaves clutter. Anything unrecognised is REPORTED, never deleted -- so a
# new top-level directory gets a loud line in the deploy log instead of a
# surprise deletion.
step_prune_pi_workshop() {
    echo "--- Step: Pruning workshop + old DB backups on the Pi ---"

    if $DRY_RUN; then
        echo "DRY-RUN would prune workshop dirs and DB backups beyond 2 on ${PI_HOST}"
        return 0
    fi

    ssh -p "${PI_PORT}" "${PI_USER}@${PI_HOST}" "
        set -e
        cd '${PI_PATH}' || exit 0

        # --- 1. DB backups: keep the 2 newest, sorted by the stamp in the NAME.
        # Not mtime: a restore or file copy rewrites mtimes and would select the
        # wrong victims.
        for db in data/*.db; do
            [ -e \"\$db\" ] || continue
            n=\$(ls -1 \"\$db\".bak-us322-* 2>/dev/null | wc -l)
            if [ \"\$n\" -gt 2 ]; then
                ls -1 \"\$db\".bak-us322-* | sort | head -n -2 | while read -r old; do
                    echo \"  pruning old backup: \$(basename \"\$old\")\"
                    rm -f \"\$old\"
                done
            fi
        done

        # --- 2. Workshop: explicit list only.
        for w in offices specs tests tools docs .claude .github .superpowers \
                 CLAUDE.md README.md Makefile pyproject.toml validate_config.py \
                 .gitattributes .env.example .env.production.example \
                 requirements-dev.txt requirements-server.txt; do
            if [ -e \"\$w\" ]; then
                echo \"  removing workshop: \$w\"
                rm -rf \"\$w\"
            fi
        done

        # --- 3. Report anything unrecognised. Never delete it.
        for e in \$(ls -A); do
            case \"\$e\" in
                data|src|scripts|deploy|config.json|config.local.json|.env|.venv|\
logs|exports|.deploy-version|requirements.txt|requirements-pi.txt|.gitignore|\
.backfill-*|.lgd-*) ;;
                *) echo \"  NOTE: unrecognised top-level entry left in place: \$e\" ;;
            esac
        done

        echo \"  Pi tree now: \$(du -sh . 2>/dev/null | cut -f1)\"
    "
    echo ""
}

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
step_prune_pi_workshop

echo ""
echo "Deploy OK: $(date -Iseconds) to ${PI_USER}@${PI_HOST}"
