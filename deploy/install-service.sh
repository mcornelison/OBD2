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
#   --user USER    Set the user to run the service (default: pi)
#   --path PATH    Set the installation path (default: /home/pi/obd2)
#   --help         Show this help message
# ==============================================================================

set -e  # Exit on error

# Default values
SERVICE_USER="pi"
INSTALL_PATH="/home/pi/obd2"
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
    echo "  --user USER    Set the user to run the service (default: pi)"
    echo "  --path PATH    Set the installation path (default: /home/pi/obd2)"
    echo "  --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0"
    echo "  sudo $0 --user myuser --path /opt/obd2"
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
print_info "User: $SERVICE_USER"
print_info "Install path: $INSTALL_PATH"

# Verify user exists
if ! id "$SERVICE_USER" &>/dev/null; then
    print_error "User '$SERVICE_USER' does not exist"
    exit 1
fi

# Verify installation path exists
if [ ! -d "$INSTALL_PATH" ]; then
    print_error "Installation path '$INSTALL_PATH' does not exist"
    exit 1
fi

# Verify virtual environment exists
if [ ! -f "$INSTALL_PATH/.venv/bin/python" ]; then
    print_error "Python virtual environment not found at $INSTALL_PATH/.venv"
    print_info "Create it with: python3 -m venv $INSTALL_PATH/.venv"
    exit 1
fi

# Verify main.py exists
if [ ! -f "$INSTALL_PATH/src/main.py" ]; then
    print_error "main.py not found at $INSTALL_PATH/src/main.py"
    exit 1
fi

# Create logs directory
LOGS_DIR="$INSTALL_PATH/logs"
if [ ! -d "$LOGS_DIR" ]; then
    print_info "Creating logs directory..."
    mkdir -p "$LOGS_DIR"
    chown "$SERVICE_USER:$SERVICE_USER" "$LOGS_DIR"
fi

# Create data directory
DATA_DIR="$INSTALL_PATH/data"
if [ ! -d "$DATA_DIR" ]; then
    print_info "Creating data directory..."
    mkdir -p "$DATA_DIR"
    chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
fi

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

# Copy and modify service file
cp "$SOURCE_SERVICE" "$SERVICE_FILE"

# Update User
sed -i "s|^User=.*|User=$SERVICE_USER|" "$SERVICE_FILE"

# Update WorkingDirectory
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_PATH|" "$SERVICE_FILE"

# Update PATH environment
sed -i "s|^Environment=PATH=.*|Environment=PATH=$INSTALL_PATH/.venv/bin:/usr/bin:/bin|" "$SERVICE_FILE"

# Update ExecStart
sed -i "s|^ExecStart=.*|ExecStart=$INSTALL_PATH/.venv/bin/python src/main.py --config src/obd_config.json|" "$SERVICE_FILE"

# Update log paths
sed -i "s|^StandardOutput=.*|StandardOutput=append:$INSTALL_PATH/logs/service.log|" "$SERVICE_FILE"
sed -i "s|^StandardError=.*|StandardError=append:$INSTALL_PATH/logs/service-error.log|" "$SERVICE_FILE"

# Reload systemd to pick up new service
print_info "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service to start on boot
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
print_info "To view logs:"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo "  tail -f $INSTALL_PATH/logs/service.log"
echo ""
print_info "To stop the service:"
echo "  sudo systemctl stop $SERVICE_NAME"
echo ""
print_info "To disable auto-start on boot:"
echo "  sudo systemctl disable $SERVICE_NAME"
