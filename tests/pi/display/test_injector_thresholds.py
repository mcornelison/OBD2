################################################################################
# File Name: test_injector_thresholds.py
# Purpose/Description: Regression pins for fuel-detail display stub injector
#                      duty-cycle thresholds (US-144 within US-220 bundle).
#                      Guards INJECTOR_CAUTION and INJECTOR_DANGER defaults
#                      against re-drift by asserting the literal Spool-spec
#                      values, not just "whatever the module defines." Spool
#                      flagged the prior 80.0% caution as too permissive on
#                      her 2026-04-12 variance report — correct value is 75%.
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
Literal-value regression pins for fuel display stub injector thresholds.

Why literal pins (not constant-identity checks):
    tests/test_fuel_detail.py already asserts
    ``InjectorDutyThresholds().cautionMin == INJECTOR_CAUTION_DEFAULT``,
    but that would still pass if the constant were reverted to 80.0.
    US-220 guards the numeric VALUES Spool specified.

Values are authoritative per Spool's Session 3 (2026-04-12) variance
report, Variance 5:
    - Normal:  0–75%
    - Caution: 75–85%
    - Danger:  >85%
INJECTOR_DANGER_DEFAULT was already correct at 85.0 pre-fix; the
caution boundary is the one US-220 nails down.
"""

from pi.display.screens.fuel_detail import (
    INJECTOR_CAUTION_DEFAULT,
    INJECTOR_DANGER_DEFAULT,
)


class TestInjectorStubDefaultsPinnedToSpoolSpec:
    """Regression pins for US-144 (injector duty-cycle thresholds)."""

    def test_injectorCautionDefault_isPinnedTo75Percent(self):
        """
        Given: Spool IDC threshold spec (variance 5)
        When:  INJECTOR_CAUTION_DEFAULT is imported
        Then:  equals 75.0 (% duty cycle)
        """
        assert INJECTOR_CAUTION_DEFAULT == 75.0

    def test_injectorDangerDefault_isPinnedTo85Percent(self):
        """
        Given: Spool IDC threshold spec (variance 5)
        When:  INJECTOR_DANGER_DEFAULT is imported
        Then:  equals 85.0 (% duty cycle — already correct pre-US-144)
        """
        assert INJECTOR_DANGER_DEFAULT == 85.0

    def test_injectorCautionBelowDanger_enforcesSeverityOrdering(self):
        """
        Given: the two display stub defaults
        When:  compared
        Then:  caution < danger (severity ordering invariant)
        """
        assert INJECTOR_CAUTION_DEFAULT < INJECTOR_DANGER_DEFAULT
