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

import pytest

from scripts import record_drain_test
from src.pi.power.battery_health import LOAD_CLASS_DEFAULT

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
