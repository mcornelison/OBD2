"""
File: tests/fleet/test_new_bench_provisioning.py
Purpose: US-676 -- New-Bench.ps1 must never leave a bench that LOOKS provisioned.
Author: Ralph (Agent 1)
Created: 2026-09-04
Story: US-676

WHAT THIS FILE MEASURES, AND WHY IT RUNS THE SCRIPT INSTEAD OF READING IT.
US-676 is about two things a text sweep cannot see: an EXIT CODE and the STATE
LEFT ON DISK by a run that died partway. So every test here invokes the shipped
`tools/fleet/New-Bench.ps1` against a hermetic sandbox (see bench_sandbox.py)
and asserts on what the run returned and what the bench directory contains.

MEASURED ON THE PRE-FIX TREE (2026-09-04, commit 2baeb105), three distinct
half-built shapes, all of them indistinguishable from success by `ls`:

  scenario                      rc   bench.ps1   .fleet/lease.json
  ----------------------------  --   ---------   -----------------
  -SkipVenv (happy path)         0   present     present
  venv step fails                1   present     ABSENT
  stamp source missing           1   ABSENT      ABSENT
  clean-tree check fails         1   present     present   <- looks COMPLETE

⚠️ ONE CORRECTION TO THE STORY, RECORDED RATHER THAN QUIETLY WORKED AROUND.
US-676 clause 2 attributes the both-artefacts-missing symptom to `-SkipVenv`.
On this tree `-SkipVenv` is the HAPPY path -- it exits 0 with both artefacts
present. New-Bench.ps1 was rewritten twice (9d0e4a6a, 90c6e938) after Atlas's
2026-09-02 report, and step 3 now writes bench.ps1 BEFORE the venv step. The
DEFECT CLASS the story names is fully alive, but it is reached by the OTHER
early exits -- which is precisely what clause 6 told us to go and check. Row 3
above is Atlas's exact symptom, reached without -SkipVenv.

THE FIX HAS TWO HALVES AND BOTH ARE PINNED HERE:
  (a) ORDER    -- .fleet/lease.json is written BEFORE the venv step, so a venv
                  failure leaves a usable bench rather than a decorative dir.
  (b) LOUDNESS -- the bench on disk carries the verdict. `provisioning` in the
                  lease is the SSOT; `.fleet/PROVISIONING-INCOMPLETE.md` is its
                  human-facing rendering, and it is ABSENT on success.
"""

from __future__ import annotations

import json

import pytest

from tests.fleet.bench_sandbox import POWERSHELL, BenchSandbox

pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason='no powershell/pwsh on this platform'
)

MARKER = '.fleet/PROVISIONING-INCOMPLETE.md'
LEASE = '.fleet/lease.json'


def _lease(run) -> dict:
    return json.loads((run.benchPath / LEASE).read_text(encoding='utf-8-sig'))


# --------------------------------------------------------------------------
# Scenarios. Each stands up a fleet and runs the script ONCE; the assertions
# below read that one measurement. Provisioning is slow (git fetch + worktree
# add + a PowerShell cold start), so the run is shared, never repeated per
# assertion.
# --------------------------------------------------------------------------


@pytest.fixture(scope='module')
def happyRun(tmp_path_factory):
    """-SkipVenv against a well-formed fleet: the run that must exit 0."""
    sandbox = BenchSandbox(tmp_path_factory.mktemp('sb_happy')).build()
    return sandbox.run(ticket='T-HAPPY', slug='probe')


@pytest.fixture(scope='module')
def venvFailureRun(tmp_path_factory):
    """VC2 -- force the venv step to fail.

    fleet.json omits `uvVenvCommand`, which is the script's OWN documented venv
    failure ('fleet.json has no uvVenvCommand'). Chosen over a broken uv
    invocation deliberately: it fails inside the venv step for a reason the
    script itself declares, on any machine, with or without uv installed.
    """
    sandbox = BenchSandbox(tmp_path_factory.mktemp('sb_venv')).build(uvVenvCommand=None)
    return sandbox.run(ticket='T-VENV', slug='probe', skipVenv=False)


@pytest.fixture(scope='module')
def earlyFailureRun(tmp_path_factory):
    """Clause 6's sweep -- an early exit that is NOT the venv step.

    The stamp manifest names a file that .stamp/ does not have, so the run dies
    at step 2, BEFORE bench.ps1 is written. This is Atlas's reported symptom
    (both artefacts missing) reached by a path he did not name.
    """
    sandbox = BenchSandbox(tmp_path_factory.mktemp('sb_stamp')).build(
        stamp=['.env', 'nope.conf']
    )
    return sandbox.run(ticket='T-STAMP', slug='probe')


