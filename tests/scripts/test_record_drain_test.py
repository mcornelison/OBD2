################################################################################
# File Name: test_record_drain_test.py
# Purpose/Description: Outcome-based tests for scripts/record_drain_test.py,
#                      centered on US-224 (--load-class CLI default flip from
#                      'production' to 'test').  Asserts the new default on the
#                      argparse boundary, pins explicit behavior for all three
#                      enum values (production / test / sim), verifies the help
#                      text carries the new-default rationale, and checks the
#                      --dry-run output so a CIO running the command blind sees
#                      the load_class printed back.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-224) | Initial -- pin 'test' as CLI default + explicit
#                                production/sim paths; guard docstring rationale.
# 2026-07-01    | Rex (US-427) | BL-015 register-SoC% wiring + US-234 cold-start
#                                guard: pin readCalibratedRegisterSocPct (past-
#                                window reads register, in-window/unknown ->
#                                None-without-reading, read-error -> None) + the
#                                _recordEvent DB path (past-window populates
#                                start/end_soc_pct; in-window records NULL).
# 2026-07-02    | Rex (US-431) | F-048: pin _resolveColdStartWindowSeconds (reads
#                                the config key, falls back to the constant) + the
#                                config-driven window flowing through _recordEvent.
# ================================================================================
################################################################################

"""Tests for :mod:`scripts.record_drain_test`.

Scope: US-224's CLI default flip.  The library-level ``LOAD_CLASS_DEFAULT``
constant at :mod:`src.pi.power.battery_health` stays ``'production'``
(that path feeds US-216's Power-Down Orchestrator auto-write for real
shutdowns); only this CLI's argparse surface changes.  These tests pin
both halves of that contract.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from pi.hardware.ups_monitor import UpsMonitorError
from pi.power.battery_health import LOAD_CLASS_DEFAULT
from scripts import record_drain_test

# Repo root: tests/scripts/test_record_drain_test.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _runEntryPointCleanEnv(
    scriptRelPath: str, *args: str,
) -> subprocess.CompletedProcess[str]:
    """Run a ``scripts/`` entry point exactly as an operator does on the Pi.

    Reproduces a bare ``python scripts/<name>.py`` invocation: a fresh
    interpreter whose only path bootstrap is whatever the script does for
    itself.  ``PYTHONPATH`` is stripped so the test fails if the script
    leans on an external path override instead of putting ``src/`` on
    ``sys.path`` itself (the convention the live systemd services use).

    Args:
        scriptRelPath: Repo-relative path to the entry point, e.g.
            ``"scripts/record_drain_test.py"``.
        *args: CLI arguments (``--help`` triggers the full module-import
            chain, then argparse exits 0).

    Returns:
        The completed subprocess with captured ``stdout`` / ``stderr``.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(_REPO_ROOT / scriptRelPath), *args],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

# =============================================================================
# Constants + fixtures
# =============================================================================


_REQUIRED_ARGS: tuple[str, ...] = (
    '--start-soc', '100',
    '--end-soc', '20',
    '--runtime', '1440',
)


# =============================================================================
# TestDefaultLoadClass -- core US-224 behavior
# =============================================================================


class TestDefaultLoadClass:
    """US-224: the CLI default flips from 'production' to 'test'."""

    def test_parseArguments_omitLoadClass_defaultsToTest(self) -> None:
        """
        Given: argv without --load-class.
        When:  parseArguments runs.
        Then:  args.load_class == 'test'.
        """
        args = record_drain_test.parseArguments(list(_REQUIRED_ARGS))
        assert args.load_class == 'test'

    def test_cliDefault_doesNotEqualLibraryDefault(self) -> None:
        """The CLI default MUST differ from the library default (invariant).

        Library default stays 'production' (US-216 orchestrator auto-write
        path).  CLI default is now 'test'.  This test locks the divergence
        so a future refactor that unifies the two gets caught.
        """
        args = record_drain_test.parseArguments(list(_REQUIRED_ARGS))
        assert LOAD_CLASS_DEFAULT == 'production'
        assert args.load_class != LOAD_CLASS_DEFAULT


# =============================================================================
# TestExplicitLoadClass -- enum value behavior preserved
# =============================================================================


