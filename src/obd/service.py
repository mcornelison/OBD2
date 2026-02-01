################################################################################
# File Name: service.py
# Purpose/Description: Systemd service management for auto-start on boot
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation (US-006)
# ================================================================================
################################################################################

"""
Systemd service management for Eclipse OBD-II auto-start on boot.

This module provides functionality to:
- Generate systemd service files from templates
- Install/uninstall the service
- Enable/disable auto-start
- Check service status
- Configure restart behavior with attempt limits

Usage:
    from obd.service import ServiceManager
    manager = ServiceManager(config)
    manager.generateServiceFile()
    manager.install()
"""

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime

# Service file template
SERVICE_TEMPLATE = """[Unit]
Description=Eclipse OBD-II Performance Monitor
Documentation=https://github.com/your-repo/eclipse-obd2
After=network.target bluetooth.target
Wants=bluetooth.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={working_dir}
ExecStart={python_path} {main_script}
ExecStop=/bin/kill -SIGTERM $MAINPID
Restart=on-failure
RestartSec={restart_delay}
StartLimitBurst={max_restarts}
StartLimitIntervalSec={restart_interval}

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

# Environment
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-{env_file}

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=eclipse-obd2

[Install]
WantedBy=multi-user.target
"""

# Default service name
DEFAULT_SERVICE_NAME = "eclipse-obd2"

# Default paths
DEFAULT_SERVICE_DIR = "/etc/systemd/system"
DEFAULT_INSTALL_DIR = "/opt/obd2"


