################################################################################
# File Name: test_edr_log_gate_import_direction.py
# Purpose/Description: US-793-b -- pins the DIRECTION of the dependency between
#     the EDR log gate and the OBD layer, not the membership of a list.
#     (a) src/pi/bus/edr_log_gate.py imports NOTHING from pi.obdii: it reads
#         reachability through a structural Protocol and compares string values,
#         which is what keeps the gate re-armable without an import cycle.
#     (b) the ONLY module under src/pi/obdii/ permitted to import the gate is the
#         composition root, orchestrator/lifecycle.py -- a ONE-ENTRY literal
#         allowlist, so growing it is a visible diff.
#     The blanket form "pi.obdii must not import edr_log_gate" is FALSE today
#     (lifecycle.py wires the gate, legitimately), so it would have been weakened
#     to green -- the inert guard this test exists to prevent. The scanner is
#     proven live here against a deliberately bad synthetic tree.
# Author: Rex (US-793-b)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-21    | Rex (US-793-b) | Initial -- both directions, one-entry allowlist,
#               |                | scanner self-test.
# ================================================================================
################################################################################

"""Lint: the EDR log gate never imports pi.obdii; only the composition root
under pi.obdii imports the gate."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()
)
_SRC = _REPO_ROOT / "src"

_GATE_MODULE = "pi.bus.edr_log_gate"
_OBDII_PACKAGE = "pi.obdii"

# ONE entry, literal. Adding a second importer must be a visible diff here.
_ALLOWED_GATE_IMPORTERS = ("pi/obdii/orchestrator/lifecycle.py",)


def _moduleName(path: Path, srcRoot: Path) -> str:
    """Dotted module name for a file under ``srcRoot`` (package __init__ -> pkg)."""
    parts = list(path.relative_to(srcRoot).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _normalise(name: str) -> str:
    """Strip the ``src.`` prefix: ``src.pi.x`` and ``pi.x`` are one module."""
    return name[len("src."):] if name.startswith("src.") else name


def _importedModules(path: Path, srcRoot: Path) -> set[str]:
    """Every module a file imports, anywhere in it (lazy imports included).

    Relative imports are resolved against the file's own package. For
    ``from X import Y`` both ``X`` and ``X.Y`` are reported, so importing a
    submodule by name (``from pi.bus import edr_log_gate``) is caught too.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _moduleName(path, srcRoot)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(_normalise(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = _normalise(node.module or "")
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def _isWithin(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def gateImportsFromObdii(srcRoot: Path) -> set[str]:
    """Modules under pi.obdii that the gate module imports (should be none)."""
    gate = srcRoot / Path(*_GATE_MODULE.split(".")).with_suffix(".py")
    return {m for m in _importedModules(gate, srcRoot) if _isWithin(m, _OBDII_PACKAGE)}


def obdiiImportersOfGate(srcRoot: Path) -> set[str]:
    """Files under src/pi/obdii/ (POSIX, relative to src) importing the gate."""
    obdiiDir = srcRoot / Path(*_OBDII_PACKAGE.split("."))
    return {
        path.relative_to(srcRoot).as_posix()
        for path in sorted(obdiiDir.rglob("*.py"))
        if any(_isWithin(m, _GATE_MODULE) for m in _importedModules(path, srcRoot))
    }


# ------------------------------------------------------------------ the rules


def test_gate_importsNothingFromObdii() -> None:
    """
    Given: src/pi/bus/edr_log_gate.py
    When: its import list is parsed
    Then: nothing from pi.obdii -- the gate reads reachability structurally
    """
    assert gateImportsFromObdii(_SRC) == set()


def test_onlyTheCompositionRootUnderObdii_importsTheGate() -> None:
    """
    Given: every module under src/pi/obdii/
    When: their imports are parsed
    Then: only the one allowlisted composition root imports the gate
    """
    assert obdiiImportersOfGate(_SRC) <= set(_ALLOWED_GATE_IMPORTERS)


def test_allowlist_isOneLiteralEntry_andStillLive() -> None:
    """
    Given: the allowlist
    When: inspected
    Then: exactly one entry, and that entry really does import the gate -- a
        stale allowlist entry would be a hole nobody sees
    """
    assert len(_ALLOWED_GATE_IMPORTERS) == 1
    assert obdiiImportersOfGate(_SRC) == set(_ALLOWED_GATE_IMPORTERS)


# ------------------------------------------- the scanner can fail (non-vacuity)


def _syntheticTree(tmp: Path, files: dict[str, str]) -> Path:
    src = tmp / "src"
    for rel, body in {
        "pi/__init__.py": "",
        "pi/bus/__init__.py": "",
        "pi/bus/edr_log_gate.py": "import logging\n",
        "pi/obdii/__init__.py": "",
        "pi/obdii/orchestrator/__init__.py": "",
        "pi/obdii/orchestrator/lifecycle.py": (
            "def f():\n    from pi.bus.edr_log_gate import EdrLogGate\n"
        ),
        **files,
    }.items():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return src


def test_scanner_flagsADeliberateObdiiImporter(tmp_path: Path) -> None:
    """
    Given: a tree where a non-root pi.obdii module imports the gate, in each
        spelling (absolute, src.-prefixed, submodule-by-name, relative, lazy)
    When: the importer rule runs
    Then: every offender is reported -- a green run on the real tree is only
        evidence because this one goes red
    """
    src = _syntheticTree(tmp_path, {
        "pi/obdii/a.py": "from pi.bus.edr_log_gate import EdrLogGate\n",
        "pi/obdii/b.py": "import src.pi.bus.edr_log_gate\n",
        "pi/obdii/c.py": "from pi.bus import edr_log_gate\n",
        "pi/obdii/d.py": "from ..bus.edr_log_gate import GATE_OPEN\n",
        "pi/obdii/e.py": "def g():\n    from pi.bus.edr_log_gate import EdrLogGate\n",
    })
    offenders = obdiiImportersOfGate(src) - set(_ALLOWED_GATE_IMPORTERS)
    assert offenders == {
        "pi/obdii/a.py", "pi/obdii/b.py", "pi/obdii/c.py",
        "pi/obdii/d.py", "pi/obdii/e.py",
    }


def test_scanner_flagsTheGateImportingObdii(tmp_path: Path) -> None:
    """
    Given: a gate module that imports pi.obdii (absolute, relative, src.)
    When: the gate rule runs
    Then: each is reported
    """
    for body, expected in [
        ("from pi.obdii.obd_connection import Reachability\n",
         "pi.obdii.obd_connection"),
        ("from ..obdii.obd_connection import Reachability\n",
         "pi.obdii.obd_connection"),
        ("import src.pi.obdii\n", "pi.obdii"),
    ]:
        src = _syntheticTree(tmp_path / str(abs(hash(body))), {
            "pi/bus/edr_log_gate.py": body,
        })
        assert expected in gateImportsFromObdii(src), body
