################################################################################
# File Name: test_obd_mac_integrity.py
# Purpose/Description: Repo-side integrity guard for the canonical OBDLink LX
#                      Bluetooth MAC (US-477 / F-120). Pins the burned-in MAC
#                      00:04:3E:85:0D:FB in both the bash SSOT (deploy/
#                      addresses.sh OBD_BT_MAC default) and config.json
#                      (pi.bluetooth.macAddress references the same env SSOT),
#                      and asserts the phantom MAC (00:04:3C:84:15:6B, the
#                      2026-07-17 mis-ID) can never enter either file. Flipping
#                      the repo MAC to the phantom -- or any other value -- turns
#                      this suite RED (US-477 validationCriterion 1).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-20    | Rex (US-477) | Initial implementation. Canonical-MAC repo guard.
# ================================================================================
################################################################################

"""Guard that the OBDLink LX MAC in the repo stays the real burned-in address.

A Bluetooth MAC is factory-burned and does NOT change on a device reset, so the
OBDLink LX's address is a fixed constant. The 2026-07-17 incident replaced it in
the Pi's config with a phantom (a mis-identified stranger's device), which bound
rfcomm to nothing and captured zero rows for a weekend. The repo was already
correct; this guard keeps it that way and makes any drift a RED test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ADDRESSES_SH = REPO_ROOT / "deploy" / "addresses.sh"
CONFIG_JSON = REPO_ROOT / "config.json"

# The one true, burned-in OBDLink LX address (specs/grounded-knowledge.md,
# specs/architecture.md, MEMORY.md). This literal is the assertion target -- do
# NOT parameterize it from the files under test (that would let both drift
# together undetected).
CANONICAL_MAC = "00:04:3E:85:0D:FB"
CANONICAL_NAME = "OBDLink LX"
# The 2026-07-17 phantom -- must never appear in the repo.
PHANTOM_MAC = "00:04:3C:84:15:6B"


def _addressesText() -> str:
    return ADDRESSES_SH.read_text(encoding="utf-8")


def _addressesObdMacDefault() -> str:
    """Extract the OBD_BT_MAC default from `OBD_BT_MAC="${OBD_BT_MAC:-<mac>}"`."""
    text = _addressesText()
    match = re.search(
        r'OBD_BT_MAC="\$\{OBD_BT_MAC:-([0-9A-Fa-f:]+)\}"',
        text,
    )
    assert match is not None, (
        "deploy/addresses.sh must declare OBD_BT_MAC with the canonical default "
        'in the form OBD_BT_MAC="${OBD_BT_MAC:-<mac>}"'
    )
    return match.group(1)


def test_addressesSh_obdMac_isCanonical():
    """deploy/addresses.sh OBD_BT_MAC default == the burned-in OBDLink LX MAC."""
    assert _addressesObdMacDefault() == CANONICAL_MAC, (
        "deploy/addresses.sh OBD_BT_MAC default drifted from the canonical "
        f"{CANONICAL_MAC}. A Bluetooth MAC is burned-in -- if capture stopped, "
        "the fix is NOT to change this address (that is the 2026-07-17 phantom "
        "mistake). Restore the canonical value."
    )


def test_addressesSh_namesTheDevice_obdlinkLx():
    """The bash SSOT documents the device by name so the MAC is unambiguous."""
    assert CANONICAL_NAME in _addressesText(), (
        f"deploy/addresses.sh must name the device '{CANONICAL_NAME}' alongside "
        "its MAC so the canonical address is self-documenting."
    )


def test_configJson_macAddress_referencesEnvSsot():
    """config.json must reference the ${OBD_BT_MAC} SSOT, never hardcode a MAC.

    Hardcoding a literal MAC in config.json is exactly how a phantom could enter
    the repo bypassing addresses.sh. Keeping it as the ${OBD_BT_MAC} placeholder
    means there is a single canonical source (addresses.sh / .env).
    """
    config = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    macAddress = config["pi"]["bluetooth"]["macAddress"]
    assert macAddress == "${OBD_BT_MAC}", (
        "config.json pi.bluetooth.macAddress must stay the ${OBD_BT_MAC} "
        f"placeholder (single SSOT), not a literal MAC (found {macAddress!r})."
    )


def test_phantomMac_absentFromAddressesSh():
    """The 2026-07-17 phantom MAC must never appear in the bash SSOT."""
    assert PHANTOM_MAC not in _addressesText(), (
        f"phantom MAC {PHANTOM_MAC} found in deploy/addresses.sh -- this is the "
        "2026-07-17 mis-identified device. The OBDLink LX MAC is burned-in and "
        f"did not change; restore {CANONICAL_MAC}."
    )


def test_phantomMac_absentFromConfigJson():
    """The phantom MAC must never appear as a literal in config.json either."""
    assert PHANTOM_MAC not in CONFIG_JSON.read_text(encoding="utf-8"), (
        f"phantom MAC {PHANTOM_MAC} found in config.json."
    )
