#!/usr/bin/env bash
################################################################################
# verify-pi-imports.sh — assert every Pi runtime entry point actually IMPORTS
#                        (US-573 / F-136)
#
# Runs ON the Pi, after the tree sync + venv deps + unit installs and BEFORE the
# services are restarted. Discovers each Python entry point from the systemd
# units systemd has actually loaded, then imports it under that unit's OWN
# working directory and PYTHONPATH. Any ModuleNotFoundError fails the deploy.
#
# **The defect class this exists for.** The Pi sync flipped BLACKLIST ->
# WHITELIST (f2c80b4f) and has already been patched twice: accfa853 excluded
# specs/ and docs/, then da5008cd restored scripts/, which Pi code imports. A
# whitelist omission fails by SILENCE -- the file is simply ABSENT on the car.
# Nothing errors at deploy time; the unit dies at its next start with a
# ModuleNotFoundError traceback that reads like a code bug rather than a deploy
# scope bug.
#
# **Why IMPORT and not a path list.** That is the a94c88a8 lesson, already
# encoded on the server half at deploy-server.sh:116-122: the first version of
# that check named 7 paths derived from the unit files and this script, and
# missed scripts/ -- which src/server/services/release_reader.py imports at
# module load. The cone looked verified and uvicorn died at restart. A hand
# written path list is only ever as good as its author's guess; an import
# exercises every real dependency, including the ones nobody remembered.
#
# **Why the units are PARSED rather than a list of entry points hardcoded here.**
# The server tier is one uvicorn app, so `import src.server.main` covers it. The
# Pi is NOT: it runs nine independent Python units, and they do not agree on how
# they are invoked. MEASURED on the current unit files:
#
#   eclipse-powerwatch.service    python -m src.pi.power.power_watch
#   eclipse-states-http.service   python -m pi.splash.states_http_server
#   eclipse-obd.service           python src/pi/main.py
#   drain-forensics.service       python scripts/drain_forensics.py
#
# Two module namespaces (`src.pi.*` and `pi.*`) and two script paths, because
# most units set PYTHONPATH=<root>:<root>/src while eclipse-obd.service sets NO
# PYTHONPATH at all and drain-forensics/orphan-cleanup set <root> only. An entry
# point imported under the wrong PYTHONPATH is not a check, it is a coin toss:
# it can pass where the unit would fail, and fail where the unit would work.
# Both are confident wrong answers. So each probe replays the unit's own
# WorkingDirectory, its own PYTHONPATH, and its own interpreter.
#
# Parsing the units also means a unit added in a later sprint is covered the day
# it lands. A hardcoded list would silently stop covering the newest unit --
# under-verification that looks exactly like success, which is the shape this
# project has catalogued repeatedly.
#
# **Why this is a .sh and not a .py.** The Pi rsync whitelist ships
# `--include=deploy/*.sh` (deploy-pi.sh:203) and nothing else out of deploy/ but
# named unit files. A `verify-pi-imports.py` would simply never arrive on the
# car -- the very failure mode this script exists to catch, committed by the
# script itself.
#
# Usage (run directly on the Pi):
#   bash deploy/verify-pi-imports.sh
#
# Environment (all optional; the defaults are the real Pi):
#   PI_UNIT_DIR       systemd unit directory to scan   (default /etc/systemd/system)
#   PI_PROJECT_ROOT   only verify units whose WorkingDirectory is under this
#                     path; empty means no filter      (default empty)
#
# Exit codes:
#   0  every discovered entry point imported cleanly
#   1  an entry point failed to import, OR none was discovered at all
#
# **A vacuous pass is treated as a failure.** Discovering ZERO entry points
# exits 1. A verifier that silently finds nothing to verify and reports success
# is the inert guard this project keeps finding -- present, green, and blind to
# the thing it was installed for.
################################################################################

set -e
set -o pipefail

UNIT_DIR="${PI_UNIT_DIR:-/etc/systemd/system}"
PROJECT_ROOT="${PI_PROJECT_ROOT:-}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found; cannot run the import verification." >&2
    exit 1
fi

if [ ! -d "$UNIT_DIR" ]; then
    echo "ERROR: unit directory ${UNIT_DIR} does not exist." >&2
    echo "  Nothing to derive entry points from, so nothing was verified." >&2
    exit 1
fi

python3 - "$UNIT_DIR" "$PROJECT_ROOT" <<'PYEOF'
"""Discover Pi runtime entry points from systemd units and import each one."""

