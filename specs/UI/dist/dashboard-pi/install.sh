#!/usr/bin/env bash
# ============================================================
# US-399 carousel dashboard installer for Raspberry Pi (3.5" 480x320).
# Run as root (or with sudo) on the target Pi after copying this whole
# folder to it. Installs the carousel render kit: assets to /opt/dashboard
# + the eclipse-dashboard.service systemd unit.
#
# Install-time checks (mirror the F-103 splash installer, spec §7):
#   V-1  detect the real Pi user (single non-root /home/* owner) and
#        substitute it into the unit template; fail loudly if it can't be
#        determined -- the kit never hardcodes User=pi.
#   V-2  detect the session manager (Wayland vs X11) and pick the matching
#        unit variant; fail loudly if unknown -- guessing wrong gives the
#        D-3 class of bug (X11 env on a Wayland session => black screen).
#   V-3  detect the chromium binary path (chromium-browser OR chromium --
#        Raspberry Pi OS Trixie ships /usr/bin/chromium) and substitute it into
#        the unit ExecStart, like V-1 substitutes User=; fail loudly if neither
#        is found. Retires the deploy-side /usr/bin/chromium-browser symlink shim
#        -- a hardcoded ExecStart=/usr/bin/chromium-browser dies 203/EXEC on
#        Trixie (US-428 / Bug 2).
#
#   --dry-run  report the user + session-type + chromium + variant it WOULD
#              pick (and the resolved ExecStart) and exit WITHOUT installing
#              (runs unprivileged).
#
# A-1 hand-off: the dashboard unit is started by splash-boot.service's
#   OnSuccess= directive (after HEALTHY_YIELD), so it is installed but NOT
#   `systemctl enable`d (it has no [Install] section by design).
#
# Detection is overridable for off-Pi CI/testing:
#   DASHBOARD_FORCE_USER       force the Pi user (empty => simulate "can't tell")
#   DASHBOARD_FORCE_SESSION    force wayland|x11 (other => simulate "unknown")
#   DASHBOARD_FORCE_CHROMIUM   force the chromium path (empty => simulate "none")
#   DASHBOARD_USER_HOME_GLOB   override the /home/* probe glob
# ============================================================
set -euo pipefail
shopt -s nullglob

SYSTEMD_DIR="/etc/systemd/system"
INSTALL_DIR="/opt/dashboard"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

DRY_RUN=0

# --- arg parse ----------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg (try --dry-run or --help)" >&2
      exit 2
      ;;
  esac
done

