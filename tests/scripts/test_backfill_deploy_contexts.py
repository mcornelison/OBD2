################################################################################
# File Name: test_backfill_deploy_contexts.py
# Purpose/Description: Regression coverage for I-031 / US-331 -- V0.27.7 US-327
#                      wired deploy-server.sh Step 4.6 to call
#                      scripts/backfill_server_battery_health_log_stranded.py
#                      idempotently, but the script itself fails in BOTH
#                      practical run contexts:
#
#                        Context 1 (Windows Git Bash): the remote Pi-side
#                            sqlite3 path `/home/.../data/obd.db` gets
#                            MSYS2 path-mangled to
#                            `C:/Program Files/Git/home/.../data/obd.db`
#                            when interpolated into the ssh argv.
#
#                        Context 2 (run on chi-srv-01 itself): loadServerCreds
#                            SSHes to mcornelison@10.27.27.10 to read
#                            DATABASE_URL -- but chi-srv-01 IS 10.27.27.10,
#                            so this self-SSH fails Host key verification.
#
#                      Both fixes live in scripts/apply_server_migrations.py
#                      (the sibling import the backfill script reuses):
#                        * _buildSubprocessEnv() injects MSYS_NO_PATHCONV=1 +
#                          MSYS2_ARG_CONV_EXCL='*' into every subprocess env;
#                        * loadServerCreds() short-circuits the remote SSH
#                          when the server address resolves to this host and
#                          reads DATABASE_URL from the local .env directly.
#
# Author: Agent2 (Ralph)
# Creation Date: 2026-05-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-13    | Agent2       | Initial -- I-031 / US-331 regression coverage
#                 (US-331)       for the two deploy-context failures of the
#                                V0.27.7 US-327 backfill.
# 2026-05-13    | Rex (US-337) | I-032 -- the V0.27.8 env-only MSYS guard
#                                false-passed: deploy-server.sh Step 4.6
#                                reproduced the byte-identical
#                                `C:/Program Files/Git/home/...` mangle on
#                                the V0.27.8 release.  Add a regression
#                                class TestScanPiRowsSurvivesGitBashMsysMangle
#                                that exercises a REAL subprocess.run boundary
#                                (not Python mocks alone) against a Python
#                                shim simulating Git for Windows ssh.exe's
#                                MSYS argv re-parser (only the '//' UNC-style
#                                prefix escapes conversion -- env vars do not).
#                                Pre-US-337 the production path is the bare
#                                '/home/.../obd.db' and the shim mangles
#                                it -> scanPiRows raises BackfillError
#                                (the failing-pre-fix invariant from the
#                                story's `invariants`).  Post-US-337 the
#                                argv-form fix renders the path with the
#                                '//' UNC escape and the shim leaves it
#                                alone.
# ================================================================================
################################################################################