@pytest.fixture(scope='module')
def lateFailureRun(tmp_path_factory):
    """The fourth shape: a failure AFTER every artefact has been written.

    An un-ignored stamped file makes the closing clean-tree check throw. Before
    this story that left a bench carrying a complete-looking lease.json whose
    provisioning had in fact FAILED -- the most dangerous of the four, because
    `fleet.ps1 status` lists it as leased and the merge would accept it.
    """
    sandbox = BenchSandbox(tmp_path_factory.mktemp('sb_dirty')).build()
    (sandbox.upstream / '.gitignore').write_text(
        '.fleet/\nbench.ps1\nCLAUDE.local.md\n.venv/\n', encoding='utf-8'
    )
    import subprocess

    for args in (['add', '-A'], ['commit', '-m', 'stop ignoring .env']):
        subprocess.run(['git', *args], cwd=str(sandbox.upstream), capture_output=True)
    subprocess.run(
        ['git', '--git-dir', str(sandbox.bare), 'fetch', 'origin'], capture_output=True
    )
    return sandbox.run(ticket='T-DIRTY', slug='probe')


# --------------------------------------------------------------------------
# VC1 -- run New-Bench.ps1 -SkipVenv and inspect the bench directory.
# --------------------------------------------------------------------------


class TestASuccessfulLeaseIsComplete:
    def test_skipVenv_exitsZeroWithBothArtefactsPresent(self, happyRun):
        """
        Given: a well-formed fleet
        When: New-Bench.ps1 -SkipVenv runs
        Then: exit 0, and both .fleet/lease.json and bench.ps1 exist
        """
        assert happyRun.returncode == 0, happyRun.output
        assert happyRun.exists('bench.ps1')
        assert happyRun.exists(LEASE)

    def test_aCompleteBenchCarriesNoIncompleteMarker(self, happyRun):
        """The negative control for every marker assertion below.

        Without this, 'the marker names the failure' is equally satisfied by a
        script that writes the marker unconditionally -- which would flag every
        healthy bench as broken and teach the operator to ignore it. That is the
        inert-guard failure this project has now catalogued six times.
        """
        assert not happyRun.exists(MARKER)

    def test_theLeaseRecordsProvisioningComplete(self, happyRun):
        assert _lease(happyRun)['provisioning'] == 'complete'

    def test_arefusedSecondLeaseDoesNotStampFailureIntoTheLiveBench(self, happyRun):
        """The fence on the failure handler, and it protects a bench in USE.

        The verdict writer runs from a trap covering the whole script scope --
        including the 'Bench already leased' refusal, which fires when the target
        directory is somebody else's ACTIVE bench. Without the $benchOwned fence,
        a second lease attempt would mark a healthy bench incomplete and the
        agent working in it would be told to abandon it.
        """
        sandbox = happyRun.sandbox
        second = sandbox.run(ticket='T-HAPPY', slug='probe')

        assert second.returncode != 0, 'the refusal itself is gone'
        assert 'already leased' in second.output.lower()
        assert not happyRun.exists(MARKER), 'a refused lease vandalised a live bench'
        assert _lease(happyRun)['provisioning'] == 'complete'

    def test_theLeaseStillCarriesEveryFieldItsConsumersRead(self, happyRun):
        """`provisioning` is ADDITIVE. fleet.ps1 status reads ticket + surface,
        and Invoke-FleetMerge reads the surface to fence the diff -- adding a
        field must not cost an existing one."""
        lease = _lease(happyRun)
        for field in ('role', 'ticket', 'slug', 'branch', 'surface', 'share', 'leasedAt'):
            assert field in lease, f'{field} lost from the lease'
        assert lease['ticket'] == 'T-HAPPY'


# --------------------------------------------------------------------------
# VC2 -- force the venv step to fail, then inspect.
# --------------------------------------------------------------------------


