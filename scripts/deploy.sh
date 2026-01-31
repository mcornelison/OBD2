#!/bin/bash
################################################################################
# File Name: deploy.sh
# Purpose/Description: Deploy Eclipse OBD-II project from Windows to Raspberry Pi
# Author: Rex (Ralph Agent)
# Creation Date: 2026-01-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-31    | Rex          | Initial implementation (US-DEP-002)
# ================================================================================
################################################################################

#
# Core Deploy Script for Eclipse OBD-II System
#
# Syncs project files from Windows (MINGW64/Git Bash) to Raspberry Pi via rsync
# over SSH. Reads connection details from deploy/deploy.conf.
#
# Usage:
#     ./scripts/deploy.sh
#
# Exit Codes:
#     0 - Success
#     1 - Configuration error (missing deploy.conf or invalid values)
#     2 - SSH connectivity failure
#     3 - rsync transfer failure
#
# Prerequisites:
#     - deploy/deploy.conf configured with Pi connection details
#     - SSH key-based auth set up (or willingness to enter password)
#     - rsync and ssh available in PATH (standard in Git Bash / MINGW64)
#

set -e  # Exit on error

# Script directory (for finding project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ================================================================================
# Constants
# ================================================================================

EXIT_SUCCESS=0
EXIT_CONFIG_ERROR=1
EXIT_SSH_FAILURE=2
EXIT_RSYNC_FAILURE=3

SSH_CONNECT_TIMEOUT=5

CONF_FILE="$PROJECT_ROOT/deploy/deploy.conf"

# ================================================================================
# Colors and Logging (matches pi_setup.sh style)
# ================================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_section() {
    echo ""
    echo "========================================"
    echo "  $1"
    echo "========================================"
}

# ================================================================================
# Configuration
# ================================================================================

load_config() {
    log_section "Loading Configuration"

    if [[ ! -f "$CONF_FILE" ]]; then
        log_error "Configuration file not found: $CONF_FILE"
        log_error "Copy the example and edit with your Pi details:"
        log_error "  cp deploy/deploy.conf.example deploy/deploy.conf"
        exit $EXIT_CONFIG_ERROR
    fi

    # Source the config file
    # shellcheck source=/dev/null
    source "$CONF_FILE"

    # Validate required variables
    local missing=0

    if [[ -z "${PI_HOST:-}" ]]; then
        log_error "PI_HOST not set in $CONF_FILE"
        missing=1
    fi
    if [[ -z "${PI_USER:-}" ]]; then
        log_error "PI_USER not set in $CONF_FILE"
        missing=1
    fi
    if [[ -z "${PI_PATH:-}" ]]; then
        log_error "PI_PATH not set in $CONF_FILE"
        missing=1
    fi
    if [[ -z "${PI_PORT:-}" ]]; then
        log_error "PI_PORT not set in $CONF_FILE"
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        log_error "Fix the configuration in $CONF_FILE and try again."
        exit $EXIT_CONFIG_ERROR
    fi

    log_info "Target: ${PI_USER}@${PI_HOST}:${PI_PATH} (port ${PI_PORT})"
}

# ================================================================================
# SSH Connectivity Check
# ================================================================================

check_ssh() {
    log_section "Checking SSH Connectivity"

    log_info "Testing connection to ${PI_HOST}:${PI_PORT}..."

    if ssh -o ConnectTimeout=$SSH_CONNECT_TIMEOUT \
           -o BatchMode=yes \
           -o StrictHostKeyChecking=accept-new \
           -p "$PI_PORT" \
           "${PI_USER}@${PI_HOST}" \
           "echo ok" > /dev/null 2>&1; then
        log_info "SSH connection successful"
    else
        log_error "Cannot connect to ${PI_USER}@${PI_HOST}:${PI_PORT}"
        log_error "Check that:"
        log_error "  1. The Pi is powered on and connected to the network"
        log_error "  2. SSH is enabled on the Pi"
        log_error "  3. PI_HOST, PI_USER, and PI_PORT are correct in $CONF_FILE"
        log_error "  4. SSH keys are set up (or use ssh-copy-id ${PI_USER}@${PI_HOST})"
        exit $EXIT_SSH_FAILURE
    fi
}

# ================================================================================
# Ensure Remote Directory Exists
# ================================================================================

ensure_remote_dir() {
    log_info "Ensuring remote directory exists: ${PI_PATH}"

    ssh -o ConnectTimeout=$SSH_CONNECT_TIMEOUT \
        -p "$PI_PORT" \
        "${PI_USER}@${PI_HOST}" \
        "mkdir -p '${PI_PATH}'" 2>/dev/null

    if [[ $? -ne 0 ]]; then
        log_warn "Could not create remote directory (may already exist)"
    fi
}

# ================================================================================
# File Sync (rsync)
# ================================================================================

