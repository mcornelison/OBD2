################################################################################
# File Name: test_boot_ladder_report.py
# Purpose/Description: US-861 (F-157) -- desk tests for
#                      scripts/boot_ladder_report.py: the COUNTED / EXCLUDED
#                      classification of each boot from a copy of obd.db plus
#                      per-boot journal exports, the fixed reason order, the
#                      before/after statistics and the VERDICT gate.  Files
#                      only; no ssh, no Pi.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-861) | Initial.
# ================================================================================
################################################################################

"""Tests for the boot ladder report (US-861)."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import boot_ladder_report as report
from src.pi.obdii.database_schema import SCHEMA_BOOT_MILESTONE, SCHEMA_STARTUP_LOG

FIXTURE_DIR = Path(__file__).parent / 'fixtures' / 'boot_ladder'
FIXTURE_DEPLOYS = ['2026-10-08T08:04:00Z', '2026-10-14T15:55:30Z']

#: The fixture README's expectations, one per boot.
FIXTURE_EXPECTED = {
    'b01counted': 'COUNTED',
    'b02nostartuplog': 'EXCLUDED(no_startup_log)',
    'b03warmreboot': 'EXCLUDED(warm_reboot)',
    'b04shortoff': 'EXCLUDED(short_off)',
    'b05noobd': 'EXCLUDED(no_obd)',
    'b06missinglight': 'EXCLUDED(missing_milestone:first_sample_light)',
    'b07obdrestarted': 'EXCLUDED(obd_restarted)',
    'b08deploymidboot': 'EXCLUDED(deploy_mid_boot)',
    'b09firstafterdeploy': 'EXCLUDED(first_after_deploy)',
    '7c6aafaa': 'EXCLUDED(no_obd, deploy_mid_boot, obd_restarted)',
}

#: boot_milestone as Sprint 98 shipped it, before US-860-b added ``id``.
S98_BOOT_MILESTONE = """
CREATE TABLE boot_milestone (
    boot_id TEXT NOT NULL,
    milestone TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    uptime_s REAL NOT NULL,
    PRIMARY KEY (boot_id, milestone)
);
"""

ISO = '%Y-%m-%dT%H:%M:%SZ'
STANDARD_UPTIMES = {
    'kernel_start': 0.0,
    'first_sample_imu': 20.0,
    'first_sample_light': 21.0,
    'first_sample_ups': 22.0,
    'obd_connected': 30.0,
    'first_sample_obd': 32.0,
}
OBD_START = 'eclipse systemd[1]: Started eclipse-obd.service - Eclipse OBD-II Data Logger.'
GRAPHICAL = 'eclipse systemd[1]: Reached target graphical.target - Graphical Interface.'
DASHBOARD = 'eclipse systemd[1]: Started eclipse-dashboard.service - Eclipse Dashboard Kiosk.'


# ================================================================================
# Builders
# ================================================================================

def _createDb(path: Path, shape: str = 'current', startupLogDdl: str = SCHEMA_STARTUP_LOG) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(startupLogDdl)
        conn.executescript(SCHEMA_BOOT_MILESTONE if shape == 'current' else S98_BOOT_MILESTONE)
        conn.commit()
    finally:
        conn.close()


def _fixtureInputs(tmp_path: Path, shape: str = 'current') -> tuple[Path, Path]:
    db = tmp_path / 'obd.db'
    _createDb(db, shape)
    conn = sqlite3.connect(db)
    try:
        conn.executescript((FIXTURE_DIR / 'boot_ladder.sql').read_text(encoding='utf-8'))
        conn.commit()
    finally:
        conn.close()
    return db, FIXTURE_DIR / 'journal'


def _journal(
    journalDir: Path,
    bootId: str,
    lastS: float = 120.0,
    obdStarts: tuple[float, ...] = (8.041,),
    graphicalS: float = 18.734,
    dashboardS: float = 19.512,
) -> None:
    rows = [(0.0, 'eclipse kernel: Booting Linux on physical CPU 0x0')]
    rows += [(s, OBD_START) for s in obdStarts]
    rows += [(graphicalS, GRAPHICAL), (dashboardS, DASHBOARD), (lastS, 'eclipse systemd[1]: idle')]
    text = '-- Journal begins --\n' + ''.join(
        f'[{s:>12.6f}] {msg}\n' for s, msg in sorted(rows, key=lambda r: r[0])
    )
    journalDir.mkdir(parents=True, exist_ok=True)
    (journalDir / f'{bootId}.log').write_text(text, encoding='utf-8')


def _addBoot(
    db: Path,
    journalDir: Path,
    bootId: str,
    kernelStart: datetime,
    uptimes: dict[str, float] | None = None,
    offS: float | None = 3600.0,
    stage: str = 'CLEAN_COMPLETE',
    clean: int = 1,
    startupRow: bool = True,
    **journalKwargs: object,
) -> None:
    """One boot: its startup_log row, its milestone rows and its journal export."""
    conn = sqlite3.connect(db)
    try:
        if startupRow:
            lossAt = None if offS is None else (kernelStart - timedelta(seconds=offS)).strftime(ISO)
            conn.execute(
                'INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, '
                'prior_boot_loss_at) VALUES (?, ?, ?, ?)',
                (bootId, clean, stage, lossAt),
            )
        for name, uptime in (STANDARD_UPTIMES if uptimes is None else uptimes).items():
            conn.execute(
                'INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) '
                'VALUES (?, ?, ?, ?)',
                (bootId, name, (kernelStart + timedelta(seconds=uptime)).strftime(ISO), uptime),
            )
        conn.commit()
    finally:
        conn.close()
    _journal(journalDir, bootId, **journalKwargs)  # type: ignore[arg-type]


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    code = report.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _statuses(out: str) -> dict[str, str]:
    """boot_id -> 'COUNTED' or 'EXCLUDED(...)' from the per-boot lines."""
    found: dict[str, str] = {}
    for line in out.splitlines():
        match = re.match(r'^(\S+)\s+\S+\s+(?:BEFORE|AFTER)\s+(COUNTED|EXCLUDED\(.*\))$', line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _baseArgs(db: Path, journalDir: Path) -> list[str]:
    return ['--db', str(db), '--journal-dir', str(journalDir)]


# ================================================================================
# The fixture set
# ================================================================================

class TestFixtureSet:

    @pytest.mark.parametrize('shape', ['current', 's98'])
    def test_fixtureSet_eachBoot_classifiedAsReadme(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], shape: str,
    ) -> None:
        """
        Given: the fixture rows in either boot_milestone shape and the fixture journals
        When: the report runs with the fixture deploy times
        Then: every boot carries exactly its README classification
        """
        db, journalDir = _fixtureInputs(tmp_path, shape)
        argv = _baseArgs(db, journalDir)
        for deployAt in FIXTURE_DEPLOYS:
            argv += ['--deploy-at', deployAt]

        code, out, _ = _run(capsys, argv)

        assert code == 0
        assert _statuses(out) == FIXTURE_EXPECTED
        assert list(_statuses(out).values()).count('COUNTED') == 1

    def test_fixtureSet_7c6aafaa_reasonsInFixedOrder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _fixtureInputs(tmp_path)
        argv = _baseArgs(db, journalDir) + ['--deploy-at', FIXTURE_DEPLOYS[0],
                                            '--deploy-at', FIXTURE_DEPLOYS[1]]

        _, out, _ = _run(capsys, argv)

        line = next(x for x in out.splitlines() if x.startswith('7c6aafaa '))
        assert line.endswith('EXCLUDED(no_obd, deploy_mid_boot, obd_restarted)')
        assert '2026-10-14T15:43:00Z' in line

    def test_fixtureSet_headerStatesCarPowerIsInferred(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _fixtureInputs(tmp_path)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert 'car power inferred from OBD connect; supply not instrumented' in out.splitlines()

    def test_fixtureSet_noChangeAt_everyBootIsBefore_noVerdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _fixtureInputs(tmp_path)
        argv = _baseArgs(db, journalDir) + ['--deploy-at', FIXTURE_DEPLOYS[0],
                                            '--deploy-at', FIXTURE_DEPLOYS[1]]

        _, out, _ = _run(capsys, argv)

        assert ' AFTER ' not in ''.join(x for x in out.splitlines() if x.startswith('b0'))
        assert 'NO VERDICT: n before 1, after 0' in out.splitlines()


# ================================================================================
# The rules, one at a time
# ================================================================================

class TestClassificationRules:

    def _boot(self, tmp_path: Path, **kwargs: object) -> tuple[Path, Path]:
        db = tmp_path / 'obd.db'
        journalDir = tmp_path / 'journal'
        _createDb(db)
        _addBoot(db, journalDir, 'boot1', datetime(2026, 10, 1, 8, tzinfo=UTC), **kwargs)  # type: ignore[arg-type]
        return db, journalDir

    def test_cleanZero_withoutCleanComplete_isCold(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A prior boot that died hard (clean=0) left the Pi off: counted."""
        db, journalDir = self._boot(tmp_path, stage='POWEROFF_INVOKED', clean=0)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'COUNTED'}

    def test_cleanOne_withoutCleanComplete_isWarmReboot(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._boot(tmp_path, stage='POWEROFF_INVOKED', clean=1)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'EXCLUDED(warm_reboot)'}

    def test_offTimeExactlyMinOff_isCounted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._boot(tmp_path, offS=60.0)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'COUNTED'}

    def test_minOffS_overridesTheDefault(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._boot(tmp_path, offS=600.0)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir) + ['--min-off-s', '900'])

        assert _statuses(out) == {'boot1': 'EXCLUDED(short_off)'}

    def test_offTimeUsesKernelStart_notRecordedAt(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """recorded_at hours after the loss must not rescue a 30 s off-time."""
        db, journalDir = self._boot(tmp_path, offS=30.0)
        conn = sqlite3.connect(db)
        conn.execute("UPDATE startup_log SET recorded_at = '2026-10-01T12:00:00Z'")
        conn.commit()
        conn.close()

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'EXCLUDED(short_off)'}

    def test_missingKernelStart_isMissingMilestone(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        uptimes = {k: v for k, v in STANDARD_UPTIMES.items() if k != 'kernel_start'}
        db, journalDir = self._boot(tmp_path, uptimes=uptimes)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'EXCLUDED(missing_milestone:kernel_start)'}

    def test_obdMilestonesReportOnlyAsNoObd(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """One OBD rung missing is no_obd, never also missing_milestone:<obd rung>."""
        uptimes = {k: v for k, v in STANDARD_UPTIMES.items() if k != 'first_sample_obd'}
        db, journalDir = self._boot(tmp_path, uptimes=uptimes)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'EXCLUDED(no_obd)'}

    def test_driveStart_isNotRequired(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._boot(tmp_path)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert 'drive_start' not in STANDARD_UPTIMES
        assert _statuses(out) == {'boot1': 'COUNTED'}

    def test_noJournalExport_isObdRestarted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No export: eclipse-obd's start count is 0, not 1."""
        db, journalDir = self._boot(tmp_path)
        (journalDir / 'boot1.log').unlink()

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'EXCLUDED(obd_restarted)'}

    def test_everyFailingReason_inFixedOrder(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        uptimes = {'kernel_start': 0.0, 'first_sample_imu': 20.0}
        db, journalDir = self._boot(
            tmp_path, uptimes=uptimes, offS=None, obdStarts=(8.0, 90.0),
        )

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': (
            'EXCLUDED(warm_reboot, no_obd, missing_milestone:first_sample_light, '
            'missing_milestone:first_sample_ups, obd_restarted)'
        )}

    def test_noStartupLogRow_isOneReason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._boot(tmp_path, startupRow=False)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {'boot1': 'EXCLUDED(no_startup_log)'}

    def test_preArch065Copy_everyBootNoStartupLog_oneWarnNamingColumn(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """
        Given: a startup_log with no prior_boot_loss_at column
        When: the report runs
        Then: every boot is EXCLUDED(no_startup_log) and one WARN names the column
        """
        db = tmp_path / 'obd.db'
        journalDir = tmp_path / 'journal'
        # Same shape minus the ARCH-065 column (a stand-in keeps the DDL valid).
        legacyDdl = SCHEMA_STARTUP_LOG.replace('prior_boot_loss_at TEXT', 'pre_arch_065 TEXT')
        assert 'prior_boot_loss_at' not in legacyDdl
        _createDb(db, startupLogDdl=legacyDdl)
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO startup_log (boot_id, prior_boot_clean) VALUES ('boot1', 0)")
        conn.commit()
        conn.close()
        _addBoot(db, journalDir, 'boot1', datetime(2026, 10, 1, 8, tzinfo=UTC), startupRow=False)
        _addBoot(db, journalDir, 'boot2', datetime(2026, 10, 2, 8, tzinfo=UTC), startupRow=False)

        _, out, err = _run(capsys, _baseArgs(db, journalDir))

        assert _statuses(out) == {
            'boot1': 'EXCLUDED(no_startup_log)', 'boot2': 'EXCLUDED(no_startup_log)',
        }
        warns = [x for x in err.splitlines() if x.startswith('WARN')]
        assert len(warns) == 1
        assert 'prior_boot_loss_at' in warns[0]


class TestDeployWindows:
    """Atlas G2: lastWall = kernel_start.ts_utc + the export's last monotonic seconds."""

    def _twoBoots(self, tmp_path: Path) -> tuple[Path, Path]:
        db = tmp_path / 'obd.db'
        journalDir = tmp_path / 'journal'
        _createDb(db)
        # boot1's lastWall is 08:05:00 (kernel_start 08:00:00 + 300 s).
        _addBoot(db, journalDir, 'boot1', datetime(2026, 10, 1, 8, tzinfo=UTC), lastS=300.0)
        _addBoot(db, journalDir, 'boot2', datetime(2026, 10, 2, 8, tzinfo=UTC))
        return db, journalDir

    def test_deployOneSecondBeforeLastWall_isDeployMidBoot(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._twoBoots(tmp_path)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir) + ['--deploy-at', '2026-10-01T08:04:59Z'])

        assert _statuses(out) == {
            'boot1': 'EXCLUDED(deploy_mid_boot)',
            'boot2': 'EXCLUDED(first_after_deploy)',
        }

    def test_deployOneSecondAfterLastWall_nextBootIsFirstAfterDeploy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._twoBoots(tmp_path)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir) + ['--deploy-at', '2026-10-01T08:05:01Z'])

        assert _statuses(out) == {
            'boot1': 'COUNTED',
            'boot2': 'EXCLUDED(first_after_deploy)',
        }

    def test_changeAtNotADeploy_oneWarn_treatedAsDeploy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._twoBoots(tmp_path)

        _, out, err = _run(capsys, _baseArgs(db, journalDir) + ['--change-at', '2026-10-01T12:00:00Z'])

        warns = [x for x in err.splitlines() if x.startswith('WARN')]
        assert len(warns) == 1
        assert '2026-10-01T12:00:00Z' in warns[0]
        assert _statuses(out) == {
            'boot1': 'COUNTED',
            'boot2': 'EXCLUDED(first_after_deploy)',
        }
        assert re.search(r'^boot1\s+\S+\s+BEFORE\s', out, re.MULTILINE)
        assert re.search(r'^boot2\s+\S+\s+AFTER\s', out, re.MULTILINE)

    def test_changeAtAlreadyADeploy_noWarn(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = self._twoBoots(tmp_path)
        argv = _baseArgs(db, journalDir) + [
            '--deploy-at', '2026-10-01T12:00:00Z', '--change-at', '2026-10-01T12:00:00Z',
        ]

        _, _, err = _run(capsys, argv)

        assert not [x for x in err.splitlines() if x.startswith('WARN')]


# ================================================================================
# Statistics and the VERDICT gate
# ================================================================================

CHANGE_AT = '2026-10-15T00:00:00Z'


def _ladder(tmp_path: Path, obdBefore: list[float], obdAfter: list[float]) -> tuple[Path, Path]:
    """Counted boots before and after CHANGE_AT, with first_sample_obd varying.

    The first boot after the change is a deliberately excluded sacrificial boot
    (first_after_deploy), so the AFTER counted set is exactly ``obdAfter``.
    """
    db = tmp_path / 'obd.db'
    journalDir = tmp_path / 'journal'
    _createDb(db)
    start = datetime(2026, 10, 1, 8, tzinfo=UTC)
    for i, obd in enumerate(obdBefore):
        uptimes = dict(STANDARD_UPTIMES, first_sample_obd=obd, obd_connected=obd - 2.0)
        _addBoot(db, journalDir, f'before{i}', start + timedelta(days=i), uptimes=uptimes,
                 graphicalS=28.0)
    afterStart = datetime(2026, 10, 16, 8, tzinfo=UTC)
    _addBoot(db, journalDir, 'sacrificial', afterStart)
    for i, obd in enumerate(obdAfter):
        uptimes = dict(STANDARD_UPTIMES, first_sample_obd=obd, obd_connected=obd - 2.0)
        _addBoot(db, journalDir, f'after{i}', afterStart + timedelta(days=i + 1),
                 uptimes=uptimes, graphicalS=18.0)
    return db, journalDir


def _statLine(out: str, milestone: str) -> str:
    return next(x for x in out.splitlines() if x.split()[:1] == [milestone])


class TestStatistics:

    def test_fiveBeforeFourAfter_statisticsButNoVerdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _ladder(tmp_path, [61.0, 63.0, 65.0, 68.0, 70.0], [52.0, 55.0, 56.0, 58.0])
        argv = _baseArgs(db, journalDir) + ['--deploy-at', CHANGE_AT, '--change-at', CHANGE_AT]

        code, out, _ = _run(capsys, argv)

        assert code == 0
        assert _statuses(out)['sacrificial'] == 'EXCLUDED(first_after_deploy)'
        line = _statLine(out, 'first_sample_obd')
        assert 'BEFORE n=5 median 65.0 s min 61.0 max 70.0 spread 9.0' in line
        assert 'AFTER n=4 median 55.5 s min 52.0 max 58.0 spread 6.0' in line
        assert 'NO VERDICT: n before 5, after 4' in out.splitlines()
        assert not [x for x in out.splitlines() if x.startswith('VERDICT')]

    def test_fiveAndFive_verdictCarriesMedianDeltas(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _ladder(
            tmp_path, [61.0, 63.0, 65.2, 68.0, 70.4], [50.0, 53.0, 55.1, 57.0, 59.0],
        )
        argv = _baseArgs(db, journalDir) + ['--deploy-at', CHANGE_AT, '--change-at', CHANGE_AT]

        _, out, _ = _run(capsys, argv)

        verdicts = [x for x in out.splitlines() if x.startswith('VERDICT')]
        assert len(verdicts) == 1
        assert 'first_sample_obd -10.1 s' in verdicts[0]
        assert 'obd_connected -10.1 s' in verdicts[0]
        assert 'graphical.target -10.0 s' in verdicts[0]
        assert 'NO VERDICT' not in out

    def test_journalMilestones_reportedBesideBootMilestones(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _ladder(tmp_path, [65.0], [])
        argv = _baseArgs(db, journalDir) + ['--deploy-at', CHANGE_AT, '--change-at', CHANGE_AT]

        _, out, _ = _run(capsys, argv)

        assert 'BEFORE n=1 median 28.0 s' in _statLine(out, 'graphical.target')
        assert 'BEFORE n=1 median 19.5 s' in _statLine(out, 'eclipse-dashboard')
        assert 'BEFORE n=1 median 20.0 s' in _statLine(out, 'first_sample_imu')

    def test_excludedBoots_neverReachTheStatistics(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _fixtureInputs(tmp_path)

        _, out, _ = _run(capsys, _baseArgs(db, journalDir) + ['--deploy-at', FIXTURE_DEPLOYS[0],
                                                              '--deploy-at', FIXTURE_DEPLOYS[1]])

        assert 'BEFORE n=1 median 32.0 s min 32.0 max 32.0 spread 0.0' in _statLine(
            out, 'first_sample_obd')


# ================================================================================
# Inputs
# ================================================================================

class TestInputs:

    def test_missingDb_failsLoudNamingThePath(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        missing = tmp_path / 'nope.db'
        (tmp_path / 'journal').mkdir()

        code, _, err = _run(capsys, _baseArgs(missing, tmp_path / 'journal'))

        assert code == 1
        assert err.startswith('ERROR') and str(missing) in err
        assert not missing.exists()

    def test_missingJournalDir_failsLoud(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / 'obd.db'
        _createDb(db)

        code, _, err = _run(capsys, _baseArgs(db, tmp_path / 'absent'))

        assert code == 1
        assert 'absent' in err

    def test_badDeployAt_isAUsageError(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        db, journalDir = _fixtureInputs(tmp_path)

        with pytest.raises(SystemExit) as exc:
            report.main(_baseArgs(db, journalDir) + ['--deploy-at', 'yesterday'])

        assert exc.value.code == 2

    def test_dbIsOpenedReadOnly(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        db, journalDir = _fixtureInputs(tmp_path)
        before = db.read_bytes()

        _run(capsys, _baseArgs(db, journalDir))

        assert db.read_bytes() == before

    def test_parseJournal_shortMonotonic(self, tmp_path: Path) -> None:
        _journal(tmp_path, 'b', lastS=812.5, obdStarts=(8.0, 700.0))

        summary = report.parseJournal(tmp_path / 'b.log')

        assert summary.obdStarts == 2
        assert summary.lastMonotonicS == 812.5
        assert summary.graphicalTargetS == 18.734
        assert summary.dashboardStartedS == 19.512
