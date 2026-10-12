################################################################################
# File Name: test_boot_battery_test.py
# Purpose/Description: Tests for the F-054 boot-time battery test (US-445). The
#   health assessment is a pure function over a single VCELL register read; the
#   runner is best-effort (a hardware read that raises resolves to UNKNOWN, and a
#   state-write failure is logged, never raised -- same contract as the F-103 +
#   F-097 emitters). Covers: the grounded VCELL band verdicts (OK / WEAK), the
#   honest-instrument UNKNOWN path (unreadable OR physically implausible read --
#   never a confident wrong health), the state-file payload shape, atomic write +
#   states-dir provisioning, and the never-raise guarantees.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-445) | Initial implementation (F-054 battery-test-on-boot)
# ================================================================================
################################################################################

"""Tests for ``pi.splash.boot_battery_test``."""

import json
import os

from pi.splash.boot_battery_test import (
    BOOT_BATTERY_TEST_FILENAME,
    VCELL_DROPOUT_KNEE_V,
    VCELL_HEALTHY_FLOOR_V,
    BootBatteryVerdict,
    assessBootBatteryHealth,
    buildBootBatteryTestState,
    runBootBatteryTest,
)

_NOW = "2026-07-03T21:42:00Z"


# ---------------------------------------------------------------------------
# assessBootBatteryHealth -- the pure, grounded health verdict
# ---------------------------------------------------------------------------


def test_assess_healthyFloatVoltage_returnsOk():
    """
    Given: a healthy AC-float VCELL (~4.02 V, above the discharge knee)
    When: assessed
    Then: OK with a grounded reason
    """
    verdict, reason = assessBootBatteryHealth(4.02)
    assert verdict is BootBatteryVerdict.OK
    assert reason == "vcell-healthy"


def test_assess_atHealthyFloor_returnsOk():
    """
    Given: VCELL exactly at the healthy floor (3.70 V, the discharge knee)
    When: assessed
    Then: OK -- the boundary is inclusive
    """
    verdict, _reason = assessBootBatteryHealth(VCELL_HEALTHY_FLOOR_V)
    assert verdict is BootBatteryVerdict.OK


def test_assess_belowHealthyFloor_returnsWeak():
    """
    Given: a plausible VCELL below the healthy floor but above the dropout knee
    When: assessed
    Then: WEAK -- the pack is low, surfaced early (not UNKNOWN, not a crash)
    """
    verdict, reason = assessBootBatteryHealth(3.60)
    assert verdict is BootBatteryVerdict.WEAK
    assert reason == "vcell-below-healthy-floor"


def test_assess_belowDropoutKnee_returnsWeakWithKneeReason():
    """
    Given: a VCELL below the buck-converter dropout knee (3.30 V, Drain-7)
    When: assessed
    Then: WEAK, with a reason that surfaces the criticality (still a coarse
          two-tier verdict -- we do NOT invent a confident third tier)
    """
    verdict, reason = assessBootBatteryHealth(3.20)
    assert verdict is BootBatteryVerdict.WEAK
    assert reason == "vcell-below-dropout-knee"


def test_assess_unreadable_returnsUnknown():
    """
    Given: no VCELL reading (register read failed -> None)
    When: assessed
    Then: UNKNOWN -- honest-instrument, never a confident wrong health
    """
    verdict, reason = assessBootBatteryHealth(None)
    assert verdict is BootBatteryVerdict.UNKNOWN
    assert reason == "vcell-unreadable"


def test_assess_implausiblyHigh_returnsUnknown():
    """
    Given: a physically implausible VCELL (~20 V -- the classic un-byte-swapped
           MAX17048 read)
    When: assessed
    Then: UNKNOWN -- a garbage read is not a health claim
    """
    verdict, reason = assessBootBatteryHealth(20.0)
    assert verdict is BootBatteryVerdict.UNKNOWN
    assert reason == "vcell-implausible"


def test_assess_implausiblyLow_returnsUnknown():
    """
    Given: a physically implausible VCELL below any operational LiPo voltage
    When: assessed
    Then: UNKNOWN, not a fabricated WEAK
    """
    verdict, reason = assessBootBatteryHealth(1.0)
    assert verdict is BootBatteryVerdict.UNKNOWN
    assert reason == "vcell-implausible"


# ---------------------------------------------------------------------------
# buildBootBatteryTestState -- the pure payload shape
# ---------------------------------------------------------------------------


