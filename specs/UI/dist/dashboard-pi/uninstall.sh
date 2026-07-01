#!/usr/bin/env bash
# ============================================================
# US-399 carousel dashboard uninstaller. Stops + removes the
# eclipse-dashboard.service unit and the /opt/dashboard assets.
# Run as root: sudo ./uninstall.sh
# ============================================================
set -euo pipefail

SYSTEMD_DIR="/etc/systemd/system"
INSTALL_DIR="/opt/dashboard"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must be run as root. Try: sudo ./uninstall.sh" >&2
  exit 1
fi

echo "==> Stopping + disabling eclipse-dashboard.service (if present)"
systemctl stop eclipse-dashboard.service 2>/dev/null || true
systemctl disable eclipse-dashboard.service 2>/dev/null || true

echo "==> Removing the dashboard unit + assets"
rm -f "$SYSTEMD_DIR/eclipse-dashboard.service"
rm -rf "$INSTALL_DIR"

echo "==> Reloading systemd"
systemctl daemon-reload

echo "Done. (The splash-boot OnSuccess= hand-off still references"
echo " eclipse-dashboard.service; re-run the splash installer to clear it,"
echo " or it simply no-ops once the unit is gone.)"
