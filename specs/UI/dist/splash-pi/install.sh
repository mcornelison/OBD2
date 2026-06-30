#!/usr/bin/env bash
# ============================================================
# F-103 splash installer for Raspberry Pi (3.5" 480x320 display)
# Run as root (or with sudo) on the target Pi after copying this
# whole folder to it. Installs the boot + grace (shutdown) splash
# render kit: assets to /opt/splash + the systemd units.
#
# Install-time checks (spec §7):
#   V-1  detect the real Pi user (single non-root /home/* owner) and
#        substitute it into the unit templates; fail loudly if it can't
#        be determined -- the kit no longer hardcodes User=pi.
#   V-2  detect the session manager (Wayland vs X11) and pick the matching
#        unit variant; fail loudly if unknown -- guessing wrong gives the
#        D-3 class of bug (X11 env on a Wayland session => black screen).
#
#   --dry-run  report the user + session-type + variants it WOULD pick and
#              exit WITHOUT installing (runs unprivileged; spec §9 S-4).
#
# Detection is overridable for off-Pi CI/testing:
#   SPLASH_FORCE_USER       force the Pi user (empty => simulate "can't tell")
#   SPLASH_FORCE_SESSION    force wayland|x11 (other => simulate "unknown")
#   SPLASH_USER_HOME_GLOB   override the /home/* probe glob
# ============================================================
set -euo pipefail
shopt -s nullglob

SYSTEMD_DIR="/etc/systemd/system"
INSTALL_DIR="/opt/splash"
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
  if [[ -n "${SPLASH_FORCE_USER+x}" ]]; then
    printf '%s' "$SPLASH_FORCE_USER"   # forced (may be empty => indeterminate)
    return 0
  fi
  local glob="${SPLASH_USER_HOME_GLOB:-/home/*}"
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
  if [[ -n "${SPLASH_FORCE_SESSION+x}" ]]; then
    printf '%s' "$SPLASH_FORCE_SESSION"   # forced (may be unknown => abort)
    return 0
  fi
  local t=""
  if command -v loginctl >/dev/null 2>&1 && [[ -n "${XDG_SESSION_ID:-}" ]]; then
    t="$(loginctl show-session "$XDG_SESSION_ID" -p Type --value 2>/dev/null || true)"
  fi
  if [[ -z "$t" ]]; then
    # Fallback (spec §10 open-question): probe the wayland-0 socket. If neither
    # an active loginctl session NOR the socket exists, type stays empty and the
    # caller aborts loudly -- never default to X11.
    local uid=""
    uid="$(id -u "$pi_user" 2>/dev/null || true)"
    if [[ -n "$uid" && -S "/run/user/$uid/wayland-0" ]]; then
      t="wayland"
    fi
  fi
  printf '%s' "$t"
}

PI_USER="$(detect_pi_user)"
if [[ -z "$PI_USER" ]]; then
  echo "ERROR: cannot determine the target Pi user (expected exactly one" >&2
  echo "       non-root /home/* owner). Set SPLASH_FORCE_USER to override." >&2
  exit 1
fi

SESSION_TYPE="$(detect_session_type "$PI_USER")"
case "$SESSION_TYPE" in
  wayland|x11) ;;
  *)
    echo "ERROR: cannot determine session type (no active loginctl session," >&2
    echo "       no wayland-0 socket; got '${SESSION_TYPE:-<empty>}'). Aborting" >&2
    echo "       splash install -- guessing X11 vs Wayland gives the D-3 bug." >&2
    exit 1
    ;;
esac

BOOT_VARIANT="splash-boot.service.${SESSION_TYPE}"
GRACE_VARIANT="splash-grace.service.${SESSION_TYPE}"

echo "==> F-103 splash kit"
echo "    Detected Pi user:      $PI_USER"
echo "    Detected session type: $SESSION_TYPE"
echo "    Boot variant:          $BOOT_VARIANT  -> $SYSTEMD_DIR/splash-boot.service"
echo "    Grace variant:         $GRACE_VARIANT -> $SYSTEMD_DIR/splash-grace.service"
echo "    Path unit:             splash-grace.path"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "==> DRY RUN -- no changes made. Would copy assets to $INSTALL_DIR,"
  echo "    substitute User=$PI_USER into the unit templates, install the units,"
  echo "    daemon-reload, and enable: splash-boot.service splash-grace.path"
  exit 0
fi

# --- real install (root only) -------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must be run as root. Try: sudo ./install.sh" >&2
  exit 1
fi

# Substitute __PI_USER__ into a template and write the destination unit.
install_unit() {
  local src="$1" dest="$2"
  sed "s/__PI_USER__/${PI_USER}/g" "$SCRIPT_DIR/$src" > "$dest"
  chmod 0644 "$dest"
}

echo "==> Installing splash assets to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
for asset in splash.svg splash-shutdown.svg index.html shutdown.html \
             boot-state-poll.js shutdown-state-poll.js styles.css; do
  if [[ -f "$SCRIPT_DIR/$asset" ]]; then
    install -m 0644 "$SCRIPT_DIR/$asset" "$INSTALL_DIR/$asset"
  else
    echo "WARN: asset missing, skipped: $asset" >&2
  fi
done

echo "==> Sweeping retired units (D-2 splash-shutdown, D-3 original boot)"
rm -f "$SYSTEMD_DIR/splash-shutdown.service"

echo "==> Installing systemd units ($SESSION_TYPE variants)"
install_unit "$BOOT_VARIANT"  "$SYSTEMD_DIR/splash-boot.service"
install_unit "$GRACE_VARIANT" "$SYSTEMD_DIR/splash-grace.service"
install -m 0644 "$SCRIPT_DIR/splash-grace.path" "$SYSTEMD_DIR/splash-grace.path"

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling units (idempotent)"
systemctl enable splash-boot.service
systemctl enable splash-grace.path

echo
echo "Done. Reboot to see the boot splash:  sudo reboot"
echo "To uninstall:                          sudo ./uninstall.sh"
