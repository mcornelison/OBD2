#!/bin/bash
################################################################################
# File Name: pi_setup.sh
# Purpose/Description: Initial setup script for Raspberry Pi deployment
# Author: Claude
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Claude       | Initial implementation (US-RPI-004)
# ================================================================================
################################################################################

#
# Raspberry Pi Setup Script for Eclipse OBD-II System
#
# This script configures a fresh Raspberry Pi for the Eclipse OBD-II system.
# It is idempotent - safe to run multiple times without side effects.
#
# Usage:
#     sudo ./scripts/pi_setup.sh
#
# Prerequisites:
#     - Raspberry Pi running Raspberry Pi OS (64-bit, Bookworm recommended)
#     - Internet connection for package installation
#     - Run as root (sudo)
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script directory (for finding project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

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

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

check_raspberry_pi() {
    if [[ ! -f /proc/device-tree/model ]]; then
        log_error "This script is designed for Raspberry Pi only"
        log_error "Device tree model file not found: /proc/device-tree/model"
        exit 1
    fi

    MODEL=$(cat /proc/device-tree/model | tr -d '\0')
    if [[ ! "$MODEL" == *"Raspberry Pi"* ]]; then
        log_error "This script is designed for Raspberry Pi only"
        log_error "Detected: $MODEL"
        exit 1
    fi

    log_info "Detected: $MODEL"
}

# ================================================================================
# System Configuration
# ================================================================================

enable_i2c() {
    log_section "Enabling I2C Interface"

    # Check if I2C is already enabled
    if [[ -e /dev/i2c-1 ]]; then
        log_info "I2C is already enabled (/dev/i2c-1 exists)"
    else
        log_info "Enabling I2C via raspi-config..."
        raspi-config nonint do_i2c 0
        log_info "I2C enabled. A reboot may be required for changes to take effect."
    fi

    # Verify I2C is in loaded modules (or will be on next boot)
    if lsmod | grep -q "i2c_dev"; then
        log_info "I2C kernel module loaded"
    else
        log_warn "I2C kernel module not loaded - will be available after reboot"
        # Try to load it now
        modprobe i2c-dev 2>/dev/null || true
    fi
}

# ================================================================================
# System Dependencies
# ================================================================================

install_system_dependencies() {
    log_section "Installing System Dependencies"

    log_info "Updating package lists..."
    apt-get update -qq

    # List of packages to install
    PACKAGES=(
        "python3-pip"
        "python3-venv"
        "python3-dev"
        "python3-smbus"
        "i2c-tools"
        "git"
        "build-essential"
        "libffi-dev"
        "libssl-dev"
    )

    for pkg in "${PACKAGES[@]}"; do
        if dpkg -l | grep -q "^ii  $pkg "; then
            log_info "Package already installed: $pkg"
        else
            log_info "Installing: $pkg"
            apt-get install -y -qq "$pkg"
        fi
    done

    log_info "System dependencies installation complete"
}

# ================================================================================
# Python Dependencies
# ================================================================================

install_python_dependencies() {
    log_section "Installing Python Dependencies"

    # Determine the user who invoked sudo
    ACTUAL_USER="${SUDO_USER:-$USER}"
    ACTUAL_HOME=$(getent passwd "$ACTUAL_USER" | cut -d: -f6)

    log_info "Installing for user: $ACTUAL_USER"

    # Check if virtual environment exists
    VENV_PATH="$PROJECT_ROOT/.venv"
    if [[ -d "$VENV_PATH" ]]; then
        log_info "Virtual environment exists: $VENV_PATH"
    else
        log_info "Creating virtual environment: $VENV_PATH"
        sudo -u "$ACTUAL_USER" python3 -m venv "$VENV_PATH"
    fi

    # Install dependencies using the virtual environment
    log_info "Installing from requirements.txt..."
    sudo -u "$ACTUAL_USER" "$VENV_PATH/bin/pip" install --quiet -r "$PROJECT_ROOT/requirements.txt"

    log_info "Installing from requirements-pi.txt..."
    sudo -u "$ACTUAL_USER" "$VENV_PATH/bin/pip" install --quiet -r "$PROJECT_ROOT/requirements-pi.txt"

    log_info "Python dependencies installation complete"
}

# ================================================================================
# Directory Setup
# ================================================================================

create_directories() {
    log_section "Creating Required Directories"

    # Log directory (system-level)
    LOG_DIR="/var/log/carpi"
    if [[ -d "$LOG_DIR" ]]; then
        log_info "Log directory exists: $LOG_DIR"
    else
        log_info "Creating log directory: $LOG_DIR"
        mkdir -p "$LOG_DIR"
    fi

    # Set permissions - allow the actual user to write logs
    ACTUAL_USER="${SUDO_USER:-$USER}"
    chown -R "$ACTUAL_USER:$ACTUAL_USER" "$LOG_DIR"
    chmod 755 "$LOG_DIR"
    log_info "Set log directory ownership to: $ACTUAL_USER"

    # Data directory (project-level)
    DATA_DIR="$PROJECT_ROOT/data"
    if [[ -d "$DATA_DIR" ]]; then
        log_info "Data directory exists: $DATA_DIR"
    else
        log_info "Creating data directory: $DATA_DIR"
        mkdir -p "$DATA_DIR"
    fi
    chown -R "$ACTUAL_USER:$ACTUAL_USER" "$DATA_DIR"
    chmod 755 "$DATA_DIR"

    log_info "Directory setup complete"
}

# ================================================================================
# I2C Verification
# ================================================================================

verify_i2c() {
    log_section "Verifying I2C Configuration"

    if [[ ! -e /dev/i2c-1 ]]; then
        log_warn "I2C device /dev/i2c-1 not found"
        log_warn "A reboot may be required to enable I2C"
        return 0
    fi

    log_info "I2C device found: /dev/i2c-1"

    # Try to scan for devices
    if command -v i2cdetect &> /dev/null; then
        log_info "Scanning I2C bus for devices..."
        i2cdetect -y 1 2>/dev/null || log_warn "Could not scan I2C bus (may need permissions)"

        # Check for X1209 UPS HAT (0x36 or 0x57)
        if i2cdetect -y 1 2>/dev/null | grep -qE "36|57"; then
            log_info "X1209 UPS HAT detected on I2C bus"
        else
            log_warn "X1209 UPS HAT not detected (address 0x36 or 0x57)"
            log_warn "This is normal if the UPS HAT is not connected"
        fi
    else
        log_warn "i2cdetect not available - skipping I2C scan"
    fi
}

# ================================================================================
# Post-Setup Verification
# ================================================================================

verify_setup() {
    log_section "Verifying Setup"

    ACTUAL_USER="${SUDO_USER:-$USER}"
    VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

    # Check Python version
    if [[ -f "$VENV_PYTHON" ]]; then
        PYTHON_VERSION=$("$VENV_PYTHON" --version 2>&1)
        log_info "Python: $PYTHON_VERSION"
    else
        log_error "Virtual environment Python not found: $VENV_PYTHON"
    fi

    # Run platform check script
    if [[ -f "$PROJECT_ROOT/scripts/check_platform.py" ]]; then
        log_info "Running platform check..."
        sudo -u "$ACTUAL_USER" "$VENV_PYTHON" "$PROJECT_ROOT/scripts/check_platform.py" || true
    fi
}

# ================================================================================
# Summary
# ================================================================================

print_summary() {
    log_section "Setup Complete"

    echo ""
    echo "  Raspberry Pi setup completed successfully!"
    echo ""
    echo "  Next steps:"
    echo "    1. Reboot if I2C was just enabled:"
    echo "       sudo reboot"
    echo ""
    echo "    2. Activate the virtual environment:"
    echo "       source $PROJECT_ROOT/.venv/bin/activate"
    echo ""
    echo "    3. Run the platform verification:"
    echo "       python scripts/check_platform.py"
    echo ""
    echo "    4. Start the application:"
    echo "       python src/main.py"
    echo ""
    echo "  For more information, see:"
    echo "    - docs/hardware-reference.md"
    echo "    - README.md"
    echo ""
}

# ================================================================================
# Main Entry Point
# ================================================================================

main() {
    echo ""
    echo "========================================"
    echo "  Eclipse OBD-II Raspberry Pi Setup"
    echo "========================================"
    echo ""

    # Pre-flight checks
    check_root
    check_raspberry_pi

    # System configuration
    enable_i2c

    # Install dependencies
    install_system_dependencies
    install_python_dependencies

    # Directory setup
    create_directories

    # Verification
    verify_i2c
    verify_setup

    # Summary
    print_summary

    return 0
}

# Run main function
main "$@"
