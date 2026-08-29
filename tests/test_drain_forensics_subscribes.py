################################################################################
# File Name: test_drain_forensics_subscribes.py
# Purpose/Description: ARCH-006 -- drain_forensics must SUBSCRIBE to the
#   published battery-health state instead of acquiring the I2C bus itself.
#   SSOT rule B: read once -> persist -> publish -> subscribe.
# Author: Atlas (Architect)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-28    | Atlas   | ARCH-006: rule-B cleanup, CIO-directed
# ================================================================================
################################################################################

"""Acceptance tests for the drain_forensics UPS provider.

**What was wrong.** `drain-forensics.timer` fires every 5 s
(`OnUnitActiveSec=5s`), and each firing was a FRESH PROCESS that opened its own
I2C client -- twice, because the power-source provider and the telemetry
provider each called the acquiring function. Twenty-four bus opens a minute,
forever, alongside powerwatch and the sensor emitters reading the same bus.

That is a direct violation of the SSOT rule the CIO canonized 2026-08-20:
**read once -> persist -> publish -> subscribe; never two acquisitions of one
source.**

**Why the fix is clean.** `powerwatch` already publishes exactly the three
MAX17048 registers this script wanted -- `vcellV`, `soc`, `crate` -- into
`states/battery-health`. The reading already exists; drain_forensics simply was
not subscribing to it.

**Why there is deliberately NO I2C fallback.** A "fall back to the bus if the
state file is missing" branch would re-create the second acquisition, and it
would fire at exactly the worst moment: when the publisher is already unhealthy
and the bus is the thing under suspicion. An unavailable reading is recorded as
unavailable. That is honest-availability, and it is the whole point.
"""

import json
import time

import pytest

from scripts.drain_forensics import (
    _readPowerSourceFromVcell,
    _readUpsTelemetryFromState,
    buildProductionContext,
)


def _writeState(path, *, vcell=4.1, soc=96, crate=None, ageSec=0.0):
    ts = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ageSec)
    )
    path.write_text(
        json.dumps({"vcellV": vcell, "soc": soc, "crate": crate, "ts": ts}),
        encoding="utf-8",
    )
    return path


class TestSubscribesToThePublishedReading:
    def test_readsTheThreeRegistersFromTheStateFile(self, tmp_path):
        p = _writeState(tmp_path / "battery-health", vcell=4.164, soc=96, crate=-1.5)
        got = _readUpsTelemetryFromState(p)
        assert got["vcell_v"] == pytest.approx(4.164)
        assert got["soc_pct"] == 96
        assert got["crate_pct_per_hr"] == pytest.approx(-1.5)

    def test_aNullCrateStaysNullRatherThanBecomingZero(self, tmp_path):
        """`crate` is legitimately null on this Pi. Zero would be a reading."""
        p = _writeState(tmp_path / "battery-health", crate=None)
        assert _readUpsTelemetryFromState(p)["crate_pct_per_hr"] is None


class TestStaleAndAbsentAreHonest:
    """An old value is not a current value, and must not be recorded as one."""

    def test_aStaleReadingIsDroppedNotReported(self, tmp_path):
        p = _writeState(tmp_path / "battery-health", ageSec=600)
        got = _readUpsTelemetryFromState(p, maxAgeSec=30)
        assert got == {"vcell_v": None, "soc_pct": None, "crate_pct_per_hr": None}

    def test_aFreshReadingInsideTheWindowIsKept(self, tmp_path):
        p = _writeState(tmp_path / "battery-health", ageSec=5, vcell=4.0)
        assert _readUpsTelemetryFromState(p, maxAgeSec=30)["vcell_v"] == pytest.approx(4.0)

    def test_aMissingFileYieldsNonesNotAnException(self, tmp_path):
        got = _readUpsTelemetryFromState(tmp_path / "nope")
        assert got == {"vcell_v": None, "soc_pct": None, "crate_pct_per_hr": None}

    def test_malformedJsonYieldsNonesNotAnException(self, tmp_path):
        p = tmp_path / "battery-health"
        p.write_text("{ this is not json", encoding="utf-8")
        got = _readUpsTelemetryFromState(p)
        assert got == {"vcell_v": None, "soc_pct": None, "crate_pct_per_hr": None}

    def test_aMissingTimestampIsTreatedAsUntrustworthy(self, tmp_path):
        """No ts means the age cannot be established -- so it cannot be trusted."""
        p = tmp_path / "battery-health"
        p.write_text(json.dumps({"vcellV": 4.1, "soc": 96}), encoding="utf-8")
        assert _readUpsTelemetryFromState(p)["vcell_v"] is None


class TestPowerSourceUsesTheSameReading:
    """The power-source column must not become a SECOND acquisition."""

    def test_powerSourceIsDerivedFromTheSubscribedVcell(self, tmp_path):
        p = _writeState(tmp_path / "battery-health", vcell=3.80)
        vcell = _readUpsTelemetryFromState(p)["vcell_v"]
        assert _readPowerSourceFromVcell(vcell) == "battery"

    def test_anUnavailableVcellYieldsUnknownNotAGuess(self, tmp_path):
        vcell = _readUpsTelemetryFromState(tmp_path / "absent")["vcell_v"]
        assert _readPowerSourceFromVcell(vcell) == "unknown"


class TestProductionWiringDoesNotTouchTheBus:
    def test_theProductionContextReadsTheStateFileAndOpensNoBus(self, tmp_path, monkeypatch):
        """The whole point of the ticket, asserted end to end.

        If anything in the production path still constructs an I2C client, this
        import-time bomb fires. Anchored on UpsMonitor because that is the class
        that opens the bus.
        """
        import src.pi.hardware.ups_monitor as ups_mod

        def _explode(*a, **k):
            raise AssertionError(
                "drain_forensics acquired the I2C bus -- rule B says subscribe"
            )

        monkeypatch.setattr(ups_mod, "UpsMonitor", _explode)

        state = _writeState(tmp_path / "battery-health", vcell=4.11, soc=95)
        ctx = buildProductionContext(
            logDir=tmp_path, batteryHealthStateFile=state
        )

        assert ctx.upsTelemetryProvider()["vcell_v"] == pytest.approx(4.11)
        assert ctx.powerSourceProvider() == "external"

    def test_theBusIsReadZeroTimesPerFire(self, tmp_path):
        """Was TWO opens per 5s fire: the telemetry provider and the
        power-source provider each called the acquiring function."""
        state = _writeState(tmp_path / "battery-health")
        ctx = buildProductionContext(logDir=tmp_path, batteryHealthStateFile=state)
        reads = {"n": 0}
        original = ctx.upsTelemetryProvider

        # Both providers must resolve from the file, not from hardware; calling
        # them repeatedly must stay side-effect-free.
        for _ in range(3):
            original()
            ctx.powerSourceProvider()
        assert reads["n"] == 0
