################################################################################
# File Name: test_splash_kit.py
# Purpose/Description: Synthetic (CI-runnable) acceptance tests for the F-103
#   splash kit defect fixes + install-time checks (US-396). Covers spec
#   2026-05-26-b103-splash-animation-design.md §9 synthetic criteria S-1..S-4
#   plus the §7 defects (D-1 wrong-SVG, D-2 self-cancel, D-3 X11/Wayland) and
#   the V-1/V-2 install-time user/session detection. Pure static-content greps
#   over the dist kit + a subprocess drive of `install.sh --dry-run` (detection
#   overridable via SPLASH_FORCE_USER / SPLASH_FORCE_SESSION so the report is
#   deterministic off-Pi). No Pi hardware required.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-396) | Initial implementation (F-103 render-side
#               |              | defects D-1/D-2/D-3 + V-1/V-2 install checks).
# 2026-08-29    | Rex (US-604) | Keyring guards: the four splash kiosk units must
#               |              | pin --password-store=basic like the dashboard
#               |              | units, without losing the US-549 stderr flag.
# 2026-10-15    | Rex (US-649-b) | INTENDED ASSERTION CHANGE: the .wayland boot
#               |              | variant orders After=eclipse-compositor.service,
#               |              | not graphical.target; .x11 unchanged.
# 2026-10-16    | Atlas (US-866) | INTENDED ASSERTION CHANGE: the .x11 boot
#               |              | variant orders After=display-manager.service,
#               |              | waits for X access, and OnFailure starts the
#               |              | dashboard. Directives parsed, not substrings.
# 2026-10-19    | Rex (US-649-c) | INTENDED ASSERTION CHANGE (US-649-c): the .wayland
#               |              | boot variant orders After=display-manager.service,
#               |              | not eclipse-compositor.service. New: the three
#               |              | .wayland units carry no BindsTo, one 30 s wayland-0
#               |              | socket gate (executed under a fake sleep), and
#               |              | OnFailure on splash-boot only.
# 2026-10-24    | Rex (US-651-a) | MOVED PIN (US-651-a): the 30 s gates are gone
#               |              | (CIO 2026-10-23, no timed waits). .wayland units:
#               |              | one `test -S` check; .x11 splash-boot: one
#               |              | `xset q`. The socket check runs with no fake sleep.
# 2026-10-24    | Rex (US-869-d) | New: motion-gate.js (Atlas G2) ships in the kit,
#               |              | is not gitignored, and both installers carry it.
# 2026-10-24    | Rex (US-869-e) | New: OFL.txt (the Michroma licence) ships in the
#               |              | kit, is not gitignored, and both installers carry it.
# ================================================================================
################################################################################