class ServiceError(Exception):
    """Base exception for service-related errors."""

    def __init__(self, message: str, details: dict | None = None):
        """
        Initialize service error.

        Args:
            message: Error message
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ServiceInstallError(ServiceError):
    """Error during service installation."""
    pass


class ServiceNotInstalledError(ServiceError):
    """Error when service is not installed."""
    pass


class ServiceCommandError(ServiceError):
    """Error executing systemctl command."""
    pass


@dataclass
class ServiceConfig:
    """Configuration for the systemd service."""
    serviceName: str = DEFAULT_SERVICE_NAME
    user: str = "pi"
    group: str = "pi"
    workingDir: str = DEFAULT_INSTALL_DIR
    pythonPath: str = "/usr/bin/python3"
    mainScript: str = "src/main.py"
    envFile: str = ".env"
    restartDelaySeconds: int = 10
    maxRestartAttempts: int = 5
    restartIntervalSeconds: int = 300  # 5 minutes window for restart attempts

    def toDict(self) -> dict:
        """Convert to dictionary."""
        return {
            'serviceName': self.serviceName,
            'user': self.user,
            'group': self.group,
            'workingDir': self.workingDir,
            'pythonPath': self.pythonPath,
            'mainScript': self.mainScript,
            'envFile': self.envFile,
            'restartDelaySeconds': self.restartDelaySeconds,
            'maxRestartAttempts': self.maxRestartAttempts,
            'restartIntervalSeconds': self.restartIntervalSeconds
        }


@dataclass
class ServiceStatus:
    """Status information for the service."""
    installed: bool = False
    enabled: bool = False
    active: bool = False
    running: bool = False
    serviceName: str = ""
    serviceFilePath: str = ""
    lastChecked: datetime | None = None

    def toDict(self) -> dict:
        """Convert to dictionary."""
        return {
            'installed': self.installed,
            'enabled': self.enabled,
            'active': self.active,
            'running': self.running,
            'serviceName': self.serviceName,
            'serviceFilePath': self.serviceFilePath,
            'lastChecked': self.lastChecked.isoformat() if self.lastChecked else None
        }


class ServiceManager:
    """
    Manages systemd service for Eclipse OBD-II auto-start.

    Handles service file generation, installation, and lifecycle
    management for auto-start on Raspberry Pi boot.
    """

    def __init__(
        self,
        config: dict | None = None,
        serviceConfig: ServiceConfig | None = None
    ):
        """
        Initialize service manager.

        Args:
            config: Application configuration dictionary with autoStart section
            serviceConfig: Direct service configuration (overrides config dict)
        """
        self._serviceConfig = serviceConfig or self._parseConfig(config)
        self._serviceDir = DEFAULT_SERVICE_DIR
        self._generatedContent: str | None = None

    def _parseConfig(self, config: dict | None) -> ServiceConfig:
        """
        Parse service configuration from application config.

        Args:
            config: Application configuration dictionary

        Returns:
            ServiceConfig with parsed values
        """
        if not config:
            return ServiceConfig()

        autoStart = config.get('autoStart', {})

        return ServiceConfig(
            serviceName=autoStart.get('serviceName', DEFAULT_SERVICE_NAME),
            user=autoStart.get('user', 'pi'),
            group=autoStart.get('group', 'pi'),
            workingDir=autoStart.get('workingDir', DEFAULT_INSTALL_DIR),
            pythonPath=autoStart.get('pythonPath', '/usr/bin/python3'),
            mainScript=autoStart.get('mainScript', 'src/main.py'),
            envFile=autoStart.get('envFile', '.env'),
            restartDelaySeconds=autoStart.get('restartDelaySeconds', 10),
            maxRestartAttempts=autoStart.get('maxRestartAttempts', 5),
            restartIntervalSeconds=autoStart.get('restartIntervalSeconds', 300)
        )

    def getServiceFilePath(self) -> str:
        """
        Get the full path to the service file.

        Returns:
            Path to the systemd service file
        """
        return os.path.join(
            self._serviceDir,
            f"{self._serviceConfig.serviceName}.service"
        )

    def generateServiceFile(self) -> str:
        """
        Generate systemd service file content.

        Returns:
            Generated service file content as string
        """
        # Use forward slashes for Linux paths (systemd runs on Linux)
        mainScriptPath = '/'.join([
            self._serviceConfig.workingDir.rstrip('/'),
            self._serviceConfig.mainScript
        ])

        envFilePath = '/'.join([
            self._serviceConfig.workingDir.rstrip('/'),
            self._serviceConfig.envFile
        ])

        content = SERVICE_TEMPLATE.format(
            user=self._serviceConfig.user,
            group=self._serviceConfig.group,
            working_dir=self._serviceConfig.workingDir,
            python_path=self._serviceConfig.pythonPath,
            main_script=mainScriptPath,
            env_file=envFilePath,
            restart_delay=self._serviceConfig.restartDelaySeconds,
            max_restarts=self._serviceConfig.maxRestartAttempts,
            restart_interval=self._serviceConfig.restartIntervalSeconds
        )

        self._generatedContent = content
        return content

    def writeServiceFile(self, outputPath: str | None = None) -> str:
        """
        Write service file to specified path.

        Args:
            outputPath: Path to write service file (defaults to local directory)

        Returns:
            Path where service file was written

        Raises:
            ServiceError: If file cannot be written
        """
        if not self._generatedContent:
            self.generateServiceFile()

        # If no output path, write to current directory
        if not outputPath:
            outputPath = f"{self._serviceConfig.serviceName}.service"

        try:
            with open(outputPath, 'w', encoding='utf-8') as f:
                f.write(self._generatedContent)
            return outputPath
        except OSError as e:
            raise ServiceError(f"Failed to write service file: {e}") from e

    def install(self, serviceFilePath: str | None = None) -> bool:
        """
        Install the systemd service.

        Copies service file to systemd directory and reloads daemon.
        Requires root/sudo privileges.

        Args:
            serviceFilePath: Path to service file to install (if not generated)

        Returns:
            True if installation succeeded

        Raises:
            ServiceInstallError: If installation fails
        """
        if not serviceFilePath and not self._generatedContent:
            self.generateServiceFile()

        targetPath = self.getServiceFilePath()

        try:
            if serviceFilePath:
                # Copy existing service file
                shutil.copy2(serviceFilePath, targetPath)
            else:
                # Write generated content
                with open(targetPath, 'w', encoding='utf-8') as f:
                    f.write(self._generatedContent)

            # Reload systemd daemon
            self._runSystemctl(['daemon-reload'])

            return True

        except OSError as e:
            raise ServiceInstallError(
                f"Failed to install service: {e}",
                {'targetPath': targetPath}
            ) from e

    def uninstall(self) -> bool:
        """
        Uninstall the systemd service.

        Stops, disables, and removes the service file.
        Requires root/sudo privileges.

        Returns:
            True if uninstallation succeeded

        Raises:
            ServiceError: If uninstallation fails
        """
        servicePath = self.getServiceFilePath()

        if not os.path.exists(servicePath):
            raise ServiceNotInstalledError(
                f"Service not installed: {servicePath}"
            )

        try:
            # Stop and disable first
            self.stop()
            self.disable()

            # Remove service file
            os.remove(servicePath)

            # Reload daemon
            self._runSystemctl(['daemon-reload'])

            return True

        except OSError as e:
            raise ServiceError(f"Failed to uninstall service: {e}") from e

    def enable(self) -> bool:
        """
        Enable service to start on boot.

        Returns:
            True if enable succeeded

        Raises:
            ServiceCommandError: If enable fails
        """
        return self._runSystemctl(
            ['enable', f'{self._serviceConfig.serviceName}.service']
        )

    def disable(self) -> bool:
        """
        Disable service from starting on boot.

        Returns:
            True if disable succeeded

        Raises:
            ServiceCommandError: If disable fails
        """
        return self._runSystemctl(
            ['disable', f'{self._serviceConfig.serviceName}.service']
        )

    def start(self) -> bool:
        """
        Start the service.

        Returns:
            True if start succeeded

        Raises:
            ServiceCommandError: If start fails
        """
        return self._runSystemctl(
            ['start', f'{self._serviceConfig.serviceName}.service']
        )

    def stop(self) -> bool:
        """
        Stop the service.

        Returns:
            True if stop succeeded

        Raises:
            ServiceCommandError: If stop fails
        """
        return self._runSystemctl(
            ['stop', f'{self._serviceConfig.serviceName}.service']
        )

    def restart(self) -> bool:
        """
        Restart the service.

        Returns:
            True if restart succeeded

        Raises:
            ServiceCommandError: If restart fails
        """
        return self._runSystemctl(
            ['restart', f'{self._serviceConfig.serviceName}.service']
        )

    def getStatus(self) -> ServiceStatus:
        """
        Get current service status.

        Returns:
            ServiceStatus with current state information
        """
        servicePath = self.getServiceFilePath()
        serviceName = f'{self._serviceConfig.serviceName}.service'

        status = ServiceStatus(
            serviceName=self._serviceConfig.serviceName,
            serviceFilePath=servicePath,
            lastChecked=datetime.now()
        )

        # Check if installed
        status.installed = os.path.exists(servicePath)

        if not status.installed:
            return status

        # Check if enabled
        try:
            result = subprocess.run(
                ['systemctl', 'is-enabled', serviceName],
                capture_output=True,
                text=True
            )
            status.enabled = result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # Check if active/running
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', serviceName],
                capture_output=True,
                text=True
            )
            status.active = result.returncode == 0
            status.running = result.stdout.strip() == 'active'
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return status

    def isInstalled(self) -> bool:
        """Check if service is installed."""
        return os.path.exists(self.getServiceFilePath())

    def isEnabled(self) -> bool:
        """Check if service is enabled for auto-start."""
        return self.getStatus().enabled

    def isRunning(self) -> bool:
        """Check if service is currently running."""
        return self.getStatus().running

    def _runSystemctl(self, args: list) -> bool:
        """
        Run a systemctl command.

        Args:
            args: Command arguments for systemctl

        Returns:
            True if command succeeded

        Raises:
            ServiceCommandError: If command fails
        """
        try:
            cmd = ['systemctl'] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                # Some commands return non-zero but are OK (e.g., stop already stopped)
                stderrLower = result.stderr.lower()
                if 'not loaded' in stderrLower or 'not found' in stderrLower:
                    # Service not installed yet - this is OK for some operations
                    return True

                raise ServiceCommandError(
                    f"systemctl {' '.join(args)} failed: {result.stderr}",
                    {'returnCode': result.returncode, 'stderr': result.stderr}
                )

            return True

        except FileNotFoundError as e:
            # systemctl not available (not on Linux or systemd not installed)
            raise ServiceCommandError(
                "systemctl not found - systemd may not be available",
                {'command': args}
            ) from e


def createServiceManagerFromConfig(config: dict) -> ServiceManager:
    """
    Create ServiceManager from application configuration.

    Args:
        config: Application configuration dictionary

    Returns:
        Configured ServiceManager instance
    """
    return ServiceManager(config=config)


def generateInstallScript(
    config: dict | None = None,
    serviceConfig: ServiceConfig | None = None,
    outputPath: str = "install_service.sh"
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
        serviceConfig: Direct service configuration
        outputPath: Path to write the script

    Returns:
        Path to the generated script
    """
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
    serviceConfig: ServiceConfig | None = None,
    outputPath: str = "uninstall_service.sh"
) -> str:
    """
    Generate a shell script for service uninstallation.

    Args:
        config: Application configuration dictionary
        serviceConfig: Direct service configuration
        outputPath: Path to write the script

    Returns:
        Path to the generated script
    """
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
