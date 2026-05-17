################################################################################
# File Name: test_boot_progress_units.py
# Purpose/Description: Static assertions on the boot-progress systemd unit files:
#                      shutdown-finalizer ordering + mandatory PYTHONPATH (US-277
#                      silent-import guard) + arm-before-eclipse-obd.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- T11 unit-file static checks.
# ================================================================================
################################################################################
"""Static checks: boot-progress finalize/arm systemd units are wired correctly."""
from pathlib import Path

FIN = Path("deploy/boot-progress-finalize.service").read_text(encoding="utf-8")
ARM = Path("deploy/boot-progress-arm.service").read_text(encoding="utf-8")


def test_finalizer_ordering_and_pythonpath():
    assert "DefaultDependencies=no" in FIN
    assert "After=eclipse-obd.service drain-forensics.service" in FIN
    assert "Before=shutdown.target" in FIN
    assert "RemainAfterExit=yes" in FIN
    assert "ExecStop=" in FIN and "--finalize" in FIN
    assert "Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01" in FIN
    assert "WorkingDirectory=/home/mcornelison/Projects/Eclipse-01" in FIN


def test_arm_runs_before_eclipse_obd():
    assert "Before=eclipse-obd.service" in ARM
    assert "--arm" in ARM
    assert "Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01" in ARM
