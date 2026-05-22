#!/usr/bin/env bash
################################################################################
# deploy-server.sh — Deploy/update the OBD2v2 server on Chi-Srv-01
#
# Usage:
#   bash deploy/deploy-server.sh              # Deploy from current branch
#   bash deploy/deploy-server.sh --init       # First-time setup (venv + DB tables)
#   bash deploy/deploy-server.sh --restart    # Just restart the service
#
# Prerequisites:
#   - SSH access to chi-srv-01 as mcornelison
#   - Project cloned at /mnt/projects/O/OBD2v2
#   - .env file configured at /mnt/projects/O/OBD2v2/.env
#   - MariaDB running with obd2db database and obd2 user created
#
# What this script does:
#   1. Pulls latest code from origin on the server
#   2. Creates/updates venv in ~/obd2-server-venv (avoids NAS symlink issues)
#   3. Installs/updates server + base dependencies
#   3.5 (--init only) API_KEY bake-in
#   4. (--init only) Creates MariaDB tables via SQLAlchemy create_all
#   4.5 Applies pending schema migrations via apply_server_migrations.py --run-all
#       (US-213 / TD-029: runs on --init AND default flow; idempotent; hard-fails
#       deploy under `set -e` if any migration fails)
#   4.6 Backfills stranded battery_health_log rows via
#       backfill_server_battery_health_log_stranded.py (US-327 / I-027): cheap
#       server-only --count-stranded pre-check, then --dry-run + --execute when
#       >0; idempotent (later deploys no-op); best-effort -- a WARN, not a
#       deploy blocker (Pi may be offline during a server deploy)
#   4.7 Installs/updates obd-server.service systemd unit (US-231; sync-if-changed)
#   4.8 Installs server-analytics-batch.service + .timer (US-350 / B-104; sync-if-changed)
#   4.9 One-shot backfill of drives 11-20 via the on-demand recompute CLI
#       (US-352 / B-104 Step 1c): runs once post-V0.27.17 deploy, guarded by
#       .backfill-V0.27.17-drives-11-20-complete marker; best-effort (failure
#       logs WARN, deploy continues, nightly server-analytics-batch.timer
#       retries via --all-stale)
#   5. Cutover: kills any orphan nohup uvicorn (one-time pre-systemd cleanup)
#   5.5 Writes ${PROJECT}/.deploy-version (US-241; SemVer-shaped release record)
#   6. Restarts via `sudo systemctl restart obd-server` (US-231; replaces nohup)
#   7. Waits 3 seconds and checks /health endpoint
################################################################################

set -e

# B-044: source canonical bash-side addresses. Operators may override by
# pre-setting SERVER_HOST / SERVER_USER / SERVER_PROJECT_PATH / SERVER_PORT
# in the environment.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=addresses.sh
. "$SCRIPT_DIR/addresses.sh"

HOST="${SERVER_USER}@${SERVER_HOSTNAME}"
PROJECT="${SERVER_PROJECT_PATH}"
VENV="$HOME/obd2-server-venv"
REMOTE_VENV="/home/${SERVER_USER}/obd2-server-venv"
PORT="${SERVER_PORT}"
LOG="/tmp/obd2-server.log"

# Parse flags
INIT=false
RESTART_ONLY=false
for arg in "$@"; do
    case $arg in
        --init) INIT=true ;;
        --restart) RESTART_ONLY=true ;;
        --help|-h)
            echo "Usage: bash deploy/deploy-server.sh [--init|--restart]"
            echo "  --init     First-time setup: create venv, install deps, create DB tables"
            echo "  --restart  Skip pull/install, just restart the server"
            echo "  (no flag)  Pull latest, install deps, restart server"
            exit 0
            ;;
    esac
done

echo "=== OBD2v2 Server Deployment ==="
echo "Host: ${SERVER_HOSTNAME}"
echo "Project: $PROJECT"
echo ""

# Step 1: Pull latest code
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 1: Pulling latest code ---"
    ssh $HOST "cd $PROJECT && git pull 2>&1"
    echo ""
fi