sync_files() {
    log_section "Syncing Files"

    # Build rsync command
    # Use --delete to remove files on Pi that were deleted locally
    # Excludes match the acceptance criteria
    local rsyncArgs=(
        -avz
        --delete
        --stats
        -e "ssh -o ConnectTimeout=$SSH_CONNECT_TIMEOUT -p $PI_PORT"
        --exclude='.venv/'
        --exclude='__pycache__/'
        --exclude='.git/'
        --exclude='*.pyc'
        --exclude='data/'
        --exclude='logs/'
        --exclude='.env'
        --exclude='node_modules/'
        --exclude='.mypy_cache/'
        --exclude='.pytest_cache/'
        --exclude='.ruff_cache/'
        --exclude='htmlcov/'
        --exclude='.coverage'
    )

    log_info "Starting rsync from project root to ${PI_USER}@${PI_HOST}:${PI_PATH}"
    log_info "Excluded: .venv/ __pycache__/ .git/ *.pyc data/ logs/ .env node_modules/"

    # Capture rsync output for summary
    local rsyncOutput
    local rsyncTmpFile
    rsyncTmpFile=$(mktemp)

    # Convert Windows path to rsync-compatible path (MINGW64 compatibility)
    local sourcePath="${PROJECT_ROOT}/"

    if rsync "${rsyncArgs[@]}" "$sourcePath" "${PI_USER}@${PI_HOST}:${PI_PATH}/" 2>&1 | tee "$rsyncTmpFile"; then
        log_info "rsync completed successfully"
    else
        local rsyncExit=$?
        log_error "rsync failed with exit code: $rsyncExit"
        cat "$rsyncTmpFile"
        rm -f "$rsyncTmpFile"
        exit $EXIT_RSYNC_FAILURE
    fi

    # Parse rsync stats for summary
    parse_rsync_stats "$rsyncTmpFile"
    rm -f "$rsyncTmpFile"
}

# ================================================================================
# Parse rsync Stats
# ================================================================================

parse_rsync_stats() {
    local statsFile="$1"

    log_section "Sync Summary"

    # Extract key stats from rsync --stats output
    local filesTransferred
    local totalSize
    local transferSize

    filesTransferred=$(grep -i "Number of regular files transferred" "$statsFile" 2>/dev/null | grep -oE '[0-9,]+$' | tr -d ',' || echo "unknown")
    totalSize=$(grep -i "Total file size" "$statsFile" 2>/dev/null | grep -oE '[0-9,]+' | head -1 | tr -d ',' || echo "unknown")
    transferSize=$(grep -i "Total transferred file size" "$statsFile" 2>/dev/null | grep -oE '[0-9,]+' | head -1 | tr -d ',' || echo "unknown")

    # Format sizes for readability
    local totalSizeFormatted="unknown"
    local transferSizeFormatted="unknown"

    if [[ "$totalSize" =~ ^[0-9]+$ ]]; then
        totalSizeFormatted=$(format_bytes "$totalSize")
    fi
    if [[ "$transferSize" =~ ^[0-9]+$ ]]; then
        transferSizeFormatted=$(format_bytes "$transferSize")
    fi

    log_info "Files transferred: ${filesTransferred}"
    log_info "Total file size:   ${totalSizeFormatted}"
    log_info "Transfer size:     ${transferSizeFormatted}"
    log_info "Target:            ${PI_USER}@${PI_HOST}:${PI_PATH}"
}

# ================================================================================
# Utility: Format Bytes
# ================================================================================

format_bytes() {
    local bytes=$1

    if [[ $bytes -ge 1073741824 ]]; then
        echo "$(( bytes / 1073741824 )) GB"
    elif [[ $bytes -ge 1048576 ]]; then
        echo "$(( bytes / 1048576 )) MB"
    elif [[ $bytes -ge 1024 ]]; then
        echo "$(( bytes / 1024 )) KB"
    else
        echo "${bytes} bytes"
    fi
}

# ================================================================================
# Final Summary
# ================================================================================

print_result() {
    log_section "Deploy Complete"

    echo ""
    echo -e "  ${GREEN}Deployment to ${PI_HOST} succeeded!${NC}"
    echo ""
    echo "  To check the Pi:"
    echo "    ssh -p ${PI_PORT} ${PI_USER}@${PI_HOST}"
    echo "    ls ${PI_PATH}/"
    echo ""
}

# ================================================================================
# Main Entry Point
# ================================================================================

main() {
    echo ""
    echo "========================================"
    echo "  Eclipse OBD-II Deploy"
    echo "========================================"
    echo ""

    # Load and validate configuration
    load_config

    # Verify SSH connectivity
    check_ssh

    # Ensure remote directory exists
    ensure_remote_dir

    # Sync files via rsync
    sync_files

    # Print success message
    print_result

    exit $EXIT_SUCCESS
}

# Run main function
main "$@"
