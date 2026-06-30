#!/usr/bin/env bash
# F-103 splash uninstaller. Removes the boot + grace render kit installed by
# install.sh, plus any legacy units (splash-shutdown.service) so an upgrade-in-
# place leaves nothing behind.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must be run as root. Try: sudo ./uninstall.sh" >&2
  exit 1
fi

SYSTEMD_DIR="/etc/systemd/system"

echo "==> Disabling splash units"
systemctl disable splash-boot.service 2>/dev/null || true
systemctl disable splash-grace.path 2>/dev/null || true
systemctl stop splash-grace.service 2>/dev/null || true
# Legacy unit from the pre-US-396 kit (retired D-2).
systemctl disable splash-shutdown.service 2>/dev/null || true

echo "==> Removing systemd units"
rm -f "$SYSTEMD_DIR/splash-boot.service"
rm -f "$SYSTEMD_DIR/splash-grace.service"
rm -f "$SYSTEMD_DIR/splash-grace.path"
rm -f "$SYSTEMD_DIR/splash-shutdown.service"
systemctl daemon-reload

echo "==> Removing $INSTALL_DIR"
INSTALL_DIR="/opt/splash"
rm -rf "$INSTALL_DIR"

echo "Done."
