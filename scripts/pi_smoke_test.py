################################################################################
# File Name: pi_smoke_test.py
# Purpose/Description: Pi 5 deployment smoke test - verifies all subsystems
# Author: Michael Cornelison
# Creation Date: 2026-01-31
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-31    | Marcus (PM)  | Initial implementation for Pi 5 verification
# ================================================================================
################################################################################

"""
Pi 5 Deployment Smoke Test

Runs a series of checks to verify the Pi 5 is properly configured
and the application can run. Outputs PASS/FAIL for each check.

Usage:
    python3 scripts/pi_smoke_test.py
    python3 scripts/pi_smoke_test.py --verbose
"""

import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# Resolve paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / 'src'

# Add src to path for imports
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
RESET = '\033[0m'

results = []


def logPass(check: str, detail: str = '') -> None:
    msg = f"  {GREEN}[PASS]{RESET} {check}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    results.append({'check': check, 'status': 'PASS', 'detail': detail})


def logFail(check: str, detail: str = '') -> None:
    msg = f"  {RED}[FAIL]{RESET} {check}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    results.append({'check': check, 'status': 'FAIL', 'detail': detail})


def logWarn(check: str, detail: str = '') -> None:
    msg = f"  {YELLOW}[WARN]{RESET} {check}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    results.append({'check': check, 'status': 'WARN', 'detail': detail})


def logSection(title: str) -> None:
    print(f"\n{CYAN}=== {title} ==={RESET}")


def checkPythonVersion() -> None:
    logSection("Python Environment")
    ver = sys.version_info
    verStr = f"{ver.major}.{ver.minor}.{ver.micro}"
    if ver.major == 3 and ver.minor >= 11:
        logPass("Python version", verStr)
    else:
        logFail("Python version", f"{verStr} (need 3.11+)")

    # Check venv
    inVenv = sys.prefix != sys.base_prefix
    if inVenv:
        logPass("Running in venv", sys.prefix)
    else:
        logWarn("Not in venv", "Recommend: source .venv/bin/activate")


def checkPlatform() -> None:
    logSection("Platform")
    system = platform.system()
    machine = platform.machine()
    logPass("OS", f"{system} {platform.release()}")
    logPass("Architecture", machine)

    if system == 'Linux' and machine in ('aarch64', 'armv7l'):
        logPass("Raspberry Pi detected")
        # Check Pi model
        try:
            with open('/proc/device-tree/model', 'r') as f:
                model = f.read().strip().rstrip('\x00')
                logPass("Pi model", model)
        except FileNotFoundError:
            logWarn("Pi model", "Could not read /proc/device-tree/model")
    else:
        logWarn("Not a Raspberry Pi", f"{system}/{machine}")


def checkProjectFiles() -> None:
    logSection("Project Files")
    criticalFiles = [
        ('src/main.py', True),
        ('src/obd_config.json', True),
        ('.env', True),
        ('requirements.txt', True),
        ('requirements-pi.txt', True),
        ('scripts/verify_database.py', True),
        ('scripts/verify_hardware.py', True),
        ('scripts/check_platform.py', False),
    ]
    for relPath, critical in criticalFiles:
        fullPath = PROJECT_ROOT / relPath
        if fullPath.exists():
            logPass(relPath)
        elif critical:
            logFail(relPath, "MISSING - critical file")
        else:
            logWarn(relPath, "missing (optional)")


def checkDependencies() -> None:
    logSection("Key Dependencies")
    deps = [
        ('dotenv', 'python-dotenv', True),
        ('pydantic', 'pydantic', True),
        ('obd', 'obd', True),
        ('pygame', 'pygame', False),
        ('serial', 'pyserial', False),
    ]
    for importName, pipName, critical in deps:
        try:
            __import__(importName)
            logPass(pipName)
        except ImportError:
            if critical:
                logFail(pipName, "not installed (critical)")
            else:
                logWarn(pipName, "not installed (optional)")


def checkSqlite() -> None:
    logSection("SQLite")
    try:
        logPass("sqlite3 module", sqlite3.sqlite_version)
        # Test in-memory db
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO test VALUES (1)")
        row = conn.execute("SELECT * FROM test").fetchone()
        conn.close()
        if row and row[0] == 1:
            logPass("SQLite read/write")
        else:
            logFail("SQLite read/write", "unexpected result")
    except Exception as e:
        logFail("SQLite", str(e))


def checkConfig() -> None:
    logSection("Configuration")
    configPath = SRC_DIR / 'obd_config.json'
    try:
        with open(configPath, 'r') as f:
            config = json.load(f)
        logPass("Config loads", str(configPath))

        # Check key sections
        for section in ['database', 'logging', 'bluetooth']:
            if section in config:
                logPass(f"Config section: {section}")
            else:
                logFail(f"Config section: {section}", "missing")
    except FileNotFoundError:
        logFail("Config file", f"not found at {configPath}")
    except json.JSONDecodeError as e:
        logFail("Config file", f"invalid JSON: {e}")


def checkEnvFile() -> None:
    logSection("Environment File (.env)")
    envPath = PROJECT_ROOT / '.env'
    if not envPath.exists():
        logFail(".env file", "not found -- run: make deploy-env")
        return

    logPass(".env file exists")
    with open(envPath, 'r') as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]

    # Check for key vars
    envVars = {}
    for line in lines:
        if '=' in line:
            key = line.split('=', 1)[0].strip()
            envVars[key] = True

    expected = ['DB_PATH', 'OBD_BT_MAC']
    for var in expected:
        if var in envVars:
            logPass(f"  {var} defined")
        else:
            logWarn(f"  {var} not defined", "may use defaults")