"""I-031 / US-331 regression tests -- deploy-context fixes for the V0.27.7
backfill of stranded server-side ``battery_health_log`` rows.

Two failure contexts surfaced during the V0.27.7 sprint-deploy:

* **Context 1 (Windows Git Bash)** -- MSYS2 path-mangling rewrites the
  remote ``/home/...`` sqlite3 path to a Windows drive path before ssh
  ever sees it.
* **Context 2 (chi-srv-01 itself)** -- ``loadServerCreds`` SSHes to
  ``mcornelison@10.27.27.10`` to read DATABASE_URL, but chi-srv-01 *is*
  10.27.27.10, so the self-SSH fails host-key verification.

Both fixes ride through to
:mod:`scripts.backfill_server_battery_health_log_stranded` via its sibling
import of :mod:`scripts.apply_server_migrations`.

The tests inject FakeRunner-style callables and explicit ``localServerCheck``
hooks so they never touch the network, never resolve DNS, and never depend
on the developer machine's hostname.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

# ================================================================================
# Module loader (mirrors test_apply_server_migrations.py + test_backfill_*.py)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'apply_server_migrations.py'


def _loadAsm():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'apply_server_migrations', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['apply_server_migrations'] = mod
    spec.loader.exec_module(mod)
    return mod


asm = _loadAsm()


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr,
    )


# ================================================================================
# Context 1 -- MSYS2 path-mangling suppression
# ================================================================================

class TestMsysPathConvSuppression:
    """The V0.27.7 deploy output captured:

        ERROR: reading Pi-side battery_health_log failed: Error: unable to
        open database "C:/Program Files/Git/home/mcornelison/.../obd.db"

    The fix sets MSYS_NO_PATHCONV=1 + MSYS2_ARG_CONV_EXCL='*' on the
    subprocess env so Git-Bash-launched ssh.exe stops rewriting argv
    paths.  Both env vars are no-ops on non-Windows platforms, so the
    fix is safe everywhere.
    """

    def test_buildSubprocessEnv_setsMsysNoPathConv(self):
        env = asm._buildSubprocessEnv()
        assert env.get('MSYS_NO_PATHCONV') == '1'

    def test_buildSubprocessEnv_setsArgConvExcl(self):
        env = asm._buildSubprocessEnv()
        assert env.get('MSYS2_ARG_CONV_EXCL') == '*'

    def test_buildSubprocessEnv_inheritsOsEnviron(self, monkeypatch):
        monkeypatch.setenv('US331_SENTINEL', 'inherited')
        env = asm._buildSubprocessEnv()
        assert env.get('US331_SENTINEL') == 'inherited'

    def test_buildSubprocessEnv_returnsFreshCopy_doesNotMutateOsEnviron(
        self, monkeypatch,
    ):
        monkeypatch.delenv('MSYS_NO_PATHCONV', raising=False)
        env = asm._buildSubprocessEnv()
        import os
        assert env.get('MSYS_NO_PATHCONV') == '1'
        # The fix must not leak back into os.environ.
        assert 'MSYS_NO_PATHCONV' not in os.environ

    def test_defaultRunner_passesMsysGuardingEnvToSubprocess(self, monkeypatch):
        captured: dict = {}

        def fakeRun(argv, **kwargs):  # noqa: ANN001
            captured['argv'] = list(argv)
            captured['kwargs'] = kwargs
            return subprocess.CompletedProcess(
                args=argv, returncode=0, stdout='', stderr='',
            )

        monkeypatch.setattr(asm.subprocess, 'run', fakeRun)
        asm._defaultRunner(['ssh', 'user@host', 'sqlite3 -readonly /home/x'])
        assert 'env' in captured['kwargs']
        env = captured['kwargs']['env']
        assert env.get('MSYS_NO_PATHCONV') == '1'
        assert env.get('MSYS2_ARG_CONV_EXCL') == '*'


# ================================================================================
# Context 2 -- localhost detection in loadServerCreds
# ================================================================================

class TestIsLocalServer:
    """Layered detection: loopback strings -> hostname match -> IP overlap.

    Probes are injectable so the tests never touch DNS or system state.
    """

    def test_localhostString_isLocal(self):
        assert asm._isLocalServer('localhost') is True

    def test_loopbackV4_isLocal(self):
        assert asm._isLocalServer('127.0.0.1') is True

    def test_loopbackV6_isLocal(self):
        assert asm._isLocalServer('::1') is True

    def test_exactHostnameMatch_isLocal(self):
        assert asm._isLocalServer(
            'chi-srv-01',
            hostnameProbe=lambda: 'chi-srv-01',
        ) is True

    def test_ipOverlap_isLocal(self):
        # chi-srv-01 has IP 10.27.27.10; the server address IS 10.27.27.10.
        assert asm._isLocalServer(
            '10.27.27.10',
            hostnameProbe=lambda: 'chi-srv-01',
            resolveProbe=lambda h: '10.27.27.10' if h == '10.27.27.10' else None,
            localIpsProbe=lambda h: {'10.27.27.10'} if h == 'chi-srv-01' else set(),
        ) is True

    def test_remoteAddress_notLocal(self):
        # The Pi (10.27.27.28) is NOT local when running on chi-srv-01.
        assert asm._isLocalServer(
            '10.27.27.28',
            hostnameProbe=lambda: 'chi-srv-01',
            resolveProbe=lambda h: {'10.27.27.28': '10.27.27.28'}.get(h),
            localIpsProbe=lambda h: (
                {'10.27.27.10'} if h == 'chi-srv-01' else set()
            ),
        ) is False

    def test_resolveFails_notLocal_failSafe(self):
        # When the IP probe fails (DNS down, gaierror etc.), we fall back
        # to "not local" so the legacy SSH path runs -- exactly what
        # happens in production when the local-detection isn't reachable.
        assert asm._isLocalServer(
            '10.99.99.99',
            hostnameProbe=lambda: 'dev-box',
            resolveProbe=lambda _h: None,
            localIpsProbe=lambda _h: set(),
        ) is False

    def test_hostnameProbeFails_notLocal_failSafe(self):
        def boom() -> str:
            raise OSError('no hostname')

        assert asm._isLocalServer(
            '10.27.27.10', hostnameProbe=boom,
        ) is False


# ================================================================================
# Context 2 -- loadServerCreds short-circuits SSH when serverHost resolves local
# ================================================================================

class TestLoadServerCredsLocalShortCircuit:
    """When ``localServerCheck`` returns True, loadServerCreds reads
    ``DATABASE_URL`` from a local .env path instead of SSHing to itself.

    The legacy SSH path stays intact for the normal "dev box -> server"
    case (covered by the existing test_apply_server_migrations.py suite).
    """

    @staticmethod
    def _writeEnv(tmp_path: Path, dsn: str) -> Path:
        envPath = tmp_path / '.env'
        envPath.write_text(
            f'OTHER_VAR=foo\nDATABASE_URL={dsn}\nAFTER_VAR=bar\n',
            encoding='utf-8',
        )
        return envPath

    def test_localServer_readsLocalEnv_doesNotShell(self, tmp_path: Path):
        envPath = self._writeEnv(
            tmp_path, 'mysql+aiomysql://obduser:secret123@10.27.27.10/obd2db',
        )
        calls: list[Sequence[str]] = []

        def fakeRunner(argv, *, input=None, timeout=None):  # noqa: A002, ANN001
            calls.append(list(argv))
            return _ok()

        addrs = asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')
        creds = asm.loadServerCreds(
            addrs,
            runner=fakeRunner,
            localEnvPath=envPath,
            localServerCheck=lambda _h: True,
        )
        assert creds.dbUser == 'obduser'
        assert creds.dbPassword == 'secret123'
        assert creds.dbName == 'obd2db'
        # Critical assertion: NO subprocess shelled out (no ssh-to-self).
        assert calls == []

    def test_remoteServer_stillUsesSshPath(self):
        """Legacy path: when the server is genuinely remote, ssh remains."""
        dsn = 'DATABASE_URL=mysql+aiomysql://u:p@10.27.27.10/dbx\n'
        sshCalls: list[Sequence[str]] = []

        def fakeRunner(argv, *, input=None, timeout=None):  # noqa: A002, ANN001
            sshCalls.append(list(argv))
            return _ok(stdout=dsn)

        addrs = asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')
        creds = asm.loadServerCreds(
            addrs,
            runner=fakeRunner,
            localServerCheck=lambda _h: False,
        )
        assert creds.dbUser == 'u'
        assert creds.dbPassword == 'p'
        assert creds.dbName == 'dbx'
        assert len(sshCalls) == 1
        assert sshCalls[0][0] == 'ssh'

    def test_localServer_missingLocalEnv_raisesClearError(self, tmp_path: Path):
        """Misconfiguration: detected-local but no local .env -- fail loud."""
        addrs = asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')
        missing = tmp_path / 'does-not-exist.env'
        with pytest.raises(asm.MigrationError, match='local .env'):
            asm.loadServerCreds(
                addrs,
                runner=lambda *a, **k: _ok(),
                localEnvPath=missing,
                localServerCheck=lambda _h: True,
            )

    def test_localServer_envHasNoDatabaseUrl_raises(self, tmp_path: Path):
        envPath = tmp_path / '.env'
        envPath.write_text('SOME_OTHER=foo\n', encoding='utf-8')
        addrs = asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')
        with pytest.raises(asm.MigrationError, match='DATABASE_URL'):
            asm.loadServerCreds(
                addrs,
                runner=lambda *a, **k: _ok(),
                localEnvPath=envPath,
                localServerCheck=lambda _h: True,
            )

    def test_localServer_malformedDsn_raises(self, tmp_path: Path):
        envPath = self._writeEnv(tmp_path, 'garbage-no-scheme')
        addrs = asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')
        with pytest.raises(asm.MigrationError, match='malformed'):
            asm.loadServerCreds(
                addrs,
                runner=lambda *a, **k: _ok(),
                localEnvPath=envPath,
                localServerCheck=lambda _h: True,
            )


# ================================================================================
# Helper: _readDatabaseUrlFromEnv
# ================================================================================

class TestReadDatabaseUrlFromEnv:
    def test_picksFirstMatch(self):
        text = (
            'OTHER=foo\n'
            'DATABASE_URL=mysql://u:p@h/db1\n'
            'DATABASE_URL=mysql://second:x@h/db2\n'
        )
        assert asm._readDatabaseUrlFromEnv(text) == 'mysql://u:p@h/db1'

    def test_stripsTrailingWhitespace(self):
        text = 'DATABASE_URL=mysql://u:p@h/db   \n'
        assert asm._readDatabaseUrlFromEnv(text) == 'mysql://u:p@h/db'

    def test_ignoresCommentedLine(self):
        text = '#DATABASE_URL=commented\nDATABASE_URL=mysql://u:p@h/db\n'
        assert asm._readDatabaseUrlFromEnv(text) == 'mysql://u:p@h/db'

    def test_ignoresPartialMatch(self):
        text = 'NOT_DATABASE_URL=foo\nDATABASE_URL=mysql://u:p@h/db\n'
        assert asm._readDatabaseUrlFromEnv(text) == 'mysql://u:p@h/db'

    def test_missing_raises(self):
        with pytest.raises(ValueError, match='no DATABASE_URL'):
            asm._readDatabaseUrlFromEnv('FOO=bar\n')


# ================================================================================
# Cross-script propagation: backfill_server_battery_health_log_stranded reuses
# the patched _defaultRunner and loadServerCreds via importlib sibling-load.
# ================================================================================

class TestPropagationToBackfillScript:
    """The backfill script imports loadServerCreds + _defaultRunner from
    apply_server_migrations via a sibling-importer (``_loadSibling``).
    That means BOTH fixes are picked up automatically with zero changes
    to the backfill script's own usage.  We verify by *behaviour* (not
    object identity) because ``_loadSibling`` re-execs the module on
    every call -- a behavioural assertion is what actually matters for
    the deploy-script wiring.
    """

    @staticmethod
    def _loadBackfillModule():  # noqa: ANN205
        backfillScript = _PROJECT_ROOT / 'scripts' / (
            'backfill_server_battery_health_log_stranded.py'
        )
        spec = importlib.util.spec_from_file_location(
            'backfill_server_battery_health_log_stranded', backfillScript,
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[
            'backfill_server_battery_health_log_stranded'
        ] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_backfillScript_inheritsMsysGuardingEnv(self):
        mod = self._loadBackfillModule()
        # The backfill script aliases _us209 internals, but re-execing
        # the sibling means the patched _buildSubprocessEnv is reachable
        # via the apply_server_migrations module the backfill loaded.
        env = mod._us209._buildSubprocessEnv()
        assert env.get('MSYS_NO_PATHCONV') == '1'
        assert env.get('MSYS2_ARG_CONV_EXCL') == '*'

    def test_backfillScript_loadServerCredsHonoursLocalShortCircuit(
        self, tmp_path: Path,
    ):
        mod = self._loadBackfillModule()
        envPath = tmp_path / '.env'
        envPath.write_text(
            'DATABASE_URL=mysql+aiomysql://u:p@10.27.27.10/dbx\n',
            encoding='utf-8',
        )
        addrs = mod.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')
        calls: list = []

        def fakeRunner(argv, *, input=None, timeout=None):  # noqa: A002, ANN001
            calls.append(list(argv))
            return _ok()

        creds = mod.loadServerCreds(
            addrs,
            runner=fakeRunner,
            localEnvPath=envPath,
            localServerCheck=lambda _h: True,
        )
        assert creds.dbUser == 'u'
        # The backfill script's loadServerCreds short-circuits exactly
        # the same way the asm one does -- no ssh-to-self.
        assert calls == []


# ================================================================================
# I-032 / US-337: REAL-subprocess regression -- the V0.27.8 env-only MSYS guard
# false-passed because Git for Windows' ssh.exe re-parses argv at the MSYS
# runtime layer and rewrites '/home/...' SUBSTRINGS within argv elements,
# regardless of MSYS_NO_PATHCONV / MSYS2_ARG_CONV_EXCL.  The deploy reproduced
# the byte-identical 'C:/Program Files/Git/home/.../obd.db' error.  This class
# exercises a real subprocess.run boundary against a Python shim that simulates
# the MSYS argv re-parser: only a '//' UNC-style leading-slash double defeats
# the mangle; env vars do not.  Pre-US-337 the production scanPiRows passes
# the bare '/home/.../obd.db' and the shim mangles it -> BackfillError.
# Post-US-337 the production path is rendered MSYS-safe and the shim leaves
# it alone -> scanPiRows returns the row.
# ================================================================================


# Python source of the MSYS-simulating ssh shim.  Written to a temp file at
# test time and invoked via real subprocess.run.  The shim mimics Git for
# Windows ssh.exe's MSYS argv conversion at the substring level (the V0.27.8
# deploy showed substring scanning *is* what mangled the path).  The only
# escape this shim honours is the '//' UNC-style leading-double-slash -- the
# argv-form fix US-337 ships in scripts/backfill_server_battery_health_log_stranded.py.
# Env vars (MSYS_NO_PATHCONV, MSYS2_ARG_CONV_EXCL) are intentionally ignored
# because that mirrors the empirical V0.27.8 deploy failure: those env vars
# were set on the subprocess and the mangle still happened.
_MSYS_SSH_SHIM_SOURCE = '''\
#!/usr/bin/env python3
"""Fake ssh.exe that simulates Git for Windows MSYS argv re-parsing.

