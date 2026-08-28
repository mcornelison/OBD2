################################################################################
# File Name: test_bond_selfheal_deploy.py
# Purpose/Description: US-545 -- the SHIPPING half of the A-18 bond self-heal.
#                      A healer nothing installs, orders or starts is an
#                      elaborate no-op on the Pi; these are the guards that the
#                      unit exists, is wired into the boot order, and is
#                      actually installed by deploy-pi.sh.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Rex (US-545) | Initial -- A-18 boot leg + deploy wiring.
# ================================================================================
################################################################################

"""Deploy-side guards for ``eclipse-bond-selfheal.service``.

US-549's lesson, in the systemd direction: the JS half of that story was a
perfectly-tested, completely inert fix until the unit passed the flag that
carried it.  The Python half of THIS story is equally inert until a unit runs
it and a deploy step installs the unit -- and both of those live outside the
Python test suite that proves the logic works.

Every assertion here parses ``Unit``/``Service`` directives rather than
substring-matching the file, because the unit deliberately DISCUSSES rfkill
and ``%U``-style traps in its header (the US-522/US-550 false-positive
direction).  The parser carries a positive control so it cannot silently stop
finding anything and pass every absence check over an empty dict.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.pi.obdii.bond_self_heal import OBD_SERVICE_UNIT, SELF_HEAL_UNIT

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_PATH = REPO_ROOT / 'deploy' / SELF_HEAL_UNIT
OBD_UNIT_PATH = REPO_ROOT / 'deploy' / OBD_SERVICE_UNIT
DEPLOY_SCRIPT = REPO_ROOT / 'deploy' / 'deploy-pi.sh'

_DIRECTIVE_RE = re.compile(r'^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*)$')


def parseUnitDirectives(text: str) -> dict[str, list[str]]:
    """Parse a systemd unit into ``directive -> [values]``.

    Comment lines are stripped FIRST.  A commented-out directive is not a
    directive, and a header paragraph explaining why we do NOT use rfkill must
    never satisfy an assertion about what the unit does.
    """
    directives: dict[str, list[str]] = {}
    for rawLine in text.splitlines():
        line = rawLine.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            continue
        match = _DIRECTIVE_RE.match(line)
        if match is None:
            continue
        directives.setdefault(match.group(1), []).append(match.group(2).strip())
    return directives


@pytest.fixture(scope='module')
def unitText() -> str:
    assert UNIT_PATH.is_file(), (
        f"{SELF_HEAL_UNIT} is missing from deploy/ -- the boot leg of US-545 "
        "cannot ship without it"
    )
    return UNIT_PATH.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def directives(unitText: str) -> dict[str, list[str]]:
    return parseUnitDirectives(unitText)


class TestParserSelfCheck:
    def test_parser_findsALiveDirective(self) -> None:
        """Positive control: the parser must actually find things."""
        parsed = parseUnitDirectives("[Service]\nType=oneshot\n")

        assert parsed['Type'] == ['oneshot']

    def test_parser_ignoresACommentedDirective(self) -> None:
        """Negative control: prose about a directive is not the directive."""
        parsed = parseUnitDirectives("[Service]\n# Type=simple\nType=oneshot\n")

        assert parsed['Type'] == ['oneshot']

    def test_parser_ignoresACommentedRfkillMention(self) -> None:
        """The unit explains why it never uses rfkill; that must not read as use."""
        parsed = parseUnitDirectives("# never ExecStart=/usr/sbin/rfkill block\n")

        assert parsed == {}


class TestUnitShape:
    def test_unit_isAOneshot(self, directives: dict[str, list[str]]) -> None:
        """
        Given: the self-heal unit
        When: its Type is read
        Then: oneshot -- it does a job and exits, it is not a daemon
        """
        assert directives.get('Type') == ['oneshot']

    def test_unit_runsBeforeCapture(self, directives: dict[str, list[str]]) -> None:
        """
        Given: the boot leg
        When: the ordering is read
        Then: it is ordered Before eclipse-obd.service

        This IS the "on boot" half of AC1.  Without it the healer and the
        logger race, and the logger reaches a dead bond first -- which is
        exactly the state the healer would have fixed.
        """
        before = ' '.join(directives.get('Before', []))

        assert OBD_SERVICE_UNIT in before

    def test_unit_runsAfterTheRadioIsUnblocked(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the boot leg
        When: the ordering is read
        Then: it runs After bluetooth.service AND eclipse-rfkill-unblock.service

        Scanning for a dongle on a soft-blocked adapter finds nothing and the
        healer would report NOT_DISCOVERABLE -- a confident, wrong, and very
        plausible answer that sends the operator out to power-cycle a dongle
        that was never the problem (BL-025's actual root cause).
        """
        after = ' '.join(directives.get('After', []))

        assert 'bluetooth.service' in after
        assert 'eclipse-rfkill-unblock.service' in after

    def test_unit_doesNotPullCaptureIntoTheBootTransaction(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the ordering directives
        When: Wants/Requires are read
        Then: eclipse-obd is ordered, never pulled in

        `Before=` orders a unit that is already in the transaction; `Wants=`
        would ADD it.  The rfkill-unblock unit makes the same distinction for
        the same reason -- a helper must not decide that capture starts.
        """
        pulled = ' '.join(directives.get('Wants', []) + directives.get('Requires', []))

        assert OBD_SERVICE_UNIT not in pulled

    def test_unit_execStart_runsTheShippedHealer(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: ExecStart
        When: read
        Then: it invokes the bond_self_heal module

        Pinned against the module path so a rename cannot leave a unit
        pointing at nothing -- a failure that surfaces only on the Pi.
        """
        execStart = ' '.join(directives.get('ExecStart', []))

        assert 'bond_self_heal' in execStart
        assert (REPO_ROOT / 'src' / 'pi' / 'obdii' / 'bond_self_heal.py').is_file()

    def test_unit_runsAsTheServiceControlUser(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the healer must `systemctl stop eclipse-obd`
        When: its User is compared with eclipse-obd's
        Then: they match

        The privilege for that stop comes from polkit rule
        51-eclipse-service-control, which keys on the USER.  Running the
        healer as anyone else means every re-pair aborts with
        ABORTED_PORT_BUSY -- correctly reported, and never actually fixed.
        """
        obdUser = parseUnitDirectives(
            OBD_UNIT_PATH.read_text(encoding='utf-8')
        ).get('User', [])

        assert directives.get('User') == obdUser
        assert obdUser, "eclipse-obd.service declares no User -- re-check the pairing"

    def test_unit_restartsCaptureEvenIfTheHealerDies(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the healer is killed mid-heal, after it stopped capture
        When: systemd tears the unit down
        Then: ExecStopPost starts eclipse-obd again

        The healer's own `finally` cannot run if the process is SIGKILLed.
        Without this, one killed heal leaves the car logging nothing until a
        human notices -- the precise failure mode ("never silent capture-death")
        the story exists to close.
        """
        stopPost = ' '.join(directives.get('ExecStopPost', []))

        assert OBD_SERVICE_UNIT in stopPost
        assert 'start' in stopPost

    def test_unit_stopPostDoesNotBlockOnTheUnitItIsOrderedBefore(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the unit declares ``Before=eclipse-obd.service``
        When: ExecStopPost runs ``systemctl start eclipse-obd.service``
        Then: it MUST pass --no-block, or the two deadlock

        Atlas 2026-08-27.  A blocking ``systemctl start`` waits for the job to
        complete; ``Before=eclipse-obd.service`` says that job may not run
        until this unit's transaction has finished -- and this unit is sitting
        in stop-post waiting on it.  Circular wait.

        Measured on the live Pi: ExecStart did its real work in 12.8s and
        returned verdict=durable / outcome=healthy / attempts=0/1, then
        stop-post blocked the full 90s TimeoutStopUSec and systemd killed the
        unit.  12.8 + 90 = 102.8s, matching `systemd-analyze blame` at
        1min 43.008s exactly.

        That 103s is paid on EVERY boot, including boots where the bond is
        healthy and the healer correctly does nothing, and capture is held
        down for all of it -- which is why a cold-engine reading was not
        merely unrecorded but UNRECORDABLE (boot-to-first-row measured in-car
        at 2m45s-2m50s, coolant already 89-93C at the first sample).

        The `-` prefix does NOT cover this: it ignores the command's exit
        STATUS, not whether it blocks.  Note the runtime entry point in this
        same design already uses --no-block correctly; the flag was missing on
        precisely the one call sitting inside an ordering cycle.
        """
        stopPost = ' '.join(directives.get('ExecStopPost', []))
        orderedBefore = ' '.join(directives.get('Before', []))

        if OBD_SERVICE_UNIT not in orderedBefore:
            pytest.skip(
                'unit no longer orders itself Before the capture service -- '
                'the deadlock this guards is structurally impossible'
            )

        assert '--no-block' in stopPost, (
            'ExecStopPost starts a unit this one is ordered Before, without '
            '--no-block: systemd deadlocks in stop-post for the full '
            'TimeoutStopUSec (90s) on every boot, holding capture down with '
            'it. Add --no-block; the safety-net intent is unchanged.'
        )

    def test_unit_neverInvokesRfkill(self, directives: dict[str, list[str]]) -> None:
        """
        Given: every executable directive in the unit
        When: inspected
        Then: none of them runs rfkill

        systemd-rfkill PERSISTS soft-blocks across reboots.  Asserted on the
        parsed values, not the raw text, because the unit's header explains
        this rule in prose -- a substring check would fail on a correct file.
        """
        execLines = ' '.join(
            value
            for name, values in directives.items()
            if name.startswith('Exec')
            for value in values
        )

        assert 'rfkill' not in execLines


class TestDeployWiring:
    def test_deployPi_installsAndEnablesTheUnit(self) -> None:
        """
        Given: deploy-pi.sh
        When: read
        Then: it installs the unit and enables it

        A unit sitting in deploy/ and never copied to /etc/systemd/system is
        the systemd version of a fix that was never wired up.
        """
        text = DEPLOY_SCRIPT.read_text(encoding='utf-8')

        assert SELF_HEAL_UNIT in text, (
            f"deploy-pi.sh never mentions {SELF_HEAL_UNIT} -- the healer would "
            "never reach the Pi"
        )
        assert f'/etc/systemd/system/{SELF_HEAL_UNIT}' in text
        assert f'systemctl enable {SELF_HEAL_UNIT}' in text

    def test_deployPi_callsTheInstallStep(self) -> None:
        """
        Given: the new install step
        When: the script's main body is read
        Then: the step is actually CALLED, not merely defined

        A defined-but-uncalled bash function is silent: the script exits 0 and
        nothing is installed.
        """
        text = DEPLOY_SCRIPT.read_text(encoding='utf-8')
        stepName = 'step_install_bond_selfheal_unit'

        assert f'{stepName}() {{' in text, f"{stepName} is not defined"
        # A call is the bare name on its own line, outside the definition.
        calls = [
            line for line in text.splitlines()
            if line.strip() == stepName
        ]
        assert calls, f"{stepName} is defined but never called"

    def test_polkit_grantsStartSoTheRequestPathCanActuallyWork(self) -> None:
        """
        Given: eclipse-obd requests the heal via `systemctl start --no-block`
        When: the polkit rule is read
        Then: the self-heal unit is granted `start`

        polkit's default is DENY for anything not on the allow-list, so without
        this clause `requestBondSelfHeal` returns False on the Pi and nowhere
        else -- the request path would be dead on arrival while every test here
        stayed green.
        """
        rule = (
            REPO_ROOT / 'deploy' / 'polkit-rules'
            / '51-eclipse-service-control.rules'
        ).read_text(encoding='utf-8')

        assert SELF_HEAL_UNIT in rule, (
            f"{SELF_HEAL_UNIT} is not on the polkit allow-list -- the runtime "
            "self-heal request will be denied on the Pi"
        )

    def test_polkit_doesNotGrantStopOnTheSelfHealUnit(self) -> None:
        """
        Given: the new polkit clause
        When: its verbs are read
        Then: only `start` is granted

        Narrowest grant that makes the request path work.  The clause is
        deliberately NOT part of the kiosk mirror it sits beside -- it exists
        for the capture service's own request path.
        """
        ruleLines = (
            REPO_ROOT / 'deploy' / 'polkit-rules'
            / '51-eclipse-service-control.rules'
        ).read_text(encoding='utf-8').splitlines()

        # Brace-DEPTH, not first-`}`: the clause contains a nested `if`, so
        # stopping at the first closing brace truncates the extract right
        # before the explicit deny -- and the assertion below would then fail
        # on a perfectly correct rule.
        clause: list[str] = []
        capturing = False
        depth = 0
        for line in ruleLines:
            stripped = line.strip()
            if stripped.startswith('//'):
                continue
            if not capturing and SELF_HEAL_UNIT in stripped:
                capturing = True
            if capturing:
                clause.append(stripped)
                depth += stripped.count('{') - stripped.count('}')
                if depth <= 0 and '{' in ' '.join(clause):
                    break

        body = ' '.join(clause)
        assert 'verb == "start"' in body
        assert 'verb == "stop"' not in body
        assert 'polkit.Result.NO' in body, (
            "the clause must explicitly deny other verbs rather than falling "
            "through to a later rule"
        )

    def test_deployPi_doesNotEnableItWithNow(self) -> None:
        """
        Given: the install step
        When: the enable verb is read
        Then: `--now` is NOT used

        `enable --now` would run a full self-heal in the middle of a deploy --
        stopping capture and cycling the radio on a box the operator is
        actively deploying to, for a bond that is probably fine.  The unit is
        for the NEXT boot; a deploy-time heal is the operator's explicit call.
        """
        text = DEPLOY_SCRIPT.read_text(encoding='utf-8')

        assert f'enable --now {SELF_HEAL_UNIT}' not in text


# ================================================================================
# The ExecStart actually RUNS -- mechanism, not declaration
# ================================================================================


def _execStartModule(directives: dict[str, list[str]]) -> str:
    """The module token of ``python -m <module>`` in ExecStart.

    Derived from the unit rather than restated, so a rename moves the test with
    the code instead of quietly leaving it asserting about a module nobody runs.
    """
    tokens = ' '.join(directives.get('ExecStart', [])).split()
    assert '-m' in tokens, "ExecStart does not use `python -m` -- re-check this guard"
    return tokens[tokens.index('-m') + 1]


def _pythonPathEntries(directives: dict[str, list[str]]) -> list[str]:
    """The unit's PYTHONPATH entries, as the Pi would see them.

    systemd spells this ``Environment=PYTHONPATH=...``, so the parsed directive
    key is ``Environment`` and the assignment has to be split back out.  Reading
    a ``PYTHONPATH`` key directly yields an empty list over a unit that sets it
    perfectly well -- an absence check that can never fail.
    """
    for assignment in directives.get('Environment', []):
        name, _, value = assignment.partition('=')
        if name.strip() == 'PYTHONPATH':
            return [entry for entry in value.split(':') if entry]
    return []


def _localPythonPath(directives: dict[str, list[str]]) -> str:
    """The unit's PYTHONPATH, remapped from the Pi's paths onto this checkout."""
    piRoot = directives['WorkingDirectory'][0]
    return os.pathsep.join(
        str(REPO_ROOT / Path(entry).relative_to(piRoot))
        for entry in _pythonPathEntries(directives)
    )


def _runExecStart(module: str, pythonPath: str | None) -> subprocess.CompletedProcess[str]:
    """Run the unit's ExecStart module the way systemd would, minus systemd."""
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'OBD_BT_MAC')}
    if pythonPath is not None:
        env['PYTHONPATH'] = pythonPath
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, '-m', module],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestExecStartActuallyImports:
    """The guard that the substring check above cannot be.

    ``'bond_self_heal' in execStart`` passes over ``-m pi.obdii.bond_self_heal``
    just as happily as over ``-m src.pi.obdii.bond_self_heal``, and this repo
    genuinely ships BOTH conventions (``-m pi.splash.states_http_server`` next
    to ``-m src.pi.power.power_watch``).  Picking the wrong one, or omitting the
    PYTHONPATH that makes it resolve, produces a unit that installs, enables,
    and is silently inert on every boot -- the V0.27.12-DOA failure, and the
    exact shape of the outage US-545 exists to end.  So this runs it.
    """

    def test_unit_declaresBothPythonPathEntries(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the unit
        When: PYTHONPATH is read
        Then: it contains BOTH the repo root and repo-root/src

        The V0.27.12-DOA rule, restated by every sibling `-m src.pi.X` unit.
        Repo-root alone resolves the `-m src.pi...` target and then dies on the
        `from pi.display import ...` inside src/pi/obdii/__init__.py.
        """
        piRoot = directives['WorkingDirectory'][0]
        entries = _pythonPathEntries(directives)

        assert entries, "the unit sets no PYTHONPATH at all -- it will be inert on the Pi"
        assert piRoot in entries
        assert f'{piRoot}/src' in entries

    def test_unit_execStart_actuallyImports(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the unit's real ExecStart module and its real PYTHONPATH
        When: it is executed with no MAC available
        Then: it reaches main() and exits 2 (usage), importing cleanly

        Exit 2 is the load-bearing part: it is main()'s own "a MAC is required"
        code, so reaching it proves the whole import chain resolved AND that the
        module is runnable as `-m`.  A missing __main__ guard, a wrong package
        prefix or a dropped PYTHONPATH entry all fail here instead of on the Pi.
        """
        result = _runExecStart(
            _execStartModule(directives), _localPythonPath(directives)
        )

        assert 'ModuleNotFoundError' not in result.stderr, result.stderr
        assert result.returncode == 2, (
            f"expected main()'s usage exit 2, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_execStart_withoutThePythonPath_failsToImport(
        self, directives: dict[str, list[str]]
    ) -> None:
        """
        Given: the same ExecStart with PYTHONPATH unset
        When: it is executed
        Then: it dies on ModuleNotFoundError

        NEGATIVE CONTROL, and the reason the test above is not self-satisfying.
        It proves the PYTHONPATH directive is load-bearing rather than
        decoration -- if this ever passes, `-m` is resolving some other way and
        the assertion above has stopped testing what it claims to test.
        """
        result = _runExecStart(_execStartModule(directives), None)

        assert result.returncode != 2
        assert 'ModuleNotFoundError' in result.stderr
