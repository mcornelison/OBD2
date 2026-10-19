################################################################################
# File Name: test_display_import_loads_no_gpio_us872.py
# Purpose/Description: US-872 import-graph fence. Importing the entry module of
#                      any Pi unit that does not drive GPIO must not even TRY to
#                      import lgpio or the Adafruit/CircuitPython stack that
#                      pulls it in. lgpio's import creates a notify FIFO named
#                      `.lgd-nfy0` in the working directory and re-opens it by
#                      name; our units share one WorkingDirectory, so concurrent
#                      importers race on it (FileNotFoundError at import, or a
#                      silent swap of FIFOs). Measured: 3 of 108 boots.
# Author: Atlas (architect)
# Creation Date: 2026-10-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-18    | Atlas        | Initial implementation for US-872
# ================================================================================
################################################################################

"""
Import-graph fence for the lgpio cwd-FIFO race (US-872).

Why a recording finder and not ``'lgpio' in sys.modules``: off the Pi, ``board``
and ``lgpio`` are not installed, so an eager ``import board`` fails quietly
inside the adapter's try/except and nothing ever lands in ``sys.modules``. That
check would pass on a dev host with the bug fully present. The finder records
every ATTEMPT to locate a GPIO module, so the test sees the import whether or
not the library exists. ``test_detector_seesAnAttempt`` is its positive control.

Each import runs in a fresh interpreter: an earlier test that imported
``pi.display`` would otherwise hide the import order this test is about.

RCA: offices/architect/findings/2026-10-18-RESULTS-US-872-lgpio-import-race-RCA.md
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Modules whose import means the GPIO stack is loading. ``board`` is the
#: Blinka entry point that pulls lgpio in on a Pi 5.
GPIO_MODULES = ('lgpio', 'board', 'digitalio', 'busio', 'adafruit_blinka', 'adafruit_rgb_display')

#: Entry module of each unit that hit the race on the car, or imports the same
#: chain, and drives no GPIO itself (journal 2026-09-18..10-18). The two units
#: that DO need GPIO (eclipse-powerwatch and eclipse-obd, PLD on BCM6) are
#: deliberately not here.
NON_GPIO_ENTRY_MODULES = (
    'pi.display',
    'pi.obdii',
    'src.pi.obdii.bond_self_heal',           # eclipse-bond-selfheal (crashed 10-02, 10-16)
    'src.pi.obdii.database_schema',          # boot-progress-arm's lazy import (10-12)
    'src.pi.diagnostics.boot_progress',      # boot-progress-arm entry
    'pi.display.kiosk_watchdog',             # eclipse-kiosk-watchdog (every 30 s)
    'pi.display.panel_liveness',             # eclipse-panel-liveness (every 30 s)
)

_PROBE = r'''
import importlib, json, sys

WATCH = set(json.loads(sys.argv[2]))
attempts = []

class _Recorder:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in WATCH:
            attempts.append(name)
        return None

sys.meta_path.insert(0, _Recorder())
importlib.import_module(sys.argv[1])
if len(sys.argv) > 3:
    exec(sys.argv[3])
print(json.dumps(sorted(set(attempts))))
'''


def _gpioImportAttempts(module: str, after: str | None = None) -> list[str]:
    """Import ``module`` in a fresh interpreter; return GPIO modules it tried to load."""
    argv = [sys.executable, '-c', _PROBE, module, json.dumps(GPIO_MODULES)]
    if after:
        argv.append(after)
    env = {
        **os.environ,
        'PYTHONPATH': f'{REPO_ROOT}{os.pathsep}{REPO_ROOT / "src"}',
        'PYTHONUTF8': '1',
    }
    result = subprocess.run(
        argv, cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=120,
    )
    assert result.returncode == 0, f'import {module} failed:\n{result.stderr[-2000:]}'
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize('module', NON_GPIO_ENTRY_MODULES)
def test_nonGpioUnitEntryModule_neverTriesToImportGpio_us872(module: str) -> None:
    attempts = _gpioImportAttempts(module)
    assert attempts == [], (
        f'importing {module} tried to load {attempts}. On the Pi that imports '
        'lgpio, which races every other unit in the shared WorkingDirectory on '
        "'.lgd-nfy0' (US-872). Load the hardware stack on first use instead."
    )


def test_detector_seesAnAttempt() -> None:
    """Positive control: reading ADAFRUIT_AVAILABLE IS a hardware load."""
    attempts = _gpioImportAttempts(
        'pi.display', after='import pi.display; pi.display.ADAFRUIT_AVAILABLE',
    )
    assert 'board' in attempts


def test_adafruitAvailableFlag_isStillReadableFromEveryReExport() -> None:
    """The lazy flag keeps its old public spellings, and they agree."""
    from pi.display import ADAFRUIT_AVAILABLE as viaDisplay
    from pi.display.adapters import ADAFRUIT_AVAILABLE as viaAdapters
    from pi.display.adapters.adafruit import ADAFRUIT_AVAILABLE as viaModule
    from pi.display.adapters.adafruit import isDisplayHardwareAvailable

    assert isinstance(viaModule, bool)
    assert viaDisplay is viaAdapters is viaModule is isDisplayHardwareAvailable()
