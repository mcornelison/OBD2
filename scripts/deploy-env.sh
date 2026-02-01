#!/bin/bash
################################################################################
# File Name: deploy-env.sh
# Purpose/Description: One-time .env secrets file push to Raspberry Pi
# Author: Rex (Ralph Agent)
# Creation Date: 2026-01-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-31    | Rex          | Initial implementation (US-DEP-007)
# ================================================================================
################################################################################

#
# One-Time .env File Push for Eclipse OBD-II System
#
# Copies the local .env secrets file to the Raspberry Pi via scp.
# This is separate from the regular deploy flow (which excludes .env from rsync).
#
# Usage:
#     ./scripts/deploy-env.sh
#
# Exit Codes:
#     0 - Success
#     1 - Configuration error (missing deploy.conf or .env)
#     2 - SSH connectivity failure
#     3 - User cancelled overwrite
#     4 - scp transfer failure
#     5 - Permission setting failure
#
# Prerequisites:
#     - deploy/deploy.conf configured with Pi connection details
#     - .env file exists in project root
#     - SSH key-based auth set up (or willingness to enter password)
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
EXIT_USER_CANCELLED=3
EXIT_SCP_FAILURE=4
EXIT_CHMOD_FAILURE=5

SSH_CONNECT_TIMEOUT=5

CONF_FILE="$PROJECT_ROOT/deploy/deploy.conf"
ENV_FILE="$PROJECT_ROOT/.env"

# ================================================================================
# Colors and Logging (matches pi_setup.sh / deploy.sh style)
# ================================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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
# Check Local .env File
# ================================================================================

check_env_file() {
    log_section "Checking Local .env File"

    if [[ ! -f "$ENV_FILE" ]]; then
        log_error ".env file not found: $ENV_FILE"
        log_error "Create .env from the example:"
        log_error "  cp .env.example .env"
        exit $EXIT_CONFIG_ERROR
    fi

    log_info "Found .env file: $ENV_FILE"
}

# ================================================================================
# Check SSH Connectivity
# ================================================================================

check_ssh() {
    log_info "Testing SSH connection to ${PI_HOST}:${PI_PORT}..."

    if ssh -o ConnectTimeout=$SSH_CONNECT_TIMEOUT \
           -o BatchMode=yes \
           -o StrictHostKeyChecking=accept-new \
           -p "$PI_PORT" \
           "${PI_USER}@${PI_HOST}" \
           "echo ok" > /dev/null 2>&1; then
        log_info "SSH connection successful"
    else
        log_error "Cannot connect to ${PI_USER}@${PI_HOST}:${PI_PORT}"
        log_error "Check that the Pi is reachable and SSH keys are configured."
        exit $EXIT_SSH_FAILURE
    fi
}

# ================================================================================
# Check for Existing .env on Pi and Prompt for Confirmation
# ================================================================================

check_existing_env() {
    log_section "Checking for Existing .env on Pi"

    local remoteEnvPath="${PI_PATH}/.env"

    # Check if .env already exists on the Pi
    local envExists
    envExists=$(ssh -o ConnectTimeout=$SSH_CONNECT_TIMEOUT \
        -p "$PI_PORT" \
        "${PI_USER}@${PI_HOST}" \
        "[ -f '${remoteEnvPath}' ] && echo 'yes' || echo 'no'" 2>/dev/null)

    if [[ "$envExists" == "yes" ]]; then
        log_warn ".env already exists on Pi at ${remoteEnvPath}"
        echo ""
        echo -n "Overwrite existing .env on ${PI_HOST}? [y/N] "
        read -r response
        echo ""

        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            log_info "Cancelled. Existing .env on Pi was not modified."
            exit $EXIT_USER_CANCELLED
        fi

        log_info "User confirmed overwrite"
    else
        log_info "No existing .env on Pi (first-time push)"
    fi
}

# ================================================================================
# Copy .env to Pi
# ================================================================================

copy_env() {
    log_section "Copying .env to Pi"

    local remoteEnvPath="${PI_PATH}/.env"

    log_info "Copying .env to ${PI_USER}@${PI_HOST}:${remoteEnvPath}..."

    if scp -P "$PI_PORT" \
           -o ConnectTimeout=$SSH_CONNECT_TIMEOUT \
           "$ENV_FILE" \
           "${PI_USER}@${PI_HOST}:${remoteEnvPath}"; then
        log_info "File transferred successfully"
    else
        log_error "Failed to copy .env to Pi"
        exit $EXIT_SCP_FAILURE
    fi

    # Set restrictive permissions (owner read/write only)
    log_info "Setting permissions to 600 (owner read/write only)..."

    if ssh -o ConnectTimeout=$SSH_CONNECT_TIMEOUT \
           -p "$PI_PORT" \
           "${PI_USER}@${PI_HOST}" \
           "chmod 600 '${remoteEnvPath}'"; then
        log_info "Permissions set to 600"
    else
        log_error "Failed to set file permissions on Pi"
        exit $EXIT_CHMOD_FAILURE
    fi
}

# ================================================================================
# Main Entry Point
# ================================================================================

main() {
    echo ""
    echo "========================================"
    echo "  Eclipse OBD-II - Push .env to Pi"
    echo "========================================"
    echo ""

    # Load and validate configuration
    load_config

    # Check local .env file exists
    check_env_file

    # Verify SSH connectivity
    check_ssh

    # Check for existing .env on Pi, prompt before overwrite
    check_existing_env

    # Copy .env file and set permissions
    copy_env

    # Success
    echo ""
    log_info ".env copied to ${PI_HOST}:${PI_PATH}/.env (permissions: 600)"
    echo ""

    exit $EXIT_SUCCESS
}

# Run main function
main "$@"