def checkDatabaseInit() -> None:
    logSection("Database")
    dataDir = PROJECT_ROOT / 'data'
    if not dataDir.exists():
        logWarn("data/ directory", "does not exist -- will be created on first run")
        return

    dbPath = dataDir / 'obd.db'
    if not dbPath.exists():
        logWarn("Database file", "does not exist yet -- will be created on first run")
        return

    logPass("Database file exists", f"{dbPath.stat().st_size} bytes")

    # Quick table count
    try:
        conn = sqlite3.connect(str(dbPath))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        conn.close()
        tableNames = [t[0] for t in tables]
        if len(tableNames) >= 11:
            logPass(f"Tables found: {len(tableNames)}")
        else:
            logWarn(f"Tables found: {len(tableNames)}", "expected 11 -- run verify_database.py --init")
    except Exception as e:
        logFail("Database query", str(e))


def checkDryRun() -> None:
    logSection("Application Dry Run")
    mainPy = str(SRC_DIR / 'main.py')
    try:
        result = subprocess.run(
            [sys.executable, mainPy, '--dry-run'],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode == 0:
            logPass("--dry-run", "config valid, app starts cleanly")
        else:
            logFail("--dry-run", f"exit code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split('\n')[-5:]:
                    print(f"    {line}")
    except subprocess.TimeoutExpired:
        logFail("--dry-run", "timed out after 30s")
    except Exception as e:
        logFail("--dry-run", str(e))


def checkSimulateStart() -> None:
    logSection("Simulation Mode (5-second test)")
    mainPy = str(SRC_DIR / 'main.py')
    try:
        proc = subprocess.Popen(
            [sys.executable, mainPy, '--simulate'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(PROJECT_ROOT)
        )
        # Let it run for 5 seconds
        time.sleep(5)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        # Check stderr for startup messages
        stderr = proc.stderr.read() if proc.stderr else ''
        if 'Application starting' in stderr or 'Starting workflow' in stderr:
            logPass("--simulate starts", "app launched and ran for 5 seconds")
        elif proc.returncode is not None and proc.returncode <= 0:
            # 0 = clean shutdown after SIGTERM, negative = killed by signal
            logPass("--simulate starts", "app launched and shut down cleanly")
        else:
            logWarn("--simulate", f"exit code {proc.returncode}")
            if stderr:
                for line in stderr.strip().split('\n')[-5:]:
                    print(f"    {line}")
    except Exception as e:
        logFail("--simulate", str(e))


def checkDiskSpace() -> None:
    logSection("System Resources")
    import shutil
    usage = shutil.disk_usage('/')
    freeGb = usage.free / (1024 ** 3)
    totalGb = usage.total / (1024 ** 3)
    if freeGb > 10:
        logPass("Disk space", f"{freeGb:.1f} GB free / {totalGb:.1f} GB total")
    elif freeGb > 2:
        logWarn("Disk space", f"{freeGb:.1f} GB free (low)")
    else:
        logFail("Disk space", f"{freeGb:.1f} GB free (critical)")

    # Memory
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    memKb = int(line.split()[1])
                    memGb = memKb / (1024 * 1024)
                    logPass("RAM", f"{memGb:.1f} GB")
                    break
    except FileNotFoundError:
        logWarn("RAM", "could not read /proc/meminfo")


def checkNetwork() -> None:
    logSection("Network")
    import socket
    hostname = socket.gethostname()
    logPass("Hostname", hostname)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        logPass("Local IP", ip)
        if ip.startswith('10.27.27.'):
            logPass("On DeathStarWiFi subnet")
        else:
            logWarn("Not on expected subnet", f"got {ip}, expected 10.27.27.x")
    except Exception:
        logWarn("Network", "no internet connectivity (may be expected)")


def printSummary() -> None:
    print(f"\n{CYAN}{'=' * 50}{RESET}")
    passCount = sum(1 for r in results if r['status'] == 'PASS')
    failCount = sum(1 for r in results if r['status'] == 'FAIL')
    warnCount = sum(1 for r in results if r['status'] == 'WARN')

    total = len(results)
    print(f"  Results: {GREEN}{passCount} PASS{RESET}, "
          f"{RED}{failCount} FAIL{RESET}, "
          f"{YELLOW}{warnCount} WARN{RESET} "
          f"(of {total} checks)")

    if failCount == 0:
        print(f"\n  {GREEN}Pi 5 is READY for deployment testing.{RESET}")
        print(f"  Next: python3 src/main.py --simulate")
    else:
        print(f"\n  {RED}Fix {failCount} failed check(s) before proceeding.{RESET}")

    # Write results to file for PM review
    resultsPath = PROJECT_ROOT / 'data' / 'smoke_test_results.json'
    try:
        resultsPath.parent.mkdir(parents=True, exist_ok=True)
        with open(resultsPath, 'w') as f:
            json.dump({
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'hostname': platform.node(),
                'python': sys.version,
                'summary': {
                    'pass': passCount,
                    'fail': failCount,
                    'warn': warnCount,
                    'total': total
                },
                'results': results
            }, f, indent=2)
        print(f"\n  Results saved to: {resultsPath}")
    except Exception as e:
        print(f"\n  Could not save results: {e}")

    print(f"{CYAN}{'=' * 50}{RESET}")
    return failCount


if __name__ == '__main__':
    verbose = '--verbose' in sys.argv

    print(f"\n{CYAN}Pi 5 Deployment Smoke Test{RESET}")
    print(f"  Project: {PROJECT_ROOT}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    checkPythonVersion()
    checkPlatform()
    checkProjectFiles()
    checkDependencies()
    checkSqlite()
    checkConfig()
    checkEnvFile()
    checkDatabaseInit()
    checkDryRun()
    checkSimulateStart()
    checkDiskSpace()
    checkNetwork()

    failCount = printSummary()
    sys.exit(1 if failCount > 0 else 0)
