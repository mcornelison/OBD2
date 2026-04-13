# Sweep 4 — Config Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `src/pi/obd_config.json` to repo root as `config.json`. Rewrite it into the single-file tier-aware shape with shared top-level keys and `pi:`/`server:` sections. Update `src/common/config/validator.py` to validate the new structure. Create `src/common/config/schema.py` with dataclass types describing the shape. Update every config-reading call site. Zero behavior change (same effective values, new layout).

**Architecture:** Today the config file lives at `src/pi/obd_config.json` (after sweep 3 moved it) with 21 flat top-level sections. The new structure groups shared keys (protocolVersion, schemaVersion, deviceId, logging) at the top level, Pi-specific sections under `pi:`, and server-specific sections under `server:`. This enforces tier-awareness in config the same way the source tree enforces it in code.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, JSON.

**Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md` — read section 7 (sweep 4) and section 5 (target config shape).

**Estimated effort:** 2–3 days.

**Prerequisites:**
- Sweeps 1, 2, 3 merged to `main`
- 24-hour cooling period after sweep 3 complete
- Clean checkout of `main`, tests green

**Exit criteria:**
1. `config.json` exists at repo root with the new tier-aware shape
2. `src/pi/obd_config.json` no longer exists
3. `src/common/config/schema.py` exists with dataclass types
4. `src/common/config/validator.py` validates the new structure
5. Every config reader uses the nested path (e.g., `config["pi"]["bluetooth"]`)
6. `python validate_config.py` passes
7. All Spool-authoritative values in `tieredThresholds` are unchanged (byte-for-byte diff)
8. All tests green
9. PR merged to `main`

**Risk**: Medium. Many call sites. Validator logic gets subtler with nested sections.

**Safety constraint:** Spool-authoritative values (everything under `tieredThresholds`) must not change. Any accidental value change stops the sweep.

---

## Task 1: Setup

- [ ] **Step 1: Start from clean main, verify 24-hour cooling complete**

Confirm at least 24 hours have passed since the sweep 3 merge.

```bash
cd Z:/o/OBD2v2
git checkout main
git log --oneline -3
git show --stat HEAD~1..HEAD 2>/dev/null | head -5
```

- [ ] **Step 2: Create sweep 4 branch**

```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep4-config main
```

- [ ] **Step 3: Verify baseline green**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 4: Snapshot tieredThresholds for preservation check**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/pi/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2, sort_keys=True))" > /tmp/sweep4-tiered-before.json
wc -l /tmp/sweep4-tiered-before.json
```

This file is the "before" snapshot. Any drift from this at task 10 is a sweep blocker.

---

## Task 2: Design the new config structure (read-only analysis)

**Goal:** Read the current `src/pi/obd_config.json` fully and decide exactly where each top-level key goes in the new structure.

- [ ] **Step 1: Enumerate current top-level keys**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/pi/obd_config.json')); print('\n'.join(sorted(c.keys())))"
```

Expected: 20 keys (`profiles` lost its `alertThresholds` in sweep 2).

Likely keys: `application`, `database`, `bluetooth`, `vinDecoder`, `display`, `autoStart`, `staticData`, `realtimeData`, `analysis`, `aiAnalysis`, `profiles`, `calibration`, `pollingTiers`, `tieredThresholds`, `alerts`, `dataRetention`, `batteryMonitoring`, `powerMonitoring`, `export`, `simulator`, `logging`.

- [ ] **Step 2: Classify each key into top-level, pi, or server**

Open `docs/superpowers/plans/sweep4-classification.md` (create new):
```markdown
# Sweep 4 Key Classification

## Top-level (shared)
- logging (both tiers need their own logger config, but the shape is shared)
- (protocolVersion, schemaVersion, deviceId are NEW keys added in sweep 4 — not in current file)

## pi: section
- application
- database (Pi-side SQLite)
- bluetooth
- vinDecoder
- display
- autoStart
- staticData
- realtimeData
- analysis (Pi-side realtime stats)
- profiles
- calibration
- pollingTiers
- tieredThresholds
- alerts
- dataRetention
- batteryMonitoring
- powerMonitoring
- export
- simulator

