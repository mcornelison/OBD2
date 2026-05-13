################################################################################
# File Name: test_backfill_stranded_idempotent.py
# Purpose/Description: US-327 / I-027 -- regression coverage for the idempotent
#                      deploy-time invocation of
#                      scripts/backfill_server_battery_health_log_stranded.py.
#                      V0.27.6 US-323 shipped the backfill script but nothing
#                      auto-invoked it, so the stranded server-side
#                      battery_health_log rows (drain_event_ids 11-15,
#                      end_timestamp NULL) stayed NULL.  US-327 wires it into
#                      deploy-server.sh via a cheap server-only --count-stranded
#                      pre-check followed by --dry-run + --execute when the count
#                      is > 0.  These tests pin (a) the new --count-stranded mode
#                      (server-only -- no Pi SSH, no mutation, no sentinel) and
#                      the countStrandedServerRows helper, and (b) the
#                      deploy-step flow run twice over a stateful fake server:
#                      first run UPDATEs all 5 rows, second run is a no-op
#                      (count-stranded returns 0).  A FakeRunner stands in for
#                      SSH/MariaDB/SQLite so nothing real is touched.
#
#                      Pre-fix these tests FAIL: --count-stranded is not a
#                      recognised CLI argument (argparse SystemExit) and
#                      countStrandedServerRows does not exist (AttributeError).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Rex (US-327) | Initial -- idempotent deploy-time backfill
#                               coverage (I-027): --count-stranded mode +
#                               countStrandedServerRows helper + run-twice
#                               no-op flow over a stateful fake server.
# ================================================================================
################################################################################

