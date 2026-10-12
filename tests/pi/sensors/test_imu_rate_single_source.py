################################################################################
# File Name: test_imu_rate_single_source.py
# Purpose/Description: US-801 -- the IMU rate triple (sampleHz / persistHz /
#     stateHz) has ONE definition. Measured on dev f429d864 it had EIGHT: three
#     module fallbacks for sampleHz, one for persistHz, one for stateHz, and three
#     validator DEFAULTS entries -- all 50/25/10 while config.json ships 4/2/1.
#     These tests pin (a) that the single definition equals the shipped config,
#     read from both files; (b) that every consumer's fallback IS that definition;
#     and (c) structurally, that no second literal definition exists anywhere in
#     src/ -- including DEFAULTS dict entries, which a constant-shaped grep cannot
#     see.
# Author: Rex (US-801)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-801)   | Initial -- agreement with config.json, consumer
#               |                | identity, AST scan incl. the DEFAULTS dict.
# ================================================================================
################################################################################
"""US-801: one definition of the IMU rate triple, equal to the shipped config."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import common.config.validator as validatorModule
import pi.bus.edr_persistence_subscriber as edrSubscriberModule
import pi.sensors.imu_state_bridge as bridgeModule
import pi.sensors.sensor_reader as readerModule

_REPO_ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file()
)
_SRC = _REPO_ROOT / "src"
_HOME = _SRC / "common" / "config" / "validator.py"

# (config key under pi.sensors.imu, the single definition's name)
_TRIPLE = [
    ("sampleHz", "DEFAULT_IMU_SAMPLE_HZ"),
    ("persistHz", "DEFAULT_IMU_PERSIST_HZ"),
    ("stateHz", "DEFAULT_IMU_STATE_HZ"),
]

# Every name under which a consumer module holds its fallback, and the single
# definition it must BE. The consumers keep their historical global names
# because the US-796-f poisoned-default tests monkeypatch them.
_CONSUMER_FALLBACKS = [
    (readerModule, "DEFAULT_IMU_SAMPLE_HZ", "DEFAULT_IMU_SAMPLE_HZ"),
    (bridgeModule, "DEFAULT_IMU_SAMPLE_HZ", "DEFAULT_IMU_SAMPLE_HZ"),
    (bridgeModule, "DEFAULT_STATE_HZ", "DEFAULT_IMU_STATE_HZ"),
    (edrSubscriberModule, "_DEFAULT_IMU_SAMPLE_HZ", "DEFAULT_IMU_SAMPLE_HZ"),
    (edrSubscriberModule, "_DEFAULT_IMU_PERSIST_HZ", "DEFAULT_IMU_PERSIST_HZ"),
]


def _shippedImu() -> dict:
    config = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    return config["pi"]["sensors"]["imu"]


@pytest.mark.parametrize(("key", "name"), _TRIPLE)
def test_singleDefinition_equalsShippedConfig(key: str, name: str) -> None:
    """
    Given: the single definition and config.json, each read from its own file
    When: compared
    Then: equal -- the default and the shipped value cannot drift apart silently
    """
    assert getattr(validatorModule, name) == _shippedImu()[key]


@pytest.mark.parametrize(("key", "name"), _TRIPLE)
def test_validatorDefaults_deriveFromTheSingleDefinition(key: str, name: str) -> None:
    """The DEFAULTS registry entry IS the single definition's value."""
    assert validatorModule.DEFAULTS[f"pi.sensors.imu.{key}"] == getattr(validatorModule, name)


@pytest.mark.parametrize(("module", "localName", "homeName"), _CONSUMER_FALLBACKS)
def test_everyConsumerFallback_isTheSingleDefinition(
    module: object, localName: str, homeName: str
) -> None:
    """Each module fallback is imported from the single home, not re-declared."""
    assert getattr(module, localName) == getattr(validatorModule, homeName)
    assert f"{homeName}" in _importedNames(Path(module.__file__))  # type: ignore[attr-defined]


def test_triple_isCoherent() -> None:
    """The defaults satisfy the validator's own rule: no consumer above its source,
    and persistHz divides sampleHz exactly (US-796-b)."""
    sample = validatorModule.DEFAULT_IMU_SAMPLE_HZ
    persist = validatorModule.DEFAULT_IMU_PERSIST_HZ
    state = validatorModule.DEFAULT_IMU_STATE_HZ
    assert persist <= sample and state <= sample
    assert sample % persist == 0


# ------------------------------------------------------- structural single source


def _importedNames(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


_RATE_NAME_MARKERS = ("IMU_SAMPLE_HZ", "IMU_PERSIST_HZ", "IMU_STATE_HZ", "DEFAULT_STATE_HZ")
_RATE_KEYS = {f"pi.sensors.imu.{key}" for key, _ in _TRIPLE}


def literalRateDefinitions(srcRoot: Path) -> list[str]:
    """Every place in ``srcRoot`` that assigns an IMU rate a numeric LITERAL.

    Two shapes: a module assignment to a rate-named constant, and a dict entry
    keyed ``pi.sensors.imu.{sampleHz,persistHz,stateHz}`` -- the validator
    DEFAULTS shape that a constant-shaped grep cannot see.
    """
    found: list[str] = []
    for path in sorted(srcRoot.rglob("*.py")):
        rel = path.relative_to(srcRoot).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                isLiteral = isinstance(node.value, ast.Constant) and isinstance(
                    node.value.value, (int, float)
                )
                for target in targets:
                    if (
                        isinstance(target, ast.Name)
                        and any(m in target.id for m in _RATE_NAME_MARKERS)
                        and isLiteral
                    ):
                        found.append(f"{rel}:{node.lineno} {target.id}")
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value in _RATE_KEYS
                        and isinstance(value, ast.Constant)
                    ):
                        found.append(f"{rel}:{key.lineno} {key.value!r}")
    return found


def test_exactlyThreeLiteralDefinitions_allInTheSingleHome() -> None:
    """
    Given: every .py under src/
    When: scanned for IMU rate literals (constants AND DEFAULTS dict entries)
    Then: exactly three -- one per rate -- and all in the single home
    """
    found = literalRateDefinitions(_SRC)
    assert len(found) == 3, found
    assert all(entry.startswith("common/config/validator.py:") for entry in found), found


def test_scanner_seesTheDictShape(tmp_path: Path) -> None:
    """
    Given: a synthetic tree with a module constant AND a DEFAULTS-style dict entry
        carrying literals (the pre-US-801 shapes)
    When: scanned
    Then: both are reported -- a zero on the real tree is only evidence because
        the scanner demonstrably sees the dict key
    """
    (tmp_path / "m.py").write_text(
        "DEFAULT_IMU_SAMPLE_HZ = 50\n"
        "DEFAULTS = {'pi.sensors.imu.sampleHz': 50, 'pi.sensors.imu.stateHz': 10}\n",
        encoding="utf-8",
    )
    found = literalRateDefinitions(tmp_path)
    assert found == [
        "m.py:1 DEFAULT_IMU_SAMPLE_HZ",
        "m.py:2 'pi.sensors.imu.sampleHz'",
        "m.py:2 'pi.sensors.imu.stateHz'",
    ]
