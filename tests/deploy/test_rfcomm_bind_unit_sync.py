################################################################################
# File Name: test_rfcomm_bind_unit_sync.py
# Purpose/Description: US-908-b -- deploy-pi.sh syncs rfcomm-bind.service on
#                      EVERY deploy (sync-if-changed + daemon-reload) and never
#                      restarts, switches on or re-binds the unit while doing it.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-21    | Rex (US-908-b) | Initial implementation.
# ================================================================================
################################################################################

"""Static guards for ``step_sync_rfcomm_bind_unit`` in deploy-pi.sh.

US-908's ``[Unit]`` fix never reached the Pi: deploy-pi.sh installed
rfcomm-bind.service only under ``--init`` (through install-rfcomm-bind.sh,
which restarts the unit).  Atlas ruling (b), 2026-10-20: every deploy syncs the
FILE if it changed and runs daemon-reload, with NO restart and NO enable; the
bind itself stays ``--init``-only.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
STEP_NAME = "step_sync_rfcomm_bind_unit"

# US-908-b acceptance: the body must hold all of these ...
REQUIRED_IN_BODY = ("install -m 644", "daemon-reload", "cmp -s")
# ... and none of these (restart, enable in any form, an rfcomm call, the MAC file).
FORBIDDEN_IN_BODY = ("systemctl restart", "enable", "rfcomm ", "/etc/default/obdlink")


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _stepBody(text: str, stepName: str) -> str:
    """The function body from ``<stepName>() {`` to its column-0 closing brace."""
    needle = f"{stepName}() {{"
    start = text.find(needle)
    assert start > -1, f"{stepName} is not defined in deploy-pi.sh"
    end = text.find("\n}\n", start)
    assert end > -1, f"{stepName} has no column-0 closing brace"
    return text[start : end + 2]


def _forbiddenIn(body: str) -> list[str]:
    return [verb for verb in FORBIDDEN_IN_BODY if verb in body]


def test_step_isDefinedAndCalledAtColumnZero():
    """
    Given: deploy-pi.sh
    When: the orchestration is read
    Then: the step is defined AND called unindented (every deploy, not --init)

    The test_reassert_obd_mac.py idiom: a call gated behind ``if $INIT; then`` is
    indented, so a bare column-0 line proves the every-deploy path.
    """
    text = _deployText()

    assert f"{STEP_NAME}() {{" in text
    assert f"\n{STEP_NAME}\n" in text, (
        f"{STEP_NAME} must be invoked unindented at top level (every deploy)"
    )


def test_step_runsAfterBondSelfhealAndBeforeTheInitBlock():
    """
    Given: the top-level call
    When: its position is read
    Then: right after step_install_bond_selfheal_unit, before the --init-only bind
    """
    text = _deployText()
    callIdx = text.index(f"\n{STEP_NAME}\n")
    bondIdx = text.index("\nstep_install_bond_selfheal_unit\n")
    initBindIdx = text.index("\n    step_install_rfcomm_bind\n")

    assert bondIdx < callIdx < initBindIdx
    # Nothing but comments/blank lines between the bond step and this one.
    between = text[bondIdx + 1 : callIdx].splitlines()[1:]
    assert all(not line.strip() or line.lstrip().startswith("#") for line in between)


def test_step_body_syncsIfChanged():
    """
    Given: the step body
    When: read
    Then: it gates on cmp -s, installs with mode 644 and daemon-reloads
    """
    body = _stepBody(_deployText(), STEP_NAME)

    for needle in REQUIRED_IN_BODY:
        assert needle in body, f"{STEP_NAME} body is missing {needle!r}"
    assert "/etc/systemd/system/rfcomm-bind.service" in body
    assert "${PI_PATH}/deploy/rfcomm-bind.service" in body


def test_step_body_upToDateBranchRunsNoDaemonReload():
    """
    Given: the cmp -s gate
    When: the up-to-date branch is read
    Then: it only prints, and daemon-reload lives in the else branch
    """
    body = _stepBody(_deployText(), STEP_NAME)
    gateIdx = body.index('sudo cmp -s \\"\\$SRC\\" \\"\\$DST\\"; then')
    elseIdx = body.index("\n        else\n", gateIdx)
    upToDateBranch = body[gateIdx:elseIdx]

    assert "rfcomm-bind.service already up-to-date." in upToDateBranch
    assert "daemon-reload" not in upToDateBranch
    assert "install -m 644" not in upToDateBranch
    assert body.count("sudo systemctl daemon-reload") == 1
    assert body.index("sudo systemctl daemon-reload") > elseIdx


def test_step_body_neverRestartsEnablesOrBinds():
    """
    Given: the step body
    When: scanned for the forbidden verbs
    Then: none present -- no restart, no enable, no rfcomm call, no MAC file
    """
    body = _stepBody(_deployText(), STEP_NAME)

    assert _forbiddenIn(body) == []


@pytest.mark.parametrize(
    "planted",
    [
        "    sudo systemctl restart rfcomm-bind.service\n",
        "    sudo systemctl enable --now rfcomm-bind.service\n",
        "    sudo rfcomm bind 0 00:00:00:00:00:00\n",
        "    echo X | sudo tee /etc/default/obdlink\n",
    ],
)
def test_forbiddenCheck_catchesAPlantedVerb(planted: str):
    """
    Given: the real step body with one forbidden line planted in it
    When: the forbidden-verb check runs
    Then: it flags the plant -- the check above cannot pass over anything
    """
    body = _stepBody(_deployText(), STEP_NAME)
    plantedBody = body.replace("        set -e\n", "        set -e\n" + planted, 1)

    assert plantedBody != body, "plant site not found -- re-check this control"
    assert _forbiddenIn(plantedBody) != []


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available on PATH")
def test_deployPi_stillParses():
    """bash -n on the whole script: the new step must not break its syntax."""
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