class TestAVenvFailureStillLeavesAUsableBench:
    def test_itExitsNonZero(self, venvFailureRun):
        assert venvFailureRun.returncode != 0

    def test_theLeaseIsStillWritten(self, venvFailureRun):
        """The ORDER half of the fix (clause 3a).

        Before this story the lease was written AFTER the venv step, so a venv
        failure produced a worktree with no lease -- and the first thing that
        said so was Invoke-FleetMerge, two steps later, with 'no leased bench
        found for ticket X'. That message names the symptom, not the cause.
        """
        assert venvFailureRun.exists(LEASE), (
            'a venv failure still leaves the bench unmergeable and silent'
        )
        assert venvFailureRun.exists('bench.ps1')

    def test_theBenchOnDiskSaysItIsIncomplete(self, venvFailureRun):
        assert venvFailureRun.exists(MARKER)
        assert _lease(venvFailureRun)['provisioning'] == 'incomplete'

    def test_itNamesWhatIsMissingRatherThanOnlyThatSomethingFailed(self, venvFailureRun):
        """END STATE, second sentence: 'After it exits non-zero, it says which
        of those is missing.' A bare non-zero exit is the status quo."""
        marker = (venvFailureRun.benchPath / MARKER).read_text(encoding='utf-8-sig')
        assert '.venv' in marker, marker
        assert 'uvVenvCommand' in marker, 'the actual failure is not quoted'

    def test_theLeaseRecordsWhichStepFailed(self, venvFailureRun):
        lease = _lease(venvFailureRun)
        assert lease['failedStep'] == 'venv'
        assert 'uvVenvCommand' in lease['error']


# --------------------------------------------------------------------------
# VC3 -- the operator truncated the output to 12 lines (Atlas's exact case).
# --------------------------------------------------------------------------


class TestTheVerdictSurvivesATruncatedTranscript:
    @pytest.mark.parametrize('keptLines', [0, 1, 12])
    def test_theVerdictSurvivesAnyAmountOfTruncation(self, venvFailureRun, keptLines):
        """
        Given: a failed run whose output the operator kept only the head of
        When: that truncated head is all the transcript they have
        Then: the bench on disk still states the verdict, in full

        ⚠️ NOT WRITTEN AS 'the failure is absent from the first 12 lines'. That
        was the first draft and it FAILED -- in a small sandbox the banner lands
        at line 11, whereas on a real bench the stamp list and uv's output push
        it far past 12. That distance is incidental, and a fix that leaned on it
        would be a fix that works because the output happens to be long.

        The invariant that does not depend on how chatty a run is: the verdict is
        recoverable with the transcript DISCARDED ENTIRELY. keptLines=0 is that
        case, and 12 is Atlas's. Nothing below reads the output.
        """
        _ = '\n'.join(venvFailureRun.output.splitlines()[:keptLines])  # all they kept

        assert venvFailureRun.exists(MARKER)
        marker = (venvFailureRun.benchPath / MARKER).read_text(encoding='utf-8-sig')
        assert 'PROVISIONING INCOMPLETE' in marker
        assert 'venv' in marker, 'the marker does not say which step failed'
        assert 'T-VENV' in marker, 'the marker does not say which ticket it belongs to'

    def test_theVerdictIsMachineReadableSoTheNextToolCanRefuse(self, venvFailureRun):
        """A marker a human must notice is only half of it. `provisioning` in the
        lease is what lets fleet.ps1 / the merge decline a half-built bench
        instead of discovering it later."""
        assert _lease(venvFailureRun)['provisioning'] != 'complete'


# --------------------------------------------------------------------------
# Clause 6 -- '-SkipVenv is the reported path but do not assume it is the only
# one.' Swept: an exit BEFORE bench.ps1, and an exit AFTER everything.
# --------------------------------------------------------------------------


