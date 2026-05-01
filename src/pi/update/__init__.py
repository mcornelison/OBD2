################################################################################
# File Name: __init__.py
# Purpose/Description: Pi self-update package (B-047 US-C / US-247).  Re-exports
#                      :class:`UpdateChecker` and the :class:`CheckOutcome`
#                      enum + :class:`CheckResult` dataclass that the
#                      orchestrator runLoop consumes.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Pi self-update package -- consumers import UpdateChecker / UpdateApplier here."""

from __future__ import annotations

from src.pi.update.update_applier import (
    ApplyOutcome,
    ApplyResult,
    UpdateApplier,
)
from src.pi.update.update_checker import (
    CheckOutcome,
    CheckResult,
    UpdateChecker,
)

__all__ = [
    "ApplyOutcome",
    "ApplyResult",
    "CheckOutcome",
    "CheckResult",
    "UpdateApplier",
    "UpdateChecker",
]
