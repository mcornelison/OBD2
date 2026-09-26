################################################################################
# File Name: test_cell_epoch_config.py
# Purpose/Description: US-790 -- pi.power.cellEpoch: which cell was fitted when a
#                      drain VCELL row was written.  Default 'unknown' (honest,
#                      never a guess), a closed vocabulary grounded in
#                      specs/grounded-knowledge.md, and the shipped config
#                      carries the cell fitted 2026-09-21.
# Author: Rex (US-790)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-25    | Rex (US-790) | Initial.
# ================================================================================
################################################################################
"""pi.power.cellEpoch validation (US-790)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from src.common.config.validator import (
    CELL_EPOCH_UNKNOWN,
    CELL_EPOCH_VALUES,
    DEFAULTS,
    ConfigValidationError,
    ConfigValidator,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KEY = "pi.power.cellEpoch"


def _shippedConfig() -> dict[str, Any]:
    with open(_REPO_ROOT / "config.json", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _withEpoch(value: Any) -> dict[str, Any]:
    config = copy.deepcopy(_shippedConfig())
    config["pi"].setdefault("power", {})["cellEpoch"] = value
    return config


class TestCellEpoch:
    def test_vocabulary_isTheFourGroundedEpochs(self) -> None:
        assert set(CELL_EPOCH_VALUES) == {
            "450mah-pouch", "2000mah-pouch", "18650-pack", "unknown",
        }
        assert CELL_EPOCH_UNKNOWN == "unknown"

    def test_defaultIsUnknown_neverAGuess(self) -> None:
        assert DEFAULTS[_KEY] == CELL_EPOCH_UNKNOWN

    def test_absentKey_resolvesToUnknown(self) -> None:
        config = copy.deepcopy(_shippedConfig())
        config["pi"]["power"].pop("cellEpoch", None)

        validated = ConfigValidator().validate(config)

        assert validated["pi"]["power"]["cellEpoch"] == "unknown"

    def test_shippedConfig_carriesTheFittedCell(self) -> None:
        validated = ConfigValidator().validate(_shippedConfig())

        assert validated["pi"]["power"]["cellEpoch"] == "2000mah-pouch"

    @pytest.mark.parametrize("value", sorted(CELL_EPOCH_VALUES))
    def test_everyVocabularyValue_isAccepted(self, value: str) -> None:
        validated = ConfigValidator().validate(_withEpoch(value))

        assert validated["pi"]["power"]["cellEpoch"] == value

    @pytest.mark.parametrize(
        "value", ["2000mAh-pouch", "2000mah", "lipo", "", 2000, True, ["2000mah-pouch"]],
    )
    def test_offVocabularyValue_isRejected(self, value: Any) -> None:
        with pytest.raises(ConfigValidationError, match="cellEpoch"):
            ConfigValidator().validate(_withEpoch(value))
