################################################################################
# File Name: test_imu_rate_triple.py
# Purpose/Description: US-796-b -- the IMU rate triple is sampleHz 4 /
#     persistHz 2 / stateHz 1 (CIO ruling 2026-09-21). Pins the shipped
#     values, the stored cadence (a UTC time grid since ARCH-064d), that no row is dropped or
#     double-counted on either consumer path, and that a consumer rate above
#     its source is WARNED (both values named, effective rate stated) rather
#     than silently clamped.
#
#     2026-09-28 (ARCH-064, Controller ruling, companion bench ARCH-064b):
#     ONE pin below -- test_configJson_imuTriple_isExactlyFourTwoOne -- is
#     updated to the shipped triple ARCH-064 ships: sampleHz 4 -> 50 (the
#     IMU's internal acquisition/fusion read rate; persistHz/stateHz stay 2/1,
#     unchanged, under the 4 Hz storage ceiling --
#     specs/data-acquisition-architecture.md §4.2.a on that branch). The rest
#     of this file's tests construct their own explicit sampleHz=4 objects and
#     are independent of what config.json ships; they are unaffected and
#     unchanged. ⚠️ THIS BENCH (ARCH-064b, branched from dev) has NOT merged
#     ARCH-064: its own config.json still ships sampleHz 4, so
#     test_configJson_imuTriple_isExactlyFourTwoOne is EXPECTED TO FAIL HERE
#     until ARCH-064 merges into dev. It is pinned to the POST-MERGE value
#     deliberately, not weakened to pass on dev -- see the commit message.
# Author: Rex (US-796-b)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-21    | Rex (US-796-b) | Initial -- ruled 4 / 2 / 1.
# 2026-09-28    | Atlas          | ARCH-064 companion fix: re-pinned the
#               | (ARCH-064b)    | config.json triple assertion to 50 / 2 / 1
#               |                | (ARCH-064's shipped values) -- fails on
#               |                | this bench until ARCH-064 merges, by design.
# ================================================================================
################################################################################
"""US-796-b: the IMU triple, every decimation factor exact, no silent clamp.
test_configJson_imuTriple_isExactlyFourTwoOne pins ARCH-064's post-merge
50 / 2 / 1 and is EXPECTED TO FAIL on this bench (still dev's 4 / 2 / 1) until
that branch merges."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from common.config.validator import ConfigValidator
from pi.bus.edr_persistence_subscriber import EdrPersistenceSubscriber
from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase
from pi.sensors.imu_state_bridge import ImuStateBridge

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VALIDATOR_LOGGER = "common.config.validator"

# The ruled triple (CIO 2026-09-21). Exact values, not bounds.
_SAMPLE_HZ = 4
_PERSIST_HZ = 2
_STATE_HZ = 1


def _imu(field: str, value, seq: int, *, capture: float) -> Sample:
    """One raw.imu.<field> sample under a burst's shared seq."""
    return Sample(
        topic=f"raw.imu.{field}",
        source="imu",
        value=value,
        unit="x",
        tsUtc="2026-09-21T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _shippedImu() -> dict:
    with open(_REPO_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)["pi"]["sensors"]["imu"]


def _baseCfg(imu: dict) -> dict:
    return {"protocolVersion": "1", "schemaVersion": "1", "deviceId": "d",
            "pi": {"sensors": {"imu": imu}}, "server": {}}


# ---------------------------------------------------------------------------
# The shipped triple
# ---------------------------------------------------------------------------

def test_configJson_imuTriple_isExactlyFourTwoOne():
    """
    Given: the shipped config.json
    When: the three pi.sensors.imu rates are read
    Then: they are exactly 50 / 2 / 1 -- not a range, not 'at most'. sampleHz
          is ARCH-064's IMU internal acquisition/fusion read rate (raised from
          the original 4 Hz ruling this test is named for); persistHz/stateHz
          are UNCHANGED, still the CIO's 2026-09-21 ruling, still under the
          4 Hz storage ceiling (specs/data-acquisition-architecture.md §4.2.a
          on the ARCH-064 branch).

          ⚠️ EXPECTED TO FAIL on this bench (ARCH-064b, branched from dev)
          until ARCH-064 merges -- this bench's own config.json still ships
          sampleHz 4. Pinned to the post-merge value deliberately; see the
          file header.
    """
    imu = _shippedImu()
    assert (imu["sampleHz"], imu["persistHz"], imu["stateHz"]) == (50, 2, 1)


def test_validator_acceptsTheShippedTriple_withoutARateWarning(caplog):
    """
    Given: the shipped 4 / 2 / 1 triple
    When: the validator runs
    Then: it is preserved as written and no rate warning is logged
    """
    imu = _shippedImu()
    triple = {"sampleHz": imu["sampleHz"], "persistHz": imu["persistHz"],
              "stateHz": imu["stateHz"]}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        result = ConfigValidator().validate(_baseCfg(dict(triple)))
    got = result["pi"]["sensors"]["imu"]
    assert {k: got[k] for k in triple} == triple
    assert not [r for r in caplog.records if "pi.sensors.imu" in r.getMessage()]


# ARCH-064d: the two "exact factor" pins on _decimationFactor were removed with
# the function. Persistence is a UTC time grid (test_persistPath_* below and
# test_edr_persist_utc_grid.py), and the state bridge already wrote on a TIME
# interval, never through that function (test_displayPath_* below).


# ---------------------------------------------------------------------------
# No row dropped or double-counted
# ---------------------------------------------------------------------------

def test_persistPath_atFourTwo_keepsExactlyOneRowPerHalfSecondUtcSlot(tmp_path: Path):
    """
    Given: the EDR subscriber at sampleHz 4 / persistHz 2, UTC offset pinned to 0
    When: 8 full bursts 0.25 s apart (captures 0.25 .. 2.00 s) are fed
    Then: the first burst in each 0.5 s UTC slot is persisted -- seq 1 opens
          slot [0, 0.5), then seqs 2, 4, 6, 8 open the next four (ARCH-064d:
          a time grid, not keep-every-2nd, so the stored rate is persistHz
          whatever the read loop actually runs at)
    """
    db = ObdDatabase(str(tmp_path / "triple.db"), walMode=False)
    db.initialize()
    sub = EdrPersistenceSubscriber(
        None, db, imuSampleHz=_SAMPLE_HZ, imuPersistHz=_PERSIST_HZ,
        wallClockOffsetFn=lambda: 0.0,
    )
    for seq in range(1, 9):
        capture = seq / _SAMPLE_HZ
        for field, value in (("accel", (0.0, 0.0, 9.8)), ("gyro", (0.0, 0.0, 0.0)),
                             ("mag", (1.0, 2.0, 3.0)), ("temp", 25.0)):
            sub.handleSample(_imu(field, value, seq, capture=capture))
    sub.flushPending()
    with db.connect() as conn:
        seqs = [r[0] for r in conn.execute("SELECT seq FROM edr_imu_sample ORDER BY seq")]
    assert seqs == [1, 2, 4, 6, 8]


def test_displayPath_atFourOne_writesExactlyOneOfEveryFourBursts(tmp_path: Path):
    """
    Given: the state bridge at sampleHz 4 / stateHz 1
    When: 8 accel bursts arrive 0.25 s apart (2 s of sampling)
    Then: exactly 2 state writes -- bursts 1 and 5, one per second
    """
    written: list[int] = []
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=_STATE_HZ, sampleHz=_SAMPLE_HZ)
    current = {"seq": 0}
    bridge._writeState = lambda payload: written.append(current["seq"])  # type: ignore[method-assign]
    for seq in range(1, 9):
        current["seq"] = seq
        bridge.handleSample(_imu("accel", (0.0, 0.0, 9.8), seq, capture=(seq - 1) / _SAMPLE_HZ))
    assert written == [1, 5]