## server: section
- aiAnalysis → renamed to "ai" for consistency with src/server/ai/ (contains ollama host, model, timeouts)
- database → there is NO current server database section; create an empty placeholder "database: { ... }" to be populated when MariaDB config is wired up

## Questions / ambiguities
- Is `aiAnalysis` Pi-side or server-side? It currently holds the Ollama host URL, which is a remote resource. The CALLER runs on the server (post-sweep 3 move of src/ai/ to src/server/ai/). Verdict: **server**.
- Is `analysis` key (separate from `aiAnalysis`) Pi or server? Currently, src/pi/analysis/ has real-time stats for display (Pi), and src/server/analysis/ is a skeleton (empty). The config keys under `analysis` (window sizes, outlier thresholds) are consumed by src/pi/analysis/engine.py. Verdict: **pi**.
```

Review and verify each classification. If anything is ambiguous, read the consumer code to decide.

- [ ] **Step 3: Identify the Spool-authoritative tieredThresholds section placement**

Spool-authoritative values live in `tieredThresholds`. In the new shape, this goes under `pi:` (the Pi reads them for real-time alerting). Document this in the classification file.

- [ ] **Step 4: Commit the classification notes**

```bash
cd Z:/o/OBD2v2
git add docs/superpowers/plans/sweep4-classification.md
git commit -m "chore: sweep 4 key classification"
```

---

## Task 3: Rewrite `config.json` at the repo root with new shape

**Goal:** Create the new `config.json` file at the repo root. Do NOT delete the old `src/pi/obd_config.json` yet — keep it as a reference until we've verified the new file works.

**Files:**
- Create: `config.json` (repo root)

- [ ] **Step 1: Write the new config.json at repo root**

Create `config.json` at the repo root with this structure. Use the values from `src/pi/obd_config.json` — don't invent new values.

Template:
```json
{
  "protocolVersion": "1.0.0",
  "schemaVersion": "1.0.0",
  "deviceId": "${DEVICE_ID}",
  "logging": {
    "__COMMENT__": "Paste the existing 'logging' section here verbatim"
  },
  "pi": {
    "application": {
      "__COMMENT__": "Paste the existing 'application' section here verbatim"
    },
    "database": {
      "__COMMENT__": "Paste the existing 'database' section here verbatim"
    },
    "bluetooth": { "__COMMENT__": "Paste verbatim" },
    "vinDecoder": { "__COMMENT__": "Paste verbatim" },
    "display": { "__COMMENT__": "Paste verbatim" },
    "autoStart": { "__COMMENT__": "Paste verbatim" },
    "staticData": { "__COMMENT__": "Paste verbatim" },
    "realtimeData": { "__COMMENT__": "Paste verbatim" },
    "analysis": { "__COMMENT__": "Paste existing 'analysis' section (Pi-side realtime stats) verbatim" },
    "profiles": { "__COMMENT__": "Paste verbatim (already stripped of alertThresholds in sweep 2)" },
    "calibration": { "__COMMENT__": "Paste verbatim" },
    "pollingTiers": { "__COMMENT__": "Paste verbatim" },
    "tieredThresholds": { "__COMMENT__": "Paste existing 'tieredThresholds' VERBATIM — Spool-authoritative values must not change" },
    "alerts": { "__COMMENT__": "Paste verbatim" },
    "dataRetention": { "__COMMENT__": "Paste verbatim" },
    "batteryMonitoring": { "__COMMENT__": "Paste verbatim" },
    "powerMonitoring": { "__COMMENT__": "Paste verbatim" },
    "export": { "__COMMENT__": "Paste verbatim" },
    "simulator": { "__COMMENT__": "Paste verbatim" }
  },
  "server": {
    "ai": {
      "__COMMENT__": "Paste existing 'aiAnalysis' section verbatim, renamed to 'ai' for consistency with src/server/ai/"
    },
    "database": {
      "__COMMENT__": "Placeholder for future MariaDB config (host, port, credentials). Empty for now."
    },
    "api": {
      "__COMMENT__": "Placeholder for future FastAPI config (port, API key, CORS). Empty for now."
    }
  }
}
```

Read `src/pi/obd_config.json` and replace every `"__COMMENT__"` placeholder with the actual JSON content from the corresponding section. For example, if the old file has:

```json
"bluetooth": {
  "deviceMac": "00:04:3E:85:0D:FB",
  "retryCount": 3,
  "retryDelay": 2.0
}
```

Then `config.json` should have:

```json
"pi": {
  ...
  "bluetooth": {
    "deviceMac": "00:04:3E:85:0D:FB",
    "retryCount": 3,
    "retryDelay": 2.0
  },
  ...
}
```

**Important**:
- `tieredThresholds` must be pasted byte-for-byte with no modifications
- `aiAnalysis` is renamed to `ai` when it moves under `server:`
- `server.database` and `server.api` are placeholders (empty objects `{}`)

- [ ] **Step 2: Validate JSON syntax**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('config.json')); print('VALID'); print('Top-level:', sorted(c.keys())); print('pi keys:', sorted(c['pi'].keys())); print('server keys:', sorted(c['server'].keys()))"
```

