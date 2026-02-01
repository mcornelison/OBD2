#!/bin/bash
################################################################################
# File Name: setup_backup.sh
# Purpose/Description: Setup script for rclone and Google Drive backup
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation (US-TD-012)
# ================================================================================
################################################################################

#
# Backup Setup Script for Eclipse OBD-II System
#
# This script configures rclone for Google Drive backup functionality.
# It is idempotent - safe to run multiple times without side effects.
#
# Usage:
#     sudo ./scripts/setup_backup.sh
#
# What this script does:
#     1. Checks if rclone is installed, installs via apt if not
#     2. Guides user through rclone configuration for Google Drive
#     3. Verifies the remote is configured with a test upload
#     4. Creates the backup destination folder in Google Drive
#
# Prerequisites:
#     - Raspberry Pi running Raspberry Pi OS (or Debian-based Linux)
#     - Internet connection for installation and Google OAuth
#     - Run as root (sudo)
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory (for finding project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Configuration
DEFAULT_REMOTE_NAME="gdrive"
DEFAULT_FOLDER_PATH="OBD2_Backups"
TEST_FILE_NAME=".obd2_backup_test"

# ================================================================================
# Helper Functions
# ================================================================================

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

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

get_actual_user() {
    # Determine the user who invoked sudo
    echo "${SUDO_USER:-$USER}"
}

# ================================================================================
# rclone Installation
# ================================================================================

is_rclone_installed() {
    command -v rclone &> /dev/null
}

get_rclone_version() {
    rclone version | head -n 1
}

install_rclone() {
    log_section "Installing rclone"

    if is_rclone_installed; then
        log_info "rclone is already installed: $(get_rclone_version)"
        return 0
    fi

    log_info "rclone not found. Installing via apt..."

    # Update package list
    log_step "Updating package lists..."
    apt-get update -qq

    # Install rclone
    log_step "Installing rclone..."
    apt-get install -y -qq rclone

    # Verify installation
    if is_rclone_installed; then
        log_info "rclone installed successfully: $(get_rclone_version)"
    else
        log_error "Failed to install rclone"
        log_error "Try manual installation: https://rclone.org/install/"
        exit 1
    fi
}

# ================================================================================
# rclone Configuration
# ================================================================================

is_remote_configured() {
    local remoteName="$1"
    rclone listremotes | grep -q "^${remoteName}:"
}

get_configured_remotes() {
    rclone listremotes | sed 's/:$//'
}

configure_gdrive_remote() {
    log_section "Configuring Google Drive Remote"

    local remoteName="${1:-$DEFAULT_REMOTE_NAME}"
    local ACTUAL_USER=$(get_actual_user)

    if is_remote_configured "$remoteName"; then
        log_info "Remote '$remoteName' is already configured"

        # Show current config (without secrets)
        log_info "Current configuration:"
        rclone config show "$remoteName" 2>/dev/null | head -5 || true

        echo ""
        read -p "Do you want to reconfigure this remote? (y/N): " reconfigure
        if [[ ! "$reconfigure" =~ ^[Yy] ]]; then
            log_info "Keeping existing configuration"
            return 0
        fi

        # Delete existing remote to reconfigure
        rclone config delete "$remoteName"
        log_info "Removed existing configuration"
    fi

    log_step "Starting Google Drive configuration..."
    echo ""
    echo "  This will open a browser to authenticate with Google."
    echo "  If you're running this on a headless Pi, you'll need to"
    echo "  use the remote authorization method."
    echo ""
    echo "  IMPORTANT: Select 'Google Drive' as the storage type when prompted."
    echo ""

    read -p "Press Enter to continue, or Ctrl+C to cancel..."
    echo ""

    # Run rclone config interactively
    # The user will be prompted to create a new remote
    log_info "Starting rclone configuration wizard..."
    log_info "When prompted for 'name>', enter: $remoteName"
    log_info "When prompted for 'Storage>', choose: drive (Google Drive)"
    echo ""

    # Run as the actual user for proper OAuth token storage
    sudo -u "$ACTUAL_USER" rclone config

    # Verify configuration was created
    if is_remote_configured "$remoteName"; then
        log_info "Remote '$remoteName' configured successfully"
    else
        log_warn "Remote '$remoteName' was not created"
        log_warn "Please run the configuration wizard again and create a remote named '$remoteName'"

        # Check if any remotes were created
        local remotes=$(get_configured_remotes)
        if [[ -n "$remotes" ]]; then
            log_info "Available remotes: $remotes"
            log_info "You can use a different remote name in your backup config"
        fi
    fi
}

# ================================================================================
# Configuration Verification
# ================================================================================

verify_remote() {
    log_section "Verifying Remote Configuration"

    local remoteName="${1:-$DEFAULT_REMOTE_NAME}"

    if ! is_remote_configured "$remoteName"; then
        log_error "Remote '$remoteName' is not configured"
        return 1
    fi

    log_step "Checking connection to Google Drive..."

    # Try to list the root directory
    if rclone lsd "${remoteName}:" --max-depth 1 &> /dev/null; then
        log_info "Successfully connected to Google Drive via '$remoteName'"
    else
        log_error "Failed to connect to Google Drive"
        log_error "Please check your configuration and internet connection"
        return 1
    fi

    return 0
}

test_upload() {
    log_section "Testing Upload Functionality"

    local remoteName="${1:-$DEFAULT_REMOTE_NAME}"
    local folderPath="${2:-$DEFAULT_FOLDER_PATH}"
    local ACTUAL_USER=$(get_actual_user)

    # Create a small test file
    local testFile="/tmp/${TEST_FILE_NAME}"
    local timestamp=$(date +%Y-%m-%d_%H%M%S)
    echo "Eclipse OBD-II backup test file - Created: $timestamp" > "$testFile"

    log_step "Creating test file: $testFile"

    # Create the backup folder if it doesn't exist
    log_step "Creating backup folder: ${remoteName}:${folderPath}/"
    rclone mkdir "${remoteName}:${folderPath}" 2>/dev/null || true

    # Upload the test file
    local remoteTestFile="${remoteName}:${folderPath}/${TEST_FILE_NAME}"
    log_step "Uploading test file to: $remoteTestFile"

    if rclone copyto "$testFile" "$remoteTestFile" --progress; then
        log_info "Test upload successful!"

        # Verify the file exists
        if rclone ls "$remoteTestFile" &> /dev/null; then
            log_info "Verified: Test file exists on Google Drive"
        fi

        # Clean up test file from remote
        log_step "Cleaning up test file from Google Drive..."
        rclone deletefile "$remoteTestFile" 2>/dev/null || true
        log_info "Test file removed from Google Drive"
    else
        log_error "Test upload failed!"
        log_error "Please check your Google Drive permissions"
        rm -f "$testFile"
        return 1
    fi

    # Clean up local test file
    rm -f "$testFile"
    log_info "Upload test completed successfully"
    return 0
}

# ================================================================================
# Summary
# ================================================================================

print_summary() {
    log_section "Setup Complete"

    local remoteName="${1:-$DEFAULT_REMOTE_NAME}"
    local folderPath="${2:-$DEFAULT_FOLDER_PATH}"

    echo ""
    echo "  Google Drive backup setup completed successfully!"
    echo ""
    echo "  Configuration:"
    echo "    - Remote name: $remoteName"
    echo "    - Backup folder: $folderPath"
    echo "    - rclone version: $(get_rclone_version)"
    echo ""
    echo "  To enable automatic backups, update your config.json:"
    echo ""
    echo "    {"
    echo "      \"backup\": {"
    echo "        \"enabled\": true,"
    echo "        \"provider\": \"google_drive\","
    echo "        \"folderPath\": \"$folderPath\","
    echo "        \"scheduleTime\": \"03:00\","
    echo "        \"maxBackups\": 30,"
    echo "        \"compressBackups\": true,"
    echo "        \"catchupDays\": 2"
    echo "      }"
    echo "    }"
    echo ""
    echo "  Manual backup commands:"
    echo "    # List backup folder contents"
    echo "    rclone ls ${remoteName}:${folderPath}/"
    echo ""
    echo "    # Upload a file manually"
    echo "    rclone copyto /path/to/file.gz ${remoteName}:${folderPath}/file.gz"
    echo ""
    echo "  For more information, see:"
    echo "    - docs/backup.md"
    echo "    - https://rclone.org/drive/"
    echo ""
}

print_headless_instructions() {
    echo ""
    echo "========================================"
    echo "  Headless Configuration Instructions"
    echo "========================================"
    echo ""
    echo "  If you're running this on a headless Raspberry Pi (no monitor),"
    echo "  you'll need to configure rclone using remote authorization:"
    echo ""
    echo "  1. On your local machine (with a browser), run:"
    echo "     rclone authorize \"drive\""
    echo ""
    echo "  2. This will open a browser for Google OAuth authorization"
    echo ""
    echo "  3. Copy the resulting authorization token"
    echo ""
    echo "  4. When running 'rclone config' on the Pi, select:"
    echo "     'n) No, I don't have a browser'"
    echo ""
    echo "  5. Paste the authorization token when prompted"
    echo ""
    echo "  See: https://rclone.org/remote_setup/"
    echo ""
}

# ================================================================================
# Main Entry Point
# ================================================================================

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Setup rclone for Google Drive backup functionality."
    echo ""
    echo "Options:"
    echo "  -n, --remote-name NAME    Set rclone remote name (default: $DEFAULT_REMOTE_NAME)"
    echo "  -f, --folder-path PATH    Set backup folder path (default: $DEFAULT_FOLDER_PATH)"
    echo "  -s, --skip-test           Skip upload test after configuration"
    echo "  -v, --verify-only         Only verify existing configuration"
    echo "  -h, --help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0                           # Full setup with defaults"
    echo "  sudo $0 -n myremote               # Use custom remote name"
    echo "  sudo $0 --verify-only             # Just verify existing setup"
    echo ""
}

