################################################################################
# File Name: test_vehicle_info_writer_path_discipline.py
# Purpose/Description: Sprint 43 V0.28.0 (US-368 / F-109, AC#4 / V-3) -- writer-
#                      path discipline regression test for the append-only
#                      vehicle_info identity invariant.  Scans src/server/ for
#                      RAW SQL that UPDATEs a vehicle_info identity column
#                      (ecu_signature / ecu_install_timestamp_utc) and asserts
#                      there are NONE: corrections go through stamp_ecu_swap's
#                      close+open, never an in-place identity rewrite.  Targets
#                      raw SQL (not ORM attribute assignment) per the US-366
#                      routing note -- stamp_ecu_swap (close timestamp) and
#                      add_ecu_note (notes) legitimately mutate NON-identity
#                      columns via the sanctioned ORM writer path.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 vehicle_info writer-path
#               |              | discipline grep regression.
# ================================================================================
################################################################################

"""US-368 AC#4 / V-3 writer-path discipline regression.

The ``vehicle_info`` ECU identity columns are append-only: a freeze-frame FK
(and per-drive joins) reference a SPECIFIC row + time window, so an in-place
identity UPDATE would silently rewrite history.  This test fails loudly if any
``src/server/`` source ever issues raw SQL that UPDATEs an identity column.
"""

from __future__ import annotations

import re
from pathlib import Path

# Identity (append-only) columns -- a raw SQL UPDATE that SETs one of these on
# vehicle_info violates the invariant.  ecu_removal_timestamp_utc + notes +
# cal_signature are deliberately EXCLUDED: stamp_ecu_swap legitimately closes a
# row (set removal) and add_ecu_note appends to notes, both via the sanctioned
# ORM writer path.
_IDENTITY_COLUMNS = ("ecu_signature", "ecu_install_timestamp_utc")

_SERVER_ROOT = Path(__file__).resolve().parents[2] / "src" / "server"

# Match a raw SQL UPDATE on vehicle_info that reaches a SET of an identity
# column.  DOTALL so the SET can be on a later line within the same statement
# string.  Case-insensitive (SQL keywords vary in casing across the codebase).
_RAW_UPDATE_RE = re.compile(
    r"UPDATE\s+vehicle_info\b.*?\bSET\b.*?(" + "|".join(_IDENTITY_COLUMNS) + r")",
    re.IGNORECASE | re.DOTALL,
)

# A bare ``SET ecu_signature =`` raw fragment (UPDATE keyword may be built
# separately) is also a violation.
_RAW_SET_RE = re.compile(
    r"\bSET\s+(" + "|".join(_IDENTITY_COLUMNS) + r")\s*=",
    re.IGNORECASE,
)


def _serverPyFiles() -> list[Path]:
    return sorted(_SERVER_ROOT.rglob("*.py"))


def test_serverRootExists():
    """Guard: the scan target must actually be there (else the test is vacuous)."""
    assert _SERVER_ROOT.is_dir(), f"expected server source root at {_SERVER_ROOT}"
    assert _serverPyFiles(), "no .py files found under src/server/ -- scan vacuous"


def test_noRawSqlUpdateOfVehicleInfoIdentityColumns():
    """V-3: zero raw-SQL UPDATEs of vehicle_info identity columns in src/server/."""
    offenders: list[str] = []
    for path in _serverPyFiles():
        text = path.read_text(encoding="utf-8", errors="replace")
        if _RAW_UPDATE_RE.search(text) or _RAW_SET_RE.search(text):
            offenders.append(str(path.relative_to(_SERVER_ROOT.parents[1])))
    assert not offenders, (
        "raw SQL UPDATE of vehicle_info identity columns "
        f"({', '.join(_IDENTITY_COLUMNS)}) found in: {offenders}. "
        "ECU identity is append-only -- correct via stamp_ecu_swap close+open, "
        "never an in-place UPDATE."
    )