import os
import shlex
import subprocess
import sys

unitDir = sys.argv[1]
projectRoot = sys.argv[2]

# Import the module under a name that is NOT __main__, so a well-formed entry
# point's `if __name__ == "__main__":` block does not run. We are proving the
# module and its dependencies RESOLVE, not starting the service.
MODULE_PROBE = 'import importlib, sys; importlib.import_module(sys.argv[1])'

# `python <script>.py` puts the SCRIPT'S directory on sys.path[0], not the cwd.
# `python -c` puts the cwd there instead, so the probe restores the script form
# before loading -- otherwise a script that imports a sibling module would fail
# here while working perfectly under its unit.
SCRIPT_PROBE = '\n'.join([
    'import importlib.util, os, sys',
    'scriptPath = os.path.abspath(sys.argv[1])',
    'sys.path[0] = os.path.dirname(scriptPath)',
    "spec = importlib.util.spec_from_file_location('_eclipseImportProbe', scriptPath)",
    'mod = importlib.util.module_from_spec(spec)',
    'spec.loader.exec_module(mod)',
])


def readUnitLines(path):
    """Return a unit file's logical lines, joining systemd line continuations.

    systemd lets a directive span lines with a trailing backslash, and
    eclipse-kiosk-watchdog.service uses it for its ExecStart. Reading the file
    line-by-line would truncate that ExecStart mid-argument and silently miss
    the entry point.

    Args:
        path: Absolute path to the unit file.

    Returns:
        List of logical (continuation-joined) lines.
    """
    with open(path, 'r', errors='replace') as handle:
        rawLines = handle.read().splitlines()

    logical = []
    pending = ''
    for rawLine in rawLines:
        stripped = rawLine.rstrip()
        if stripped.endswith('\\'):
            pending += stripped[:-1] + ' '
            continue
        logical.append(pending + stripped)
        pending = ''
    if pending:
        logical.append(pending)
    return logical


def parseUnit(path):
    """Extract the ExecStart, WorkingDirectory and PYTHONPATH from a unit.

    Args:
        path: Absolute path to the unit file.

    Returns:
        Tuple of (execStart, workingDir, pythonPath); each is None when the
        unit does not set it.
    """
    execStart = None
    workingDir = None
    pythonPath = None

    for line in readUnitLines(path):
        stripped = line.strip()
        if not stripped or stripped[0] in '#;':
            continue
        if stripped.startswith('ExecStart=') and execStart is None:
            execStart = stripped.split('=', 1)[1].strip()
        elif stripped.startswith('WorkingDirectory='):
            workingDir = stripped.split('=', 1)[1].strip()
        elif stripped.startswith('Environment='):
            value = stripped.split('=', 1)[1].strip()
            try:
                tokens = shlex.split(value)
            except ValueError:
                tokens = [value]
            for token in tokens:
                if token.startswith('PYTHONPATH='):
                    pythonPath = token.split('=', 1)[1]
    return execStart, workingDir, pythonPath


def extractEntryPoint(execStart):
    """Classify a unit's ExecStart as a Python entry point, or reject it.

    Args:
        execStart: The raw ExecStart value from the unit.

    Returns:
        Tuple of (kind, target, interpreter) where kind is 'module' or
        'script', or None when this ExecStart does not launch Python.
    """
    try:
        argv = shlex.split(execStart)
    except ValueError:
        return None
    if not argv:
        return None

    # systemd allows '-', '@', '+', '!' and ':' prefixes on the executable.
    interpreter = argv[0].lstrip('-@+!:')
    if not os.path.basename(interpreter).startswith('python'):
        return None

    for index, token in enumerate(argv[1:]):
        if token == '-m':
            remaining = argv[index + 2:]
            return ('module', remaining[0], interpreter) if remaining else None
        if token.endswith('.py') and not token.startswith('-'):
            return ('script', token, interpreter)
    return None


def describe(entry):
    """Render an entry point as a short human-readable label."""
    kind, target, _ = entry
    return f'-m {target}' if kind == 'module' else target


# --- Discovery -------------------------------------------------------------
# Sorted so the deploy log reads the same way every run; a stable order makes a
# diff between two deploys meaningful.
unitFiles = sorted(
    os.path.join(unitDir, name)
    for name in os.listdir(unitDir)
    if name.endswith('.service')
)

discovered = {}
skippedOutOfScope = []

