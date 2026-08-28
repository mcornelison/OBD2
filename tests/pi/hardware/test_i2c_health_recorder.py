################################################################################
# File Name: test_i2c_health_recorder.py
# Purpose/Description: ARCH-003 -- acceptance gate for I2C transaction-health
#   instrumentation. The bus is read by several independent processes (notably
#   drain-forensics, which systemd re-spawns every 5s), so a per-process counter
#   is worthless: it dies with the process. These tests pin the properties that
#   make the record usable as EVIDENCE after a power loss.
# Author: Atlas (Architect)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-28    | Atlas   | ARCH-003: instrument first, fix second (CIO-directed)
# ================================================================================
################################################################################

"""Acceptance tests for :mod:`src.pi.hardware.i2c_health`.

Why this exists, stated plainly: the CIO's hypothesis is that an I2C bus hiccup
starves the UPS read, so ``powerwatch`` never sees the power transition and the
Pi dies without a graceful shutdown. That hypothesis is PLAUSIBLE AND UNPROVEN --
on 2026-08-28 the bus enumerated clean (0x0c/0x29/0x36/0x69) with zero
``Remote I/O`` errors in the journal.

So the first job is not a fix. It is an instrument that will still be there,
with a readable record, the next time the failure happens.

Three properties make the difference between evidence and noise:

1. **It must outlive the process.** ``drain-forensics`` runs for ~1 second every
   5 seconds. An in-memory counter never survives to be read.
2. **It must be interpretable with a WRONG WALL CLOCK.** A-23: this Pi's RTC
   trickle-charger was never enabled, so in the car -- where there is no NTP --
   the clock reads whatever it last synced to. A record stamped only with wall
   time is exactly the kind of confident-but-wrong artefact this project keeps
   finding. Every record therefore carries a monotonic reading AND an explicit
   flag saying whether the wall clock was trustworthy when it was written.
3. **It must never become a new failure mode.** An instrument that can take down
   the thing it measures is worse than no instrument.
"""

import pytest

from src.pi.hardware.i2c_health import I2cEvent, I2cHealthRecorder


class _Boom(OSError):
    """An OSError with a controllable errno, for driving the retry path."""

    def __init__(self, errno: int = 5):
        super().__init__("simulated bus error")
        self.errno = errno


class TestRecordSurvivesTheProcess:
    """Property 1 -- the record is durable, not in-memory."""

    def test_recordsAppendToFileSoASecondProcessCanReadThem(self, tmp_path):
        path = tmp_path / "i2c-health.jsonl"

        first = I2cHealthRecorder(path=path)
        first.record(I2cEvent.FAILED, address=0x36, register=0x02,
                     operation="readWord", attempts=4, errno=5)

        # A DIFFERENT recorder instance -- standing in for the next 5-second
        # respawn of drain-forensics -- must see what the first one wrote.
        second = I2cHealthRecorder(path=path)
        rows = second.readAll()

        assert len(rows) == 1
        assert rows[0]["event"] == "failed"
        assert rows[0]["address"] == "0x36"

    def test_appendsRatherThanTruncating(self, tmp_path):
        path = tmp_path / "i2c-health.jsonl"
        for _ in range(3):
            I2cHealthRecorder(path=path).record(
                I2cEvent.RETRIED, address=0x69, register=0x00,
                operation="readByte", attempts=2, errno=5)

        assert len(I2cHealthRecorder(path=path).readAll()) == 3


class TestInterpretableWithAWrongClock:
    """Property 2 -- A-23. A timestamp that might be wrong must SAY SO."""

    def test_everyRecordCarriesMonotonicAndAClockTrustFlag(self, tmp_path):
        path = tmp_path / "i2c-health.jsonl"
        rec = I2cHealthRecorder(path=path, clockSyncedFn=lambda: False)
        rec.record(I2cEvent.FAILED, address=0x36, register=0x02,
                   operation="readWord", attempts=4, errno=5)

        row = rec.readAll()[0]
        assert "monotonic" in row, "a monotonic reading is the only ordering we can trust"
        assert row["clockSynced"] is False, (
            "an unsynced clock must be declared, not silently written as if true"
        )

    def test_aSyncedClockIsRecordedAsSynced(self, tmp_path):
        path = tmp_path / "i2c-health.jsonl"
        rec = I2cHealthRecorder(path=path, clockSyncedFn=lambda: True)
        rec.record(I2cEvent.RECOVERED, address=0x29, register=0x00,
                   operation="readByte", attempts=2, errno=5)
        assert rec.readAll()[0]["clockSynced"] is True

    def test_monotonicIsStrictlyOrderedWithinAProcess(self, tmp_path):
        path = tmp_path / "i2c-health.jsonl"
        rec = I2cHealthRecorder(path=path)
        for _ in range(3):
            rec.record(I2cEvent.RETRIED, address=0x36, register=0x02,
                       operation="readWord", attempts=2, errno=5)
        vals = [r["monotonic"] for r in rec.readAll()]
        assert vals == sorted(vals)


