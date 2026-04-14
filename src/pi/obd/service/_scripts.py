################################################################################
# File Name: _scripts.py
# Purpose/Description: Install/uninstall shell script generators for the systemd service
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation (US-006)
# 2026-04-14    | Sweep 5      | Extracted from service.py (task 4 split)
# ================================================================================
################################################################################

"""
Shell script generators for installing/uninstalling the Eclipse OBD-II systemd service.

These were factored out of the huge service.py module because they contained
hundreds of lines of bash heredoc bodies. They live in the service/ subpackage
so the caller interface `obd.service.generateInstallScript(...)` is preserved.

ServiceManager/ServiceConfig are resolved lazily at call time via the parent
package (obd.service), avoiding the spec_from_file_location loader cycle.
"""

import os
import stat
from datetime import datetime
from typing import Any


def _getServiceManager() -> Any:
    """
    Lazily resolve the ServiceManager class from the parent package.

    service/__init__.py loads service.py via spec_from_file_location as
    `_obd_service_legacy`, then binds ServiceManager/ServiceConfig on the
    package namespace. We read them back here rather than importing at
    module top to avoid a load-order cycle.
    """
    from . import ServiceManager  # noqa: PLC0415 — intentional lazy resolve
    return ServiceManager


def generateInstallScript(
    config: dict | None = None,
    serviceConfig: Any = None,
    outputPath: str = "install_service.sh",
) -> str:
    """
    Generate a shell script for service installation.

    The script handles:
    - Service file installation
    - Daemon reload
    - Service enable
    - Optional start

    Args:
        config: Application configuration dictionary
        serviceConfig: Direct ServiceConfig (overrides config dict)
        outputPath: Path to write the script

    Returns:
        Path to the generated script
    """
    ServiceManager = _getServiceManager()
    manager = ServiceManager(config=config, serviceConfig=serviceConfig)
    serviceContent = manager.generateServiceFile()
    serviceName = manager._serviceConfig.serviceName
    servicePath = manager.getServiceFilePath()

    script = f'''#!/bin/bash
################################################################################
# Eclipse OBD-II Service Installation Script
# Generated: {datetime.now().isoformat()}
#
# This script installs and enables the Eclipse OBD-II systemd service.
# Run with sudo: sudo ./install_service.sh
################################################################################

set -e

# Configuration
SERVICE_NAME="{serviceName}"
SERVICE_FILE="{servicePath}"
INSTALL_DIR="{manager._serviceConfig.workingDir}"

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

# Print with color
print_status() {{
    echo -e "${{GREEN}}[OK]${{NC}} $1"
}}

print_error() {{
    echo -e "${{RED}}[ERROR]${{NC}} $1"
}}

print_warning() {{
    echo -e "${{YELLOW}}[WARN]${{NC}} $1"
}}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

echo "=================================================="
echo "Eclipse OBD-II Service Installation"
echo "=================================================="
echo ""

# Check if systemd is available
if ! command -v systemctl &> /dev/null; then
    print_error "systemctl not found - systemd is required"
    exit 1
fi

# Create install directory if needed
if [[ ! -d "$INSTALL_DIR" ]]; then
    print_warning "Install directory does not exist: $INSTALL_DIR"
    read -p "Create directory? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        mkdir -p "$INSTALL_DIR"
        print_status "Created directory: $INSTALL_DIR"
    else
        print_error "Installation cancelled"
        exit 1
    fi
fi

# Stop existing service if running
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    print_status "Stopping existing service..."
    systemctl stop "$SERVICE_NAME"
fi

# Write service file
echo "Installing service file..."
cat > "$SERVICE_FILE" << 'SERVICEEOF'
{serviceContent}SERVICEEOF

print_status "Service file installed: $SERVICE_FILE"

# Reload systemd daemon
echo "Reloading systemd daemon..."
systemctl daemon-reload
print_status "Daemon reloaded"

# Enable service
echo "Enabling service for auto-start..."
systemctl enable "$SERVICE_NAME"
print_status "Service enabled"

# Ask to start now
echo ""
read -p "Start service now? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl start "$SERVICE_NAME"
    print_status "Service started"
    echo ""
    systemctl status "$SERVICE_NAME" --no-pager
else
    print_status "Service will start on next boot"
fi

echo ""
echo "=================================================="
echo "Installation Complete!"
echo "=================================================="
echo ""
echo "Useful commands:"
echo "  sudo systemctl status $SERVICE_NAME   - Check status"
echo "  sudo systemctl start $SERVICE_NAME    - Start service"
echo "  sudo systemctl stop $SERVICE_NAME     - Stop service"
echo "  sudo systemctl restart $SERVICE_NAME  - Restart service"
echo "  sudo journalctl -u $SERVICE_NAME -f   - View logs"
echo ""
'''

    with open(outputPath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(script)

    # Make executable
    currentMode = os.stat(outputPath).st_mode
    os.chmod(outputPath, currentMode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return outputPath


def generateUninstallScript(
    config: dict | None = None,
    serviceConfig: Any = None,
    outputPath: str = "uninstall_service.sh",
) -> str:
    """
    Generate a shell script for service uninstallation.

    Args:
        config: Application configuration dictionary
        serviceConfig: Direct ServiceConfig
        outputPath: Path to write the script

    Returns:
        Path to the generated script
    """
    ServiceManager = _getServiceManager()
    manager = ServiceManager(config=config, serviceConfig=serviceConfig)
    serviceName = manager._serviceConfig.serviceName
    servicePath = manager.getServiceFilePath()

    script = f'''#!/bin/bash
################################################################################
# Eclipse OBD-II Service Uninstallation Script
# Generated: {datetime.now().isoformat()}
################################################################################

set -e

SERVICE_NAME="{serviceName}"
SERVICE_FILE="{servicePath}"

# Colors
RED='\\033[0;31m'
GREEN='\\033[0;32m'
NC='\\033[0m'

print_status() {{
    echo -e "${{GREEN}}[OK]${{NC}} $1"
}}

print_error() {{
    echo -e "${{RED}}[ERROR]${{NC}} $1"
}}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

echo "=================================================="
echo "Eclipse OBD-II Service Uninstallation"
echo "=================================================="
echo ""

# Stop service if running
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Stopping service..."
    systemctl stop "$SERVICE_NAME"
    print_status "Service stopped"
fi

# Disable service
if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Disabling service..."
    systemctl disable "$SERVICE_NAME"
    print_status "Service disabled"
fi

# Remove service file
if [[ -f "$SERVICE_FILE" ]]; then
    echo "Removing service file..."
    rm "$SERVICE_FILE"
    print_status "Service file removed"
fi

# Reload daemon
systemctl daemon-reload
print_status "Daemon reloaded"

echo ""
echo "=================================================="
echo "Uninstallation Complete!"
echo "=================================================="
'''

    with open(outputPath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(script)

    # Make executable
    currentMode = os.stat(outputPath).st_mode
    os.chmod(outputPath, currentMode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return outputPath