# Step 2: Create venv if needed (--init or first run)
if [ "$INIT" = true ] || ! ssh $HOST "test -f $REMOTE_VENV/bin/python3" 2>/dev/null; then
    echo "--- Step 2: Creating venv at $REMOTE_VENV ---"
    ssh $HOST "python3 -m venv $REMOTE_VENV"
    echo "Venv created."
    echo ""
fi

# Step 3: Install/update dependencies
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 3: Installing dependencies ---"
    ssh $HOST "$REMOTE_VENV/bin/pip install -q -r $PROJECT/requirements.txt -r $PROJECT/requirements-server.txt 2>&1 | tail -5"
    echo ""
fi

# Step 3.5: API_KEY bake-in (--init only) -- US-201.
# Ensures /etc/eclipse-obd-server/.env (or $PROJECT/.env, the default)
# has API_KEY. Idempotent: never overwrites an existing value (rotating
# would break the already-paired Pi).
if [ "$INIT" = true ]; then
    echo "--- Step 3.5: Ensuring server .env has API_KEY (US-201) ---"
    SERVER_ENV="$PROJECT/.env"
    KEY_PRESENT=$(ssh "$HOST" \
        "grep -E '^API_KEY=.+' '$SERVER_ENV' >/dev/null 2>&1 && echo yes || echo no")
    if [ "$KEY_PRESENT" = "yes" ]; then
        echo "API_KEY already present in server .env -- no change (idempotent)."
    else
        echo "API_KEY missing or empty in server .env."
        echo "Choose:"
        echo "  [g] Generate a fresh 64-hex key"
        echo "  [p] Paste an existing key (when pairing with a pre-configured Pi)"
        echo "  [s] Skip"
        read -r -p "Choice [g/p/s]: " CHOICE
        NEW_KEY=""
        case "$CHOICE" in
            g|G)
                SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
                NEW_KEY=$(bash "$SCRIPT_ROOT/scripts/generate_api_key.sh")
                echo "Generated fresh key (not echoed). Writing..."
                ;;
            p|P)
                read -r -s -p "Paste API key (input hidden): " NEW_KEY
                echo ""
                [ -z "$NEW_KEY" ] && { echo "Empty paste -- aborting."; exit 1; }
                ;;
            *)
                echo "Skipped. Wire API_KEY into $SERVER_ENV manually later."
                NEW_KEY=""
                ;;
        esac
        if [ -n "$NEW_KEY" ]; then
            printf 'API_KEY=%s\n' "$NEW_KEY" | \
                ssh "$HOST" "cat >> '$SERVER_ENV' && chmod 600 '$SERVER_ENV'"
            echo "API_KEY written to $SERVER_ENV on $HOST (chmod 600)."
        fi
    fi
    echo ""
fi

# Step 4: Create DB tables (--init only)
if [ "$INIT" = true ]; then
    echo "--- Step 4: Creating MariaDB tables ---"
    ssh $HOST "cd $PROJECT && PYTHONPATH=$PROJECT $REMOTE_VENV/bin/python -c \"
from src.server.db.models import Base
from sqlalchemy import create_engine
from src.server.config import Settings
s = Settings(_env_file='$PROJECT/.env')
url = str(s.DATABASE_URL).replace('aiomysql', 'pymysql')
e = create_engine(url)
Base.metadata.create_all(e)
print('Tables:', list(Base.metadata.tables.keys()))
\" 2>&1"
    echo ""
fi

# Step 4.5: Apply pending schema migrations (US-213 / TD-029 closure).
# Runs on --init AND the default deploy flow; skipped when --restart.  `set -e`
# at top of script + non-zero rc from apply_server_migrations.py --run-all
# halts the deploy before the service restart -- no partially-migrated state.
# The runner is idempotent; a fully-migrated server emits a single
# "0 applied" line and exits 0.  US-209 manual-migrated servers will record
# version='0001' on first run (scan returns empty plan, so no DDL emitted).
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 4.5: Applying pending schema migrations ---"
    # Runs LOCALLY (not via SSH on server) because apply_server_migrations.py
    # is designed to SSH to the server itself; running it server-side
    # attempts a self-SSH that fails host-key verification.
    LOCAL_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    PYTHONPATH="$LOCAL_REPO_ROOT" python "$LOCAL_REPO_ROOT/scripts/apply_server_migrations.py" --run-all --addresses "$LOCAL_REPO_ROOT/deploy/addresses.sh"
    echo ""