# ---------------------------------------------------------------------------
# No silent clamp: a consumer rate above its source is WARNED
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["persistHz", "stateHz"])
def test_validator_consumerRateAboveSource_warnsNamingBothValues(caplog, key):
    """
    Given: a consumer rate (persistHz or stateHz) of 8 against sampleHz 4
    When: the validator runs
    Then: a WARNING names 8 and 4 and reports the effective rate (4 Hz); the
          config still loads (the path degrades to every burst, not a crash)
    """
    imu = {"sampleHz": 4, "persistHz": 2, "stateHz": 1, key: 8}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        ConfigValidator().validate(_baseCfg(imu))
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and f"pi.sensors.imu.{key}" in r.getMessage()]
    assert len(lines) == 1
    line = lines[0]
    assert f"pi.sensors.imu.{key} 8" in line
    assert "pi.sensors.imu.sampleHz 4" in line
    assert "effective rate 4 Hz" in line


def test_validator_persistRateOffTheRecommendedSet_warnsNamingIt(caplog):
    """
    Given: persistHz 3 against sampleHz 50
    When: the validator runs
    Then: ONE WARNING names 3 and the ECU-matchable recording rates 1, 2, 4
          (CIO 2026-09-30) -- and the config still loads.
    ARCH-064d: this REPLACES the old "inexact ratio" warning. Persistence is a
    UTC time grid now, so 3 Hz really IS stored at 3 Hz; the old warning's
    "effective rate 4 Hz" would itself be a lie.
    """
    imu = {"sampleHz": 50, "persistHz": 3, "stateHz": 1}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        ConfigValidator().validate(_baseCfg(imu))
    lines = [r.getMessage() for r in caplog.records
             if r.levelno == logging.WARNING and "pi.sensors.imu.persistHz" in r.getMessage()]
    assert len(lines) == 1
    assert "pi.sensors.imu.persistHz 3" in lines[0]
    assert "1, 2, 4" in lines[0]


@pytest.mark.parametrize("persistHz", [1, 2, 4])
def test_validator_recommendedPersistRates_doNotWarn(caplog, persistHz):
    """Any of 1, 2 or 4 Hz against sampleHz 50 is silent: exact on a UTC grid."""
    imu = {"sampleHz": 50, "persistHz": persistHz, "stateHz": 1}
    with caplog.at_level(logging.WARNING, logger=_VALIDATOR_LOGGER):
        ConfigValidator().validate(_baseCfg(imu))
    assert not [r for r in caplog.records
                if r.levelno == logging.WARNING and "pi.sensors.imu.persistHz" in r.getMessage()]
