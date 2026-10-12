################################################################################
# File Name: test_migration_drift_runs_the_parity_gate.py
# Purpose/Description: US-807 -- pin that the migration-drift CI job actually
#   RUNS the A-4 applied-schema parity gate, and that a PR able to break it
#   starts the job.
#
# WHY THIS EXISTS
#   The A-4 applied check was written 2026-08-10 and had never executed
#   anywhere by 2026-10-06: the only job with a real MariaDB ran one other
#   file, its paths trigger did not list the gate, and the live test carried
#   no `integration` marker, so even adding the file to the job's
#   `-m integration` command would have deselected it while the skip-guard
#   still read green. Each of those is a one-line regression that nothing
#   else would notice -- a gate that silently stops running looks exactly
#   like a gate that passes.
#
# Author: Atlas (Architect) -- US-807, CIO-directed build
# Creation Date: 2026-10-06
################################################################################

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'migration-drift.yml'
PARITY_TEST = 'tests/lint/test_pi_server_contract_parity.py'

# A change to any of these can turn the gate red, so each must start the job.
MUST_TRIGGER = (
    PARITY_TEST,
    'scripts/audit_sync_contract_parity.py',
    'tests/server/_production_schema_snapshot.py',
    'src/server/db/**',
    'src/common/**',
    'src/pi/obdii/**',
    'src/pi/data/**',
    'src/pi/power/**',
    'src/pi/calibration/**',
)


@pytest.fixture(scope='module')
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))


def _trigger(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as boolean True (YAML 1.1).
    return workflow.get('on', workflow.get(True))


def _steps(workflow: dict) -> list[dict]:
    (job,) = workflow['jobs'].values()
    return job['steps']


def test_aChangeThatCanBreakTheGate_startsTheJob(workflow: dict) -> None:
    paths = _trigger(workflow)['pull_request']['paths']
    missing = [p for p in MUST_TRIGGER if p not in paths]
    assert not missing, f'migration-drift.yml paths do not include: {missing}'


def test_aStepRunsTheParityGatesLiveLayer(workflow: dict) -> None:
    runs = [step.get('run', '') for step in _steps(workflow)]
    matching = [r for r in runs if PARITY_TEST in r]
    assert matching, 'no step runs the A-4 parity gate'
    assert all('-m integration' in r for r in matching), (
        'the parity step must select the live layer (-m integration)'
    )


def test_theSkipGuardCoversTheParityReport(workflow: dict) -> None:
    """A green job over a SKIPPED live layer is the honest-skip-in-CI trap."""
    parityStep = next(s for s in _steps(workflow) if PARITY_TEST in s.get('run', ''))
    report = parityStep['run'].split('--junitxml=', 1)[1].split()[0]
    guards = [s for s in _steps(workflow) if 'skipped' in s.get('run', '')]
    assert any(report in g['run'] for g in guards), (
        f'no guard step reads {report}; a skipped parity layer would pass'
    )


def test_theLiveLayerCarriesTheIntegrationMarker() -> None:
    """Without it, `-m integration` deselects the live tests and the guard sees 0."""
    from tests.lint import test_pi_server_contract_parity as gate

    marks = {m.name for m in getattr(gate.TestA2AppliedSchemaLive, 'pytestmark', [])}
    assert 'integration' in marks