# --- V-1: detect the Pi user --------------------------------------------------
detect_pi_user() {
  if [[ -n "${DASHBOARD_FORCE_USER+x}" ]]; then
    printf '%s' "$DASHBOARD_FORCE_USER"   # forced (may be empty => indeterminate)
    return 0
  fi
  local glob="${DASHBOARD_USER_HOME_GLOB:-/home/*}"
  local found=()
  local d
  for d in $glob; do
    [[ -d "$d" ]] || continue
    found+=("$(basename -- "$d")")
  done
  if [[ ${#found[@]} -eq 1 ]]; then
    printf '%s' "${found[0]}"
  fi
  # 0 or >1 matches => print nothing => caller treats as indeterminate.
}

# --- V-2: detect the session type (wayland|x11) -------------------------------
detect_session_type() {
  local pi_user="$1"
  if [[ -n "${DASHBOARD_FORCE_SESSION+x}" ]]; then
    printf '%s' "$DASHBOARD_FORCE_SESSION"   # forced (may be unknown => abort)
    return 0
  fi
  local t=""
  if command -v loginctl >/dev/null 2>&1 && [[ -n "${XDG_SESSION_ID:-}" ]]; then
    t="$(loginctl show-session "$XDG_SESSION_ID" -p Type --value 2>/dev/null || true)"
  fi
  if [[ -z "$t" ]]; then
    local uid=""
    uid="$(id -u "$pi_user" 2>/dev/null || true)"
    if [[ -n "$uid" && -S "/run/user/$uid/wayland-0" ]]; then
      t="wayland"
    fi
  fi
  printf '%s' "$t"
}

# --- V-3: detect the chromium binary path -------------------------------------
detect_chromium_bin() {
  if [[ -n "${DASHBOARD_FORCE_CHROMIUM+x}" ]]; then
    printf '%s' "$DASHBOARD_FORCE_CHROMIUM"   # forced (may be empty => indeterminate)
    return 0
  fi
  # Prefer the historical name, then the Trixie name. Either is a valid
  # executable for ExecStart; command -v resolves the absolute path.
  local c
  for c in chromium-browser chromium; do
    if command -v "$c" >/dev/null 2>&1; then
      command -v "$c"
      return 0
    fi
  done
  # neither found => print nothing => caller aborts loudly (like V-1/V-2).
}

PI_USER="$(detect_pi_user)"
if [[ -z "$PI_USER" ]]; then
  echo "ERROR: cannot determine the target Pi user (expected exactly one" >&2
  echo "       non-root /home/* owner). Set DASHBOARD_FORCE_USER to override." >&2
  exit 1
fi

SESSION_TYPE="$(detect_session_type "$PI_USER")"
case "$SESSION_TYPE" in
  wayland|x11) ;;
  *)
    echo "ERROR: cannot determine session type (no active loginctl session," >&2
    echo "       no wayland-0 socket; got '${SESSION_TYPE:-<empty>}'). Aborting" >&2
    echo "       dashboard install -- guessing X11 vs Wayland gives the D-3 bug." >&2
    exit 1
    ;;
esac

CHROMIUM_BIN="$(detect_chromium_bin)"
if [[ -z "$CHROMIUM_BIN" ]]; then
  echo "ERROR: cannot find a chromium binary (looked for chromium-browser then" >&2
  echo "       chromium on PATH). Install chromium, or set DASHBOARD_FORCE_CHROMIUM" >&2
  echo "       to override. Aborting -- a hardcoded ExecStart=/usr/bin/chromium-" >&2
  echo "       browser dies with 203/EXEC on Trixie (US-428 / Bug 2)." >&2
  exit 1
fi

DASH_VARIANT="dashboard.service.${SESSION_TYPE}"

echo "==> US-399 carousel dashboard kit"
echo "    Detected Pi user:      $PI_USER"
echo "    Detected session type: $SESSION_TYPE"
echo "    Chromium binary:       $CHROMIUM_BIN  (V-3 -> ExecStart)"
echo "    Dashboard variant:     $DASH_VARIANT -> $SYSTEMD_DIR/eclipse-dashboard.service"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "==> DRY RUN -- no changes made. Would copy assets to $INSTALL_DIR,"
  echo "    substitute User=$PI_USER + chromium=$CHROMIUM_BIN into the unit"
  echo "    template, install eclipse-dashboard.service, and daemon-reload. The"
  echo "    unit is started by splash-boot's OnSuccess= hand-off, NOT enabled here."
  echo "    Resolved ExecStart:"
  sed -e "s/__PI_USER__/${PI_USER}/g" -e "s#__CHROMIUM_BIN__#${CHROMIUM_BIN}#g" \
      "$SCRIPT_DIR/$DASH_VARIANT" | grep -m1 '^ExecStart=' | sed 's/^/      /' || true
  exit 0
fi

# --- real install (root only) -------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must be run as root. Try: sudo ./install.sh" >&2
  exit 1
fi

# Substitute __PI_USER__ (V-1) and __CHROMIUM_BIN__ (V-3) into the template.
install_unit() {
  local src="$1" dest="$2"
  sed -e "s/__PI_USER__/${PI_USER}/g" \
      -e "s#__CHROMIUM_BIN__#${CHROMIUM_BIN}#g" \
      "$SCRIPT_DIR/$src" > "$dest"
  chmod 0644 "$dest"
}

echo "==> Installing dashboard assets to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
for asset in dashboard.html dashboard.css carousel.js; do
  if [[ -f "$SCRIPT_DIR/$asset" ]]; then
    install -m 0644 "$SCRIPT_DIR/$asset" "$INSTALL_DIR/$asset"
  else
    echo "WARN: asset missing, skipped: $asset" >&2
  fi
done

echo "==> Installing systemd unit ($SESSION_TYPE variant)"
install_unit "$DASH_VARIANT" "$SYSTEMD_DIR/eclipse-dashboard.service"

echo "==> Reloading systemd"
systemctl daemon-reload

echo
echo "Done. The dashboard is started by the boot splash hand-off (A-1)."
echo "Ensure eclipse-states-http.service has /opt/dashboard on its --assets-dir."
echo "To uninstall:  sudo ./uninstall.sh"