Expected:
```
VALID
Top-level: ['deviceId', 'logging', 'pi', 'protocolVersion', 'schemaVersion', 'server']
pi keys: [19 keys]
server keys: ['ai', 'api', 'database']
```

- [ ] **Step 3: Diff tieredThresholds against the snapshot**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('config.json')); print(json.dumps(c['pi']['tieredThresholds'], indent=2, sort_keys=True))" > /tmp/sweep4-tiered-after.json
diff /tmp/sweep4-tiered-before.json /tmp/sweep4-tiered-after.json && echo "TIERED UNCHANGED"
```

Expected: `TIERED UNCHANGED` and no diff. If any diff, stop — you accidentally touched a Spool-authoritative value.

- [ ] **Step 4: Commit the new config.json**

```bash
cd Z:/o/OBD2v2
git add config.json
git commit -m "feat: create config.json at repo root with tier-aware shape (sweep 4, task 3)

New structure:
- Top-level shared keys: protocolVersion, schemaVersion, deviceId, logging
- pi: section with 19 Pi-specific settings
- server: section with ai, database (placeholder), api (placeholder)

Values copied verbatim from src/pi/obd_config.json. tieredThresholds
preserved byte-for-byte (verified via diff). The old file stays in
place until all callers are updated in tasks 4-6."
```

---

## Task 4: Create `src/common/config/schema.py` with dataclass types

**Goal:** Add typed schemas for the new config structure. Each section gets a `@dataclass(slots=True, kw_only=True)` type. These types are consumed by the validator and eventually by typed config-reading helpers.

**Files:**
- Create: `src/common/config/schema.py`

- [ ] **Step 1: Create schema.py**

Create `src/common/config/schema.py`:
```python
################################################################################
# File Name: schema.py
# Purpose/Description: Dataclass types describing config.json structure
# Author: Ralph Agent
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial — sweep 4 config restructure
# ================================================================================
################################################################################
"""
Typed schema for config.json.

Provides dataclass types describing the tier-aware config structure. These
types are used by the validator and by typed config-reading helpers.

**Intentional scope limit**: These dataclasses describe the SHAPE, not every
leaf value's type. Where a section is a free-form dict (e.g., per-parameter
threshold values), the type is `dict[str, Any]`. Tighter typing lands
incrementally as specific sections stabilize.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, kw_only=True)
class LoggingConfig:
    """Shared logging configuration."""

    level: str = "INFO"
    format: str = ""
    filePath: str | None = None
    maxBytes: int = 100 * 1024 * 1024
    backupCount: int = 7


@dataclass(slots=True, kw_only=True)
class PiConfig:
    """Pi-specific config sections. Each field is a free-form dict for now."""

    application: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    bluetooth: dict[str, Any] = field(default_factory=dict)
    vinDecoder: dict[str, Any] = field(default_factory=dict)
    display: dict[str, Any] = field(default_factory=dict)
    autoStart: dict[str, Any] = field(default_factory=dict)
    staticData: dict[str, Any] = field(default_factory=dict)
    realtimeData: dict[str, Any] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    profiles: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    pollingTiers: dict[str, Any] = field(default_factory=dict)
    tieredThresholds: dict[str, Any] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    dataRetention: dict[str, Any] = field(default_factory=dict)
    batteryMonitoring: dict[str, Any] = field(default_factory=dict)
    powerMonitoring: dict[str, Any] = field(default_factory=dict)
    export: dict[str, Any] = field(default_factory=dict)
    simulator: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class ServerConfig:
    """Server-specific config sections."""

    ai: dict[str, Any] = field(default_factory=dict)
    database: dict[str, Any] = field(default_factory=dict)
    api: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class AppConfig:
    """Top-level config shape."""

    protocolVersion: str
    schemaVersion: str
    deviceId: str
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    pi: PiConfig = field(default_factory=PiConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> "AppConfig":
        """Build AppConfig from a loaded config.json dict."""
        return cls(
            protocolVersion=data["protocolVersion"],
            schemaVersion=data["schemaVersion"],
            deviceId=data["deviceId"],
            logging=LoggingConfig(**(data.get("logging") or {})),
            pi=PiConfig(**(data.get("pi") or {})),
            server=ServerConfig(**(data.get("server") or {})),
        )


__all__ = ["AppConfig", "LoggingConfig", "PiConfig", "ServerConfig"]
```

- [ ] **Step 2: Update `src/common/config/__init__.py` to re-export schema types**

Add to `src/common/config/__init__.py`:
```python
from .schema import AppConfig, LoggingConfig, PiConfig, ServerConfig  # noqa: F401
```

- [ ] **Step 3: Smoke-test the schema**

```bash
cd Z:/o/OBD2v2
python -c "
import json
from src.common.config.schema import AppConfig
with open('config.json') as f:
    data = json.load(f)
cfg = AppConfig.fromDict(data)
print('protocolVersion:', cfg.protocolVersion)
print('pi.bluetooth:', cfg.pi.bluetooth)
print('server.ai:', cfg.server.ai)
print('OK')
"
```

Expected: prints the values and `OK`. If any KeyError, the config file is missing a required field — go back to task 3 and add it.

- [ ] **Step 4: Commit schema.py**

```bash
cd Z:/o/OBD2v2
git add src/common/config/schema.py src/common/config/__init__.py
git commit -m "feat: add src/common/config/schema.py with AppConfig dataclasses (sweep 4, task 4)"
```

---

## Task 5: Update `src/common/config/validator.py` for the new shape

**Goal:** Teach the validator about the new structure. Top-level required fields, pi section validation, server section validation.

**Files:**
- Modify: `src/common/config/validator.py`

- [ ] **Step 1: Read the current validator**

Read: `src/common/config/validator.py`

Note the structures that exist today:
- A `REQUIRED_FIELDS` list (or similar) — probably uses flat paths like `bluetooth.deviceMac`
- A `DEFAULTS` dict — probably uses dot-notation paths
- A `validateConfig()` function (or similar)

- [ ] **Step 2: Update REQUIRED_FIELDS for the new shape**

Change the required field paths to use the nested structure:
- `bluetooth.deviceMac` → `pi.bluetooth.deviceMac`
- `database.path` → `pi.database.path`
- `aiAnalysis.ollamaHost` → `server.ai.ollamaHost`

Also add new required top-level fields:
- `protocolVersion`
- `schemaVersion`
- `deviceId`

The full list of required fields depends on what the current validator requires. Preserve the existing requirements, just move them under `pi.` or `server.` prefixes.

- [ ] **Step 3: Update DEFAULTS for the new shape**

Similarly, prefix dot-notation paths:
- `database.timeout` → `pi.database.timeout`
- `api.retry.maxRetries` → (likely `pi.alerts.retryMaxRetries` or similar — whatever the current key is, prefix with `pi.` or `server.`)

- [ ] **Step 4: Update the validation function to understand nested sections**

If the validator uses a recursive approach with dot-notation, it should already work. If it assumes flat keys, update it to walk nested sections.

- [ ] **Step 5: Add a top-level shape sanity check**

At the start of `validateConfig()`, add:
```python
if "pi" not in config:
    raise ConfigValidationError("Missing top-level 'pi' section")
if "server" not in config:
    raise ConfigValidationError("Missing top-level 'server' section")
if "protocolVersion" not in config:
    raise ConfigValidationError("Missing top-level 'protocolVersion'")
if "schemaVersion" not in config:
    raise ConfigValidationError("Missing top-level 'schemaVersion'")
```

- [ ] **Step 6: Run validate_config.py against the new config.json**

```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -15
```

**This will probably fail** because `validate_config.py` still references the old config path (`src/pi/obd_config.json`). That's fine — task 7 handles it. For now, try direct validation:

```bash
cd Z:/o/OBD2v2
python -c "
import json
from src.common.config.validator import validateConfig
with open('config.json') as f:
    data = json.load(f)
validateConfig(data)
print('VALID')
"
```

Expected: `VALID`. If any error, fix the validator.

- [ ] **Step 7: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -20
```

Expected: `test_config_validator.py` and any test that exercises the validator may fail because they use the OLD flat-config format. Those get rewritten in task 8. For now, record which tests fail.

- [ ] **Step 8: Commit validator updates**

```bash
cd Z:/o/OBD2v2
git add src/common/config/validator.py
git commit -m "refactor: update config validator for tier-aware shape (sweep 4, task 5)"
```

---

## Task 6: Update every config reader to use nested paths

**Goal:** Every call site that reads from the config dict needs to use the new nested path.

**Files:**
- Modify: every file that reads from config

- [ ] **Step 1: Find all config-reading patterns**

```bash
cd Z:/o/OBD2v2
grep -rn "config\[['\"]bluetooth['\"]\]\|config\.get(['\"]bluetooth['\"]" src/ tests/ 2>/dev/null | head -30
```

Also search for other top-level keys:
```bash
cd Z:/o/OBD2v2
for key in application database bluetooth vinDecoder display autoStart staticData realtimeData analysis aiAnalysis profiles calibration pollingTiers tieredThresholds alerts dataRetention batteryMonitoring powerMonitoring export simulator logging; do
    echo "=== $key ==="
    grep -rn "config\[['\"]$key['\"]\]\|config\.get(['\"]$key['\"]" src/ 2>/dev/null | head -5
done
```

Record which files access which keys.

- [ ] **Step 2: Update each reader to use the nested path**

For each file returned by step 1:
- `config["bluetooth"]` → `config["pi"]["bluetooth"]`
- `config.get("bluetooth", {})` → `config.get("pi", {}).get("bluetooth", {})`
- `config["aiAnalysis"]` → `config["server"]["ai"]` (note also the rename)
- `config["logging"]` → `config["logging"]` (unchanged — logging is top-level)

Pattern: every section that moved under `pi:` or `server:` gets a nested path; top-level shared keys (logging, protocolVersion, schemaVersion, deviceId) stay flat.

- [ ] **Step 3: Update config file path references**

Find any code that hardcodes `src/pi/obd_config.json` or `src/obd_config.json`:
```bash
cd Z:/o/OBD2v2
grep -rn "obd_config\.json" src tests 2>/dev/null
```

For each, update to `config.json` at the repo root. The exact path depends on how paths are resolved — absolute paths should now point to the repo root + `config.json`.

Common patterns:
- `'src/pi/obd_config.json'` → `'config.json'` (relative to CWD = repo root)
- `Path(__file__).parent / 'obd_config.json'` → `Path(__file__).resolve().parents[N] / 'config.json'` (where N is the distance to repo root)

- [ ] **Step 4: Update default config path in CLI argparse**

Search for `--config` default value:
```bash
cd Z:/o/OBD2v2
grep -rn "default=.*obd_config\|default=.*config\.json" src tests 2>/dev/null
```

Update defaults to point at `config.json` at repo root.

- [ ] **Step 5: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: most tests pass. Remaining failures are likely:
- Tests that use a fixture with the OLD flat config shape (task 8)
- Tests that hardcode the old config path (task 8)

- [ ] **Step 6: Commit the config reader updates**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: update all config readers to use nested pi:/server: paths (sweep 4, task 6)"
```

---

## Task 7: Update `validate_config.py` at repo root

**Files:**
- Modify: `validate_config.py`

- [ ] **Step 1: Read the current validate_config.py**

Read `validate_config.py` at the repo root.

- [ ] **Step 2: Update config path to point at the new location**

Find any reference to `src/obd_config.json` or `src/pi/obd_config.json` and change it to `config.json`.

- [ ] **Step 3: Update imports**

If the file imports `from src.common.config_validator import X`, that path changed in sweep 3 — it's now `from src.common.config.validator import X`. Verify and update if needed.

- [ ] **Step 4: Run validate_config.py**

```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -20
```
Expected: passes cleanly.

- [ ] **Step 5: Run with --verbose if supported**

```bash
cd Z:/o/OBD2v2
python validate_config.py --verbose 2>&1 | tail -30
```
Expected: passes, shows details.

- [ ] **Step 6: Commit**

```bash
cd Z:/o/OBD2v2
git add validate_config.py
git commit -m "refactor: update validate_config.py for new config path and shape (sweep 4, task 7)"
```

---

## Task 8: Update tests for the new config shape

**Goal:** Tests that build or assert on the old flat config shape need updating.

**Files:**
- Modify: test files that use config fixtures

- [ ] **Step 1: Run the full test suite and capture failures**

```bash
cd Z:/o/OBD2v2
pytest tests/ -q --tb=short 2>&1 | tail -60
```

Record every failing test. Common patterns:
- `KeyError: 'bluetooth'` — test reads from old flat shape
- `FileNotFoundError: src/obd_config.json` — test hardcodes old path
- `ConfigValidationError: Missing top-level 'pi' section` — test builds a flat config fixture

- [ ] **Step 2: Find test fixtures that build flat configs**

```bash
cd Z:/o/OBD2v2
grep -rn "'bluetooth':\|'database':\|'display':" tests/ 2>/dev/null | head -30
```

For each fixture returned, read the test file to find the config-building function (often called `make_config`, `valid_config`, `get_test_config`, etc.). Rewrite to produce the new nested shape:

Before:
```python
def make_config():
    return {
        "bluetooth": {...},
        "database": {...},
        "tieredThresholds": {...},
    }
```

After:
```python
def make_config():
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "test-device",
        "logging": {"level": "DEBUG"},
        "pi": {
            "bluetooth": {...},
            "database": {...},
            "tieredThresholds": {...},
        },
        "server": {
            "ai": {},
            "database": {},
            "api": {},
        },
    }
```

- [ ] **Step 3: Update each failing test**

For each test file:
1. Update its fixture
2. Run just that file: `pytest tests/test_X.py -v`
3. Commit when green

Use commits like:
```bash
git add tests/test_X.py
git commit -m "test: update test_X fixtures for tier-aware config (sweep 4, task 8)"
```

- [ ] **Step 4: Run full fast suite again**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
```

Expected: all pass.

---

## Task 9: Delete the old `src/pi/obd_config.json`

**Goal:** Now that all callers use `config.json` at the repo root, delete the old file.

- [ ] **Step 1: Final grep for any stragglers**

```bash
cd Z:/o/OBD2v2
grep -rn "obd_config\.json" src tests validate_config.py 2>/dev/null
```

Expected: zero hits. If any remain, they're missed call sites — fix them before deleting.

- [ ] **Step 2: Delete the old config file**

```bash
cd Z:/o/OBD2v2
git rm src/pi/obd_config.json
git status
```

- [ ] **Step 3: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
```

Expected: green. If red, a test hardcoded the old path and grep missed it — find and fix.

- [ ] **Step 4: Commit the deletion**

```bash
cd Z:/o/OBD2v2
git commit -m "refactor: delete old src/pi/obd_config.json (sweep 4, task 9)"
```

---

## Task 10: Spool preservation check + full verification

**Goal:** Final check that tieredThresholds values are unchanged, plus full test/lint/type/simulator verification.

- [ ] **Step 1: Diff tieredThresholds final state**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('config.json')); print(json.dumps(c['pi']['tieredThresholds'], indent=2, sort_keys=True))" > /tmp/sweep4-tiered-final.json
diff /tmp/sweep4-tiered-before.json /tmp/sweep4-tiered-final.json && echo "TIERED UNCHANGED FROM SWEEP 4 START"
```

Expected: no diff. If diff, stop and revert.

- [ ] **Step 2: Full test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -15
```
Expected: same count as sweep 3 end.

- [ ] **Step 3: Ruff**

```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -10
```

- [ ] **Step 4: Mypy**

```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -10
```

- [ ] **Step 5: validate_config.py**

```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -10
```

- [ ] **Step 6: Simulator smoke test**

```bash
cd Z:/o/OBD2v2
timeout 30 python src/pi/main.py --simulate --dry-run 2>&1 | tail -30
```

**Note**: if main.py's default `--config` path was updated in task 6 step 4, the simulator should find the new `config.json` automatically. If not, run with `--config config.json`.

---

## Task 11: Cleanup, design doc update, merge

- [ ] **Step 1: Delete sweep 4 classification notes**

```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep4-classification.md
git commit -m "chore: remove sweep 4 classification scratch file"
```

- [ ] **Step 2: Append sweep 4 status to design doc section 12**

Append to `docs/superpowers/specs/2026-04-12-reorg-design.md`:
```markdown
| YYYY-MM-DD | 4 | Sweep 4 complete. Promoted obd_config.json to config.json at repo root. Restructured into tier-aware shape (top-level shared + pi:/server: sections). Added AppConfig dataclass schema. Updated validator, all readers, tests. tieredThresholds preserved byte-for-byte. All tests green. Simulator smoke test green. |
```

- [ ] **Step 3: Commit and merge**

```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs: sweep 4 status update"
```

- [ ] **Step 4: Surface to CIO for merge approval**

> "Sweep 4 complete. Config.json now lives at repo root with tier-aware sections. Spool values preserved byte-for-byte. All tests green. Ready to merge to main?"

Wait for approval.

- [ ] **Step 5: Merge to main**

```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep4-config -m "Merge sprint/reorg-sweep4-config: Sweep 4 complete — config restructure

Sweep 4 of 6 for the structural reorganization (B-040).

- Promoted obd_config.json → config.json at repo root
- Rewrote into tier-aware shape: top-level shared + pi: + server: sections
- Created src/common/config/schema.py with AppConfig dataclass types
- Updated validator for the new structure
- Updated every config reader to use nested paths
- Renamed 'aiAnalysis' → 'server.ai' for consistency with src/server/ai/
- Added placeholder server.database and server.api sections
- All Spool-authoritative values in tieredThresholds unchanged (verified via diff)
- All tests green, simulator green
- Design doc: docs/superpowers/specs/2026-04-12-reorg-design.md"
```

- [ ] **Step 6: Announce**

> "Sweep 4 merged. Sweep 5 (split oversized files, including orchestrator per TD-003) is ready. Sweep 5 has a 24-hour cooling period after merge before sweep 6 starts."

---

## End of Sweep 4 Plan

**Success criteria:**
- ✅ `config.json` at repo root with new shape
- ✅ `src/common/config/schema.py` with AppConfig dataclasses
- ✅ Validator handles new shape
- ✅ Every reader uses nested paths
- ✅ Spool values unchanged
- ✅ All tests green, simulator green
- ✅ Merged to main

**On to sweep 5**: `docs/superpowers/plans/2026-04-12-reorg-sweep5-file-sizes.md`