for unitFile in unitFiles:
    execStart, workingDir, pythonPath = parseUnit(unitFile)
    if not execStart:
        continue
    entry = extractEntryPoint(execStart)
    if entry is None:
        continue

    unitName = os.path.basename(unitFile)

    # Scope filter. Units belonging to another project on the same box are not
    # this deploy's business, but they are REPORTED rather than dropped -- a
    # silent skip is how a real entry point goes unverified.
    if projectRoot:
        if not workingDir or not os.path.abspath(workingDir).startswith(
            os.path.abspath(projectRoot)
        ):
            skippedOutOfScope.append((unitName, describe(entry), workingDir))
            continue

    key = (entry[0], entry[1], workingDir or '/', pythonPath or '', entry[2])
    discovered.setdefault(key, []).append(unitName)

print(f'Scanned {len(unitFiles)} unit file(s) in {unitDir}')

for unitName, label, workingDir in skippedOutOfScope:
    print(
        f'  NOTE: {unitName} runs "{label}" from WorkingDirectory={workingDir or "(unset)"} '
        f'-- outside {projectRoot}; not verified'
    )

# A verifier that finds nothing must not report success. On a fresh Pi this
# fires when the units have not been installed yet, and on a broken one when
# the unit directory was wiped -- both are states where "all imports OK" would
# be a lie.
if not discovered:
    print('', file=sys.stderr)
    print('ERROR: no Python entry points were discovered -- nothing was verified.', file=sys.stderr)
    print(f'  Scanned {len(unitFiles)} unit file(s) in {unitDir}.', file=sys.stderr)
    if projectRoot:
        print(f'  Scope filter in effect: WorkingDirectory under {projectRoot}', file=sys.stderr)
    print('  Expected the eclipse-* Pi units to be installed before this step.', file=sys.stderr)
    print('  Refusing to report success on an empty verification.', file=sys.stderr)
    sys.exit(1)

print(f'Discovered {len(discovered)} distinct Python entry point(s) to import:')
print('')

# --- Probe -----------------------------------------------------------------
failures = []

for key in sorted(discovered):
    kind, target, workingDir, pythonPath, interpreter = key
    unitNames = ', '.join(sorted(discovered[key]))
    label = describe((kind, target, interpreter))

    env = dict(os.environ)
    if pythonPath:
        env['PYTHONPATH'] = pythonPath
    else:
        env.pop('PYTHONPATH', None)

    program = MODULE_PROBE if kind == 'module' else SCRIPT_PROBE
    command = [interpreter, '-c', program, target]

    try:
        completed = subprocess.run(
            command,
            cwd=workingDir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        returnCode = completed.returncode
        output = completed.stdout.decode('utf-8', errors='replace')
    except FileNotFoundError:
        returnCode = 127
        output = f'interpreter not found: {interpreter}'
    except subprocess.TimeoutExpired:
        returnCode = 124
        output = 'import timed out after 120s (module-level code is blocking)'
    except OSError as exc:
        returnCode = 126
        output = f'could not run the probe: {exc}'

    if returnCode == 0:
        print(f'  OK    {label}   [{unitNames}]')
    else:
        print(f'  FAIL  {label}   [{unitNames}]')
        failures.append((label, unitNames, workingDir, pythonPath, output.strip()))

print('')

if failures:
    print(
        f'ERROR: {len(failures)} of {len(discovered)} Pi entry point(s) do not import '
        f'on the target.',
        file=sys.stderr,
    )
    for label, unitNames, workingDir, pythonPath, output in failures:
        print('', file=sys.stderr)
        print(f'--- {label}  [{unitNames}]', file=sys.stderr)
        print(f'    WorkingDirectory: {workingDir}', file=sys.stderr)
        print(f'    PYTHONPATH:       {pythonPath or "(unset)"}', file=sys.stderr)
        for outputLine in output.splitlines():
            print(f'    {outputLine}', file=sys.stderr)
    print('', file=sys.stderr)
    print('  A ModuleNotFoundError here is a DEPLOY SCOPE bug, not a code bug:', file=sys.stderr)
    print('    the rsync whitelist in deploy-pi.sh did not ship something Pi code', file=sys.stderr)
    print('    imports. Patch the WHITELIST -- do not widen it back to a blacklist.', file=sys.stderr)
    sys.exit(1)

print(f'All {len(discovered)} Pi runtime entry point(s) import cleanly.')
PYEOF