"""Static + dry-run acceptance tests for the F-103 splash kit (US-396)."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

# ONE definition of "a flag on this unit's ExecStart", shared with the dashboard
# suite rather than re-implemented here. US-604's contract is that the splash
# units MATCH the dashboard units, so both sides must be read by the same
# tokenizer -- two parsers would let "matching" mean two different things, the
# failure shape US-572 recorded ("if two guards enforce one rule, they must read
# the file the same way"). Established precedent: tests/ui/
# test_shutdown_splash_terminal_reason.py already imports this same helper.
from tests.deploy.test_dashboard_kit import _execStartFlags, _passwordStoreValues

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KIT_DIR = REPO_ROOT / "src" / "pi" / "ui" / "splash"
DASHBOARD_DIR = REPO_ROOT / "src" / "pi" / "ui" / "dashboard"
INSTALL_SH = KIT_DIR / "install.sh"
UNINSTALL_SH = KIT_DIR / "uninstall.sh"


def _read(name: str) -> str:
    return (KIT_DIR / name).read_text(encoding="utf-8")


def _serviceFiles() -> list[Path]:
    """Every splash-* unit/template file shipped in the kit."""
    return sorted(KIT_DIR.glob("splash-*.service*")) + sorted(KIT_DIR.glob("splash-*.path"))


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


# ---------------------------------------------------------------------------
# D-1 / S-1 -- shutdown.html must load the REVERSE svg, not the boot svg.
# ---------------------------------------------------------------------------


def test_shutdownHtml_loadsShutdownSvg_d1():
    """S-1/D-1: shutdown.html embeds splash-shutdown.svg, never splash.svg."""
    html = _read("shutdown.html")
    assert "splash-shutdown.svg" in html
    assert 'data="splash.svg"' not in html


def test_shutdownHtml_wiresStateMachine_renderSide():
    """shutdown.html is a real render page: token placeholder + poll script."""
    html = _read("shutdown.html")
    assert "__SPLASH_TOKEN__" in html
    assert "shutdown-state-poll.js" in html


def test_shutdownStatePollJs_present_and_handlesPhases():
    """shutdown-state-poll.js exists and renders the spec §6 phase contract."""
    js = _read("shutdown-state-poll.js")
    for phase in ("grace", "cancelled", "flushing", "powering_off"):
        assert phase in js, f"shutdown-state-poll.js missing phase {phase!r}"
    assert "/shutdown-state" in js


def test_shutdownStage_shipsHidden_untilTheFirstFlushingRead_us870a():
    """shutdown.html's stage starts visibility:hidden; only the poller reveals it.

    US-870-a moves the reveal from a 1 s pre-roll to the first flushing read,
    but the hidden start is what keeps a blip (grace then cancelled) from
    flashing a frame over the dashboard.
    """
    html = _read("shutdown.html")
    assert re.search(r'<div id="splash-stage" style="visibility:hidden">', html)
    assert "PRE_ROLL" not in html
    assert 'stage.style.visibility = "visible"' in _read("shutdown-state-poll.js")


def test_motionGateJs_presentAndShippedByBothInstallers_us869d():
    """motion-gate.js (the ONE event-will-fire helper) reaches /opt/splash.

    index.html loads it before the poller; an asset the installers do not carry
    leaves a 404 that turns every hand-off into the no-event branch.
    """
    assert (KIT_DIR / "motion-gate.js").is_file()
    assert "motionGate = { willFire" in _read("motion-gate.js")
    assert "motion-gate.js" in INSTALL_SH.read_text(encoding="utf-8")
    deploySh = (REPO_ROOT / "deploy" / "deploy-pi.sh").read_text(encoding="utf-8")
    assert re.search(r'local assets="[^"]*motion-gate\.js', deploySh)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(KIT_DIR / "motion-gate.js")],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert ignored.returncode == 1, "motion-gate.js is gitignored -- it would never ship"


def test_oflLicenceShipsWithTheKitAndBothInstallers_us869e():
    """OFL.txt reaches /opt/splash beside the stylesheet that carries the face.

    styles.css inlines Michroma (US-869-e), and SIL OFL 1.1 requires the licence
    to accompany every copy of the font -- one pattern with the dashboard kit.
    """
    assert (KIT_DIR / "OFL.txt").read_bytes() == (DASHBOARD_DIR / "OFL.txt").read_bytes()
    loop = re.search(
        r"for asset in (.*?); do", INSTALL_SH.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    assert loop and "OFL.txt" in loop.group(1).replace("\\\n", " ").split()
    deploySh = (REPO_ROOT / "deploy" / "deploy-pi.sh").read_text(encoding="utf-8")
    assert re.search(r'local assets="[^"]*splash-shutdown\.svg[^"]*OFL\.txt', deploySh)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(KIT_DIR / "OFL.txt")],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    assert ignored.returncode == 1, "splash OFL.txt is gitignored -- it would never ship"


# ---------------------------------------------------------------------------
# D-2 / S-2 -- the self-cancelling splash-shutdown.service is gone; no unit
#             carries a Conflicts= directive; the grace pair replaces it.
# ---------------------------------------------------------------------------


def test_splashShutdownService_retired_d2():
    """D-2: the original self-cancelling unit is deleted from the kit."""
    assert not (KIT_DIR / "splash-shutdown.service").exists()


def test_noServiceFile_containsConflicts_d2():
    """S-2: no splash-* unit declares Conflicts= (the D-2 root cause)."""
    offenders = [p.name for p in _serviceFiles() if "Conflicts=" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"Conflicts= still present in: {offenders}"


def test_graceUnits_present():
    """The replacement grace pair (.path + wayland/x11 service variants) ships."""
    assert (KIT_DIR / "splash-grace.path").exists()
    assert (KIT_DIR / "splash-grace.service.wayland").exists()
    assert (KIT_DIR / "splash-grace.service.x11").exists()


def test_gracePath_watchesShutdownState():
    """splash-grace.path watches the shutdown-state SSOT + fires the grace svc."""
    path_unit = _read("splash-grace.path")
    assert "PathExists=/run/eclipse-obd/states/shutdown-state" in path_unit
    assert "Unit=splash-grace.service" in path_unit


def test_graceService_loadsShutdownEntry():
    """Both grace variants render the shutdown entry via the token-injecting
    HTTP server (same-origin), Type=simple, JS-driven exit (no pkill)."""
    for variant in ("splash-grace.service.wayland", "splash-grace.service.x11"):
        unit = _read(variant)
        assert "Type=simple" in unit
        assert "shutdown.html" in unit
        assert "127.0.0.1:9899" in unit
        assert "pkill" not in unit


# ---------------------------------------------------------------------------
# D-3 / S-3 -- the original DISPLAY=:0/Before=graphical splash-boot.service is
#             retired; the wayland/x11 variants carry the right display env.
# ---------------------------------------------------------------------------


def test_originalSplashBootService_retired_d3():
    """D-3: the X11/Before=graphical original boot unit is deleted from the kit."""
    assert not (KIT_DIR / "splash-boot.service").exists()


def test_waylandVariants_referenceWayland_s3():
    """S-3: wayland variants use WAYLAND_DISPLAY; x11 variants use DISPLAY=:0."""
    for wl in ("splash-boot.service.wayland", "splash-grace.service.wayland"):
        unit = _read(wl)
        assert "WAYLAND_DISPLAY" in unit
        assert "ozone-platform=wayland" in unit
    for x11 in ("splash-boot.service.x11", "splash-grace.service.x11"):
        unit = _read(x11)
        assert "DISPLAY=:0" in unit


def test_bootVariants_orderAfterGraphical_d3():
    """D-3: variants defer until the display server is up (After=, not Before=).

    The wayland variant no longer orders After=graphical.target (US-649-b: that
    queued the kiosk behind multi-user, 18.73 s on boot 7c6aafaa).
    """
    # INTENDED ASSERTION CHANGE (US-649-c): design A (CIO 2026-10-16) -- lightdm
    # owns the Wayland session too, so the wayland variant orders After= the
    # display manager, as the x11 one does; eclipse-compositor.service is gone.
    wayland = _read("splash-boot.service.wayland")
    waylandAfter = _directiveValues(wayland, "After")
    assert "display-manager.service" in waylandAfter
    assert "eclipse-compositor.service" not in waylandAfter
    assert "graphical.target" not in waylandAfter
    assert _directiveValues(wayland, "Before") == []

    # US-866 INTENDED ASSERTION CHANGE (.x11): the display server is lightdm
    # (display-manager.service), so the x11 variant orders After= IT, not
    # graphical.target, which waits on the Bluetooth bond check. Read the
    # DIRECTIVES, not the text: a substring test passed on a comment naming
    # the old line once that line was gone.
    x11After = _directiveValues(_read("splash-boot.service.x11"), "After")
    assert "display-manager.service" in x11After
    assert "graphical.target" not in x11After
    assert _directiveValues(_read("splash-boot.service.x11"), "Before") == []


def _directiveValues(unit: str, key: str) -> list[str]:
    """Every space-separated value of ``key=`` lines, comments ignored."""
    values: list[str] = []
    for line in unit.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            values.extend(stripped[len(key) + 1:].split())
    return values


def test_x11BootVariant_checksXAccessOnce_us651a():
    """US-866 / US-651-a: the x11 splash checks ONCE that X accepts the user.

    MEASURED boot 3f8c767d (US-866): chromium connected 0.13 s before the
    autologin session's xhost grant, exited 1, and OnSuccess never started the
    dashboard. MOVED PIN (US-651-a): the 150 x 0.2 s poll is gone -- the start
    now waits on the eclipse-x-ready marker the session's autostart writes after
    the grant -- so one `xset q` remains, as the unit's user with no
    XAUTHORITY, exactly as chromium connects. A failure exits non-zero at once
    and OnFailure brings up the dashboard.
    """
    unit = _read("splash-boot.service.x11")
    assert _directiveLines(unit, "ExecStartPre") == ["/usr/bin/xset q"]


def test_x11BootVariant_failedSplashStillStartsDashboard_us866():
    """US-866: a FAILED splash starts the dashboard; success still hands off."""
    unit = _read("splash-boot.service.x11")
    assert _directiveValues(unit, "OnSuccess") == ["eclipse-dashboard.service"]
    assert _directiveValues(unit, "OnFailure") == ["eclipse-dashboard.service"]


# ---------------------------------------------------------------------------
# US-649-c -- design A (CIO 2026-10-16): lightdm's own autologin session hosts
#             labwc, so the three .wayland kiosk units no longer bind to
#             eclipse-compositor.service. They order After= the display manager.
# US-651-a -- MOVED PIN: the 30 s wayland-0 poll is replaced by ONE `test -S`
#             check (CIO 2026-10-23, no timed waits); eclipse-kiosk-socket.path
#             starts the kiosk when the socket appears.
# ---------------------------------------------------------------------------

# Unit name (the template file name minus '.service.wayland') -> template path.
WAYLAND_UNITS = {
    "splash-boot": KIT_DIR / "splash-boot.service.wayland",
    "splash-grace": KIT_DIR / "splash-grace.service.wayland",
    "dashboard": DASHBOARD_DIR / "dashboard.service.wayland",
}

# The other After= units each template already carried, which must survive.
WAYLAND_KEPT_AFTER = {
    "splash-boot": ["eclipse-states-http.service", "eclipse-boot-state.service"],
    "splash-grace": ["eclipse-states-http.service"],
    "dashboard": ["eclipse-states-http.service"],
}

UID_TOKEN_RUNTIME_DIR = "/run/user/__PI_UID__"


# MOVED PIN (US-651-a): one check, the same for all three units.
WAYLAND_SOCKET_CHECK = "/usr/bin/test -S /run/user/__PI_UID__/wayland-0"


def _directiveLines(unit: str, key: str) -> list[str]:
    """The whole value of every ``key=`` line, comments ignored."""
    return [
        line.strip()[len(key) + 1 :]
        for line in unit.splitlines()
        if line.strip().startswith(f"{key}=")
    ]


@pytest.mark.parametrize("name", sorted(WAYLAND_UNITS))
def test_waylandUnit_noBindsToAndNoCompositor_us649c(name: str):
    """No BindsTo= line, and the old compositor unit is not named anywhere."""
    text = WAYLAND_UNITS[name].read_text(encoding="utf-8")
    assert _directiveValues(text, "BindsTo") == []
    assert "BindsTo" not in text
    assert "eclipse-compositor" not in text


@pytest.mark.parametrize("name", sorted(WAYLAND_UNITS))
def test_waylandUnit_ordersAfterTheDisplayManager_us649c(name: str):
    """After= names display-manager.service and keeps its other units."""
    after = _directiveValues(WAYLAND_UNITS[name].read_text(encoding="utf-8"), "After")
    assert "display-manager.service" in after
    for kept in WAYLAND_KEPT_AFTER[name]:
        assert kept in after, f"{name}: After= lost {kept}"


@pytest.mark.parametrize("name", sorted(WAYLAND_UNITS))
def test_waylandUnit_hasExactlyTheOneSocketGate_us649c(name: str):
    """Exactly one ExecStartPre, the one-shot wayland-0 check, uid left as the token."""
    pre = _directiveLines(WAYLAND_UNITS[name].read_text(encoding="utf-8"), "ExecStartPre")
    assert pre == [WAYLAND_SOCKET_CHECK]
    assert "/run/user/1000" not in pre[0]  # rendered by install.sh, never literal


@pytest.mark.parametrize("name", sorted(WAYLAND_UNITS))
def test_waylandUnit_onFailureOnSplashBootOnly_us649c(name: str):
    """splash-boot gains OnFailure (parity with .x11); its OnSuccess is unchanged."""
    text = WAYLAND_UNITS[name].read_text(encoding="utf-8")
    if name == "splash-boot":
        assert _directiveValues(text, "OnFailure") == ["eclipse-dashboard.service"]
        assert _directiveValues(text, "OnSuccess") == ["eclipse-dashboard.service"]
    else:
        assert _directiveValues(text, "OnFailure") == []


def _runWaylandCheck(runtimeDir: Path) -> subprocess.CompletedProcess[str]:
    """Run splash-boot's one-shot socket check against ``runtimeDir``.

    The template's __PI_UID__ runtime dir is swapped for a temp dir; the check
    is run by name (``test``), as the shell resolves it on any box.
    """
    pre = _directiveLines(WAYLAND_UNITS["splash-boot"].read_text(encoding="utf-8"), "ExecStartPre")
    argv = shlex.split(pre[0])
    assert argv[0] == "/usr/bin/test"
    assert UID_TOKEN_RUNTIME_DIR in argv[-1]
    argv = ["test", *argv[1:-1], argv[-1].replace(UID_TOKEN_RUNTIME_DIR, runtimeDir.as_posix())]
    return subprocess.run(
        ["sh", "-c", shlex.join(argv)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=dict(os.environ),
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_waylandCheck_runsAgainstTheSocket_us651a(tmp_path: Path):
    """
    Given: a runtime dir without, then with, a wayland-0 socket
    When:  the splash-boot check runs
    Then:  absent -> non-zero at once (no retry); present -> exit 0.

    MOVED PIN (US-651-a): replaces the 150-poll run under a fake sleep. The
    absent half runs everywhere. The present half needs a real AF_UNIX socket
    (``-S``, not ``-e``), which a Windows CPython cannot make, so there it is
    skipped AFTER the absent half has asserted.
    """
    for sub in ("present", "absent"):
        (tmp_path / sub).mkdir()

    result = _runWaylandCheck(tmp_path / "absent")
    assert result.returncode == 1

    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("absent case passed; the socket-present case needs AF_UNIX sockets")
    sock = socket.socket(socket.AF_UNIX)  # type: ignore[attr-defined]
    try:
        sock.bind(str(tmp_path / "present" / "wayland-0"))
        result = _runWaylandCheck(tmp_path / "present")
    finally:
        sock.close()
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# V-1 / V-2 / S-4 -- install.sh detects the Pi user + session type, picks the
#                   matching variants, fails loudly on the unknowns, and
#                   --dry-run reports its picks without installing.
# ---------------------------------------------------------------------------


def _runInstall(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    # V-3 (US-428): the installer now also resolves a chromium binary and aborts
    # loudly if none is found (mirrors the V-1/V-2 gates). These off-Pi
    # user/session previews are orthogonal to the browser path, and a dev box has
    # no chromium -- default it so the preview reaches the report, unless a test
    # overrides SPLASH_FORCE_CHROMIUM explicitly (e.g. to simulate "none").
    env.setdefault("SPLASH_FORCE_CHROMIUM", "/usr/bin/chromium")
    # V-4 (US-550 / I-044): the installer also resolves the Pi user's numeric uid
    # via `id -u` for XDG_RUNTIME_DIR, and aborts if it can't. The forced users
    # here ("tunerbox") do not exist on a dev box, so default it for the same
    # reason as the chromium path above -- unless a test overrides it explicitly.
    env.setdefault("SPLASH_FORCE_UID", "1000")
    return subprocess.run(
        ["bash", str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_reportsUserAndSession_s4():
    """S-4/V-1/V-2: --dry-run reports the user + session it WOULD pick, no install."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "wayland"},
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "tunerbox" in out
    assert "wayland" in out
    # It must name the variant it would pick so the report is actionable.
    assert "splash-boot.service.wayland" in out
    # Dry run never touches the live system.
    assert "DRY" in out.upper()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_picksX11Variant_whenSessionX11():
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "x11"},
    )
    assert result.returncode == 0, result.stderr
    assert "splash-boot.service.x11" in result.stdout


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_failsLoudly_onUnknownSession_v2():
    """V-2: an unresolvable session type aborts loudly (no X11 default-guess)."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "mystery"},
    )
    assert result.returncode != 0
    assert "session" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_failsLoudly_onIndeterminateUser_v1():
    """V-1: an unresolvable Pi user aborts loudly."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "", "SPLASH_FORCE_SESSION": "wayland",
                   "SPLASH_USER_HOME_GLOB": "/nonexistent-home-root/*"},
    )
    assert result.returncode != 0
    assert "user" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_doesNotRequireRoot():
    """--dry-run must run unprivileged (it only reports); the root gate is for
    the real install path only."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "wayland"},
    )
    assert "must be run as root" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# uninstall.sh -- removes the grace pair + legacy units (migration cleanup).
# ---------------------------------------------------------------------------


def test_uninstall_removesGraceAndLegacyUnits():
    sh = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "splash-grace.service" in sh
    assert "splash-grace.path" in sh
    # Legacy units are still swept so an upgrade-in-place leaves nothing behind.
    assert "splash-shutdown.service" in sh


# ---------------------------------------------------------------------------
# US-604 -- the splash kiosks must pin the OSCrypt backend, like the dashboard.
#
# US-522 (reopen) added `--password-store=basic` to the DASHBOARD kiosk units to
# stop a recurring gcr-prompter "Authentication Required" dialog painting over
# the kiosk. With no `--password-store`, chromium auto-detects a Linux backend
# and picks the GNOME keyring for its OSCrypt "Safe Storage" key; this Pi's
# Default keyring is password-protected and under PASSWORDLESS auto-login
# `pam_gnome_keyring` never unlocks it, so the collection stays LOCKED and the
# unlock request reaches gcr-prompter. The four SPLASH units launch chromium
# through the SAME Debian wrapper and carried no such flag.
#
# BE HONEST ABOUT THE EXPOSURE -- it is LATENT, not active, and that is what
# sized this story an S rather than a defect fix. gcr-prompter fired
# 05:43:09 / 08:33:52 / 08:52:23 on 2026-08-03, every one ~9h AFTER splash-boot
# exited, and NONE inside the splash's own 9.806s window. The HEALTHY splash
# does not prompt because it exits too fast. It becomes reachable on a DEGRADED
# boot, where the splash deliberately STAYS UP (no window.close hand-off to the
# dashboard) -- i.e. precisely when an operator is trying to read a fault report
# off the panel, and precisely when an auth dialog over it costs the most.
# ---------------------------------------------------------------------------

_PASSWORD_STORE_FLAG = "--password-store=basic"
_STDERR_LOGGING_FLAG = "--enable-logging=stderr"
_DASHBOARD_UNITS = ("dashboard.service.wayland", "dashboard.service.x11")
_GRACE_UNITS = ("splash-grace.service.wayland", "splash-grace.service.x11")
_EXPECTED_SPLASH_KIOSK_UNITS = [
    "splash-boot.service.wayland",
    "splash-boot.service.x11",
    "splash-grace.service.wayland",
    "splash-grace.service.x11",
]


def _splashKioskUnits() -> list[str]:
    """Every splash chromium unit template, DISCOVERED rather than hardcoded.

    Derived from the kit directory so a splash variant added next sprint is
    covered the day it lands. US-573 recorded the opposite shape as a
    self-renewing debt: a hardcoded inventory silently stops covering the newest
    unit, and under-verification looks exactly like success.
    """
    return sorted(p.name for p in KIT_DIR.glob("splash-*.service.*"))


def test_splashKioskUnitDiscovery_isNotVacuous_us604():
    """The guard's own INPUT, asserted before anything loops over it.

    Every US-604 assertion below is a `for unit in _splashKioskUnits()` loop, so
    a glob that silently returned nothing would make all of them pass while
    verifying NOTHING -- the inert-guard shape this project has catalogued
    repeatedly. Pinning the names (not merely a count) also makes a NEW variant
    an explicit acknowledgement rather than a silent expansion.
    """
    assert _splashKioskUnits() == _EXPECTED_SPLASH_KIOSK_UNITS, (
        "splash kiosk unit inventory changed. A NEW variant is already covered "
        "by the guards below -- add it here to acknowledge it. A MISSING one "
        "means those guards verify less than they claim to."
    )


def test_splashUnits_carryPasswordStoreBasic_us604():
    """AC-5 / VC-1: all four splash variants pin the OSCrypt backend to `basic`.

    Compared by VALUE, not by flag presence: `--password-store` is a valued
    switch, so a substring check would happily accept `--password-store=gnome`
    -- which is the broken configuration this story exists to prevent, not a fix.
    """
    for unit in _splashKioskUnits():
        values = _passwordStoreValues(_read(unit))
        assert values == ["basic"], (
            f"{unit}: ExecStart must carry exactly {_PASSWORD_STORE_FLAG} "
            f"(found {values!r}) -- an unset password store lets chromium pick "
            "the locked GNOME keyring and paint an auth dialog over a splash "
            "that a DEGRADED boot leaves on screen"
        )


def test_splashUnits_matchTheDashboardKeyringBackend_us604():
    """VC-1 says "matching the dashboard units", so assert the RELATIONSHIP
    rather than re-hardcoding the literal on this side too.

    Derived from the dashboard units at run time: if US-522's backend choice is
    ever revised there, the splash units either follow or this goes red. Two
    independently hardcoded copies of one decision are free to drift into
    silently disagreeing about the same OSCrypt question.
    """
    dashboardValues = {
        value
        for unit in _DASHBOARD_UNITS
        for value in _passwordStoreValues((DASHBOARD_DIR / unit).read_text(encoding="utf-8"))
    }
    # Premise check: this test is only meaningful while the dashboard still
    # carries the fix it is being compared against (US-522 must not have
    # regressed out from under it).
    assert dashboardValues, "no --password-store on the dashboard units -- US-522 regressed"
    assert len(dashboardValues) == 1, f"dashboard variants disagree: {dashboardValues!r}"
    expected = dashboardValues.pop()
    for unit in _splashKioskUnits():
        assert _passwordStoreValues(_read(unit)) == [expected], (
            f"{unit}: splash must match the dashboard OSCrypt backend "
            f"({expected!r}); they launch the same chromium through the same wrapper"
        )


def test_splashUnits_neverSelectKeyringBackedPasswordStore_us604():
    """The awkward direction: no variant may select a LOCKED backend.

    `gnome` / `gnome-libsecret` / `kwallet*` all route through a collection that
    passwordless auto-login leaves locked -- i.e. they re-open the defect while
    still technically "having a --password-store flag".
    """
    for unit in _splashKioskUnits():
        for value in _passwordStoreValues(_read(unit)):
            assert value == "basic", f"{unit}: --password-store={value} re-opens the keyring popup"


def test_splashGraceUnits_keepLoadBearingStderrLogging_us604():
    """The adjacent-line hazard, and why "match the dashboard units" must NOT be
    read as "make the two flag sets identical".

    The grace units carry `--enable-logging=stderr`, which US-549 (I-043) makes
    LOAD-BEARING: shutdown-state-poll.js logs its terminal reason to the console
    on every exit, and chromium DISCARDS console output without that flag. (This
    used to say the dashboard kiosk "deliberately carries NO logging flag". That
    went stale: ARCH-014 put it on the X11 dashboard, and US-866 on the Wayland
    one and both boot splashes. The point stands: the flag is load-bearing here,
    not a debug leftover.) Both halves are asserted on one pass so a revert aimed
    at either cannot quietly take the other with it (the US-536 lesson).
    """
    for unit in _GRACE_UNITS:
        flags = _execStartFlags(_read(unit))
        assert _STDERR_LOGGING_FLAG in flags, (
            f"{unit}: lost the US-549/I-043 terminal-reason logging -- it is "
            "load-bearing on the grace units and is NOT a debug leftover to be "
            "tidied away while aligning them with the dashboard"
        )
        assert _PASSWORD_STORE_FLAG in flags, f"{unit}: lost the US-604 keyring fix"


def test_splashUnits_carryNoRemoteDebuggingPort_us604():
    """Do not import the live box's OTHER debug flags along with the fix.

    The hand-patched unit on the Pi carried `--remote-debugging-port=9222` right
    beside Atlas's `--password-store=basic`. An open DevTools port on a
    car-mounted kiosk is unauthenticated full-page control. Both splash unit
    headers already refuse it in prose (US-522); this asserts the refusal, since
    prose is not a guard. The dashboard suite fences the same flag.
    """
    for unit in _splashKioskUnits():
        offenders = [f for f in _execStartFlags(_read(unit)) if f.startswith("--remote-debugging-")]
        assert offenders == [], f"{unit}: kiosk must not expose DevTools ({offenders!r})"


def test_bootPathKioskUnits_logToTheJournal_us866():
    """US-866: every BOOT-PATH chromium (both splashes, both dashboards) passes
    --enable-logging=stderr, so its "[kiosk] first-frame" line and its errors
    reach the journal in BOTH display modes. The Wayland dashboard was written
    without it, which left Wayland mode unmeasurable against the X11 baseline
    (ADR ARCH-016 11.4).
    """
    units = [
        (KIT_DIR, "splash-boot.service.x11"),
        (KIT_DIR, "splash-boot.service.wayland"),
        (DASHBOARD_DIR, "dashboard.service.x11"),
        (DASHBOARD_DIR, "dashboard.service.wayland"),
    ]
    for directory, name in units:
        flags = _execStartFlags((directory / name).read_text(encoding="utf-8"))
        assert _STDERR_LOGGING_FLAG in flags, f"{name}: chromium is not heard by the journal"