Argv ingress: each argv element is scanned for '/home/...' SUBSTRINGS.
A token with a single leading slash is rewritten to
'C:/Program Files/Git/home/...' (mirroring the V0.27.8 deploy error
verbatim).  A token with two or more leading slashes ('//home/...') is
recognised as a UNC-style path and left alone -- the documented MSYS
escape from path conversion.

If any argv element still contains the mangle prefix after this pass,
the shim emits an sqlite3-like 'unable to open database file' error and
exits 1 (mirrors the actual deploy log).  Otherwise it emits a single
fake battery_health_log row in sqlite3 -list format for drain_event_id=11
so scanPiRows treats the call as a successful Pi-side query.

Env vars are intentionally ignored: the V0.27.8 deploy set
MSYS_NO_PATHCONV=1 + MSYS2_ARG_CONV_EXCL='*' and the mangle still
happened -- so the shim must mangle independent of env.
"""
import re
import sys

MANGLE_PREFIX = 'C:/Program Files/Git'
_TOKEN_RE = re.compile(r'/+home/[^\\s\\\'"]+')

def _mangleToken(match):
    full = match.group(0)
    leading = re.match(r'^/+', full).group(0)
    if len(leading) >= 2:
        return full  # UNC-style escape -- MSYS leaves it alone
    return MANGLE_PREFIX + full

mangledArgv = [_TOKEN_RE.sub(_mangleToken, arg) for arg in sys.argv[1:]]

# Detect the mangle in any argv element; mirror the deploy log's wording.
for arg in mangledArgv:
    if MANGLE_PREFIX in arg:
        sys.stderr.write(
            'Error: unable to open database '
            '"' + MANGLE_PREFIX + '/home/.../obd.db": '
            'unable to open database file\\n'
        )
        sys.exit(1)

# Happy path: emit a row for drain_event_id=11 in sqlite3 -list format
# (pipe-separated; matches scanPiRows' line.split("|") parser).
sys.stdout.write('11|2026-05-13T12:34:56Z|0.0|600\\n')
sys.exit(0)
'''


class TestScanPiRowsSurvivesGitBashMsysMangle:
    """I-032 / US-337 -- the V0.27.8 deploy reproduced the byte-identical
    ``Error: unable to open database "C:/Program Files/Git/home/.../obd.db"``
    despite US-331 shipping ``MSYS_NO_PATHCONV=1`` +
    ``MSYS2_ARG_CONV_EXCL='*'`` on every subprocess env -- proving the
    env-only guard does not defeat Git for Windows' ssh.exe MSYS argv
    re-parser when it scans for path SUBSTRINGS within argv elements.

    This test crosses the actual subprocess boundary: a Python shim acting
    as a fake ssh.exe applies the same substring mangle the V0.27.8 deploy
    suffered, with only the documented ``//`` UNC-style escape leaving
    tokens alone.  The production ``scanPiRows`` is invoked through a
    runner that calls real ``subprocess.run`` against the shim -- so the
    test fails pre-fix (BackfillError raised because the shim mangles the
    bare ``/home/...`` and exits 1) and passes post-fix (the argv-form
    fix renders ``//home/...`` so the shim's UNC heuristic skips it).
    """

    @staticmethod
    def _loadBackfillModule():  # noqa: ANN205
        backfillScript = _PROJECT_ROOT / 'scripts' / (
            'backfill_server_battery_health_log_stranded.py'
        )
        spec = importlib.util.spec_from_file_location(
            'backfill_server_battery_health_log_stranded', backfillScript,
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules['backfill_server_battery_health_log_stranded'] = mod
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _writeMsysShim(tmp_path: Path) -> Path:
        shim = tmp_path / 'fake_ssh_msys_shim.py'
        shim.write_text(_MSYS_SSH_SHIM_SOURCE, encoding='utf-8')
        return shim

    def test_realSubprocess_unsafePath_isMangledByShim_baseline(
        self, tmp_path: Path,
    ):
        """Baseline: prove the shim faithfully reproduces the V0.27.8 deploy
        error when fed the bare ``/home/...`` path (no production code on
        the call path -- just the shim contract).  This guards against the
        shim silently regressing into a no-op, which would mask future
        false-passes of the *real* regression test below.
        """
        shim = self._writeMsysShim(tmp_path)
        remoteCmd = (
            "sqlite3 -readonly '/home/mcornelison/Projects/Eclipse-01/data/"
            "obd.db' 'SELECT drain_event_id FROM battery_health_log'"
        )
        result = subprocess.run(
            [sys.executable, str(shim), 'mcornelison@10.27.27.28', remoteCmd],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1, (
            'shim must reproduce the V0.27.8 deploy failure when given the '
            f'bare /home/... path; got rc={result.returncode!r} '
            f'stdout={result.stdout!r} stderr={result.stderr!r}'
        )
        assert 'C:/Program Files/Git' in result.stderr

    def test_realSubprocess_safePath_survivesShim_baseline(
        self, tmp_path: Path,
    ):
        """Baseline: prove the shim honours the ``//`` UNC-style escape
        (the post-US-337 form).  Without this assertion, the regression
        test below could pass trivially via a buggy shim.
        """
        shim = self._writeMsysShim(tmp_path)
        remoteCmd = (
            "sqlite3 -readonly '//home/mcornelison/Projects/Eclipse-01/data/"
            "obd.db' 'SELECT drain_event_id FROM battery_health_log'"
        )
        result = subprocess.run(
            [sys.executable, str(shim), 'mcornelison@10.27.27.28', remoteCmd],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f'shim should leave //home/... tokens alone; got rc='
            f'{result.returncode!r} stderr={result.stderr!r}'
        )
        assert '11|2026-05-13T12:34:56Z|0.0|600' in result.stdout

    def test_scanPiRows_pathSurvivesGitBashMsysMangleAtRealSubprocessBoundary(
        self, tmp_path: Path,
    ):
        """The actual I-032 regression gate.

        Calls the production ``scanPiRows`` with a runner that invokes
        ``subprocess.run`` for real against the MSYS-simulating ssh shim.
        Pre-US-337 the production code passes ``/home/...`` and the shim
        mangles it -> ``BackfillError``.  Post-US-337 the production code
        renders the path in MSYS-safe form and the shim leaves it intact
        -> scanPiRows returns the row.
        """
        mod = self._loadBackfillModule()
        shim = self._writeMsysShim(tmp_path)

        capturedArgv: list = []

        def realSubprocessRunner(argv, *, input=None, timeout=None):  # noqa: A002, ANN001
            assert argv[0] == 'ssh', (
                f'expected ssh as argv[0] (the boundary under test), got {argv[0]!r}'
            )
            shimArgv = [sys.executable, str(shim), *list(argv[1:])]
            capturedArgv.append(shimArgv)
            return subprocess.run(
                shimArgv,
                capture_output=True, text=True,
                input=input, timeout=timeout,
            )

        piCoords = mod.PiCoordinates(
            piHost='10.27.27.28',
            piUser='mcornelison',
            piDbPath='/home/mcornelison/Projects/Eclipse-01/data/obd.db',
        )

        rows = mod.scanPiRows(
            piCoords, realSubprocessRunner, drainEventIds=(11,),
        )

        assert capturedArgv, 'realSubprocessRunner was never called'
        # The MSYS-safe form must have reached the shim -- otherwise the shim
        # would have mangled the path and exited 1, raising BackfillError.
        assert len(rows) == 1, (
            'scanPiRows should return 1 row when the path survives MSYS '
            f'mangle; capturedArgv={capturedArgv!r}'
        )
        assert rows[0].drainEventId == 11
        assert rows[0].endTimestamp == '2026-05-13T12:34:56Z'
