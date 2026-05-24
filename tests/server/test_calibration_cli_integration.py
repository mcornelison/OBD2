################################################################################
# File Name: test_calibration_cli_integration.py
# Purpose/Description: Sprint 29 US-312 (I-018 close) -- end-to-end integration
#                      gate for the calibration CLI. Two layers:
#                        Layer 1 -- importing src/server/analytics/calibration.py
#                          as a script must NOT raise ImportError. Pre-fix this
#                          fails because src/server/analytics/types.py shadows
#                          the Python stdlib `types` module: when statistics ->
#                          re -> enum -> `from types import GenericAlias` runs
#                          under sys.path[0]=src/server/analytics/, Python
#                          finds the local types.py and raises ImportError.
#                        Layer 2 -- scripts/report.py --calibrate --apply must
#                          run to completion against a DB with the baselines
#                          table present, returning exit-0 and writing at
#                          least one baselines row for the seeded real
#                          drives. Pre-fix this fails on either layer.
#                      Acceptance criterion #4 from sprint.json: "would FAIL
#                      pre-fix on either import-error or missing-table error".
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex          | Initial -- Sprint 29 US-312 TDD (I-018 close).
# ================================================================================
################################################################################

"""TDD integration test for the US-312 calibration CLI fix (I-018 close).

Layer 1: stdlib `types` shadow.  Pre-fix repro is exactly what the I-018
issue documents:

    python src/server/analytics/calibration.py
    -> ImportError: cannot import name 'GenericAlias' from 'types'

The post-fix world has the analytics types renamed to ``analytics_types``
so stdlib lookups never collide.  The subprocess test sets
``PYTHONPATH`` to the project root so ``src.server.db.models`` resolves
when the script's ``sys.path[0]`` is ``src/server/analytics/`` -- the
discriminator we care about is whether the stdlib ``types`` shadow
fires, NOT the script's ability to find project modules.

Layer 2: missing baselines table.  The CLI lives in scripts/report.py
under --calibrate --apply (calibration.py itself has no CLI).  The
in-process test builds an in-memory SQLite DB via SQLAlchemy
``Base.metadata.create_all()`` -- this tests that the Baseline ORM model
is wired into the metadata graph at all.  The migration runner that
creates the table on live MariaDB (where create_all does not run) is
covered separately in tests/server/test_migration_0008_baselines.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.db.models import Base, Baseline, DriveStatistic, DriveSummary

# ================================================================================
# Layer 1 -- stdlib types shadow regression gate
# ================================================================================


PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CALIBRATION_SCRIPT: Path = (
    PROJECT_ROOT / 'src' / 'server' / 'analytics' / 'calibration.py'
)


class TestStdlibTypesShadowRegression:
    """Discriminator for the I-018 Layer 1 bug.

    Running ``python src/server/analytics/calibration.py`` puts
    ``src/server/analytics/`` at ``sys.path[0]``.  Pre-fix that directory
    contained a ``types.py``, which shadows the stdlib ``types`` module
    when stdlib code tries to import ``GenericAlias`` from it.  Post-fix
    the file is named ``analytics_types.py`` so the shadow is impossible.
    """

    def test_calibrationModule_importsCleanly_asScript(self) -> None:
        # The exact production-shape invocation from the I-018 issue,
        # with PYTHONPATH=project root so project imports also resolve
        # (the script's auto-sys.path[0] would otherwise hide the
        # `src` package).  Pre-fix: subprocess exits non-zero with
        # ImportError on `GenericAlias` (stdlib types shadow).  Post-fix:
        # exits 0 (calibration.py has no __main__ guard so it runs its
        # module-level imports and ends cleanly).
        env = os.environ.copy()
        env['PYTHONPATH'] = str(PROJECT_ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        result = subprocess.run(
            [sys.executable, str(CALIBRATION_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # The discriminator we care about: NO GenericAlias error in
        # stderr.  Pre-fix this assertion fails because the stdlib types
        # shadow fires before line 58's project import even runs.
        assert 'GenericAlias' not in result.stderr, (
            f'GenericAlias error in stderr indicates the stdlib types '
            f'shadow is back (I-018 Layer 1 regression): {result.stderr}'
        )
        assert result.returncode == 0, (
            f'calibration.py crashed at import (post-fix Layer 1 should '
            f'be clean). stderr=\n{result.stderr}'
        )

    def test_analyticsPackage_doesNotExposeShadowingTypesModule(self) -> None:
        # Standing rule from I-014 + I-018: never name a local module after
        # a Python stdlib module.  This test asserts the analytics package
        # honors the rule by NOT having a `types.py` file alongside its
        # other modules.  If a future refactor re-introduces `types.py`,
        # this test fails loudly before the production crash returns.
        analyticsDir = PROJECT_ROOT / 'src' / 'server' / 'analytics'
        shadowingFile = analyticsDir / 'types.py'
        assert not shadowingFile.exists(), (
            'src/server/analytics/types.py shadows stdlib types '
            '(I-018 regression). Rename to analytics_types.py.'
        )


# ================================================================================
# Layer 2 -- end-to-end calibration CLI happy path
# ================================================================================


@pytest.fixture()
def seededSqliteEngine(tmp_path: Path):
    """Build an in-memory SQLite DB with all server models + seeded data.

    Seeds 5 real drives (>= MIN_REAL_DRIVES) plus 5 sim drives with
    diverging stats on a single parameter so proposeCalibration produces
    at least one UPDATE proposal.  ``baselines`` is created from the
    Baseline ORM via ``Base.metadata.create_all`` -- mirrors a fresh-DB
    deploy where the live-MariaDB migration ALSO has to land (Layer 2
    coverage in test_migration_0008_baselines.py).
    """
    dbPath = tmp_path / 'us312.db'
    engine = create_engine(f'sqlite:///{dbPath}')
    Base.metadata.create_all(engine)

    deviceId = 'chi-eclipse-01'
    paramName = 'COOLANT_TEMP'
    baseTime = datetime(2026, 5, 1, 12, 0, 0)
    with Session(engine) as session:
        # 5 real drives with avg_value diverging materially from sim baseline.
        for i in range(5):
            startTs = baseTime + timedelta(days=i)
            drive = DriveSummary(
                device_id=deviceId,
                start_time=startTs,
                end_time=startTs + timedelta(minutes=15),
                duration_seconds=900,
                row_count=500,
                is_real=True,
                data_source='real',
            )
            session.add(drive)
            session.flush()
            session.add(
                DriveStatistic(
                    drive_id=drive.id,
                    parameter_name=paramName,
                    min_value=80.0,
                    max_value=95.0,
                    avg_value=90.0,
                    std_dev=2.0,
                    outlier_min=78.0,
                    outlier_max=98.0,
                    sample_count=500,
                ),
            )
        # 5 sim baseline drives with a noticeably different avg_value so
        # the percentage delta clears the 2% threshold.
        for i in range(5):
            startTs = baseTime - timedelta(days=10 + i)
            drive = DriveSummary(
                device_id=deviceId,
                start_time=startTs,
                end_time=startTs + timedelta(minutes=15),
                duration_seconds=900,
                row_count=500,
                is_real=False,
                data_source='physics_sim',
            )
            session.add(drive)
            session.flush()
            session.add(
                DriveStatistic(
                    drive_id=drive.id,
                    parameter_name=paramName,
                    min_value=70.0,
                    max_value=85.0,
                    avg_value=80.0,
                    std_dev=2.0,
                    outlier_min=68.0,
                    outlier_max=88.0,
                    sample_count=500,
                ),
            )
        session.commit()

    yield engine, deviceId
    engine.dispose()


class TestCalibrationCliEndToEnd:
    """Layer 2 + integrated path: calibrate --apply must run to completion
    and write rows to the baselines table.  Pre-fix this fails because
    the import chain through scripts/report.py picks up the broken
    analytics package and never reaches the SQL INSERT.
    """

    def test_calibrateApply_runsToCompletion_andWritesBaselineRow(
        self, seededSqliteEngine, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        engine, deviceId = seededSqliteEngine
        # Pin the env so report._resolveDbUrl picks our SQLite engine path.
        # SQLAlchemy URL string round-trips through engine.url.
        monkeypatch.setenv('DATABASE_URL', str(engine.url))

        # Late import is intentional -- we want the import to resolve
        # AFTER the env is set and AFTER the rename fix is in place.
        # The rename fix updates the analytics-package types module so the
        # whole import graph through scripts/report.py -> drive_report ->
        # analytics_types resolves cleanly without shadowing stdlib.
        from scripts import report

        exitCode = report.main([
            '--calibrate', '--apply', '--device', deviceId,
        ])
        assert exitCode == 0, (
            'calibrate --apply CLI did not exit 0 cleanly'
        )
        captured = capsys.readouterr()
        assert 'Applied' in captured.out, (
            f'expected "Applied N baseline(s)" in CLI output; got: '
            f'{captured.out!r}'
        )

        # The acceptance criterion: at least one baselines row is written.
        with Session(engine) as session:
            rows = session.execute(
                select(Baseline).where(Baseline.device_id == deviceId),
            ).scalars().all()
            assert len(rows) >= 1, (
                'calibrate --apply must write at least one baselines row '
                f'for device {deviceId!r}'
            )
            # Spot-check the proposal landed for our seeded parameter.
            paramNames = {row.parameter_name for row in rows}
            assert 'COOLANT_TEMP' in paramNames, (
                f'expected COOLANT_TEMP in baselines; got {paramNames}'
            )

    def test_baselineModelRegisteredInMetadata(self) -> None:
        # Sanity gate: if a future refactor forgets to import Baseline in
        # the analytics-package __init__, Base.metadata.create_all stops
        # creating the table and Layer 2 silently regresses for tests.
        # The migration v0008 covers production; this test covers tests.
        assert 'baselines' in Base.metadata.tables, (
            'Baseline ORM not registered in metadata; '
            'create_all will not produce the baselines table'
        )
