################################################################################
# File Name: test_kiosk_runtime_dir.py
# Purpose/Description: I-044 guard -- the chromium kiosk units must not derive
#                      XDG_RUNTIME_DIR from a systemd %-specifier. On the live Pi
#                      `Environment=XDG_RUNTIME_DIR=/run/user/%U` under
#                      `User=mcornelison` (uid 1000) resolved to /run/user/0 --
#                      root's runtime dir, which the kiosk user cannot write:
#                      "unable to create directory '/run/user/0/dconf': Permission
#                      denied" x3 plus a run of dbus "Could not parse server
#                      address" in the boot dc7a3848 journal. The uid is now
#                      resolved at INSTALL time and substituted as __PI_UID__,
#                      exactly like __PI_USER__ (V-1) and __CHROMIUM_BIN__ (V-3).
#                      Two halves, both asserted: the DECLARATION (templates carry
#                      the placeholder, no specifier) and the MECHANISM (each
#                      install.sh actually resolves + substitutes it, and fails
#                      loudly rather than falling back to 0).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Rex (US-550) | Initial implementation (Sprint 73 V0.29.28):
#               |              | I-044 %U -> __PI_UID__ guard, tokenized.
# ================================================================================
################################################################################

"""Deploy-smoke tests for the kiosk units' XDG_RUNTIME_DIR (I-044 / US-550).

The assertion here is an ABSENCE (no ``%``-specifier in the value), and an
absence assertion is only as good as the parser that feeds it -- a parser that
silently returns ``{}`` makes every such test pass vacuously (the US-548
lesson). So ``_environmentAssignments`` carries its own self-test with a
POSITIVE control: it must still FIND ``/run/user/%U`` when a unit genuinely
declares it, and must NOT find it when only a comment mentions it.

That second direction is not hypothetical. The fixed units explain in their
headers *why* ``%U`` is wrong, so those files contain the literal string ``%U``
on purpose. A naive ``"%U" not in text`` check would fail on a correct file --
the US-522 substring lesson, in its false-positive direction.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPLASH_KIT = REPO_ROOT / "specs" / "UI" / "dist" / "splash-pi"
DASH_KIT = REPO_ROOT / "specs" / "UI" / "dist" / "dashboard-pi"
SPLASH_INSTALL = SPLASH_KIT / "install.sh"
DASH_INSTALL = DASH_KIT / "install.sh"

# The install-time seam this story adds, and the only value the templates may
# carry. Named once -- every assertion below reads from here.
UID_PLACEHOLDER = "__PI_UID__"
RUNTIME_DIR_KEY = "XDG_RUNTIME_DIR"
EXPECTED_RUNTIME_DIR = f"/run/user/{UID_PLACEHOLDER}"

# The defect, verbatim from the units as they shipped before US-550. Kept as a
# named constant so the positive control below plants the REAL string.
DEFECTIVE_RUNTIME_DIR = "/run/user/%U"

# systemd specifier: '%' followed by a letter (%%, a literal percent, is not one).
_SPECIFIER_RE = re.compile(r"%[A-Za-z]")

# Expected count of kiosk unit templates across both kits: splash-boot,
# splash-grace and dashboard, each in an x11 and a wayland variant. Pinned so a
# broken discovery glob cannot make the per-unit assertions vacuous.
EXPECTED_UNIT_TEMPLATE_COUNT = 6


def _kioskUnitTemplates() -> list[Path]:
    """Every kiosk unit template shipped by the two kits.

    DISCOVERED, not listed. I-044's own "affected files" list named six units,
    but only five declare XDG_RUNTIME_DIR (dashboard.service.x11 never set it) --
    which is precisely why the issue says "confirm the set, do not assume this
    list is complete". Discovery also means a unit added later is covered the day
    it lands rather than the day someone remembers to extend a literal list.
    """
    units: list[Path] = []
    for kit in (SPLASH_KIT, DASH_KIT):
        units.extend(sorted(kit.glob("*.service.x11")))
        units.extend(sorted(kit.glob("*.service.wayland")))
    return sorted(units)


def _logicalLines(unitText: str) -> list[str]:
    """Comment-stripped, continuation-joined lines of a systemd unit.

    Comments go FIRST so a header paragraph discussing a directive can never be
    read as that directive (the US-501/US-513 prose trap). Continuations are then
    joined so a directive split across lines still parses as one assignment.
    """
    kept: list[str] = []
    for raw in unitText.splitlines():
        stripped = raw.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            continue
        kept.append(raw)

    joined: list[str] = []
    pending = ""
    for line in kept:
        stripped = line.strip()
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        joined.append((pending + stripped).strip())
        pending = ""
    if pending:
        joined.append(pending.strip())
    return joined


def _environmentAssignments(unitText: str) -> dict[str, str]:
    """Parse a unit's ``Environment=`` assignments into {NAME: value}.

    Later assignments win, matching systemd (a repeated name overrides). Values
    are returned RAW -- unresolved specifiers included -- because an unresolved
    specifier is exactly what these tests are looking for.
    """
    assignments: dict[str, str] = {}
    for line in _logicalLines(unitText):
        if not line.startswith("Environment="):
            continue
        payload = line[len("Environment=") :].strip()
        # Values here are simple paths; split on whitespace for the multi-pair
        # form (Environment=A=1 B=2), keeping surrounding quotes off the value.
        for token in payload.split():
            if "=" not in token:
                continue
            name, _, value = token.partition("=")
            assignments[name.strip()] = value.strip().strip('"').strip("'")
    return assignments


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _runInstaller(
    script: Path,
    kitEnvPrefix: str,
    *,
    uid: str | None,
    session: str = "wayland",
) -> subprocess.CompletedProcess:
    """Run a kit install.sh --dry-run off-Pi with every FORCE_* override set.

    ``uid=None`` sets FORCE_UID EMPTY -- the "id -u told us nothing" case, which
    must abort rather than emit a unit. Session defaults to wayland because both
    wayland variants declare XDG_RUNTIME_DIR (dashboard.service.x11 does not), so
    the rendered preview is guaranteed to carry the line under test.
    """
    env = dict(os.environ)
    env[f"{kitEnvPrefix}_FORCE_USER"] = "pi"
    env[f"{kitEnvPrefix}_FORCE_SESSION"] = session
    env[f"{kitEnvPrefix}_FORCE_CHROMIUM"] = "/opt/test/chromium"
    env[f"{kitEnvPrefix}_FORCE_UID"] = "" if uid is None else uid
    return subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


# ----------------------------------------------------------------------------
# Group 0: the parser itself (positive control -- guards against a vacuous pass)
# ----------------------------------------------------------------------------


def test_environmentParser_findsASpecifierValue_positiveControl():
    """The parser must FIND `/run/user/%U` when a unit really declares it.

    Without this control every absence assertion below would pass on a parser
    that returned nothing at all -- which is how an inverted guard rots silently
    (US-548, mutation C).
    """
    planted = "\n".join(
        [
            "[Service]",
            "Environment=DISPLAY=:0",
            f"Environment={RUNTIME_DIR_KEY}={DEFECTIVE_RUNTIME_DIR}",
        ]
    )
    parsed = _environmentAssignments(planted)
    assert parsed.get(RUNTIME_DIR_KEY) == DEFECTIVE_RUNTIME_DIR, (
        "the Environment= parser failed to see a genuinely declared "
        f"{RUNTIME_DIR_KEY}={DEFECTIVE_RUNTIME_DIR} -- every absence assertion "
        "in this file would pass vacuously"
    )
    assert parsed.get("DISPLAY") == ":0", "the parser must read sibling assignments too"


def test_environmentParser_ignoresCommentedDirectives():
    """A header paragraph explaining why `%U` is wrong must NOT read as a
    declaration -- otherwise the fix's own documentation fails the guard.
    """
    documented = "\n".join(
        [
            "# The units used to say:",
            f"#   Environment={RUNTIME_DIR_KEY}={DEFECTIVE_RUNTIME_DIR}",
            "# ...which resolved to /run/user/0 on the live Pi (I-044).",
            "[Service]",
            "Environment=DISPLAY=:0",
        ]
    )
    parsed = _environmentAssignments(documented)
    assert RUNTIME_DIR_KEY not in parsed, (
        f"a commented-out {RUNTIME_DIR_KEY} was parsed as a live assignment -- "
        "the guard would reject a correct unit that documents the defect"
    )


# ----------------------------------------------------------------------------
# Group 1: the unit templates (declaration)
# ----------------------------------------------------------------------------


def test_kioskUnitTemplates_discoveryIsComplete():
    """Discovery must find every kiosk unit template.

    Pins the per-unit assertions below against a glob that silently stops
    matching: an empty list passes an absence check without reading a file.
    """
    units = _kioskUnitTemplates()
    assert len(units) == EXPECTED_UNIT_TEMPLATE_COUNT, (
        f"expected {EXPECTED_UNIT_TEMPLATE_COUNT} kiosk unit templates across "
        f"the two kits, discovered {len(units)}: {[u.name for u in units]}"
    )


def test_kioskUnits_runtimeDirIsNeverSpecifierDerived_i044():
    """No kiosk unit may derive XDG_RUNTIME_DIR from a systemd %-specifier.

    Grounded on the live Pi (I-044): with `User=mcornelison` (uid 1000),
    `systemctl show splash-boot.service -p Environment` reported
    `XDG_RUNTIME_DIR=/run/user/0`, and `ls -d /run/user/*` showed the real dir was
    /run/user/1000. Asserted against the PARSED value, so the header comments
    that explain this are not mistaken for the directive.
    """
    declaring = []
    for tpl in _kioskUnitTemplates():
        value = _environmentAssignments(tpl.read_text(encoding="utf-8")).get(RUNTIME_DIR_KEY)
        if value is None:
            continue
        declaring.append(tpl.name)
        assert not _SPECIFIER_RE.search(value), (
            f"{tpl.name} sets {RUNTIME_DIR_KEY}={value} -- a %-specifier does not "
            f"resolve from User= here, it resolved to /run/user/0 on the live Pi "
            f"(I-044). Use {EXPECTED_RUNTIME_DIR}, substituted at install time."
        )
    assert len(declaring) >= 4, (
        f"only {len(declaring)} unit(s) declare {RUNTIME_DIR_KEY} ({declaring}) -- "
        "too few for this guard to mean anything; expected the four splash "
        "variants plus dashboard.service.wayland"
    )


def test_kioskUnits_runtimeDirUsesTheInstallTimeUidSeam():
    """Where a kiosk unit declares XDG_RUNTIME_DIR it must be exactly
    ``/run/user/__PI_UID__`` -- the install-time seam, not a specifier and not a
    hardcoded uid (the kit deliberately does not hardcode the Pi user either).
    """
    for tpl in _kioskUnitTemplates():
        value = _environmentAssignments(tpl.read_text(encoding="utf-8")).get(RUNTIME_DIR_KEY)
        if value is None:
            continue
        assert value == EXPECTED_RUNTIME_DIR, (
            f"{tpl.name} sets {RUNTIME_DIR_KEY}={value}; expected "
            f"{EXPECTED_RUNTIME_DIR} so install.sh can substitute the real uid"
        )


def test_waylandKioskUnits_stillDeclareARuntimeDir():
    """Both Wayland variants must keep XDG_RUNTIME_DIR -- it is load-bearing
    there (the compositor socket lives at $XDG_RUNTIME_DIR/wayland-0). "Fixing"
    I-044 by deleting the line would take the Wayland session down with it.
    """
    for tpl in _kioskUnitTemplates():
        if not tpl.name.endswith(".wayland"):
            continue
        parsed = _environmentAssignments(tpl.read_text(encoding="utf-8"))
        assert RUNTIME_DIR_KEY in parsed, (
            f"{tpl.name} no longer declares {RUNTIME_DIR_KEY} -- chromium cannot "
            f"find the wayland-0 socket without it"
        )


# ----------------------------------------------------------------------------
# Group 2: the installers (mechanism)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script,var",
    [(SPLASH_INSTALL, "SPLASH_FORCE_UID"), (DASH_INSTALL, "DASHBOARD_FORCE_UID")],
)
def test_installer_resolvesAndSubstitutesTheUid(script: Path, var: str):
    """Static: each installer must resolve the uid with `id -u`, substitute
    __PI_UID__, and expose a FORCE_UID override for off-Pi testing.

    The placeholder alone is not a fix -- an unsubstituted template ships
    ``/run/user/__PI_UID__`` literally, which is worse than /run/user/0.
    """
    text = script.read_text(encoding="utf-8")
    assert UID_PLACEHOLDER in text, f"{script.name} must substitute {UID_PLACEHOLDER}"
    assert "id -u" in text, f"{script.name} must resolve the uid with `id -u`"
    assert var in text, f"{script.name} must honour the {var} override (off-Pi testing)"


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
@pytest.mark.parametrize(
    "script,prefix",
    [(SPLASH_INSTALL, "SPLASH"), (DASH_INSTALL, "DASHBOARD")],
)
def test_installerDryRun_rendersTheResolvedRuntimeDir(script: Path, prefix: str):
    """End-to-end: --dry-run must render the real template through the real sed
    and show the resolved runtime dir -- the observable that proves the
    substitution runs, not merely that the placeholder is spelled right.
    """
    forcedUid = "4242"
    result = _runInstaller(script, prefix, uid=forcedUid)
    assert result.returncode == 0, f"dry-run should exit 0; stderr={result.stderr}"
    assert f"{RUNTIME_DIR_KEY}=/run/user/{forcedUid}" in result.stdout, (
        f"dry-run must render {RUNTIME_DIR_KEY}=/run/user/{forcedUid}; got:\n{result.stdout}"
    )
    assert UID_PLACEHOLDER not in result.stdout, (
        f"the {UID_PLACEHOLDER} placeholder must be substituted, not printed raw"
    )
    assert DEFECTIVE_RUNTIME_DIR not in result.stdout, (
        "the rendered unit must not carry the %U specifier (I-044)"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
@pytest.mark.parametrize(
    "script,prefix",
    [(SPLASH_INSTALL, "SPLASH"), (DASH_INSTALL, "DASHBOARD")],
)
def test_installer_failsLoudWhenTheUidIsUnresolvable(script: Path, prefix: str):
    """An unresolvable uid must abort (exit 1), never fall back to 0.

    Falling back would re-create I-044 exactly -- and silently, since the unit
    would install and chromium would still start. Mirrors the V-1/V-2/V-3
    fail-loud discipline.
    """
    result = _runInstaller(script, prefix, uid=None)
    assert result.returncode == 1, (
        f"an unresolvable uid must abort with exit 1; got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "UID" in combined or "uid" in combined, (
        "the abort message must name the uid it could not resolve"
    )
    assert "/run/user/0" not in result.stdout, (
        "the installer must not report a /run/user/0 fallback -- that IS the defect"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
@pytest.mark.parametrize(
    "script,prefix",
    [(SPLASH_INSTALL, "SPLASH"), (DASH_INSTALL, "DASHBOARD")],
)
def test_installer_failsLoudWhenIdUItselfFails(script: Path, prefix: str):
    """The REAL detection path must fail loud too -- FORCE_UID deliberately unset.

    The test above forces the uid EMPTY, which short-circuits at the override and
    never runs `id -u` at all. This one names a user that cannot exist, so the
    installer runs the genuine probe and `id -u` genuinely fails -- the actual
    production failure mode (a user that vanished, or a mistyped FORCE_USER).

    Both are needed: a mutation adding `|| echo 0` to the probe leaves the
    forced-empty test GREEN and is caught only here. That fallback would install
    a working-looking unit pointed at root's runtime dir -- I-044, silently
    reintroduced by a one-word "robustness" edit.
    """
    env = dict(os.environ)
    env[f"{prefix}_FORCE_USER"] = "nosuchuser__us550"
    env[f"{prefix}_FORCE_SESSION"] = "wayland"
    env[f"{prefix}_FORCE_CHROMIUM"] = "/opt/test/chromium"
    env.pop(f"{prefix}_FORCE_UID", None)  # exercise the real `id -u` probe
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 1, (
        f"a failing `id -u` must abort with exit 1, never fall back to 0; got "
        f"{result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "/run/user/0" not in result.stdout, (
        "the installer must not render a /run/user/0 unit when the uid is unknown"
    )