def test_buildState_hasExactKeys_andCarriesReadings():
    """
    Given: an assessed OK result with a raw (uncalibrated) SoC read
    When: the state payload is built
    Then: it has exactly the documented keys and carries the readings verbatim
    """
    payload = buildBootBatteryTestState(
        verdict=BootBatteryVerdict.OK,
        reason="vcell-healthy",
        vcellV=4.02,
        socPct=76,
        socCalibrated=False,
        nowIso=_NOW,
    )
    assert payload == {
        "verdict": "ok",
        "reason": "vcell-healthy",
        "vcellV": 4.02,
        "socPct": 76,
        "socCalibrated": False,
        "ts": _NOW,
    }


# ---------------------------------------------------------------------------
# runBootBatteryTest -- read + assess + emit
# ---------------------------------------------------------------------------


def test_run_healthyRead_writesStateFile_andReturnsOk(tmp_path):
    """
    Given: readers that return a healthy VCELL + an SoC
    When: the boot battery test runs against a not-yet-existing states dir
    Then: the dir is provisioned, an OK state file is written with the readings,
          and the returned result matches
    """
    statesDir = str(tmp_path / "states")  # does NOT exist yet
    result = runBootBatteryTest(
        readVcell=lambda: 4.02,
        readSoc=lambda: 76,
        statesDir=statesDir,
        socCalibrated=True,
        nowIsoFn=lambda: _NOW,
    )

    assert result.verdict is BootBatteryVerdict.OK
    assert result.vcellV == 4.02
    assert result.socPct == 76
    assert result.socCalibrated is True

    written = json.loads(
        (tmp_path / "states" / BOOT_BATTERY_TEST_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert written["verdict"] == "ok"
    assert written["reason"] == "vcell-healthy"
    assert written["vcellV"] == 4.02
    assert written["socPct"] == 76
    assert written["ts"] == _NOW


def test_run_readerRaises_resolvesToUnknown_andStillWrites(tmp_path):
    """
    Given: a VCELL reader that raises (a missing/broken fuel gauge on boot)
    When: the boot battery test runs
    Then: the verdict is UNKNOWN (unreadable), a state file is still written,
          and nothing propagates -- a battery test must never fail boot
    """
    def boom():
        raise RuntimeError("i2c device not found")

    statesDir = str(tmp_path / "states")
    result = runBootBatteryTest(
        readVcell=boom,
        readSoc=boom,
        statesDir=statesDir,
        nowIsoFn=lambda: _NOW,
    )

    assert result.verdict is BootBatteryVerdict.UNKNOWN
    assert result.reason == "vcell-unreadable"
    assert result.vcellV is None
    assert result.socPct is None

    written = json.loads(
        (tmp_path / "states" / BOOT_BATTERY_TEST_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert written["verdict"] == "unknown"
    assert written["vcellV"] is None


def test_run_neverRaises_onWriteFailure(tmp_path):
    """
    Given: a states dir whose parent is a regular file (mkdir will fail)
    When: the boot battery test runs
    Then: it never raises, no file is created, and the assessed result is still
          returned (best-effort emit contract)
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    statesDir = str(blocker / "states")  # parent is a file -> mkdir fails

    result = runBootBatteryTest(
        readVcell=lambda: 3.60,
        readSoc=lambda: 40,
        statesDir=statesDir,
        nowIsoFn=lambda: _NOW,
    )

    assert result.verdict is BootBatteryVerdict.WEAK
    assert not os.path.exists(statesDir)


def test_run_noSocReader_omitsSoc_butStillAssessesVcell(tmp_path):
    """
    Given: only a VCELL reader (SoC read intentionally skipped)
    When: the boot battery test runs
    Then: socPct is None but the VCELL-driven verdict is still produced
    """
    statesDir = str(tmp_path / "states")
    result = runBootBatteryTest(
        readVcell=lambda: 3.20,
        readSoc=None,
        statesDir=statesDir,
        nowIsoFn=lambda: _NOW,
    )
    assert result.socPct is None
    assert result.verdict is BootBatteryVerdict.WEAK
    assert result.reason == "vcell-below-dropout-knee"


def test_dropoutKnee_isBelowHealthyFloor():
    """Grounding sanity: the dropout knee sits below the healthy floor."""
    assert VCELL_DROPOUT_KNEE_V < VCELL_HEALTHY_FLOOR_V
