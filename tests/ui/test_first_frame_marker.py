################################################################################
# File Name: test_first_frame_marker.py
# Purpose/Description: US-866 first-frame marker -- the dashboard (and splash)
#                      log ONE console line after their first drawn frame, so
#                      the journal timestamps when the driver gets gauges.
# Author: Atlas (architect)
# Creation Date: 2026-10-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-16    | Atlas        | Initial (US-866 boot work, CIO-directed)
# ================================================================================
################################################################################

"""The first-frame marker fires once, after two animation frames, on any log level."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CAROUSEL = REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "carousel.js"
SPLASH_POLL = REPO_ROOT / "src" / "pi" / "ui" / "splash" / "boot-state-poll.js"

_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);
const lines = [];
console.info = (m) => lines.push(m);
const frames = [];
const win = {
  requestAnimationFrame: (cb) => frames.push(cb),
  performance: { now: () => 1234.4 },
};
assert.strictEqual(c.reportFirstFrame(win, 'dashboard'), true);
assert.deepStrictEqual(lines, [], 'nothing before the first frame');
frames.shift()();
assert.deepStrictEqual(lines, [], 'not after ONE frame: that callback runs before it paints');
frames.shift()();
assert.deepStrictEqual(lines, ['[kiosk] first-frame page=dashboard sinceNavigationMs=1234']);
assert.strictEqual(frames.length, 0, 'fires once, never re-arms');
assert.strictEqual(c.reportFirstFrame({}, 'dashboard'), false, 'no rAF: refuses quietly');
process.stdout.write('FIRST_FRAME_OK');
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available on PATH")
def test_reportFirstFrame_logsOnceAfterTheSecondFrame():
    result = subprocess.run(
        ["node", "-e", _NODE_SCRIPT, str(CAROUSEL)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "FIRST_FRAME_OK" in result.stdout


def test_dashboardSetup_reportsItsFirstFrame():
    """setup() calls the marker for the dashboard page, ungated by the log level."""
    text = CAROUSEL.read_text(encoding="utf-8")
    assert 'reportFirstFrame(global, "dashboard");' in text


def test_splash_reportsItsFirstFrame_inTheSameFormat():
    text = SPLASH_POLL.read_text(encoding="utf-8")
    assert '"[kiosk] first-frame page=splash sinceNavigationMs="' in text
