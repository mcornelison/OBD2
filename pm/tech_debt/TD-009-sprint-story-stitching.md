# TD-009: Sprint Stories Need Better "Stitching"

**Filed by**: Ralph Agent (per CIO direction)
**Date**: 2026-02-05
**Related Stories**: US-OLL-001, US-OLL-002, US-OLL-003
**Priority**: Medium

## Problem

User stories in the current sprint modify `obd_config.json` (adding new config keys) but don't include corresponding updates to:

1. **ConfigValidator** (`src/common/config_validator.py`) — New keys like `aiAnalysis.apiTimeoutSeconds` and `aiAnalysis.healthTimeoutSeconds` may need to be registered in the validator's DEFAULTS dict or schema.
2. **Config documentation** — No story covers documenting the new config keys.
3. **Integration testing** — No story validates the end-to-end flow: config file -> secrets_loader -> validator -> OllamaManager.

Stories are written as isolated units but config changes have downstream effects that cross story boundaries.

## CIO Direction

CIO and PM will work together to make future sprints more "stitched together" — ensuring that when a story adds a config key, related validator/doc/integration updates are included in the same sprint.

## Suggested Fix

For future sprints, include a checklist in story templates:
- [ ] If adding config keys: update ConfigValidator DEFAULTS
- [ ] If adding env vars: update .env.example
- [ ] If changing integration points: include integration test story

## Impact

Medium — Missing stitching causes developer confusion and potential runtime issues when new config keys bypass validation.