class TestEveryOtherEarlyExitIsAlsoDiscoverable:
    def test_aFailureBeforeBenchPs1LeavesADiscoverableBench(self, earlyFailureRun):
        """Atlas's exact symptom -- BOTH artefacts missing -- reached by the
        stamp step, not by -SkipVenv."""
        assert earlyFailureRun.returncode != 0
        assert earlyFailureRun.benchPath.exists(), 'the worktree is created regardless'
        assert earlyFailureRun.exists(MARKER), (
            'a worktree with no lease and no bench.ps1 still looks provisioned'
        )

    def test_itSaysWhichArtefactIsMissingRatherThanListingThemAll(self, earlyFailureRun):
        """END STATE: 'it says WHICH of those is missing.'

        Asserted as the RENDERED STATE, not as the labels. A marker that printed
        both names with no state would satisfy a substring check and tell the
        operator nothing -- and at this point in provisioning the two artefacts
        genuinely differ, which is what makes the distinction measurable.
        """
        marker = (earlyFailureRun.benchPath / MARKER).read_text(encoding='utf-8-sig')
        rendered = {
            line.split()[1]: line.split()[2]
            for line in marker.splitlines()
            if line.startswith('- ') and len(line.split()) >= 3
        }
        assert rendered['bench.ps1'] == 'MISSING', marker
        assert rendered['.fleet\\lease.json'] == 'present', marker

    def test_aFailureAfterEveryArtefactIsStillNotReportedComplete(self, lateFailureRun):
        """The fourth shape and the nastiest: everything is on disk, so the bench
        LOOKS finished. Only the verdict distinguishes it."""
        assert lateFailureRun.returncode != 0
        assert lateFailureRun.exists(LEASE), 'premise: the lease was already written'
        assert lateFailureRun.exists('bench.ps1'), 'premise: bench.ps1 was already written'
        assert _lease(lateFailureRun)['provisioning'] == 'incomplete', (
            'a complete-looking bench whose provisioning failed is exactly the '
            'negative case: it must not be left LOOKING usable'
        )
        assert lateFailureRun.exists(MARKER)


class TestAKilledRunIsStillHonest:
    """The case no error handler can cover, and the reason the verdict is
    written EARLY rather than only on the way out.

    A trap fires on a terminating error. It does not fire when the process is
    killed -- Ctrl-C, a closed terminal, taskkill, a dropped RDP session. If the
    lease were stamped 'complete' on the way in and corrected on the way out, a
    killed run would leave a bench claiming to be finished, which is precisely
    the ambiguity US-676 exists to remove.

    ⚠️ THIS TEST EXISTS BECAUSE A MUTATION SURVIVED. Making the step-1a lease
    write 'complete' instead of 'incomplete' left the whole suite green: on every
    path the suite exercised, the trap rewrote it anyway, so the initial value
    was unobservable. It is observable exactly here.
    """

    @pytest.fixture(scope='class')
    def killedRun(self, tmp_path_factory):
        sandbox = BenchSandbox(tmp_path_factory.mktemp('sb_kill')).build(
            # Blocks inside the venv step so the kill lands mid-provisioning
            # deterministically instead of racing a run that takes ~2 s.
            uvVenvCommand='Start-Sleep -Seconds 120'
        )
        return sandbox.runThenKill(watchFor='bench.ps1')

    def test_bothArtefactsArePresentSoTheBenchLooksFinished(self, killedRun):
        """The premise. Without it the assertions below are satisfied by a bench
        that is merely empty, which is a different and much more obvious fault."""
        assert killedRun.exists(LEASE)
        assert killedRun.exists('bench.ps1')

    def test_theLeaseDoesNotClaimToBeComplete(self, killedRun):
        assert _lease(killedRun)['provisioning'] == 'incomplete'

    def test_theMarkerIsStillThere(self, killedRun):
        assert killedRun.exists(MARKER)


# --------------------------------------------------------------------------
# The negative case: 'a partially-provisioned bench must not be left LOOKING
# usable. Either it is complete, or its incompleteness is discoverable without
# running the merge.' fleet.ps1 status is where a bench looks usable.
# --------------------------------------------------------------------------


class TestFleetStatusRefusesToCallAHalfBuiltBenchLeased:
    def test_statusFlagsAnIncompleteBench(self, venvFailureRun):
        """Discoverable WITHOUT running the merge -- the story's own wording.

        `fleet.ps1 status` already reads .fleet/lease.json to list benches; before
        this story it read the lease's PRESENCE as proof of a good lease, which is
        exactly the assumption US-676 exists to remove.
        """
        result = venvFailureRun.sandbox.runFleet('status')
        output = (result.stdout + result.stderr).upper()
        assert 'T-VENV' in output, f'status did not see the bench at all:\n{output}'
        assert 'PROVISIONING INCOMPLETE' in output, output

    def test_statusDoesNotFlagAHealthyBench(self, happyRun):
        """The control. A status line that always warns is a status line nobody
        reads -- the same inert-guard shape as the marker's own control above."""
        result = happyRun.sandbox.runFleet('status')
        output = (result.stdout + result.stderr).upper()
        assert 'T-HAPPY' in output, f'status did not see the bench at all:\n{output}'
        assert 'PROVISIONING INCOMPLETE' not in output, output
