################################################################################
# File Name: test_boost_thresholds.py
# Purpose/Description: Regression pins for boost-detail display stub constants
#                      (US-143 within US-220 bundle). Guards BOOST_CAUTION and
#                      BOOST_DANGER defaults against re-drift by asserting the
#                      literal stock-TD04-13G safe values, not just
#                      "whatever the module defines." If a future edit pushes
#                      these back toward the dangerously-wrong 18.0/22.0 values
#                      that Spool flagged in her 2026-04-12 variance report,
#                      these tests fail immediately.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-22    | Rex          | Initial implementation for US-220 (Sprint 17)
# ================================================================================
################################################################################

"""
Literal-value regression pins for boost display stub thresholds.

Why literal pins (not constant-identity checks):
    tests/test_boost_detail.py already asserts
    ``BoostThresholds().cautionMin == BOOST_CAUTION_DEFAULT``, but that
    assertion would still pass if someone changed BOOST_CAUTION_DEFAULT
    back to 18.0 — it only checks that the dataclass default wires to the
    module constant. US-220's goal is preventing re-drift of the VALUES
    Spool specified, so these tests pin the literals.

Values are authoritative per Spool's Session 3 (2026-04-12) variance
report, Variance 4 — stock TD04-13G safe operating range.
"""

from pi.display.screens.boost_detail import (
    BOOST_CAUTION_DEFAULT,
    BOOST_DANGER_DEFAULT,
)


class TestBoostStubDefaultsPinnedToStockTurboValues:
    """Regression pins for US-143 (stock-turbo safe range)."""

    def test_boostCautionDefault_isPinnedToStockTurboCaution(self):
        """
        Given: stock TD04-13G turbo operating range (Spool variance 4)
        When:  BOOST_CAUTION_DEFAULT is imported
        Then:  equals 14.0 psi (approaching stock turbo efficiency limit)
        """
        assert BOOST_CAUTION_DEFAULT == 14.0

    def test_boostDangerDefault_isPinnedToStockTurboDanger(self):
        """
        Given: stock TD04-13G turbo operating range (Spool variance 4)
        When:  BOOST_DANGER_DEFAULT is imported
        Then:  equals 15.0 psi (above stock turbo safe range)
        """
        assert BOOST_DANGER_DEFAULT == 15.0

    def test_boostCautionBelowDanger_enforcesSeverityOrdering(self):
        """
        Given: the two display stub defaults
        When:  compared
        Then:  caution < danger (severity ordering invariant)
        """
        assert BOOST_CAUTION_DEFAULT < BOOST_DANGER_DEFAULT
