################################################################################
# File Name: test_calibration_cli_local_invocation.py
# Purpose/Description: Sprint 30 US-316 (I-020 close) -- regression gate for the
#                      "third layer" of I-018: invoking calibration.py as a
#                      script from a fresh subprocess WITHOUT PYTHONPATH set,
#                      which is exactly how CIO ran it from his local Windows
#                      shell on 2026-05-10. Pre-fix the script crashes at
#                      module-import time with
#                      ``ModuleNotFoundError: No module named 'src'`` because
#                      Python's auto-injected ``sys.path[0]`` is the script's
#                      own directory (``src/server/analytics/``), and ``src``
#                      itself is not on the path. Post-fix the script gains a
#                      self-bootstrapping ``sys.path.insert(0, repo_root)`` at
#                      the top so the import resolves regardless of
#                      invocation cwd or env.
#
#                      The existing US-312 Layer 1 test (test_calibration_cli_
#                      integration.py) explicitly sets
#                      ``PYTHONPATH=PROJECT_ROOT`` in the subprocess env --
#                      that is the path PM validated server-side and is the
#                      reason I-018 Layer 3 (this bug) wasn't caught there.
#                      This file complements it by testing the OTHER path:
#                      no PYTHONPATH, no repo-root cwd, just the bare
#                      invocation CIO actually uses.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex          | Initial -- Sprint 30 US-316 TDD (I-020 close).
# ================================================================================
################################################################################

"""TDD regression gate for the US-316 calibration.py PYTHONPATH bootstrap.

Discriminator design: the existing US-312 Layer 1 test runs the same
script with ``PYTHONPATH=PROJECT_ROOT`` in the subprocess env, which is
why it never caught I-018 Layer 3.  This test scrubs ``PYTHONPATH`` from
the subprocess env, picks a neutral cwd outside the repo root, and runs
the script via its absolute path.  Pre-fix this fails with
``ModuleNotFoundError: No module named 'src'`` at line 58.  Post-fix the
self-bootstrap block at the top of calibration.py inserts the repo root
onto ``sys.path`` before the project import runs, so the module-level
imports resolve cleanly and the script exits 0 (calibration.py has no
``__main__`` guard or argv handling -- it just runs its imports and
ends).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CALIBRATION_SCRIPT: Path = (
    PROJECT_ROOT / 'src' / 'server' / 'analytics' / 'calibration.py'
)


class TestCalibrationLocalInvocation:
    """Pre-fix: subprocess crashes with ModuleNotFoundError at the
    ``from src.server.db.models import ...`` line because ``src`` is not on
    sys.path when invoked as a script with no PYTHONPATH.  Post-fix the
    self-bootstrap block at the top of calibration.py prepends the repo
    root onto sys.path before the project import runs.
    """

    def _runCalibrationScript(self, tmp_path: Path) -> subprocess.CompletedProcess[str]:
        # Mirror CIO's exact 2026-05-10 invocation context:
        #   * fresh subprocess (no inherited Python state)
        #   * PYTHONPATH explicitly cleared (CIO had none set)
        #   * cwd outside the repo root (tmp_path) so even
        #     accidental "cwd is on sys.path" rescues do not mask the bug
        #   * absolute script path (no relative-path resolution)
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        return subprocess.run(
            [sys.executable, str(CALIBRATION_SCRIPT), '--calibrate', '--apply'],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_calibrationScript_runsCleanly_withNoPythonpathSet(
        self, tmp_path: Path,
    ) -> None:
        # The acceptance-criterion-2 IRL discriminator: this assertion is
        # the difference between PM's server-side validation path (which
        # passed) and CIO's local-Windows path (which crashed).  Pre-fix
        # the subprocess returns 1 with ModuleNotFoundError in stderr;
        # post-fix it returns 0.
        result = self._runCalibrationScript(tmp_path)
        assert result.returncode == 0, (
            f'calibration.py crashed when invoked without PYTHONPATH; '
            f'stdout={result.stdout!r} stderr={result.stderr!r}'
        )

    def test_calibrationScript_doesNotRaiseModuleNotFoundError(
        self, tmp_path: Path,
    ) -> None:
        # Anti-regression: if the bootstrap block ever gets removed or
        # the relative-path math drifts (e.g. parent count changes after
        # a directory restructure), this test fails loudly with the
        # exact pre-fix error string.  Independent assertion from the
        # exit-code check -- a different future bug could exit non-zero
        # for a different reason, and this signature is the I-020 marker.
        result = self._runCalibrationScript(tmp_path)
        combined = result.stdout + result.stderr
        assert 'ModuleNotFoundError' not in combined, (
            f"ModuleNotFoundError surfaced -- I-020 regression: "
            f"{combined}"
        )
        assert "No module named 'src'" not in combined, (
            f"'No module named src' surfaced -- I-020 regression: "
            f"{combined}"
        )