fi

# Step 4.6 (US-327 / I-027): idempotent backfill of the stranded server-side
# battery_health_log rows.  V0.27.6 US-323 shipped
# scripts/backfill_server_battery_health_log_stranded.py to populate the
# pre-V0.27.4 rows (drain_event_ids 11-15) whose end_timestamp is still NULL
# server-side -- but nothing auto-invoked it, so they stayed stranded.  Wire-in:
#   1. `--count-stranded` -- cheap server-only pre-check (no Pi SSH, no
#      mutation, no sentinel) prints how many of those rows are still NULL;
#   2. if >0, `--dry-run` (writes the sentinel) then `--execute` (mysqldump
#      backup first, then the UPDATE batch in one transaction);
#   3. if 0, the whole step is a no-op (idempotent -- subsequent deploys skip
#      straight past after the first successful backfill).
# Runs LOCALLY (the backfill script SSHes to BOTH the server and the Pi itself,
# same as Step 4.5).  Best-effort: a Pi-unreachable / preflight failure logs a
# WARN and the deploy continues -- rows stay stranded and the next deploy
# retries (the `AND end_timestamp IS NULL` guard keeps every retry safe).
# Must run AFTER Step 4.5 (the end_timestamp/end_soc/runtime_seconds columns
# come from those migrations).  The dry-run sentinel goes to a temp dir (not
# the repo root) so an interrupted deploy never leaves a stray dotfile in the
# working tree.  Skipped on --restart.
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 4.6: Backfilling stranded battery_health_log rows (US-327) ---"
    LOCAL_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    BACKFILL_PY="$LOCAL_REPO_ROOT/scripts/backfill_server_battery_health_log_stranded.py"
    ADDRESSES_SH="$LOCAL_REPO_ROOT/deploy/addresses.sh"
    BACKFILL_SENTINEL_DIR="${TMPDIR:-/tmp}"
    STRANDED_COUNT=$(PYTHONPATH="$LOCAL_REPO_ROOT" python "$BACKFILL_PY" --count-stranded --addresses "$ADDRESSES_SH" || echo "ERR")
    if [ "$STRANDED_COUNT" = "ERR" ]; then
        echo "WARN: stranded-row preflight failed (server unreachable?); skipping backfill -- safe to retry next deploy."
    elif [ "$STRANDED_COUNT" -gt 0 ] 2>/dev/null; then
        echo "Found ${STRANDED_COUNT} stranded battery_health_log row(s); running backfill..."
        if PYTHONPATH="$LOCAL_REPO_ROOT" python "$BACKFILL_PY" --dry-run --addresses "$ADDRESSES_SH" --sentinel-dir "$BACKFILL_SENTINEL_DIR" \
           && PYTHONPATH="$LOCAL_REPO_ROOT" python "$BACKFILL_PY" --execute --addresses "$ADDRESSES_SH" --sentinel-dir "$BACKFILL_SENTINEL_DIR"; then
            echo "Stranded-row backfill complete."
        else
            echo "WARN: backfill did not complete (Pi unreachable?); rows stay stranded -- safe to retry next deploy."
        fi
    else
        echo "No stranded battery_health_log rows; backfill no-op (idempotent)."
    fi
    echo ""
fi