"""TDD tests for the US-327 / I-027 idempotent stranded-row backfill wiring.

``deploy/deploy-server.sh`` Step 4.6 invokes
``scripts/backfill_server_battery_health_log_stranded.py`` like so::

    n=$(python backfill_..._stranded.py --count-stranded --addresses addresses.sh)
    if [ "$n" -gt 0 ]; then
        python backfill_..._stranded.py --dry-run  --addresses addresses.sh
        python backfill_..._stranded.py --execute  --addresses addresses.sh
    fi

so the first deploy after V0.27.7 populates rows 11-15 and every subsequent
deploy is a no-op.  These tests exercise that flow against a stateful
:class:`StatefulServerFakeRunner` that flips the targeted rows from NULL to
populated once the UPDATE batch is applied, proving the second run does
nothing.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ================================================================================
# Module loader -- mirror the sibling backfill-script tests so the module name
# stays stable regardless of sys.path ordering.
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    _PROJECT_ROOT / 'scripts'
    / 'backfill_server_battery_health_log_stranded.py'
)


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'backfill_server_battery_health_log_stranded', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['backfill_server_battery_health_log_stranded'] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _loadScript()


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr,
    )


# ================================================================================
# Stateful fake runner -- models server-side battery_health_log state so a
# second run sees the rows already populated.
# ================================================================================

_PI_ROWS_OUTPUT = (
    '11|2026-05-10T00:52:28Z|3.42|757\n'
    '12|2026-05-10T01:12:43Z|3.44|642\n'
    '13|2026-05-10T02:34:59Z|3.43|612\n'
    '14|2026-05-10T03:47:44Z|3.42|722\n'
    '15|2026-05-10T14:13:49Z|3.445|786\n'
)
_ENV_DUMP = (
    'SERVER_HOST=10.2.2.2\nSERVER_USER=b\n'
    'PI_HOST=10.2.2.1\nPI_USER=a\nPI_PATH=/x\n'
)
_DATABASE_URL_LINE = 'mysql+aiomysql://u:p@localhost/dbx\n'


@dataclass
class StatefulServerFakeRunner:
    """Scripted CommandRunner that tracks server-side row state across calls.

    A ``SELECT id, end_timestamp ...`` reflects the current NULL/populated
    state; an ``UPDATE battery_health_log ... WHERE id = N`` flips id N to
    populated so a later SELECT (next deploy run) sees a no-op.
    """

    knownIds: set[int] = field(default_factory=lambda: {11, 12, 13, 14, 15})
    strandedIds: set[int] = field(default_factory=lambda: {11, 12, 13, 14, 15})
    piRowsOutput: str = _PI_ROWS_OUTPUT
    calls: list[dict] = field(default_factory=list)
    updateBatchesSent: int = 0

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- matches Protocol
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append({'argv': list(argv), 'input': input})
        joined = ' '.join(argv)
        payload = input or ''
        # NOTE: mysql/mysqldump get their SQL via the `input` payload, not argv
        # (see _runServerSql), so SELECT/UPDATE dispatch keys off `payload`.
        if 'bash' in argv and '-c' in argv:  # loadAddresses / loadPiCoordinates
            return _ok(stdout=_ENV_DUMP)
        if 'DATABASE_URL=' in joined:  # loadServerCreds ssh (cmd in argv)
            return _ok(stdout=_DATABASE_URL_LINE)
        if 'sqlite3' in joined:  # scanPiRows ssh (cmd in argv)
            return _ok(stdout=self.piRowsOutput)
        if 'SELECT id, end_timestamp FROM battery_health_log' in payload:
            match = re.search(r'id IN \(([^)]*)\)', payload)
            requested = (
                {int(tok) for tok in match.group(1).split(',') if tok.strip()}
                if match else set(self.knownIds)
            )
            lines = []
            for rowId in sorted(self.knownIds & requested):
                if rowId in self.strandedIds:
                    lines.append(f'{rowId}\tNULL')
                else:
                    lines.append(f'{rowId}\t2026-05-10 0{rowId % 10}:00:00')
            return _ok(stdout='\n'.join(lines) + '\n')
        if 'mysqldump' in joined:  # backupServer ssh (cmd in argv)
            return _ok(stdout='')
        if 'stat -c %s' in joined:  # backupServer size guard
            return _ok(stdout='2048\n')
        if 'UPDATE battery_health_log' in payload:  # applyBackfill ssh
            updated = {int(m) for m in re.findall(r'WHERE id = (\d+)', payload)}
            self.strandedIds -= updated
            self.updateBatchesSent += 1
            return _ok(stdout='')
        return _ok(stdout='')

    def sqliteCalled(self) -> bool:
        return any(
            'sqlite3' in arg for call in self.calls for arg in call['argv']
        )

    def updateCalled(self) -> bool:
        return any(
            'UPDATE battery_health_log' in (call['input'] or '')
            for call in self.calls
        )


def _addressesShFile(tmp_path: Path) -> Path:
    addresses = tmp_path / 'addresses.sh'
    addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
    return addresses


# ================================================================================
# countStrandedServerRows -- pure helper (no I/O)
# ================================================================================

class TestCountStrandedServerRows:
    def test_allNull_countsEveryRow(self) -> None:
        rows = [bf.ServerDrainRow(rowId=i, endTimestamp=None)
                for i in (11, 12, 13, 14, 15)]
        assert bf.countStrandedServerRows(rows) == 5

    def test_allPopulated_countsZero(self) -> None:
        rows = [bf.ServerDrainRow(rowId=i, endTimestamp='2026-05-10 00:00:00')
                for i in (11, 12, 13, 14, 15)]
        assert bf.countStrandedServerRows(rows) == 0

    def test_mixed_countsOnlyTheNullOnes(self) -> None:
        rows = [
            bf.ServerDrainRow(rowId=11, endTimestamp='2026-05-10 00:52:28'),
            bf.ServerDrainRow(rowId=12, endTimestamp=None),
            bf.ServerDrainRow(rowId=13, endTimestamp=None),
            bf.ServerDrainRow(rowId=14, endTimestamp='2026-05-10 03:47:44'),
            bf.ServerDrainRow(rowId=15, endTimestamp=None),
        ]
        assert bf.countStrandedServerRows(rows) == 3

    def test_emptyInput_countsZero(self) -> None:
        assert bf.countStrandedServerRows([]) == 0

    def test_inAllExport(self) -> None:
        assert 'countStrandedServerRows' in bf.__all__


# ================================================================================
# --count-stranded CLI mode -- cheap server-only pre-check for deploy-server.sh
# ================================================================================

class TestCountStrandedCli:
    def test_printsCount_andExitsZero_whenRowsStranded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        runner = StatefulServerFakeRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        rc = bf.main([
            '--count-stranded',
            '--addresses', str(_addressesShFile(tmp_path)),
        ])
        assert rc == 0
        assert capsys.readouterr().out.strip() == '5'

    def test_printsZero_whenNothingStranded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        runner = StatefulServerFakeRunner(strandedIds=set())
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        rc = bf.main([
            '--count-stranded',
            '--addresses', str(_addressesShFile(tmp_path)),
        ])
        assert rc == 0
        assert capsys.readouterr().out.strip() == '0'

    def test_isServerOnly_doesNotSshThePi_norMutate_norWriteSentinel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = StatefulServerFakeRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        bf.main([
            '--count-stranded',
            '--addresses', str(_addressesShFile(tmp_path)),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert not runner.sqliteCalled()       # no Pi SSH (cheap pre-check)
        assert not runner.updateCalled()        # no mutation
        assert runner.updateBatchesSent == 0
        assert not (sentinelDir / bf.DRY_RUN_SENTINEL_NAME).exists()

    def test_respectsDrainEventIdsOverride(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        # Only ids 12 and 14 still stranded; restrict the scan to {11,12,13}.
        runner = StatefulServerFakeRunner(
            knownIds={11, 12, 13, 14, 15}, strandedIds={12, 14},
        )
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        rc = bf.main([
            '--count-stranded',
            '--addresses', str(_addressesShFile(tmp_path)),
            '--drain-event-ids', '11,12,13',
        ])
        assert rc == 0
        assert capsys.readouterr().out.strip() == '1'  # only id 12 in scope

    def test_mutuallyExclusiveWithDryRunAndExecute(self) -> None:
        with pytest.raises(SystemExit):
            bf.main(['--count-stranded', '--dry-run'])
        with pytest.raises(SystemExit):
            bf.main(['--count-stranded', '--execute'])

    def test_serverUnreachable_returnsTwo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003 -- test stub
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout='', stderr='Access denied',
            )

        # addresses.sh sourcing still works; the server SSH fails.
        runner = StatefulServerFakeRunner()
        original = runner.__call__

        def failingServer(argv, *, input=None, timeout=None):  # noqa: A002
            joined = ' '.join(argv)
            if 'DATABASE_URL=' in joined or 'SELECT id, end_timestamp' in joined:
                return boom()
            return original(argv, input=input, timeout=timeout)

        monkeypatch.setattr(bf, '_defaultRunner', failingServer)
        rc = bf.main([
            '--count-stranded',
            '--addresses', str(_addressesShFile(tmp_path)),
        ])
        assert rc == 2


# ================================================================================
# Deploy-step flow run twice -- first run heals all 5, second run is a no-op.
# ================================================================================

class TestDeployStepIdempotent:
    def _deployBackfillStep(
        self, runner: StatefulServerFakeRunner, addresses: Path,
        sentinelDir: Path, capsys,
    ) -> int:
        """Mirror deploy-server.sh Step 4.6: count -> (dry-run -> execute)."""
        assert bf.main([
            '--count-stranded', '--addresses', str(addresses),
        ]) == 0
        count = int(capsys.readouterr().out.strip())
        if count == 0:
            return 0
        assert bf.main([
            '--dry-run', '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 0
        capsys.readouterr()  # drain dry-run report
        assert bf.main([
            '--execute', '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 0
        capsys.readouterr()  # drain execute report
        return count

    def test_firstRunPopulatesFiveRows_secondRunIsNoOp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        runner = StatefulServerFakeRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = _addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()

        # Deploy #1: 5 stranded rows -> 1 UPDATE batch -> all healed.
        firstCount = self._deployBackfillStep(
            runner, addresses, sentinelDir, capsys,
        )
        assert firstCount == 5
        assert runner.strandedIds == set()
        assert runner.updateBatchesSent == 1
        assert runner.updateCalled()
        # sentinel cleared by --execute.
        assert not (sentinelDir / bf.DRY_RUN_SENTINEL_NAME).exists()

        # Deploy #2: nothing stranded -> count-stranded returns 0 -> skip.
        secondCount = self._deployBackfillStep(
            runner, addresses, sentinelDir, capsys,
        )
        assert secondCount == 0
        assert runner.updateBatchesSent == 1  # unchanged: no second batch

    def test_secondExecuteWithoutFreshDryRun_isRejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        # Safety: --execute always requires a prior --dry-run sentinel, so a
        # stale execute cannot fire without re-confirming the plan.
        runner = StatefulServerFakeRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = _addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        assert bf.main([
            '--dry-run', '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 0
        capsys.readouterr()
        assert bf.main([
            '--execute', '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 0
        capsys.readouterr()
        # Second --execute without a fresh --dry-run -> rejected (rc 2).
        assert bf.main([
            '--execute', '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 2
