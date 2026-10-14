################################################################################
# File Name: test_kiosk_unit_single_source.py
# Purpose/Description: US-884 [F-139] -- the running kiosk unit's name has ONE
#   source, unit_manifest.KIOSK_UNIT, and nothing else spells it on its own.
#
#   Before US-884 the name was a separate literal in ~14 runtime places, so a
#   DRM kiosk under another name (Sprint 99) would have run UNSHED at power
#   loss -- and with the dashboard up the box dies 0.678 s after a cut
#   (ARCH-031). Three properties are pinned here:
#     1. the Python consumers (load_shed, kiosk_watchdog, panel_liveness) DERIVE
#        their defaults from the constant, and follow it when it changes;
#     2. with no override those defaults are exactly today's values, so the car
#        behaves identically (dev d78ed143);
#     3. every non-Python file that names the kiosk names exactly the constant,
#        so a rename that misses one fails the suite and names the file.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-13    | Ralph (Rex)  | Initial implementation (US-884).
# ================================================================================
################################################################################

"""US-884: one kiosk unit name, read by the shed, the watchdogs and the splash."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Today's kiosk unit (dev d78ed143). Restated ONCE, as the fixture the
# no-override defaults are measured against -- not a second production source.
TODAYS_KIOSK_UNIT = "eclipse-dashboard.service"

# A name nothing in the repo uses, standing in for Sprint 99's DRM kiosk.
TEST_KIOSK_UNIT = "eclipse-us884-probe.service"


# ---------------------------------------------------------------------------
# The non-Python pin
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KioskSlot:
    """Where one file names the kiosk unit.

    Attributes:
        path: Repo-relative path of the file.
        pattern: Regex whose group 1 captures the kiosk name at a load-bearing
            spot. Anchored on the CONTEXT, never on the name, so a stale name is
            still captured -- and reported -- after a rename.
        bareStem: True where the file uses the name without ``.service``.
    """

    path: str
    pattern: str
    bareStem: bool = False


KIOSK_SLOTS: tuple[KioskSlot, ...] = (
    KioskSlot("deploy/eclipse-kiosk-watchdog.service", r"--unit\s+(\S+)"),
    KioskSlot("deploy/eclipse-panel-liveness.service", r"--unit\s+(\S+)"),
    KioskSlot(
        "deploy/polkit-rules/51-eclipse-service-control.rules",
        r"^//\s+(\S+)\s+-> start / stop / restart\s+\(A-8",
    ),
    KioskSlot(
        "deploy/polkit-rules/51-eclipse-service-control.rules",
        r'unit == "([^"]+)"\)\s*\{\s*//\s*kiosk',
    ),
    KioskSlot("src/pi/ui/splash/splash-boot.service.x11", r"^OnSuccess=(\S+)"),
    KioskSlot("src/pi/ui/splash/splash-boot.service.wayland", r"^OnSuccess=(\S+)"),
    KioskSlot("src/pi/ui/dashboard/install.sh", r'"\$SYSTEMD_DIR/([^"]+)"'),
    KioskSlot("src/pi/ui/dashboard/uninstall.sh", r"^systemctl (?:stop|disable) (\S+)"),
    KioskSlot("src/pi/ui/dashboard/uninstall.sh", r'^rm -f "\$SYSTEMD_DIR/([^"]+)"'),
    KioskSlot("src/pi/ui/dashboard/carousel.js", r'"([^"]+)": \["stop", "restart"\]'),
    KioskSlot("src/pi/ui/dashboard/carousel.js", r'doAction\("([^"]+)", "stop"\)'),
    KioskSlot("tools/imu/drive_console.py", r'^DASHBOARD = "([^"]+)"', bareStem=True),
)


def _expectedName(kioskUnit: str, slot: KioskSlot) -> str:
    """The exact spelling ``slot`` must carry for ``kioskUnit``."""
    return kioskUnit.removesuffix(".service") if slot.bareStem else kioskUnit


def findStaleKioskNames(kioskUnit: str) -> list[str]:
    """Return one problem line per file that does not name exactly ``kioskUnit``.

    Args:
        kioskUnit: The manifest's kiosk unit name to check every file against.

    Returns:
        ``"<path>: <found>"`` for every captured name that differs, and
        ``"<path>: no kiosk unit found by <pattern>"`` where a slot vanished.
        Empty when every file agrees.
    """
    problems: list[str] = []
    for slot in KIOSK_SLOTS:
        text = (REPO_ROOT / slot.path).read_text(encoding="utf-8")
        found = re.findall(slot.pattern, text, flags=re.MULTILINE)
        if not found:
            problems.append(f"{slot.path}: no kiosk unit found by {slot.pattern!r}")
            continue
        expected = _expectedName(kioskUnit, slot)
        problems.extend(f"{slot.path}: {name}" for name in found if name != expected)
    return problems


def test_everyNonPythonFile_namesExactlyTheManifestKioskUnit():
    """
    Given: the manifest's KIOSK_UNIT
    When: every non-Python file that names the kiosk is read
    Then: each names exactly that constant at its load-bearing spot
    """
    from pi.ops.unit_manifest import KIOSK_UNIT

    assert findStaleKioskNames(KIOSK_UNIT) == []


def test_aRenamedConstant_failsThePin_namingEveryFileStillOnTheOldName():
    """
    Given: the manifest constant changed to a test value
    When: the pin runs against it
    Then: it fails, naming every pinned file -- each still holds the old name
    """
    problems = findStaleKioskNames(TEST_KIOSK_UNIT)

    flagged = {line.split(": ", 1)[0] for line in problems}
    assert flagged == {slot.path for slot in KIOSK_SLOTS}
    assert all(line.endswith(("eclipse-dashboard.service", "eclipse-dashboard"))
               for line in problems)


# ---------------------------------------------------------------------------
# The manifest constant
# ---------------------------------------------------------------------------


def test_manifest_exportsKioskUnit_andTheDashboardEntryUsesIt():
    """
    Given: unit_manifest
    When: its kiosk constant and UNIT_MANIFEST are read
    Then: KIOSK_UNIT is today's name and the kiosk entry carries it
    """
    from pi.ops import unit_manifest

    assert unit_manifest.KIOSK_UNIT == TODAYS_KIOSK_UNIT
    kioskSpecs = [spec for spec in unit_manifest.UNIT_MANIFEST if "kiosk" in spec.aliases]
    assert [spec.unit for spec in kioskSpecs] == [unit_manifest.KIOSK_UNIT]

    source = Path(unit_manifest.__file__).read_text(encoding="utf-8")
    assert source.count('"eclipse-dashboard.service"') == 1
    assert "unit=KIOSK_UNIT" in source


def test_manifest_staysStdlibOnly():
    """
    Given: unit_manifest, now imported by powerwatch
    When: its imports are listed
    Then: only __future__ and dataclasses -- powerwatch cannot pull in the display chain
    """
    from pi.ops import unit_manifest

    tree = ast.parse(Path(unit_manifest.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported == {"__future__", "dataclasses"}


# ---------------------------------------------------------------------------
# The Python consumers
# ---------------------------------------------------------------------------


def test_noOverride_defaultsResolveToTodaysValues():
    """
    Given: no config override
    When: the shed, both watchdogs and the splash OnSuccess= are resolved
    Then: all name the same kiosk, and the values are exactly today's
    """
    from pi.display import kiosk_watchdog, panel_liveness
    from src.pi.power.power_watch import load_shed

    assert load_shed.DEFAULT_SHED_UNITS == ("eclipse-dashboard",)
    assert kiosk_watchdog.DEFAULT_UNIT == TODAYS_KIOSK_UNIT
    assert panel_liveness.DEFAULT_UNIT == TODAYS_KIOSK_UNIT

    for variant in ("x11", "wayland"):
        unitFile = REPO_ROOT / f"src/pi/ui/splash/splash-boot.service.{variant}"
        onSuccess = re.findall(r"^OnSuccess=(\S+)", unitFile.read_text(encoding="utf-8"),
                               flags=re.MULTILINE)
        assert onSuccess == [TODAYS_KIOSK_UNIT]


def test_eachProcess_importsTheManifestUnderItsOwnPrefix():
    """
    Given: powerwatch runs as src.pi.*, the display units as pi.*
    When: each consumer's import of unit_manifest is read
    Then: load_shed uses src.pi.ops, the display modules use pi.ops
    """
    expected = {
        "src/pi/power/power_watch/load_shed.py": "src.pi.ops.unit_manifest",
        "src/pi/display/kiosk_watchdog.py": "pi.ops.unit_manifest",
        "src/pi/display/panel_liveness.py": "pi.ops.unit_manifest",
    }
    for path, module in expected.items():
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        modules = {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert module in modules, path
        assert not {m for m in modules if m and m.endswith("unit_manifest")} - {module}, path


def test_grepForTheKioskLiteral_findsOnlyTheManifestConstant():
    """
    Given: src/pi/power, src/pi/display and src/pi/ops
    When: searched for a quoted "eclipse-dashboard literal (the AC grep)
    Then: the only hit is the manifest constant
    """
    hits = []
    for package in ("src/pi/power", "src/pi/display", "src/pi/ops"):
        for path in sorted((REPO_ROOT / package).rglob("*")):
            if not path.is_file() or path.suffix == ".pyc":
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if '"eclipse-dashboard' in line:
                    hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{number}")

    assert len(hits) == 1, hits
    assert hits[0].startswith("src/pi/ops/unit_manifest.py:")


def _loadFresh(relativePath: str, name: str) -> ModuleType:
    """Execute a module file under a throwaway name, leaving the real one alone."""
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relativePath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module


def test_aChangedConstant_isFollowedByEveryPythonDefault(monkeypatch: pytest.MonkeyPatch):
    """
    Given: the manifest constant changed to a test value (both import prefixes)
    When: load_shed, kiosk_watchdog and panel_liveness are loaded fresh
    Then: all three defaults follow it; load_shed keeps the no-.service form
    """
    import pi.ops.unit_manifest as piManifest
    import src.pi.ops.unit_manifest as srcManifest

    monkeypatch.setattr(piManifest, "KIOSK_UNIT", TEST_KIOSK_UNIT)
    monkeypatch.setattr(srcManifest, "KIOSK_UNIT", TEST_KIOSK_UNIT)

    loadShed = _loadFresh("src/pi/power/power_watch/load_shed.py", "_us884_load_shed")
    watchdog = _loadFresh("src/pi/display/kiosk_watchdog.py", "_us884_kiosk_watchdog")
    liveness = _loadFresh("src/pi/display/panel_liveness.py", "_us884_panel_liveness")

    assert loadShed.DEFAULT_SHED_UNITS == ("eclipse-us884-probe",)
    assert watchdog.DEFAULT_UNIT == TEST_KIOSK_UNIT
    assert liveness.DEFAULT_UNIT == TEST_KIOSK_UNIT