class TestExplicitLoadClass:
    """All three enum values remain explicitly selectable (story invariant)."""

    @pytest.mark.parametrize(
        'loadClass', ['production', 'test', 'sim'],
    )
    def test_parseArguments_explicitLoadClass_preserved(
        self, loadClass: str,
    ) -> None:
        """
        Given: argv with --load-class <value> for each enum member.
        When:  parseArguments runs.
        Then:  args.load_class equals the explicit value.
        """
        argv = list(_REQUIRED_ARGS) + ['--load-class', loadClass]
        args = record_drain_test.parseArguments(argv)
        assert args.load_class == loadClass

    def test_parseArguments_invalidLoadClass_argparseExits(self) -> None:
        """
        Given: argv with --load-class <bogus>.
        When:  parseArguments runs.
        Then:  argparse raises SystemExit(2) (unchanged from before US-224).
        """
        argv = list(_REQUIRED_ARGS) + ['--load-class', 'bogus']
        with pytest.raises(SystemExit):
            record_drain_test.parseArguments(argv)


# =============================================================================
# TestHelpText -- operator sees the new default + rationale
# =============================================================================


class TestHelpText:
    """Help text must communicate the new default + the drill rationale."""

    def test_helpText_mentionsTestAsDefault(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--help output names 'test' as the --load-class default."""
        with pytest.raises(SystemExit):
            record_drain_test.parseArguments(['--help'])
        captured = capsys.readouterr().out
        assert '--load-class' in captured
        assert 'default: test' in captured

    def test_helpText_carriesDrillRationale(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--help output explains WHY the CLI default differs from the library.

        The phrase 'typically a drill' is unique to the US-224 help prose
        -- it names the reason CIO CLI invocations default to
        load_class='test' instead of the library default 'production'.
        Using a distinctive phrase (not just 'drill', which appears in
        unrelated --start-soc help) pins the rationale to the
        --load-class section specifically.
        """
        with pytest.raises(SystemExit):
            record_drain_test.parseArguments(['--help'])
        captured = capsys.readouterr().out
        # argparse HelpFormatter wraps long help text across lines with
        # leading whitespace; normalize so wrapping does not masquerade
        # as a missing phrase.
        normalized = ' '.join(captured.split())
        assert 'typically a drill' in normalized


# =============================================================================
# TestDryRunSurface -- CIO-visible confirmation of load_class
# =============================================================================


class TestDryRunSurface:
    """--dry-run must print the resolved load_class so a CIO sees the default."""

    def test_main_dryRunOmitLoadClass_printsTest(
        self,
        tmp_path: pytest.TempPathFactory,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given: --dry-run with no --load-class.
        When:  main runs.
        Then:  stdout shows 'load_class:  test' AND exit code is 0.
        """
        cfgPath = _writeMinimalConfig(tmp_path)
        monkeypatch.setenv('COMPANION_API_KEY', 'test-key')
        argv = list(_REQUIRED_ARGS) + ['--dry-run', '--config', cfgPath]

        exitCode = record_drain_test.main(argv)

        out = capsys.readouterr().out
        assert exitCode == 0
        assert 'DRY RUN' in out
        assert 'load_class:  test' in out

    def test_main_dryRunExplicitProduction_printsProduction(
        self,
        tmp_path: pytest.TempPathFactory,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given: --dry-run with --load-class production.
        When:  main runs.
        Then:  stdout shows 'load_class:  production' (opt-in still works).
        """
        cfgPath = _writeMinimalConfig(tmp_path)
        monkeypatch.setenv('COMPANION_API_KEY', 'test-key')
        argv = (
            list(_REQUIRED_ARGS)
            + ['--dry-run', '--load-class', 'production', '--config', cfgPath]
        )

        exitCode = record_drain_test.main(argv)

        out = capsys.readouterr().out
        assert exitCode == 0
        assert 'load_class:  production' in out


# =============================================================================
# Helpers
# =============================================================================


def _writeMinimalConfig(tmp_path) -> str:  # type: ignore[no-untyped-def]
    """Write a minimal config.json the secrets loader + validator accept."""
    import json

    config = {
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'chi-eclipse-01',
        'pi': {
            'database': {'path': str(tmp_path / 'pi-test.db')},
            'companionService': {
                'enabled': True,
                'baseUrl': 'http://10.27.27.10:8000',
                'apiKeyEnv': 'COMPANION_API_KEY',
                'syncTimeoutSeconds': 30,
                'batchSize': 500,
                'retryMaxAttempts': 3,
                'retryBackoffSeconds': [1, 2, 4, 8, 16],
            },
        },
        'server': {},
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    return str(path)


class TestOperatorRuntimeImport:
    """US-397: the CLI must import + run under the bare operator invocation.

    Same regression class as ``test_sync_now`` -- ``record_drain_test``
    inserted only the repo ROOT on ``sys.path`` and imported ``src.pi.*``,
    so the bare ``from pi.display`` inside ``pi.obdii.__init__`` raised
    ``ModuleNotFoundError: No module named 'pi'`` under the real
    ``python scripts/record_drain_test.py`` runtime.  The in-process tests
    above never caught it because ``tests/conftest.py`` seeds ``src/`` onto
    ``sys.path`` for the whole pytest session.
    """

    def test_recordDrainTestCli_bareOperatorInvocation_importsWithoutModuleError(
        self,
    ) -> None:
        """
        Given: a fresh interpreter with no PYTHONPATH override.
        When:  python scripts/record_drain_test.py --help is run from root.
        Then:  the module-import chain resolves (no ModuleNotFoundError)
               and argparse exits 0 after printing help.
        """
        result = _runEntryPointCleanEnv(
            "scripts/record_drain_test.py", "--help",
        )

        assert "ModuleNotFoundError" not in result.stderr, result.stderr
        assert "No module named 'pi'" not in result.stderr, result.stderr
        assert result.returncode == 0, (
            "--help should exit 0 after a clean import; "
            f"rc={result.returncode}\nstderr={result.stderr}"
        )


# =============================================================================
# US-427 -- register SoC% wiring + US-234 cold-start guard
# =============================================================================


class _FakeUps:
    """Minimal UpsMonitor double: counts reads, returns a set percent or raises."""

    def __init__(self, socPct: int = 50, raiseError: bool = False) -> None:
        self._socPct = socPct
        self._raiseError = raiseError
        self.calls = 0

    def getBatteryPercentage(self) -> int:
        self.calls += 1
        if self._raiseError:
            raise UpsMonitorError("UPS not available (bench double)")
        return self._socPct


def _querySocPct(tmp_path) -> tuple[float | None, float | None]:  # type: ignore[no-untyped-def]
    """Read (start_soc_pct, end_soc_pct) from the single recorded drain row."""
    dbPath = tmp_path / 'pi-test.db'
    conn = sqlite3.connect(str(dbPath))
    try:
        row = conn.execute(
            "SELECT start_soc_pct, end_soc_pct FROM battery_health_log "
            "ORDER BY drain_event_id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return (row[0], row[1])


class TestColdStartGuard:
    """readCalibratedRegisterSocPct: honest-instrument cold-start guard (US-234)."""

    def test_pastWindow_returnsRegisterValue(self) -> None:
        """
        Given: uptime beyond the calibration window.
        When:  readCalibratedRegisterSocPct runs.
        Then:  it returns the register SoC% (the gauge is trustworthy).
        """
        fake = _FakeUps(socPct=61)
        result = record_drain_test.readCalibratedRegisterSocPct(
            fake, uptimeSeconds=300.0,
        )
        assert result == 61
        assert fake.calls == 1

    def test_withinWindow_returnsNoneWithoutReading(self) -> None:
        """
        Given: uptime inside the ~3-min cold-start window.
        When:  readCalibratedRegisterSocPct runs.
        Then:  it returns None and NEVER reads the garbage register.
        """
        fake = _FakeUps(socPct=61)
        result = record_drain_test.readCalibratedRegisterSocPct(
            fake, uptimeSeconds=10.0,
        )
        assert result is None
        assert fake.calls == 0

    def test_uptimeUnknown_returnsNone(self) -> None:
        """
        Given: uptime cannot be determined (None).
        When:  readCalibratedRegisterSocPct runs.
        Then:  it returns None -- calibration cannot be proven, so no number.
        """
        fake = _FakeUps(socPct=61)
        result = record_drain_test.readCalibratedRegisterSocPct(
            fake, uptimeSeconds=None,
        )
        assert result is None
        assert fake.calls == 0

    def test_readError_returnsNone(self) -> None:
        """
        Given: the register read raises (hardware absent / I2C error).
        When:  readCalibratedRegisterSocPct runs past the window.
        Then:  it returns None rather than propagating -- NULL, not a crash.
        """
        fake = _FakeUps(raiseError=True)
        result = record_drain_test.readCalibratedRegisterSocPct(
            fake, uptimeSeconds=300.0,
        )
        assert result is None


class TestSocPctRecordingPath:
    """_recordEvent writes register SoC% into start/end_soc_pct (guarded)."""

    def test_recordEvent_pastWindow_populatesSocPct(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given: a bench drill outside the cold-start window.
        When:  _recordEvent runs with an injected UPS reading 73%.
        Then:  the closed row has start_soc_pct == end_soc_pct == 73.
        """
        cfgPath = _writeMinimalConfig(tmp_path)
        monkeypatch.setenv('COMPANION_API_KEY', 'test-key')
        config = record_drain_test._loadConfig(cfgPath)
        args = record_drain_test.parseArguments(list(_REQUIRED_ARGS))
        fake = _FakeUps(socPct=73)

        record_drain_test._recordEvent(
            config, args, monitor=fake, uptimeReader=lambda: 9999.0,
        )

        startPct, endPct = _querySocPct(tmp_path)
        assert startPct == 73.0
        assert endPct == 73.0

    def test_recordEvent_withinWindow_recordsNullSocPct(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given: a drill opened inside the ~3-min cold-start window.
        When:  _recordEvent runs.
        Then:  start/end_soc_pct are NULL (never a garbage percent) and the
               register was never read.
        """
        cfgPath = _writeMinimalConfig(tmp_path)
        monkeypatch.setenv('COMPANION_API_KEY', 'test-key')
        config = record_drain_test._loadConfig(cfgPath)
        args = record_drain_test.parseArguments(list(_REQUIRED_ARGS))
        fake = _FakeUps(socPct=88)

        record_drain_test._recordEvent(
            config, args, monitor=fake, uptimeReader=lambda: 5.0,
        )

        startPct, endPct = _querySocPct(tmp_path)
        assert startPct is None
        assert endPct is None
        assert fake.calls == 0

    def test_recordEvent_populatesVoltageSlotIndependently(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given: a drill outside the window with operator --start-soc voltage.
        When:  _recordEvent runs.
        Then:  the operator voltage still lands in start_vcell_v (US-426),
               separate from the register SoC% -- the two facts don't collide.
        """
        cfgPath = _writeMinimalConfig(tmp_path)
        monkeypatch.setenv('COMPANION_API_KEY', 'test-key')
        config = record_drain_test._loadConfig(cfgPath)
        args = record_drain_test.parseArguments(list(_REQUIRED_ARGS))
        fake = _FakeUps(socPct=42)

        record_drain_test._recordEvent(
            config, args, monitor=fake, uptimeReader=lambda: 9999.0,
        )

        conn = sqlite3.connect(str(tmp_path / 'pi-test.db'))
        try:
            vcell, socPct = conn.execute(
                "SELECT start_vcell_v, start_soc_pct FROM battery_health_log "
                "ORDER BY drain_event_id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        # --start-soc 100 -> the voltage slot; register 42 -> the pct slot.
        assert vcell == 100.0
        assert socPct == 42.0


# =============================================================================
# US-431 -- config-driven cold-start window (F-048 feeds the guard)
# =============================================================================


class TestColdStartWindowConfig:
    """The cold-start guard window is fed from config, not a hard constant."""

    def test_resolve_readsConfigKey(self) -> None:
        """
        Given: a config with pi.hardware.upsMonitor.socColdStartWindowSeconds.
        When:  _resolveColdStartWindowSeconds runs.
        Then:  it returns that measured value (calibration output feeds here).
        """
        config = {
            'pi': {'hardware': {'upsMonitor': {'socColdStartWindowSeconds': 42.0}}}
        }
        assert record_drain_test._resolveColdStartWindowSeconds(config) == 42.0

    def test_resolve_missingKey_fallsBackToConstant(self) -> None:
        """
        Given: a config without the key (older config).
        When:  _resolveColdStartWindowSeconds runs.
        Then:  it falls back to the conservative module constant, no crash.
        """
        assert (
            record_drain_test._resolveColdStartWindowSeconds({})
            == record_drain_test.COLD_START_CALIBRATION_WINDOW_SECONDS
        )

    def test_recordEvent_usesConfiguredWindow(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Given: a lowered window (4s) + an uptime (5s) past THAT window but
               inside the default 180s guard.
        When:  _recordEvent runs.
        Then:  the register IS read (soc_pct populated), proving the config
               value -- not the 180s constant -- drove the guard.
        """
        cfgPath = _writeMinimalConfig(tmp_path)
        monkeypatch.setenv('COMPANION_API_KEY', 'test-key')
        config = record_drain_test._loadConfig(cfgPath)
        config['pi']['hardware']['upsMonitor']['socColdStartWindowSeconds'] = 4.0
        args = record_drain_test.parseArguments(list(_REQUIRED_ARGS))
        fake = _FakeUps(socPct=66)

        record_drain_test._recordEvent(
            config, args, monitor=fake, uptimeReader=lambda: 5.0,
        )

        startPct, endPct = _querySocPct(tmp_path)
        assert startPct == 66.0
        assert endPct == 66.0


# ================================================================================
# US-526: the cold-start guard is SHARED with the production writer, not copied
# ================================================================================


class TestSocCalibrationIsSharedNotCopied:
    """One implementation, two callers (SSOT design directive).

    US-526 moved the cold-start-guarded register read into
    ``src/pi/power/soc_calibration.py`` so the PRODUCTION drain writer reuses
    the identical guard (a ``src/`` module must never import from ``scripts/``).
    These guards fail if someone re-adds a local copy here -- at which point the
    CLI and the production writer could drift on the one rule that keeps a
    garbage SoC%% out of the database.
    """

    def test_cliNamesAreTheSharedObjects(self) -> None:
        """
        Given: the CLI's public register-read surface.
        When:  compared with pi.power.soc_calibration.
        Then:  they are the SAME objects, not equal-looking copies.
        """
        from pi.power import soc_calibration

        assert (
            record_drain_test.readCalibratedRegisterSocPct
            is soc_calibration.readCalibratedRegisterSocPct
        )
        assert (
            record_drain_test._resolveColdStartWindowSeconds
            is soc_calibration.resolveColdStartWindowSeconds
        )
        assert (
            record_drain_test._readSystemUptimeSeconds
            is soc_calibration.readSystemUptimeSeconds
        )
        assert (
            record_drain_test.COLD_START_CALIBRATION_WINDOW_SECONDS
            == soc_calibration.COLD_START_CALIBRATION_WINDOW_SECONDS
        )

    def test_productionWriterUsesTheSameGuard(self) -> None:
        """
        Given: the production drain writer.
        When:  its gauge-read dependency is traced back to a source FILE.
        Then:  it is the same file the CLI's guard comes from -- so the AC's
               "reuse readCalibratedRegisterSocPct + its cold-start window" is
               literally true, not approximately.

        Compared by source file rather than by ``is``: the writer resolves the
        helper through ``src.pi.power.*`` (the form its powerwatch caller uses)
        while this test reaches it through ``pi.power.*``, and those are two
        distinct module objects holding two distinct function objects for the
        SAME source.  That is the dual-import identity trap itself -- which is
        exactly why the writer compares power-source ENUMS by ``.value`` and the
        shared guard catches ``Exception`` rather than a specific class.
        A re-added local copy still fails this: it is a different file.

        Compared with ``os.path.samefile`` and NOT string equality, because the
        two import roots spell the same file differently on the shared checkout:
        one resolves under the mapped drive (``Z:\\o\\OBD2v2\\...``) and the
        other under its UNC target (``\\\\chi-nas-01\\PPS-Projects\\...``).
        String equality reports "different implementation" for a file that IS
        the same file -- a false alarm on the exact SSOT claim this guards.
        ``samefile`` asks the filesystem (st_dev/st_ino) instead, so the guard
        keeps its teeth against a real drifted copy while surviving the
        drive-mapping aliasing.
        """
        import inspect
        import os

        from pi.power import drain_event_writer, soc_calibration

        canonicalSource = inspect.getsourcefile(
            soc_calibration.readCalibratedRegisterSocPct
        )
        assert canonicalSource is not None
        for shared in (
            drain_event_writer.readCalibratedRegisterSocPct,
            record_drain_test.readCalibratedRegisterSocPct,
        ):
            sharedSource = inspect.getsourcefile(shared)
            assert sharedSource is not None
            assert os.path.samefile(sharedSource, canonicalSource)

    def test_aNonUpsErrorAlsoRecordsNull(self) -> None:
        """
        Given: a gauge raising an OSError (not UpsMonitorError).
        When:  the guarded read runs past the cold-start window.
        Then:  NULL is recorded rather than the error propagating.

        US-526 widened the catch deliberately: UpsMonitor is imported both as
        ``pi.hardware.ups_monitor`` and ``src.pi.hardware.ups_monitor``, so
        those are two distinct class objects and an ``except UpsMonitorError``
        bound to one would not catch the other's instance.  On the shutdown path
        that miss would propagate out of a gauge read.
        """
        class _RaisingUps:
            def getBatteryPercentage(self) -> int:
                raise OSError('i2c bus error')

        assert record_drain_test.readCalibratedRegisterSocPct(
            _RaisingUps(), uptimeSeconds=9999.0,
        ) is None
