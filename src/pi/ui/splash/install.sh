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
#   V-3  detect the chromium binary path (chromium-browser OR chromium --
#        Raspberry Pi OS Trixie ships /usr/bin/chromium) and substitute it into
#        the unit ExecStart, like V-1 substitutes User=; fail loudly if neither
#        is found. This retires the deploy-side /usr/bin/chromium-browser symlink
#        shim -- a hardcoded ExecStart=/usr/bin/chromium-browser dies 203/EXEC on
#        Trixie (US-428 / Bug 2).
#   V-4  resolve the Pi user's NUMERIC UID (`id -u`) and substitute it into the
#        units' XDG_RUNTIME_DIR; fail loudly if it can't be resolved. I-044: the
#        templates used systemd's %U specifier, which did NOT resolve from User=
#        on the live Pi -- `systemctl show splash-boot.service -p Environment`
#        reported /run/user/0 (root's) under User=mcornelison (uid 1000), giving
#        "unable to create directory '/run/user/0/dconf': Permission denied" and
#        a run of dbus "Could not parse server address". Never falls back to 0:
#        that IS the defect, and it installs silently.
#
#   --dry-run  report the user + uid + session-type + chromium + variants it
#              WOULD pick (and the resolved ExecStart + runtime dir) and exit
#              WITHOUT installing (runs unprivileged; spec §9 S-4).
#
# Detection is overridable for off-Pi CI/testing:
#   SPLASH_FORCE_USER       force the Pi user (empty => simulate "can't tell")
#   SPLASH_FORCE_UID        force the numeric uid (empty => simulate "can't tell")
#   SPLASH_FORCE_SESSION    force wayland|x11 (other => simulate "unknown")
#   SPLASH_FORCE_CHROMIUM   force the chromium path (empty => simulate "none")
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

# --- V-4: resolve the Pi user's numeric UID (I-044) ---------------------------
detect_pi_uid() {
  local pi_user="$1"
  if [[ -n "${SPLASH_FORCE_UID+x}" ]]; then
    printf '%s' "$SPLASH_FORCE_UID"   # forced (may be empty => indeterminate)
    return 0
  fi
  # Unknown user => id fails => print nothing => caller aborts loudly. NEVER
  # substitute a default here: /run/user/0 is exactly the I-044 breakage.
  id -u "$pi_user" 2>/dev/null || true
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

# --- V-3: detect the chromium binary path -------------------------------------
detect_chromium_bin() {
  if [[ -n "${SPLASH_FORCE_CHROMIUM+x}" ]]; then
    printf '%s' "$SPLASH_FORCE_CHROMIUM"   # forced (may be empty => indeterminate)
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

CHROMIUM_BIN="$(detect_chromium_bin)"
if [[ -z "$CHROMIUM_BIN" ]]; then
  echo "ERROR: cannot find a chromium binary (looked for chromium-browser then" >&2
  echo "       chromium on PATH). Install chromium, or set SPLASH_FORCE_CHROMIUM" >&2
  echo "       to override. Aborting -- a hardcoded ExecStart=/usr/bin/chromium-" >&2
  echo "       browser dies with 203/EXEC on Trixie (US-428 / Bug 2)." >&2
  exit 1
fi

# V-4 runs LAST of the four probes on purpose: V-1/V-2/V-3 are about whether an
# install is possible at all, and their abort messages are the ones an operator
# needs first. This one is about rendering a correct unit.
PI_UID="$(detect_pi_uid "$PI_USER")"
if [[ ! "$PI_UID" =~ ^[0-9]+$ ]]; then
  echo "ERROR: cannot resolve a numeric UID for user '$PI_USER' (got" >&2
  echo "       '${PI_UID:-<empty>}'). Set SPLASH_FORCE_UID to override." >&2
  echo "       Aborting rather than defaulting -- XDG_RUNTIME_DIR=/run/user/0" >&2
  echo "       is root's runtime dir, installs silently, and is I-044 itself." >&2
  exit 1
fi

BOOT_VARIANT="splash-boot.service.${SESSION_TYPE}"
GRACE_VARIANT="splash-grace.service.${SESSION_TYPE}"

# Render a unit template to stdout with every install-time placeholder resolved:
# __PI_USER__ (V-1), __CHROMIUM_BIN__ (V-3) and __PI_UID__ (V-4). ONE definition
# of the substitution set, shared by the dry-run preview and the real install --
# a second copy is how a placeholder gets added to one path and not the other,
# and an unsubstituted __PI_UID__ ships a literal /run/user/__PI_UID__.
# The chromium path uses a '#' sed delimiter since it contains '/'.
render_unit() {
  sed -e "s/__PI_USER__/${PI_USER}/g" \
      -e "s/__PI_UID__/${PI_UID}/g" \
      -e "s#__CHROMIUM_BIN__#${CHROMIUM_BIN}#g" \
      "$SCRIPT_DIR/$1"
}

echo "==> F-103 splash kit"
echo "    Detected Pi user:      $PI_USER"
echo "    Resolved user UID:     $PI_UID  (V-4 -> XDG_RUNTIME_DIR; I-044)"
echo "    Detected session type: $SESSION_TYPE"
echo "    Chromium binary:       $CHROMIUM_BIN  (V-3 -> ExecStart)"
echo "    Boot variant:          $BOOT_VARIANT  -> $SYSTEMD_DIR/splash-boot.service"
echo "    Grace variant:         $GRACE_VARIANT -> $SYSTEMD_DIR/splash-grace.service"
echo "    Path unit:             splash-grace.path"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "==> DRY RUN -- no changes made. Would copy assets to $INSTALL_DIR,"
  echo "    substitute User=$PI_USER + uid=$PI_UID + chromium=$CHROMIUM_BIN into"
  echo "    the unit templates, install the units, daemon-reload, and enable:"
  echo "    splash-boot.service splash-grace.path"
  echo "    Resolved ExecStart (boot unit):"
  render_unit "$BOOT_VARIANT" | grep -m1 '^ExecStart=' | sed 's/^/      /' || true
  # I-044: print the RESOLVED runtime dir, not just the uid we detected -- the
  # only off-Pi evidence that the substitution actually reaches the template.
  # (The x11 dashboard variant sets none; an absent line is not an error.)
  echo "    Resolved XDG_RUNTIME_DIR (boot unit):"
  render_unit "$BOOT_VARIANT" | grep -m1 '^Environment=XDG_RUNTIME_DIR=' | sed 's/^/      /' || true
  exit 0
fi

# --- real install (root only) -------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must be run as root. Try: sudo ./install.sh" >&2
  exit 1
fi

# Write a rendered template (see render_unit) to the destination unit path.
install_unit() {
  local src="$1" dest="$2"
  render_unit "$src" > "$dest"
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
