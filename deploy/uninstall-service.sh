#!/bin/bash
# ==============================================================================
# File: uninstall-service.sh
# Purpose: Uninstall Eclipse OBD-II systemd service from Raspberry Pi
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Usage:
#   sudo ./uninstall-service.sh [OPTIONS]
#
# Options:
#   --keep-logs    Keep log files (default: remove)
#   --help         Show this help message
# ==============================================================================

set -e  # Exit on error

# Default values
SERVICE_NAME="eclipse-obd"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
KEEP_LOGS=false

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print functions
print_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Show help message
show_help() {
    echo "Uninstall Eclipse OBD-II systemd service"
    echo ""
    echo "Usage: sudo $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --keep-logs    Keep log files (default: remove)"
    echo "  --help         Show this help message"
    echo ""
    echo "Note: This script only removes the systemd service."
    echo "      It does not remove the application files."
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-logs)
            KEEP_LOGS=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

print_info "Uninstalling Eclipse OBD-II service..."

# Check if service exists
if [ ! -f "$SERVICE_FILE" ]; then
    print_warn "Service file not found at $SERVICE_FILE"
    print_info "Service may not be installed"
    exit 0
fi

# Stop the service if running
if systemctl is-active --quiet "$SERVICE_NAME"; then
    print_info "Stopping service..."
    systemctl stop "$SERVICE_NAME"
fi

# Disable the service
if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    print_info "Disabling service..."
    systemctl disable "$SERVICE_NAME"
fi

# Remove the service file
print_info "Removing service file..."
rm -f "$SERVICE_FILE"

# Reload systemd
print_info "Reloading systemd daemon..."
systemctl daemon-reload

# Reset failed state if any
systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true

# Optionally clean up log files
if [ "$KEEP_LOGS" = false ]; then
    # Try to extract logs path from service file backup or use default
    LOGS_PATTERN="/home/*/obd2/logs"
    for LOGS_DIR in $LOGS_PATTERN; do
        if [ -d "$LOGS_DIR" ]; then
            print_info "Removing log files from $LOGS_DIR..."
            rm -f "$LOGS_DIR/service.log"
            rm -f "$LOGS_DIR/service-error.log"
        fi
    done
else
    print_info "Keeping log files (--keep-logs specified)"
fi

# Verify uninstallation
if [ ! -f "$SERVICE_FILE" ]; then
    print_info "Service uninstalled successfully!"
else
    print_error "Failed to remove service file"
    exit 1
fi

echo ""
print_info "=============================================="
print_info "Uninstallation complete!"
print_info "=============================================="
echo ""
print_info "The systemd service has been removed."
print_info "Application files remain in place."
echo ""
print_info "To reinstall the service:"
echo "  sudo ./install-service.sh"
