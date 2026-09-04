"""
File: tests/fleet/bench_sandbox.py
Purpose: Hermetic sandbox that lets tests RUN tools/fleet/New-Bench.ps1 for real.
Author: Ralph (Agent 1)
Created: 2026-09-04
Story: US-676

WHY THIS EXISTS RATHER THAN A STATIC PARSE OF THE SCRIPT.
US-676's validationCriteria are behavioural -- "force the venv step to fail,
then inspect" and "run with output truncated to 12 lines". A text sweep over
New-Bench.ps1 can assert the ORDER of two Set-Content calls, but it cannot
witness an exit code, and it cannot witness what a half-finished run leaves on
disk. Those are the two things the story is actually about.

So the sandbox stands up every external fact New-Bench.ps1 reads -- a real bare
git repo with an origin remote, a fleet.json, a .stamp/ manifest, an offices
share with a charter, a fake fleet kit and a fake user profile -- and the tests
invoke the SHIPPED script against it. Nothing in the real fleet is touched:
USERPROFILE and FLEET_KIT are redirected into the tmp tree, so
Initialize-ProjectConfig.ps1 hardlinks a FAKE credentials file, never the CIO's.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_BENCH = REPO_ROOT / 'tools' / 'fleet' / 'New-Bench.ps1'

# powershell.exe (5.1) is what the fleet actually runs these scripts under -- see
# the PS 5.1 notes in FleetRoles.ps1 and Initialize-ProjectConfig.ps1. Prefer it,
# so the tests exercise the same interpreter the operator does.
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')


def _git(*args: str, cwd: Path | None = None) -> None:
    """Run git, raising with the captured output if it fails."""
    result = subprocess.run(
        ['git', *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f'git {" ".join(args)} failed ({result.returncode})\n'
            f'{result.stdout}\n{result.stderr}'
        )


@dataclass
class BenchRun:
    """One invocation of New-Bench.ps1 and everything it left behind."""

    returncode: int
    stdout: str
    stderr: str
    benchPath: Path
    sandbox: BenchSandbox

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    @property
    def firstTwelveLines(self) -> str:
        """Atlas's exact case: the operator read only the head of the output."""
        return '\n'.join(self.output.splitlines()[:12])

    def exists(self, rel: str) -> bool:
        return (self.benchPath / rel).exists()


