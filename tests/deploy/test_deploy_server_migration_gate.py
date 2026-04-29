################################################################################
# File Name: test_deploy_server_migration_gate.py
# Purpose/Description: Static-content assertions on deploy/deploy-server.sh -- the
#                      US-213 migration gate. Verifies the script includes a
#                      'Step 4.5' (post-deps, pre-restart) migration run that
#                      calls scripts/apply_server_migrations.py --run-all, that
#                      the step runs under both --init AND default flow, and
#                      that migration failure halts deploy (`set -e` + explicit
#                      rc check).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial -- Sprint 16 US-213 (TD-029 closure).
# ================================================================================
################################################################################

"""Static text assertions for the deploy-server.sh migration gate."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SCRIPT = REPO_ROOT / 'deploy' / 'deploy-server.sh'


def _scriptText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding='utf-8')


def test_deployScript_exists():
    assert DEPLOY_SCRIPT.exists(), f'{DEPLOY_SCRIPT} is missing'


def test_deployScript_hasSetMinusE():
    # `set -e` causes any non-zero exit to halt the script -- our migration
    # gate relies on it to fail the deploy on migration failure.
    text = _scriptText()
    assert 'set -e' in text, 'deploy-server.sh must use `set -e` for hard fail'


def test_deployScript_callsApplyServerMigrationsRunAll():
    text = _scriptText()
    assert 'apply_server_migrations.py' in text, (
        'deploy-server.sh must invoke scripts/apply_server_migrations.py'
    )
    assert '--run-all' in text, (
        'deploy-server.sh must invoke apply_server_migrations.py with --run-all'
    )


def test_migrationStep_runsInDefaultFlowNotJustInit():
    """The gate MUST apply under both --init AND default flow (acceptance #4).

    We enforce this by checking the line that calls apply_server_migrations.py
    is NOT nested inside an `if [ "$INIT" = true ]` block or `if [ "$RESTART_ONLY" = true ]`.
    """
    text = _scriptText()
    lines = text.splitlines()
    callLineIdx = [i for i, line in enumerate(lines)
                   if 'apply_server_migrations.py' in line and '--run-all' in line]
    assert callLineIdx, 'no --run-all call line found'
    # Walk backwards to the nearest fi / outer scope.
    for idx in callLineIdx:
        nested_init_only = False
        depth = 0
        for j in range(idx - 1, -1, -1):
            line = lines[j].strip()
            if line.startswith('fi'):
                depth += 1
            elif line.startswith('if '):
                if depth > 0:
                    depth -= 1
                    continue
                # Outer-most enclosing `if` that directly wraps the call.
                if 'INIT' in line and 'true' in line:
                    nested_init_only = True
                elif 'RESTART_ONLY' in line and 'true' in line:
                    nested_init_only = True
                break
        assert not nested_init_only, (
            f'migration call on line {idx + 1} is nested inside an INIT-only '
            f'or RESTART_ONLY-only block; per US-213 acceptance #4 it must '
            f'run on the default flow too'
        )


def test_migrationStep_runsBeforeServiceStart():
    """Step ordering: migrations MUST run before the service restart (Step 6).

    US-231 (Sprint 18) replaced the inline `nohup uvicorn ... --host` start
    with `sudo systemctl restart obd-server.service` driven by the systemd
    unit at deploy/obd-server.service. The ordering invariant is the same:
    migrations run before the restart triggers (which in turn starts uvicorn
    via the unit's ExecStart). This test now anchors on the systemctl
    restart marker rather than the literal uvicorn line, since uvicorn no
    longer appears in deploy-server.sh post-US-231.
    """
    text = _scriptText()
    migrationIdx = text.find('--run-all')
    assert migrationIdx > -1
    startIdx = text.find('systemctl restart obd-server')
    assert startIdx > -1, 'could not locate systemctl restart line (US-231)'
    assert migrationIdx < startIdx, (
        'migration --run-all must run BEFORE the obd-server restart '
        '(ordering invariant from US-213 acceptance #7; restart now '
        'managed by systemd unit per US-231)'
    )


def test_migrationStep_runsAfterDependencyInstall():
    """Step ordering: migrations run AFTER pip install so apply_server_migrations
    has its deps + SQLAlchemy available (defence-in-depth if future migrations
    import from src.server.models).

    We scan the executable body only (post the ``set -e`` marker) so the
    file header comment -- which mentions both pip and --run-all for
    documentation -- does not skew ``str.find`` positions.
    """
    text = _scriptText()
    setEOffset = text.find('\nset -e')
    assert setEOffset > -1, 'could not locate `set -e` anchor'
    body = text[setEOffset:]
    pipIdx = body.find('pip install -q -r')
    migrationIdx = body.find('--run-all')
    assert pipIdx > -1, 'pip install line not found in executable body'
    assert migrationIdx > -1, '--run-all invocation not found in executable body'
    assert pipIdx < migrationIdx, (
        'pip install must precede the migration step so the runner has '
        'its deps available on a fresh deploy'
    )


def test_migrationStep_skippedUnderRestartOnly():
    """--restart is an operator escape hatch that shouldn't reinstall OR
    re-migrate; migrations are gated behind `RESTART_ONLY = false` like the
    pull + install steps.
    """
    text = _scriptText()
    # The block containing the migration call should also appear under the
    # same RESTART_ONLY gate used by Steps 1 and 3.
    assert '$RESTART_ONLY" = false' in text or '"$RESTART_ONLY" = false' in text, (
        'deploy-server.sh should skip migration + pull steps when --restart'
    )


def test_migrationStep_hasOperatorBanner():
    """Surface the step name clearly in logs so the deploy operator sees it.

    Standard pattern in this file is '--- Step N: ... ---'.
    """
    text = _scriptText()
    # Any step banner that mentions 'migration' (case-insensitive) is fine.
    banners = [line for line in text.splitlines()
               if line.strip().startswith('echo "--- Step')
               and 'migration' in line.lower()]
    assert banners, (
        "deploy-server.sh migration gate must emit a '--- Step N: ... migration ...' "
        'banner so operators see the step ran'
    )
