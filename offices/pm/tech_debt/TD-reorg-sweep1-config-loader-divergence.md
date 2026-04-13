# TD — Reorg Sweep 1: obd_config_loader divergence

**Status**: BLOCKER (sweep 1 cannot proceed until CIO resolves)
**Discovered**: 2026-04-13 during sweep 1 audit (Task 2)
**Audit notes**: `docs/superpowers/plans/sweep1-audit-notes.md`

## Problem

Sweep 1 (facade cleanup) treated `src/obd/obd_config_loader.py` as a
flat re-export facade over `src/obd/config/loader.py`. The audit found
that assumption is wrong:

1. `src/obd/obd_config_loader.py` is **not a facade** — it is 871 lines
   of real implementation with 24 function/class definitions.
2. The nominated canonical (`src/obd/config/loader.py`) is ~584 lines
   and contains only a subset of the flat file's public API.
3. The flat file exports 14 getter functions that are **absent** from
   `src/obd/config/loader.py`.

## Symbols in flat file but NOT in `src/obd/config/loader.py`

```
getActiveProfile
getConfigSection
getLoggedParameters
getPollingInterval
getRealtimeParameters
getSimulatorConfig
getSimulatorConnectionDelay
getSimulatorFailures
getSimulatorProfilePath
getSimulatorScenarioPath
getSimulatorUpdateInterval
getStaticParameters
isSimulatorEnabled
shouldQueryStaticOnFirstConnection
```

Per the sweep 1 plan's decision tree, this makes the file **AMBIGUOUS**
and the sweep is BLOCKED pending resolution.

## Mitigating context (not a fix — CIO still decides)

All 14 "missing" functions **do** exist elsewhere in the `obd.config`
subpackage:

- `obd/config/helpers.py` — `getConfigSection`, `getActiveProfile`,
  `getLoggedParameters`, `getStaticParameters`, `getRealtimeParameters`,
  `getPollingInterval`, `shouldQueryStaticOnFirstConnection`
- `obd/config/simulator.py` — `getSimulatorConfig`, `isSimulatorEnabled`,
  `getSimulatorProfilePath`, `getSimulatorScenarioPath`,
  `getSimulatorConnectionDelay`, `getSimulatorUpdateInterval`,
  `getSimulatorFailures`

And `src/obd/config/__init__.py` re-exports **all** of them at the
package level. So the `obd.config` package as a whole **is** a strict
public-API superset of `obd.obd_config_loader`:

```
set(public_symbols(obd.obd_config_loader))
  == {ObdConfigError, OBD_DEFAULTS, OBD_REQUIRED_FIELDS,
      VALID_DISPLAY_MODES, loadObdConfig,
      ConfigValidationError, ConfigValidator, loadEnvFile, resolveSecrets,
      getActiveProfile, getConfigSection, getLoggedParameters,
      getPollingInterval, getRealtimeParameters, getStaticParameters,
      shouldQueryStaticOnFirstConnection,
      getSimulatorConfig, isSimulatorEnabled, getSimulatorProfilePath,
      getSimulatorScenarioPath, getSimulatorConnectionDelay,
      getSimulatorUpdateInterval, getSimulatorFailures}

set(public_symbols(obd.config))  # the package
  ⊇ the above
  plus parameter definitions (ALL_PARAMETERS, STATIC_PARAMETERS,
  REALTIME_PARAMETERS, ParameterInfo, CATEGORY_*, getParameterInfo,
  isValidParameter, etc.) AND validateObdConfig (flat has only the
  private _validateObdConfig).
```

The flat file contains DUPLICATE implementation code — not drifted,
but not actively kept in sync either. Any future edits to the config
loading logic will risk silent divergence.

## Current callers of the flat file

```
src/obd/__init__.py                  # re-exports 9 symbols
src/obd/simulator_integration.py     # direct import
src/obd/obd_connection.py            # 2 lazy imports inside methods
tests/test_obd_config_loader.py      # test module
```

## Suggested resolution (CIO decides)

Three plausible paths:

### Option A — Treat the subpackage as the canonical location
Reclassify `obd_config_loader.py` as **SUPERSEDED** (canonical is the
`obd.config` package, not the `config/loader.py` submodule). In Task 3,
wire `src/obd/__init__.py` to re-export directly from `obd.config`
rather than from `.obd_config_loader`. Update the three other callers
to import from `obd.config`. Rename/retarget
`tests/test_obd_config_loader.py` to test `obd.config` instead. Delete
the flat file in Task 7. **No symbol loss.** This is the cleanest path
and matches the pattern the rest of sweep 1 is following.

### Option B — Convert the flat file to a re-export facade first
Keep the flat file temporarily, but rewrite its body to be pure
re-exports `from .config import (...)` matching the public API it
currently exposes. This removes the duplication without changing any
caller imports. Then run sweep 1 unchanged. Slightly more mechanical
work but lowest blast radius.

### Option C — Treat the flat file as the canonical
Rejected unless there's a reason I'm missing. The subpackage split is
cleaner (helpers vs simulator vs loader separation), and this is the
direction the rest of the codebase has already moved.

My recommendation is **Option A** (reclassify as SUPERSEDED via the
package) — it's consistent with how every other flat file in sweep 1
is being handled (the canonical "location" is really a package, not a
specific submodule), and it finishes the decomposition that was already
started.

## Unblock criteria

CIO picks A / B / C (or a variant), documents the choice here and in
the audit notes, then sweep 1 can resume with Task 3.