class TestNeverBecomesANewFailureMode:
    """Property 3 -- the instrument must not be able to take down the bus read."""

    def test_anUnwritablePathIsSwallowed(self, tmp_path):
        # A directory where a file should be: every write will fail.
        bad = tmp_path / "not-a-file"
        bad.mkdir()
        rec = I2cHealthRecorder(path=bad)
        rec.record(I2cEvent.FAILED, address=0x36, register=0x02,
                   operation="readWord", attempts=4, errno=5)  # must not raise

    def test_readAllOnAMissingFileReturnsEmptyRatherThanRaising(self, tmp_path):
        assert I2cHealthRecorder(path=tmp_path / "nope.jsonl").readAll() == []

    def test_corruptLinesAreSkippedNotFatal(self, tmp_path):
        path = tmp_path / "i2c-health.jsonl"
        path.write_text('{"event":"failed"}\nNOT JSON AT ALL\n', encoding="utf-8")
        rows = I2cHealthRecorder(path=path).readAll()
        assert len(rows) == 1, "one good line survives; the garbage is skipped"


class TestWiredIntoTheClient:
    """The recorder is useless unless the retry path actually calls it."""

    def _client(self, recorder):
        from src.pi.hardware.i2c_client import I2cClient
        client = I2cClient.__new__(I2cClient)      # bypass hardware init
        client._maxRetries = 2
        client._initialDelay = 0
        client._backoffMultiplier = 1
        client._recorder = recorder
        # Set explicitly because __new__ skips __init__: I2cClient.__del__ calls
        # close(), which reads self._smbus. Production always has it (__init__
        # assigns it before it can raise), so this is a test-construction
        # artefact, NOT a defect being papered over -- but a __del__ that raises
        # produces unraisable-exception noise that would obscure a real failure
        # in this suite later.
        client._smbus = None
        return client

    def test_firstAttemptSuccessRecordsNOTHING(self, tmp_path):
        """The healthy path must stay silent -- else the record is all noise."""
        rec = I2cHealthRecorder(path=tmp_path / "h.jsonl")
        client = self._client(rec)
        assert client._executeWithRetry("readWord", 0x36, 0x02, lambda: 4200) == 4200
        assert rec.readAll() == []

    def test_retryThenSuccessIsRecordedAsRECOVERED(self, tmp_path):
        """The early-warning signal: a bus that is degrading but still working."""
        rec = I2cHealthRecorder(path=tmp_path / "h.jsonl")
        client = self._client(rec)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise _Boom(5)
            return 4200

        assert client._executeWithRetry("readWord", 0x36, 0x02, flaky) == 4200
        rows = rec.readAll()
        assert [r["event"] for r in rows] == ["retried", "recovered"]
        assert rows[-1]["attempts"] == 2

    def test_exhaustedRetriesRecordedAsFAILED(self, tmp_path):
        from src.pi.hardware.i2c_client import I2cCommunicationError
        rec = I2cHealthRecorder(path=tmp_path / "h.jsonl")
        client = self._client(rec)

        def always():
            raise _Boom(5)

        with pytest.raises(I2cCommunicationError):
            client._executeWithRetry("readWord", 0x36, 0x02, always)

        assert rec.readAll()[-1]["event"] == "failed"

    def test_deviceNotFoundIsDistinctFromABusFault(self, tmp_path):
        """ENODEV means 'nothing is there', which is NOT the bus misbehaving.
        Conflating them would make an absent sensor look like the contention
        we are hunting."""
        from src.pi.hardware.i2c_client import I2cDeviceNotFoundError
        rec = I2cHealthRecorder(path=tmp_path / "h.jsonl")
        client = self._client(rec)

        def missing():
            raise _Boom(19)

        with pytest.raises(I2cDeviceNotFoundError):
            client._executeWithRetry("readWord", 0x36, 0x02, missing)

        assert rec.readAll()[-1]["event"] == "device_missing"

    def test_aBrokenRecorderDoesNotBreakTheRead(self, tmp_path):
        """If the instrument throws, the bus read still returns."""
        class Exploding:
            def record(self, *a, **k):
                raise RuntimeError("instrument is broken")

        client = self._client(Exploding())
        assert client._executeWithRetry("readWord", 0x36, 0x02, lambda: 4200) == 4200
