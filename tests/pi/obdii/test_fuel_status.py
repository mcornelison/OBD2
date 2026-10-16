################################################################################
# File Name: test_fuel_status.py
# Purpose/Description: US-890-c -- the ONE closed-loop FUEL_SYSTEM_STATUS code
#   set (Atlas S104 total-trim ruling): its value, the loop state it names, and
#   the grep gate that keeps a second copy of it out of src/pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-890-c) | Initial -- shared code set + grep gate.
# ================================================================================
################################################################################

"""US-890-c: the shared closed-loop code set and its single-copy gate."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Any

import pytest

from pi.obdii import fuel_status

_SRC_PI = Path(__file__).resolve().parents[3] / "src" / "pi"
_HOME = _SRC_PI / "obdii" / "fuel_status.py"
_IMPORTERS = (
    _SRC_PI / "obdii" / "fuel_economy_emitter.py",
    _SRC_PI / "obdii" / "obd_live_emitter.py",
)


def test_closedLoopCodes_areCLAndCLFault() -> None:
    assert fuel_status.CLOSED_LOOP_FUEL_STATUS_CODES == frozenset({2, 5})


@pytest.mark.parametrize(
    ("value", "loop"),
    [(2, "closed"), (5, "closed"), (2.0, "closed"), (5.0, "closed"),
     (1, "open"), (3, "open"), (3.0, "open"), (4, "open"), (0, "open")],
)
def test_fuelLoopState_mapsEveryCodeThroughTheOneSet(value: Any, loop: str) -> None:
    """
    Given: a numeric FUEL_SYSTEM_STATUS code (as realtime_data stores it)
    When: mapped
    Then: 2/5 closed, every other code open (Atlas: 1/3/4 are open loop)
    """
    assert fuel_status.fuelLoopState(value) == loop


@pytest.mark.parametrize(
    "value", [None, True, False, "CL", "2", 2.5, math.nan, math.inf],
    ids=["none", "true", "false", "label", "numeric-string", "fractional", "nan", "inf"],
)
def test_fuelLoopState_notACode_isUnknown_neverOpen(value: Any) -> None:
    assert fuel_status.fuelLoopState(value) is None


# ------------------------------------------------------------------ grep gate


def _codeSetLiterals(source: str) -> list[int]:
    """Line numbers of every {2, 5} set literal (bare or frozenset/set call)."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        elts: list[ast.expr] | None = None
        if isinstance(node, ast.Set):
            elts = node.elts
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("frozenset", "set") and len(node.args) == 1
              and isinstance(node.args[0], (ast.Set, ast.List, ast.Tuple))):
            elts = node.args[0].elts
        if elts is None:
            continue
        values = {e.value for e in elts if isinstance(e, ast.Constant)}
        if len(values) == len(elts) and values == {2, 5}:
            hits.append(node.lineno)
    return hits


def test_codeSet_hasExactlyOneLiteral_inSrcPi() -> None:
    """
    Given: every Python file under src/pi
    When: scanned (AST, so prose is not counted)
    Then: the {2, 5} code set is written ONCE, in fuel_status.py
    """
    owners = {
        path.relative_to(_SRC_PI).as_posix()
        for path in _SRC_PI.rglob("*.py")
        if _codeSetLiterals(path.read_text(encoding="utf-8"))
    }
    assert owners == {"obdii/fuel_status.py"}


@pytest.mark.parametrize(
    "planted",
    ["CODES = frozenset({2, 5})", "CODES = {5, 2}", "CODES = set([2, 5])"],
)
def test_codeSetGate_catchesAPlantedCopy(planted: str) -> None:
    assert _codeSetLiterals(planted) != []


@pytest.mark.parametrize("path", _IMPORTERS, ids=lambda p: p.name)
def test_bothEmitters_importTheSharedModule(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pi.obdii.fuel_status"
    ]
    assert imported, f"{path.name} does not import pi.obdii.fuel_status"


def test_fuelEconomyEmitter_usesTheSharedObject() -> None:
    from pi.obdii import fuel_economy_emitter

    assert fuel_economy_emitter.CLOSED_LOOP_FUEL_STATUS_CODES is (
        fuel_status.CLOSED_LOOP_FUEL_STATUS_CODES
    )
    assert _HOME.exists()
