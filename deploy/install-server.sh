#!/bin/bash
# ==============================================================================
# File: install-server.sh
# Purpose: Install Eclipse OBD-II Server as a systemd service on Chi-Srv-01
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Usage:
#   sudo ./install-server.sh [OPTIONS]
#
# Options:
#   --user USER    Set the user to run the service (default: mcornelison)
#   --path PATH    Set the installation path (default: /home/mcornelison/Projects/OBD2v2)
#   --port PORT    Set the uvicorn port (default: 8000)
#   --help         Show this help message
# ==============================================================================

set -e  # Exit on error

# Default values
SERVICE_USER="mcornelison"
INSTALL_PATH="/home/mcornelison/Projects/OBD2v2"
SERVICE_PORT="8000"
SERVICE_NAME="obd2-server"
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
    echo "Install Eclipse OBD-II Server as a systemd service"
    echo ""
    echo "Usage: sudo $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --user USER    Set the user to run the service (default: mcornelison)"
    echo "  --path PATH    Set the installation path (default: /home/mcornelison/Projects/OBD2v2)"
    echo "  --port PORT    Set the uvicorn port (default: 8000)"
    echo "  --help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  sudo $0"
    echo "  sudo $0 --user myuser --path /opt/obd2 --port 9000"
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
        --port)
            SERVICE_PORT="$2"
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

print_info "Installing Eclipse OBD-II Server service..."
print_info "User: $SERVICE_USER"
print_info "Install path: $INSTALL_PATH"
print_info "Port: $SERVICE_PORT"

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

# Verify uvicorn is installed in venv
if [ ! -f "$INSTALL_PATH/.venv/bin/uvicorn" ]; then
    print_error "uvicorn not found in virtual environment"
    print_info "Install it with: $INSTALL_PATH/.venv/bin/pip install uvicorn"
    exit 1
fi

# Verify main.py exists
if [ ! -f "$INSTALL_PATH/src/server/main.py" ]; then
    print_error "Server main.py not found at $INSTALL_PATH/src/server/main.py"
    exit 1
fi

# Verify .env exists (DATABASE_URL is required)
if [ ! -f "$INSTALL_PATH/.env" ]; then
    print_warn ".env file not found at $INSTALL_PATH/.env"
    print_warn "The server requires DATABASE_URL to be set. Create .env before starting."
fi

# Create logs directory
LOGS_DIR="$INSTALL_PATH/logs"
if [ ! -d "$LOGS_DIR" ]; then
    print_info "Creating logs directory..."
    mkdir -p "$LOGS_DIR"
    chown "$SERVICE_USER:$SERVICE_USER" "$LOGS_DIR"
fi

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_SERVICE="$SCRIPT_DIR/obd2-server.service"

# Verify source service file exists
if [ ! -f "$SOURCE_SERVICE" ]; then
    print_error "Service file not found at $SOURCE_SERVICE"
    exit 1
fi

# Copy and customize service file
print_info "Installing service file to $SERVICE_FILE..."
cp "$SOURCE_SERVICE" "$SERVICE_FILE"

# Update User
sed -i "s|^User=.*|User=$SERVICE_USER|" "$SERVICE_FILE"

# Update WorkingDirectory
sed -i "s|^WorkingDirectory=.*|WorkingDirectory=$INSTALL_PATH|" "$SERVICE_FILE"

# Update PATH environment
sed -i "s|^Environment=PATH=.*|Environment=PATH=$INSTALL_PATH/.venv/bin:/usr/bin:/bin|" "$SERVICE_FILE"

# Update ExecStart with correct path and port
sed -i "s|^ExecStart=.*|ExecStart=$INSTALL_PATH/.venv/bin/uvicorn src.server.main:app --host 0.0.0.0 --port $SERVICE_PORT|" "$SERVICE_FILE"

# Update log paths
sed -i "s|^StandardOutput=.*|StandardOutput=append:$INSTALL_PATH/logs/server.log|" "$SERVICE_FILE"
sed -i "s|^StandardError=.*|StandardError=append:$INSTALL_PATH/logs/server-error.log|" "$SERVICE_FILE"

# Reload systemd to pick up new service
print_info "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service to start on boot
print_info "Enabling service to start on boot..."
systemctl enable "$SERVICE_NAME"

# Start the service
print_info "Starting service..."
systemctl start "$SERVICE_NAME"

# Print status
echo ""
print_info "=============================================="
print_info "Installation complete!"
print_info "=============================================="
echo ""

systemctl status "$SERVICE_NAME" --no-pager || true

echo ""
print_info "Useful commands:"
echo "  sudo systemctl status $SERVICE_NAME    # Check status"
echo "  sudo systemctl restart $SERVICE_NAME   # Restart"
echo "  sudo systemctl stop $SERVICE_NAME      # Stop"
echo "  sudo journalctl -u $SERVICE_NAME -f    # Follow journal logs"
echo "  tail -f $INSTALL_PATH/logs/server.log  # Follow file logs"
