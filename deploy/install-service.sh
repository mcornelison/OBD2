#!/bin/bash
# ==============================================================================
# File: install-service.sh
# Purpose: Install Eclipse OBD-II systemd service on Raspberry Pi
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Usage:
#   sudo ./install-service.sh [OPTIONS]
#
# Options:
#   --user USER    Set the user to run the service
#                  (default: mcornelison)
#   --path PATH    Set the installation path (WorkingDirectory)
#                  (default: /home/mcornelison/Projects/Eclipse-01)
#   --venv PATH    Set the Python venv path
#                  (default: /home/mcornelison/obd2-venv)
#   --help         Show this help message
#
# Idempotency: Running this script twice in a row produces the same end state.
# The service file is overwritten with the current template + substitutions,
# directory creation uses mkdir -p, and systemctl enable is a no-op on re-run.
# ==============================================================================

set -e  # Exit on error

# Default values (match deploy/eclipse-obd.service and the Sprint 10 Pi-crawl
# hostname migration — mcornelison on chi-eclipse-01, venv at ~/obd2-venv to
# mirror the server's ~/obd2-server-venv convention).
SERVICE_USER="mcornelison"
INSTALL_PATH="/home/mcornelison/Projects/Eclipse-01"
VENV_PATH="/home/mcornelison/obd2-venv"
SERVICE_NAME="eclipse-obd"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

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
    echo "Install Eclipse OBD-II systemd service"
    echo ""
    echo "Usage: sudo $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --user USER    Set the user to run the service"
    echo "                 (default: $SERVICE_USER)"
    echo "  --path PATH    Set the installation path"
    echo "                 (default: $INSTALL_PATH)"
    echo "  --venv PATH    Set the Python venv path"
    echo "                 (default: $VENV_PATH)"
    echo "  --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0"
    echo "  sudo $0 --user myuser --path /opt/obd2 --venv /opt/obd2-venv"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --user)
            SERVICE_USER="$2"
            shift 2
            ;;
        --path)
            INSTALL_PATH="$2"
            shift 2
            ;;
        --venv)
            VENV_PATH="$2"
            shift 2
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

print_info "Installing Eclipse OBD-II service..."
print_info "User:         $SERVICE_USER"
print_info "Install path: $INSTALL_PATH"
print_info "Venv path:    $VENV_PATH"

# Verify user exists
if ! id "$SERVICE_USER" &>/dev/null; then
    print_error "User '$SERVICE_USER' does not exist"
    exit 1
fi

# Verify installation path exists
if [ ! -d "$INSTALL_PATH" ]; then
    print_error "Installation path '$INSTALL_PATH' does not exist"
    print_info "Run 'bash deploy/deploy-pi.sh --init' first to stand up the tree."
    exit 1
fi

# Verify virtual environment exists
if [ ! -f "$VENV_PATH/bin/python" ]; then
    print_error "Python virtual environment not found at $VENV_PATH"
    print_info "Create it with: python3 -m venv $VENV_PATH"
    print_info "Or run:         bash deploy/deploy-pi.sh --init"
    exit 1
fi

# Verify main.py exists (post-reorg canonical path)
if [ ! -f "$INSTALL_PATH/src/pi/main.py" ]; then
    print_error "main.py not found at $INSTALL_PATH/src/pi/main.py"
    exit 1
fi

# Create data directory (idempotent)
DATA_DIR="$INSTALL_PATH/data"
if [ ! -d "$DATA_DIR" ]; then
    print_info "Creating data directory..."
    mkdir -p "$DATA_DIR"
    chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
fi

# Note: no logs/ directory creation — runtime logs live in the systemd journal
# (view with 'sudo journalctl -u eclipse-obd -f'). The legacy on-disk log path
# was removed when the service file moved to journal-default logging.

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_SERVICE="$SCRIPT_DIR/eclipse-obd.service"

# Verify source service file exists
if [ ! -f "$SOURCE_SERVICE" ]; then
    print_error "Service file not found at $SOURCE_SERVICE"
    exit 1
fi

# Create service file with substituted values
print_info "Installing service file to $SERVICE_FILE..."

# Copy and modify service file (overwrite is idempotent)
cp "$SOURCE_SERVICE" "$SERVICE_FILE"

# Update User
sed -i "s|^User=.*|User=$SERVICE_USER|" "$SERVICE_FILE"

# Update WorkingDirectory
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_PATH|" "$SERVICE_FILE"

# Update PATH environment (venv bin first, then system bins)
sed -i "s|^Environment=PATH=.*|Environment=PATH=$VENV_PATH/bin:/usr/bin:/bin|" "$SERVICE_FILE"

# Update ExecStart (venv python + post-reorg src/pi/main.py, no --config flag
# needed — main.py resolves config.json via Path(__file__) lookup)
sed -i "s|^ExecStart=.*|ExecStart=$VENV_PATH/bin/python src/pi/main.py|" "$SERVICE_FILE"

# Reload systemd to pick up new service
print_info "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service to start on boot (idempotent)
print_info "Enabling service to start on boot..."
systemctl enable "$SERVICE_NAME"

# Check if service was installed correctly
if systemctl list-unit-files | grep -q "$SERVICE_NAME.service"; then
    print_info "Service installed successfully!"
else
    print_error "Service installation failed"
    exit 1
fi

echo ""
print_info "=============================================="
print_info "Installation complete!"
print_info "=============================================="
echo ""
print_info "To start the service now:"
echo "  sudo systemctl start $SERVICE_NAME"
echo ""
print_info "To check service status:"
echo "  sudo systemctl status $SERVICE_NAME"
echo ""
print_info "To view logs (systemd journal is the source of truth):"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo ""
print_info "To stop the service:"
echo "  sudo systemctl stop $SERVICE_NAME"
echo ""
print_info "To disable auto-start on boot:"
echo "  sudo systemctl disable $SERVICE_NAME"
