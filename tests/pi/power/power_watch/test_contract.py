################################################################################
# File Name: test_contract.py
# Purpose/Description: Contract tests: power_watch OutcomeKind + PipelineTask
#                      protocol are the single source of truth.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T1 contract tests.
# ================================================================================
################################################################################
"""Contract: outcome kinds + pipeline-task protocol are the single source of truth."""
from src.pi.power.power_watch.contract import RECORD_SCHEMA_VERSION, OutcomeKind


def test_outcomeKinds_exact():
    assert {k.value for k in OutcomeKind} == {
        "server_unavailable", "sync_failed_after_retry", "real_error", "ok"
    }


def test_schema_version_is_int():
    assert isinstance(RECORD_SCHEMA_VERSION, int) and RECORD_SCHEMA_VERSION >= 1