main() {
    local remoteName="$DEFAULT_REMOTE_NAME"
    local folderPath="$DEFAULT_FOLDER_PATH"
    local skipTest=false
    local verifyOnly=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -n|--remote-name)
                remoteName="$2"
                shift 2
                ;;
            -f|--folder-path)
                folderPath="$2"
                shift 2
                ;;
            -s|--skip-test)
                skipTest=true
                shift
                ;;
            -v|--verify-only)
                verifyOnly=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    echo ""
    echo "========================================"
    echo "  Eclipse OBD-II Backup Setup"
    echo "========================================"
    echo ""

    # Pre-flight checks
    check_root

    # Verify-only mode
    if [[ "$verifyOnly" == true ]]; then
        if verify_remote "$remoteName"; then
            if [[ "$skipTest" != true ]]; then
                test_upload "$remoteName" "$folderPath"
            fi
            log_info "Verification complete"
        else
            log_error "Verification failed"
            exit 1
        fi
        exit 0
    fi

    # Full setup
    install_rclone

    # Show headless instructions before config
    print_headless_instructions

    # Configure remote
    configure_gdrive_remote "$remoteName"

    # Verify configuration
    if ! verify_remote "$remoteName"; then
        log_error "Remote verification failed"
        log_error "Please ensure the remote '$remoteName' is properly configured"
        exit 1
    fi

    # Test upload
    if [[ "$skipTest" != true ]]; then
        if ! test_upload "$remoteName" "$folderPath"; then
            log_error "Upload test failed"
            exit 1
        fi
    fi

    # Print summary
    print_summary "$remoteName" "$folderPath"

    return 0
}

# Run main function
main "$@"
