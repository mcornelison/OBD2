################################################################################
# File Name: test_unit_is_typed_label.py
# Purpose/Description: US-455 / D-4 / F-082 invariant guard -- the ``unit`` field
#                      is a typed LABEL, never a number.  Asserts (1) the ORM
#                      RealtimeData.unit column is a string type, and (2) no code
#                      under src/ coerces or numerically compares a ``.unit``
#                      attribute (float(x.unit), int(x.unit), x.unit > 0, ...).
#                      This encodes the [ATLAS] acceptance "analytics treat unit
#                      as a typed label, never a numeric".
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-455) | Initial -- D-4 unit-is-a-label invariant guard.
# ================================================================================
################################################################################

"""US-455 / D-4: guard that ``unit`` is a typed label, never parsed numerically."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import String

from src.server.db.models import RealtimeData

# Repo layout: tests/test_unit_is_typed_label.py -> parents[1] is the repo root.
_SRC_ROOT = Path(__file__).resolve().parents[1] / 'src'

# Numeric coercion of a ``.unit`` attribute: float(x.unit) / int(x.unit) / etc.
# ``\.unit\b`` requires the literal attribute ``.unit`` (word boundary excludes
# ``.units`` -- pint's plural -- and ``.speed_unit``/``.accel_unit`` columns).
_NUMERIC_COERCE = re.compile(
    r'\b(?:float|int|Decimal|complex)\s*\(\s*[^)]*\.unit\b',
)

# Numeric comparison of a ``.unit`` attribute against a number: x.unit > 0, etc.
_NUMERIC_COMPARE = re.compile(
    r'\.unit\s*(?:<=|>=|<|>)\s*-?\d',
)


def _srcPyFiles() -> list[Path]:
    return sorted(_SRC_ROOT.rglob('*.py'))


def test_realtimeDataUnitColumnIsAStringType() -> None:
    """The persisted ``unit`` column is a text label, not a numeric type."""
    unitCol = RealtimeData.__table__.c.unit
    assert isinstance(unitCol.type, String), (
        f'realtime_data.unit must be a String label type, got {unitCol.type!r}'
    )


def test_srcTreeHasPythonFilesToScan() -> None:
    """Sanity guard: the scan below is non-vacuous."""
    files = _srcPyFiles()
    assert len(files) > 50, f'expected a populated src/ tree, found {len(files)} .py files'


def test_noCodeParsesUnitNumerically() -> None:
    """No src/ code coerces or numerically compares a ``.unit`` label.

    [ATLAS] US-455 AC: analytics treat ``unit`` as a typed label, never a
    number.  A violation here means a code path is reading the unit string as a
    magnitude (the exact fragility unit-string canonicalization removes).
    """
    violations: list[str] = []
    for path in _srcPyFiles():
        text = path.read_text(encoding='utf-8')
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _NUMERIC_COERCE.search(line) or _NUMERIC_COMPARE.search(line):
                rel = path.relative_to(_SRC_ROOT.parent)
                violations.append(f'{rel}:{lineno}: {line.strip()}')

    assert not violations, (
        'unit must be a typed label, never parsed numerically; found:\n'
        + '\n'.join(violations)
    )
