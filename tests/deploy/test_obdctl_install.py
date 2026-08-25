################################################################################
# File Name: test_obdctl_install.py
# Purpose/Description: US-492 [F-122] deploy-side guards for the obdctl operator
#   CLI. Two jobs:
#
#   1. INSTALL -- obdctl must actually land on the Pi and be on PATH after a
#      deploy (AC-9). A maintenance tool that only exists in the repo is a tool
#      the operator does not have at 2am in a cold garage.
#
#   2. DRIFT (AC-10, the load-bearing one) -- the manifest claims a unit is
#      "installed by deploy". These tests check that claim against what the
#      deploy scripts actually install, in BOTH directions: no canonical unit
#      that deploy never installs, and no unit flagged not-installed that deploy
#      quietly does install. That bidirectional check is the whole point of
#      having ONE list -- a one-way check would let the manifest rot silently on
#      the side nobody asserts.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial implementation (US-492 obdctl).
# ================================================================================
################################################################################

"""Deploy-side install + manifest-vs-deploy drift guards for obdctl (US-492)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pi.ops import unit_manifest as manifest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
DEPLOY_README = REPO_ROOT / "deploy" / "README.md"
OBDCTL_SOURCE = REPO_ROOT / "src" / "pi" / "ops" / "obdctl.py"

# Every script that installs a systemd unit onto the Pi. The splash + dashboard
# kits install their own units, which is exactly why the manifest had to become
# the SSOT: the unit list was previously spread across these three files.
INSTALLING_SCRIPTS = (
    DEPLOY_SCRIPT,
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "install.sh",
    REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "install.sh",
)

INSTALL_STEP = "step_install_obdctl"
INSTALL_TARGET = "/usr/local/bin/obdctl"


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _stepBody(text: str, stepName: str) -> str:
    """Return the body of `<stepName>() { ... }` so a check stays scoped to it."""
    marker = f"{stepName}() {{"
    start = text.index(marker)
    end = text.index("\n}\n", start)
    return text[start:end]


def _installerCorpus() -> str:
    """All deploy-side installer text, lower-cased, concatenated."""
    return "\n".join(
        path.read_text(encoding="utf-8").lower() for path in INSTALLING_SCRIPTS if path.is_file()
    )


# ---------------------------------------------------------------------------
# AC-10 -- the manifest's installedByDeploy claim vs what deploy actually does.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unit", manifest.CANONICAL_UNITS)
def test_everyCanonicalUnit_isActuallyInstalledBySomeDeployScript(unit):
    """
    Given: the manifest says these 8 units are deploy-installed
    When: the deploy scripts are searched for each unit name
    Then: each one is there. A canonical unit no deploy script installs would
        make `obdctl status all` report a permanent phantom `not-installed`.
    """
    assert unit.lower() in _installerCorpus(), (
        f"{unit} is flagged installedByDeploy but no deploy script mentions it -- "
        "either deploy stopped installing it or the manifest is wrong"
    )


def test_unitsFlaggedNotInstalled_areNotSilentlyInstalledByDeploy():
    """
    Given: eclipse-sync is flagged installedByDeploy=False (conditionalOutcome 2)
    When: the deploy scripts are searched
    Then: none of them installs it. The other direction of the same guard: if a
        future deploy DOES start installing it, this trips and the unit gets
        promoted into `all` instead of being quietly excluded forever.
    """
    corpus = _installerCorpus()
    absent = [u for u in manifest.UNIT_MANIFEST if not u.installedByDeploy]

    assert absent, "the fixture is meaningless if nothing is flagged not-installed"
    for spec in absent:
        assert spec.unit.lower() not in corpus, (
            f"{spec.unit} is flagged NOT installed by deploy, but a deploy script "
            "references it -- reconcile the manifest (AC-2: one SSOT, no drift)"
        )


def test_theKioskPolkitRule_coversEveryUnitTheKioskAllowlistGrants():
    """
    Given: the 51- polkit rule is the authorization backstop mirroring the
        kiosk allow-list
    When: the derived allow-list is compared to the rule file
    Then: every granted unit is named in the rule. Deriving the allow-list from
        a manifest makes it easy to widen the kiosk's reach by adding kioskVerbs
        to a unit -- and a widened list without a widened rule ships a UI that
        offers actions PolicyKit then denies.
    """
    rulePath = REPO_ROOT / "deploy" / "polkit-rules" / "51-eclipse-service-control.rules"
    ruleText = rulePath.read_text(encoding="utf-8")

    for unit in manifest.kioskAllowlist():
        assert unit in ruleText, f"{unit} is kiosk-reachable but absent from the polkit rule"


# ---------------------------------------------------------------------------
# AC-9 -- deploy-installed and on PATH.
# ---------------------------------------------------------------------------


def test_deployPi_definesAnObdctlInstallStep():
    """
    Given: AC-9 -- deploy-installed via deploy-pi.sh
    When: the script is read
    Then: the install step exists AND is wired into the run sequence (a defined
        function that is never called installs nothing)
    """
    text = _deployText()

    assert f"{INSTALL_STEP}()" in text
    calls = [ln for ln in text.splitlines() if ln.strip() == INSTALL_STEP]
    assert calls, f"{INSTALL_STEP} is defined but never invoked"


def test_obdctlInstallStep_putsItOnPathPointingAtTheDeployedSource():
    """
    Given: AC-9 -- on PATH or a known location
    When: the install step body is read
    Then: it installs an executable at /usr/local/bin/obdctl that runs the
        deployed obdctl.py
    """
    body = _stepBody(_deployText(), INSTALL_STEP)

    assert INSTALL_TARGET in body
    assert "src/pi/ops/obdctl.py" in body
    assert "755" in body, "the wrapper must be executable"


def test_obdctlInstallStep_isDryRunSafe():
    """
    Given: deploy-pi.sh --dry-run must change nothing
    When: the install step body is read
    Then: it returns early under $DRY_RUN, before any remote install
    """
    body = _stepBody(_deployText(), INSTALL_STEP)
    dryRunIndex = body.index("$DRY_RUN")

    assert "DRY-RUN would" in body
    assert body.index("return 0", dryRunIndex) < body.index("remote", dryRunIndex)


def test_obdctlWrapper_usesSystemPythonNotTheAppVenv():
    """
    Given: obdctl exists to fix a broken Pi, and the venv is one of the things
        that can be broken
    When: the wrapper's interpreter is read
    Then: it is the system python3. Pointing the maintenance tool at the app's
        venv would make it unavailable in exactly the situation it is for.
    """
    body = _stepBody(_deployText(), INSTALL_STEP)

    assert "/usr/bin/python3" in body
    assert "obd2-venv" not in body


def test_obdctlSource_importsNothingFromTheApplication():
    """
    Given: the same "works when broken" requirement
    When: obdctl's imports are read
    Then: it imports only the stdlib + its own manifest -- no config loader, no
        orchestrator, nothing that can fail to import on a half-broken Pi
    """
    imports = [
        line.strip()
        for line in OBDCTL_SOURCE.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    ]

    for line in imports:
        assert "config" not in line
        if line.startswith("from pi") or line.startswith("import pi"):
            assert "unit_manifest" in line, f"unexpected application import: {line}"


def test_obdctlInstallStep_actuallyProducesARunnableWrapper():
    """
    Given: the wrapper is written by a heredoc nested inside a double-quoted
        string that is itself sent over SSH
    When: the real step body is executed off-Pi with `remote` and `sudo` stubbed
    Then: the file it writes is executable, RUNS, and a second pass is a no-op.
        Static greps on the step body cannot see a mis-escaped `$@` or a heredoc
        that expanded on the wrong side -- and that class of bug would only
        surface on the Pi, after the deploy, as `obdctl: not found`.
    """
    sim = REPO_ROOT / "tests" / "deploy" / "obdctl_wrapper_sim.sh"
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash unavailable on this host")

    proc = subprocess.run(
        [bash, str(sim)], capture_output=True, text=True, timeout=180, cwd=str(REPO_ROOT)
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OBDCTL WRAPPER SIM: PASS" in proc.stdout


def test_deployReadme_documentsObdctl():
    """
    Given: AC-9 -- documented in deploy/README
    When: the README is read
    Then: the command, its purpose and the powerwatch caveat are all there
    """
    readme = DEPLOY_README.read_text(encoding="utf-8")

    assert "obdctl" in readme
    assert "powerwatch" in readme