class BenchSandbox:
    """A throwaway fleet: bare repo, share, stamp manifest, kit, user profile."""

    ROLE = 'dev'
    TRUNK_BRANCH = 'main'

    def __init__(self, root: Path) -> None:
        self.root = root
        self.projectRoot = root / 'project'
        self.share = root / 'share'
        self.kit = root / 'kit'
        self.home = root / 'home'
        self.upstream = root / 'upstream'
        self.bare = self.projectRoot / 'repo.git'
        self.trunk = self.projectRoot / 'trunk'
        self.worktrees = self.projectRoot / 'wt'
        self.stampDir = self.projectRoot / '.stamp'
        self.fleetJson = self.projectRoot / 'fleet.json'

    # -- construction --------------------------------------------------------

    def build(self, *, uvVenvCommand: str | None = 'uv venv', stamp: list[str] | None = None) -> BenchSandbox:
        """Stand the whole thing up.

        Args:
            uvVenvCommand: what fleet.json records as the venv invocation.
                Passing None omits the key, which is the script's own documented
                venv-step failure ("fleet.json has no uvVenvCommand"). That is
                how VC2 forces the venv step to fail without needing uv at all.
            stamp: the stamp manifest. Entries that do not exist under .stamp/
                make the stamp step throw -- an early exit BEFORE the venv, used
                to sweep for the same half-built state on another path.
        """
        self._buildGitRepos()
        self._buildShare()
        self._buildKit()
        self._buildHome()
        self._buildStamp()
        self._writeFleetJson(uvVenvCommand=uvVenvCommand, stamp=stamp)
        return self

    def _buildGitRepos(self) -> None:
        self.upstream.mkdir(parents=True)
        _git('init', '-b', self.TRUNK_BRANCH, cwd=self.upstream)
        _git('config', 'user.email', 'sandbox@example.invalid', cwd=self.upstream)
        _git('config', 'user.name', 'Sandbox', cwd=self.upstream)
        (self.upstream / 'README.md').write_text('sandbox\n', encoding='utf-8')
        # A .gitignore that ignores the untracked artefacts the bench acquires,
        # because New-Bench.ps1 fails the lease on a dirty tree and the real
        # repo ignores exactly these.
        (self.upstream / '.gitignore').write_text(
            '.fleet/\nbench.ps1\nCLAUDE.local.md\n.venv/\n.env\n', encoding='utf-8'
        )
        _git('add', '-A', cwd=self.upstream)
        _git('commit', '-m', 'sandbox base', cwd=self.upstream)

        self.projectRoot.mkdir(parents=True, exist_ok=True)
        _git('init', '--bare', str(self.bare))
        # remote add gives the bare repo the default
        # +refs/heads/*:refs/remotes/origin/* refspec, so `fetch origin` creates
        # origin/<trunk> -- which is the ref New-Bench.ps1 branches from.
        _git('--git-dir', str(self.bare), 'remote', 'add', 'origin', str(self.upstream))
        _git('--git-dir', str(self.bare), 'fetch', 'origin')
        # `git init --bare` points HEAD at refs/heads/master, which never exists
        # here. fleet.ps1 status runs `git log` against the bare repo and that
        # unborn HEAD makes it die on a NativeCommandError before it ever lists a
        # bench. The real repo.git has a real trunk branch; give the sandbox one.
        _git('--git-dir', str(self.bare), 'branch', self.TRUNK_BRANCH,
             f'origin/{self.TRUNK_BRANCH}')
        _git('--git-dir', str(self.bare), 'symbolic-ref', 'HEAD',
             f'refs/heads/{self.TRUNK_BRANCH}')
        self.worktrees.mkdir(parents=True, exist_ok=True)
        self.trunk.mkdir(parents=True, exist_ok=True)

    def _buildShare(self) -> None:
        (self.share / 'board' / 'wip').mkdir(parents=True)
        (self.share / 'CLAUDE.md').write_text('# sandbox fleet\n', encoding='utf-8')
        office = self.share / 'offices' / self.ROLE
        (office / '.claude' / 'commands').mkdir(parents=True)
        (office / 'CHARTER.md').write_text('# dev charter\n', encoding='utf-8')
        (office / '.claude' / 'commands' / 'hello.md').write_text('hello\n', encoding='utf-8')

    def _buildKit(self) -> None:
        hooks = self.kit / 'hooks'
        hooks.mkdir(parents=True)
        for hook in ('git-guard.ps1', 'config-guard.ps1'):
            (hooks / hook).write_text('# fake hook\n', encoding='utf-8')

    def _buildHome(self) -> None:
        claude = self.home / '.claude'
        claude.mkdir(parents=True)
        (claude / '.credentials.json').write_text('{"fake": true}\n', encoding='utf-8')

    def _buildStamp(self) -> None:
        self.stampDir.mkdir(parents=True, exist_ok=True)
        (self.stampDir / '.env').write_text('SANDBOX=1\n', encoding='utf-8')

    def _writeFleetJson(self, *, uvVenvCommand: str | None, stamp: list[str] | None) -> None:
        cfg = {
            'share': str(self.share),
            'worktrees': str(self.worktrees),
            'bare': str(self.bare),
            'trunk': str(self.trunk),
            'trunkBranch': self.TRUNK_BRANCH,
            'stamp': stamp if stamp is not None else ['.env'],
            'roles': [self.ROLE],
            'fleetKit': str(self.kit),
        }
        if uvVenvCommand is not None:
            cfg['uvVenvCommand'] = uvVenvCommand
        self.fleetJson.write_text(json.dumps(cfg, indent=2), encoding='utf-8')

    # -- invocation ----------------------------------------------------------

    def benchPathFor(self, ticket: str, slug: str) -> Path:
        return self.worktrees / f'{self.ROLE}-{ticket}-{slug}'

    def run(self, *, ticket: str = 'T-1', slug: str = 'probe', skipVenv: bool = True,
            extraArgs: list[str] | None = None) -> BenchRun:
        """Invoke the SHIPPED New-Bench.ps1 against this sandbox."""
        args = [
            POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(NEW_BENCH),
            '-Role', self.ROLE,
            '-Ticket', ticket,
            '-Slug', slug,
            '-ProjectRoot', str(self.projectRoot),
        ]
        if skipVenv:
            args.append('-SkipVenv')
        if extraArgs:
            args.extend(extraArgs)

        env = dict(os.environ)
        env['USERPROFILE'] = str(self.home)
        env['FLEET_KIT'] = str(self.kit)
        # The bare repo is inside the sandbox; make sure no ambient git config
        # from the calling bench leaks a different identity into the commit path.
        env['GIT_CONFIG_NOSYSTEM'] = '1'

        result = subprocess.run(
            args, capture_output=True, text=True, env=env, cwd=str(self.root)
        )
        return BenchRun(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            benchPath=self.benchPathFor(ticket, slug),
            sandbox=self,
        )

    def runThenKill(self, *, watchFor: str, ticket: str = 'T-KILL', slug: str = 'probe',
                    timeoutSeconds: float = 90.0) -> BenchRun:
        """Start provisioning, wait for `watchFor` to appear, then KILL the run.

        This is the case the early marker exists for and the ONLY one a trap
        cannot cover: the process dies without unwinding -- Ctrl-C, a closed
        terminal, taskkill, a lost RDP session. Whatever is on disk at that
        instant is all anyone will ever have.

        Requires a fleet.json whose uvVenvCommand blocks (see the test), so the
        kill lands reliably in the middle of provisioning rather than racing it.
        """
        args = [
            POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(NEW_BENCH),
            '-Role', self.ROLE, '-Ticket', ticket, '-Slug', slug,
            '-ProjectRoot', str(self.projectRoot),
        ]
        env = dict(os.environ)
        env['USERPROFILE'] = str(self.home)
        env['FLEET_KIT'] = str(self.kit)

        benchPath = self.benchPathFor(ticket, slug)
        target = benchPath / watchFor
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=env, cwd=str(self.root),
        )
        try:
            deadline = time.monotonic() + timeoutSeconds
            while time.monotonic() < deadline:
                if target.exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError(
                        f'provisioning exited (rc={process.returncode}) before {watchFor} '
                        f'appeared:\n{process.stdout.read() if process.stdout else ""}'
                    )
                time.sleep(0.1)
            else:
                raise RuntimeError(f'{watchFor} never appeared within {timeoutSeconds}s')
            # /T because Invoke-Expression has spawned a child; killing only the
            # parent would leave it holding the bench.
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True
            )
        finally:
            process.kill()
            process.wait(timeout=30)

        return BenchRun(
            returncode=process.returncode, stdout='', stderr='',
            benchPath=benchPath, sandbox=self,
        )

    def installFleetTooling(self) -> Path:
        """Copy tools/fleet/*.ps1 into the sandbox and return fleet.ps1's path.

        fleet.ps1 finds its fleet.json by walking UP from its own location -- it
        takes no -ProjectRoot. Run in place it would therefore report on the REAL
        fleet, so any assertion about its output would be about the operator's
        live benches. Copying the shipped scripts under the sandbox project root
        makes that walk land on the sandbox fleet.json instead. The files are
        byte copies, so it is still the shipped tooling under test.
        """
        destination = self.projectRoot / 'tools' / 'fleet'
        destination.mkdir(parents=True, exist_ok=True)
        for script in (REPO_ROOT / 'tools' / 'fleet').glob('*.ps1'):
            shutil.copy2(script, destination / script.name)
        return destination / 'fleet.ps1'

    def runFleet(self, *args: str) -> subprocess.CompletedProcess:
        """Invoke the sandbox copy of fleet.ps1."""
        fleet = self.installFleetTooling()
        env = dict(os.environ)
        env['USERPROFILE'] = str(self.home)
        env['FLEET_KIT'] = str(self.kit)
        return subprocess.run(
            [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(fleet), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.root),
        )
