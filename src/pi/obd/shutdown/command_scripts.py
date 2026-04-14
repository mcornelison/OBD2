################################################################################
# File Name: command_scripts.py
# Purpose/Description: Shell/Python script generators for shutdown + GPIO trigger
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# 2026-04-14    | Sweep 5       | Extracted from command.py (task 4 split)
# ================================================================================
################################################################################

"""
Script generators that render shutdown.sh (bash) and gpio_shutdown_trigger.py
(standalone Python service) from a ShutdownConfig. Used for creating deploy
artifacts on the Pi.
"""

import os
import stat
from datetime import datetime

from .command_types import ShutdownConfig


def generateShutdownScript(
    outputPath: str = 'shutdown.sh',
    config: ShutdownConfig | None = None,
    powerOff: bool = False
) -> str:
    """
    Generate a shell script for shutting down the OBD-II system.

    The script:
    - Sends SIGTERM to the running process
    - Waits for graceful shutdown (max 30 seconds)
    - Optionally powers down the Raspberry Pi

    Args:
        outputPath: Path to write the script
        config: Shutdown configuration
        powerOff: Whether to include power off option

    Returns:
        Path to the generated script
    """
    cfg = config or ShutdownConfig()

    # Build power off section
    powerOffSection = ''
    if powerOff or cfg.powerOffEnabled:
        powerOffSection = f'''
# Power off option
POWER_OFF_DELAY={cfg.powerOffDelaySeconds}

if [[ "$POWER_OFF" == "true" ]]; then
    print_status "Scheduling system power off in $POWER_OFF_DELAY seconds"
    sudo shutdown -h +$((POWER_OFF_DELAY / 60)) "Eclipse OBD-II scheduled shutdown"
fi
'''

    script = f'''#!/bin/bash
################################################################################
# Eclipse OBD-II Shutdown Script
# Generated: {datetime.now().isoformat()}
#
# This script gracefully shuts down the Eclipse OBD-II system.
# Usage: ./shutdown.sh [--power-off]
################################################################################

set -e

# Configuration
SERVICE_NAME="{cfg.serviceName}"
PID_FILE="{cfg.pidFile}"
SHUTDOWN_TIMEOUT={cfg.timeoutSeconds}
POWER_OFF="${{1:-false}}"

# Process --power-off argument
if [[ "$1" == "--power-off" ]] || [[ "$1" == "-p" ]]; then
    POWER_OFF="true"
fi

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

print_status() {{
    echo -e "${{GREEN}}[OK]${{NC}} $1"
}}

print_error() {{
    echo -e "${{RED}}[ERROR]${{NC}} $1"
}}

print_warning() {{
    echo -e "${{YELLOW}}[WARN]${{NC}} $1"
}}

echo "=================================================="
echo "Eclipse OBD-II Shutdown"
echo "=================================================="
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Shutdown initiated"
echo ""

# Function to get PID
get_pid() {{
    # Try PID file first
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi

    # Try systemd
    if command -v systemctl &> /dev/null; then
        local pid=$(systemctl show "$SERVICE_NAME" --property=MainPID --value 2>/dev/null)
        if [[ -n "$pid" ]] && [[ "$pid" != "0" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi

    # Try pgrep as last resort
    local pid=$(pgrep -f "python.*main.py" 2>/dev/null | head -1)
    if [[ -n "$pid" ]]; then
        echo "$pid"
        return 0
    fi

    return 1
}}

# Function to wait for process exit
wait_for_exit() {{
    local pid=$1
    local timeout=$2
    local elapsed=0

    echo -n "Waiting for process to exit "
    while kill -0 "$pid" 2>/dev/null && [[ $elapsed -lt $timeout ]]; do
        echo -n "."
        sleep 1
        ((elapsed++))
    done
    echo ""

    if kill -0 "$pid" 2>/dev/null; then
        return 1  # Still running
    fi
    return 0  # Exited
}}

# Get the process ID
PID=$(get_pid)

if [[ -z "$PID" ]]; then
    print_warning "No running Eclipse OBD-II process found"
    echo ""

    # Check if service exists but is stopped
    if systemctl is-enabled "$SERVICE_NAME" 2>/dev/null; then
        print_status "Service exists but is not running"
    fi

    # Handle power off even if process not running
    if [[ "$POWER_OFF" == "true" ]]; then
        echo ""
        read -p "Power off system anyway? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_status "Scheduling system power off"
            sudo shutdown -h +0 "Eclipse OBD-II shutdown"
        fi
    fi

    exit 0
fi

echo "Found process: PID=$PID"
echo ""

# Send SIGTERM for graceful shutdown
echo "Sending SIGTERM to process $PID..."
kill -TERM "$PID" 2>/dev/null || true

# Wait for graceful shutdown
if wait_for_exit "$PID" "$SHUTDOWN_TIMEOUT"; then
    print_status "Process terminated gracefully"
else
    print_warning "Process did not exit within $SHUTDOWN_TIMEOUT seconds"
    echo ""
    read -p "Send SIGKILL to force termination? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kill -9 "$PID" 2>/dev/null || true
        sleep 1
        if kill -0 "$PID" 2>/dev/null; then
            print_error "Failed to terminate process"
            exit 1
        else
            print_status "Process terminated (forced)"
        fi
    else
        print_error "Shutdown incomplete - process still running"
        exit 1
    fi
fi

# Clean up PID file
if [[ -f "$PID_FILE" ]]; then
    rm -f "$PID_FILE" 2>/dev/null || true
fi

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Shutdown completed"
{powerOffSection}
echo ""
echo "=================================================="
echo "Shutdown Complete!"
echo "=================================================="
'''

    with open(outputPath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(script)

    # Make executable
    try:
        currentMode = os.stat(outputPath).st_mode
        os.chmod(outputPath, currentMode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except (OSError, AttributeError):
        pass  # May fail on Windows

    return outputPath


def generateGpioTriggerScript(
    outputPath: str = 'gpio_shutdown_trigger.py',
    config: ShutdownConfig | None = None
) -> str:
    """
    Generate a Python script for GPIO button shutdown trigger.

    This is a standalone script that can be run as a service to
    monitor a GPIO button and initiate shutdown when pressed.

    Args:
        outputPath: Path to write the script
        config: Shutdown configuration

    Returns:
        Path to the generated script
    """
    cfg = config or ShutdownConfig()

    script = f'''#!/usr/bin/env python3
################################################################################
# Eclipse OBD-II GPIO Shutdown Trigger
# Generated: {datetime.now().isoformat()}
#
# Standalone script to monitor GPIO button and initiate shutdown when pressed.
# Run as a service: sudo systemctl start eclipse-obd2-gpio
################################################################################

import signal
import sys
import time
import logging
import subprocess

# Configuration
GPIO_PIN = {cfg.gpioPin}
DEBOUNCE_MS = {cfg.gpioDebounceMs}
SERVICE_NAME = "{cfg.serviceName}"
POWER_OFF_ENABLED = {str(cfg.powerOffEnabled).lower()}
POWER_OFF_DELAY = {cfg.powerOffDelaySeconds}

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import GPIO
try:
    import RPi.GPIO as GPIO
except ImportError:
    logger.error("RPi.GPIO not available - this script requires Raspberry Pi")
    sys.exit(1)

running = True

def signal_handler(signum, frame):
    global running
    logger.info("Received signal, stopping...")
    running = False

def initiate_shutdown():
    logger.info("Button pressed - initiating shutdown")

    # Stop the OBD-II service
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'stop', SERVICE_NAME],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"Service {{SERVICE_NAME}} stopped")
        else:
            logger.warning(f"Failed to stop service: {{result.stderr}}")
    except Exception as e:
        logger.error(f"Error stopping service: {{e}}")

    # Power off if enabled
    if POWER_OFF_ENABLED:
        logger.info(f"Scheduling power off in {{POWER_OFF_DELAY}} seconds")
        try:
            subprocess.run(
                ['sudo', 'shutdown', '-h', f'+{{POWER_OFF_DELAY // 60}}'],
                check=False
            )
        except Exception as e:
            logger.error(f"Error scheduling power off: {{e}}")

def button_callback(channel):
    initiate_shutdown()

def main():
    global running

    logger.info(f"Eclipse OBD-II GPIO Shutdown Trigger starting")
    logger.info(f"Monitoring GPIO pin {{GPIO_PIN}}")

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Set up GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(
        GPIO_PIN,
        GPIO.FALLING,
        callback=button_callback,
        bouncetime=DEBOUNCE_MS
    )

    logger.info("GPIO button trigger running")

    try:
        while running:
            time.sleep(1)
    finally:
        GPIO.cleanup(GPIO_PIN)
        logger.info("GPIO cleanup complete")

if __name__ == '__main__':
    main()
'''

    with open(outputPath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(script)

    # Make executable
    try:
        currentMode = os.stat(outputPath).st_mode
        os.chmod(outputPath, currentMode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except (OSError, AttributeError):
        pass

    return outputPath