# Step 4.7 (US-231): Install/update obd-server.service systemd unit.
# Mirror of deploy-pi.sh step_install_eclipse_obd_unit -- sync-if-changed via
# cmp -s so re-deploys are no-ops when the unit content matches the installed
# copy. Runs on every default deploy AND on --restart (so a sprint that only
# tweaks the unit can ship via `bash deploy/deploy-server.sh --restart` if
# the operator prefers).
#
# Idempotency: the cmp -s gate skips daemon-reload when nothing changed --
# important because daemon-reload triggers a brief unit re-evaluation that
# can stall systemd-analyze on a busy box.
#
# sudo prompts: `sudo install` + `sudo systemctl daemon-reload` +
# `sudo systemctl enable` will prompt for the operator's password unless
# /etc/sudoers grants NOPASSWD for these systemctl operations. Pre-US-231
# scout (Session 105) confirmed sudo REQUIRES password on chi-srv-01;
# operator handles the prompt during deploy.
echo "--- Step 4.7: Installing obd-server.service systemd unit (US-231) ---"
# `ssh -t` allocates a pseudo-TTY so sudo can prompt the operator
# interactively. Without -t, sudo errors with "a terminal is required to read
# the password" and the SSH session exits non-zero -- but the remote shell
# without `set -e` would have run subsequent commands anyway, hiding the
# failure behind a misleading success-echo. `set -e` inside the heredoc
# closes that gap so any sudo failure halts the remote shell + exits non-zero.
ssh -t $HOST "
    set -e
    SRC='${PROJECT}/deploy/obd-server.service'
    DST='/etc/systemd/system/obd-server.service'
    if [ ! -f \"\$SRC\" ]; then
        echo \"WARN: \$SRC not present on ${SERVER_HOSTNAME} -- skipping unit install.\"
        exit 0
    fi
    if [ -f \"\$DST\" ] && cmp -s \"\$SRC\" \"\$DST\"; then
        echo 'obd-server.service already up-to-date; no install needed.'
    else
        echo 'Installing new obd-server.service -> /etc/systemd/system/'
        sudo /usr/bin/install -m 644 \"\$SRC\" \"\$DST\"
        sudo /usr/bin/systemctl daemon-reload
        sudo /usr/bin/systemctl enable obd-server.service
        echo 'Unit installed + daemon-reload + enabled.'
    fi
"
echo ""

# Step 4.8 (US-350 / B-104 Step 1a, V0.27.17): install server-analytics-batch
# nightly recompute unit + timer.  Mirrors Step 4.7 sync-if-changed-via-cmp -s
# pattern: skip install + daemon-reload + enable when both files already
# match.  Daemon-reload is intentionally batched at the END (after both files
# are in place) so systemd evaluates the pair as a coherent install.
echo "--- Step 4.8: Installing server-analytics-batch.service + .timer (US-350 / B-104) ---"
ssh -t $HOST "
    set -e
    SVC_SRC='${PROJECT}/deploy/server-analytics-batch.service'
    SVC_DST='/etc/systemd/system/server-analytics-batch.service'
    TIM_SRC='${PROJECT}/deploy/server-analytics-batch.timer'
    TIM_DST='/etc/systemd/system/server-analytics-batch.timer'
    if [ ! -f \"\$SVC_SRC\" ] || [ ! -f \"\$TIM_SRC\" ]; then
        echo \"WARN: analytics-batch unit/timer not present on ${SERVER_HOSTNAME} -- skipping install.\"
        exit 0
    fi
    CHANGED=0
    if [ ! -f \"\$SVC_DST\" ] || ! cmp -s \"\$SVC_SRC\" \"\$SVC_DST\"; then
        echo 'Installing new server-analytics-batch.service -> /etc/systemd/system/'
        sudo /usr/bin/install -m 644 \"\$SVC_SRC\" \"\$SVC_DST\"
        CHANGED=1
    fi
    if [ ! -f \"\$TIM_DST\" ] || ! cmp -s \"\$TIM_SRC\" \"\$TIM_DST\"; then
        echo 'Installing new server-analytics-batch.timer -> /etc/systemd/system/'
        sudo /usr/bin/install -m 644 \"\$TIM_SRC\" \"\$TIM_DST\"
        CHANGED=1
    fi
    if [ \"\$CHANGED\" = '1' ]; then
        sudo /usr/bin/systemctl daemon-reload
        sudo /usr/bin/systemctl enable --now server-analytics-batch.timer
        echo 'analytics-batch unit + timer installed + daemon-reload + enabled --now.'
    else
        echo 'analytics-batch unit + timer already up-to-date; no install needed.'
    fi
"
echo ""

# Step 4.9 (US-352 / B-104 Step 1c, V0.27.17): one-shot backfill of drives
# 11-20 via the new server compute path.  Drives 11-20 shipped to production
# with NULL drive_summary computed fields + zero drive_statistics rows under
# the V0.27.7-V0.27.16 trigger-seam writer (US-326 / US-348 / US-328 / US-349
# false-pass class).  US-350 + US-351 land the server compute paths; this
# step is the FIRST exercise of the on-demand recompute CLI -- the empirical
# validation of the new architecture against 10 real drives' raw data + the
# close of the historical data hole.  Drive 11 inclusion per Spool FLAG-2 +
# Argus DB-state check 2026-05-21 outcome (a) confirming Drive 11 has the
# same NULL/zero pre-fix state as drives 12-19 (knock-retard reference
# baseline on 93 octane; Spool knowledge.md anchor).
#
# Idempotency comes from a marker file at
# ${PROJECT}/.backfill-V0.27.17-drives-11-20-complete on chi-srv-01.  The
# first successful invocation writes the marker; subsequent deploys check
# the marker and skip.  The CLI itself is also idempotent (re-run produces
# identical data values; computed_at advances via onupdate=func.now()), so
# even if the marker check ever races, no harm done -- this guard is for
# deploy ergonomics (skip the 10-drive recompute on every redeploy), not
# correctness.
#
# Best-effort: a failure logs a WARN and the deploy continues (mirrors the
# Step 4.6 stranded-row backfill idiom).  The nightly server-analytics-batch
# timer (Step 4.8) will catch any drives still NULL via --all-stale on its
# next tick -- the backfill is a deploy-time convenience, not a load-bearing
# gate.  Skipped on --restart (no data state changes; restarts shouldn't
# trigger backfills).
#
# Runs ON the server via ssh + the server venv because the CLI imports
# src.server.config.Settings which reads chi-srv-01's .env DATABASE_URL.
# Mirrors Step 4 (DB table creation) which uses the same idiom.
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 4.9: Backfilling drives 11-20 via server compute path (US-352 / B-104) ---"
    BACKFILL_MARKER="${PROJECT}/.backfill-V0.27.17-drives-11-20-complete"
    MARKER_PRESENT=$(ssh "$HOST" "test -f '${BACKFILL_MARKER}' && echo yes || echo no")
    if [ "$MARKER_PRESENT" = "yes" ]; then
        echo "Backfill already complete (marker at ${BACKFILL_MARKER}); skipping (idempotent)."
    else
        echo "Running one-shot backfill of drives 11-20 on ${SERVER_HOSTNAME}..."
        if ssh "$HOST" "cd $PROJECT && PYTHONPATH=$PROJECT $REMOTE_VENV/bin/python -m src.server.cli.recompute_drive_analytics --drive-id-range 11-20"; then
            ssh "$HOST" "printf 'BACKFILL_COMPLETE_V0_27_17_DRIVES_11_20=true\n' > '${BACKFILL_MARKER}'"
            echo "Backfill complete; marker written to ${BACKFILL_MARKER}."
        else
            echo "WARN: drives-11-20 backfill did not complete cleanly; rows may stay stale -- nightly server-analytics-batch.timer (Step 4.8) will retry via --all-stale."
        fi
    fi
    echo ""
fi

# Step 5 (US-231 cutover): kill orphan pre-systemd uvicorn ONLY when systemd
# isn't managing it yet. The pre-US-231 deploy launched uvicorn via `ssh -f
# ... nohup`; that process is NOT systemd-managed and will conflict on port
# 8000 if left running when we switch to the systemd unit. Once the systemd
# unit IS managing the process, we MUST NOT pkill (that would race with the
# systemctl restart in step 6 and the legacy [u]vicorn pattern matches the
# systemd-managed cmdline too). Conditional gate: pkill only when the unit
# is NOT active. Use the broad cmdline pattern (catches both the bash
# `nohup` wrapper AND the detached uvicorn child -- the narrower
# `nohup .*[u]vicorn` pattern would only catch the wrapper, leaving the
# detached child alive). The [u]vicorn bracket trick prevents the SSH shell
# hosting the pkill from self-matching.
echo "--- Step 5: Cutover -- killing orphan pre-systemd uvicorn (only if systemd not managing) ---"
ssh $HOST "
    if systemctl is-active --quiet obd-server.service 2>/dev/null; then
        echo 'obd-server.service is systemd-managed; pkill not needed.'
    else
        pkill -f '[u]vicorn src.server.main:app' 2>/dev/null && echo 'Pre-systemd orphan stopped.' || echo 'No orphan running.'
    fi
"
sleep 1
echo ""

# Step 5.5 (US-241): write .deploy-version on the server.
# Mirrors deploy-pi.sh step_write_deploy_version. Stamps {version, releasedAt,
# gitHash, description} into ${PROJECT}/.deploy-version so B-047 US-B's
# /api/v1/version endpoint can return the current server version. Composed
# via scripts/version_helpers.py compose-record so the JSON shape lives in
# one testable Python module. Idempotent: re-running with the same version +
# gitHash overwrites with a refreshed releasedAt.
echo "--- Step 5.5: Writing .deploy-version on server (US-241) ---"
LOCAL_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -d "$LOCAL_REPO_ROOT/.git" ]; then
    GIT_HASH=$(git -C "$LOCAL_REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)
else
    GIT_HASH="unknown"
fi
VERSION_JSON=$(python "$LOCAL_REPO_ROOT/scripts/version_helpers.py" compose-record \
    --version-file "$LOCAL_REPO_ROOT/deploy/RELEASE_VERSION" \
    --git-hash "$GIT_HASH")
if [ -z "$VERSION_JSON" ]; then
    echo "ERROR: failed to compose release record from $LOCAL_REPO_ROOT/deploy/RELEASE_VERSION" >&2
    exit 1
fi
printf '%s\n' "$VERSION_JSON" | \
    ssh "$HOST" "cat > '${PROJECT}/.deploy-version'"
echo "Wrote ${PROJECT}/.deploy-version: ${VERSION_JSON}"
echo ""

# Step 6 (US-231): restart the systemd-managed server.
# `ssh -t` so sudo can prompt the operator interactively (chi-srv-01 sudo
# requires a password per Session 105 pre-flight). Replaces the pre-US-231
# `ssh -f nohup` pattern. systemctl restart handles both the start-from-stopped
# case (post-step-5 cutover) and the restart case (subsequent deploys).
# is-active check + 2s settle window catches a unit that fails to come up
# (DB connection rejected, port already bound, etc.) before the health check.
echo "--- Step 6: Restarting obd-server.service ---"
ssh -t $HOST "sudo systemctl restart obd-server.service"
sleep 2
ACTIVE=$(ssh $HOST "systemctl is-active obd-server.service" 2>/dev/null)
if [ "$ACTIVE" = "active" ]; then
    echo "obd-server.service active."
else
    echo "ERROR: obd-server.service not active after restart (state=$ACTIVE)."
    echo "  Check: ssh $HOST 'sudo journalctl -u obd-server.service -n 50 --no-pager'"
    exit 1
fi
echo ""

# Step 7: Health check
echo "--- Step 7: Health check ---"
sleep 3
HEALTH=$(curl -s "http://${SERVER_HOSTNAME}:${PORT}/api/v1/health" 2>/dev/null)
if [ $? -eq 0 ] && echo "$HEALTH" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Status: {d[\"status\"]}, Drives: {d[\"driveCount\"]}, Uptime: {d[\"uptime\"]}')" 2>/dev/null; then
    echo "Server is healthy."
else
    echo "HEALTH CHECK FAILED. Check log:"
    ssh $HOST "tail -20 $LOG"
    exit 1
fi

echo ""
echo "=== Deployment complete ==="
