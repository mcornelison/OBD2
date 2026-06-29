# Issue: stale test asserts the dead `.10` server IP (pre-existing red)

**Filed by:** Rex (Dev), 2026-06-28, during US-391 (Sprint 47 / V0.29.1).
**Severity:** Low (test-only; product is correct).
**Scope:** OUTSIDE US-391 — filed per Scope Fence (Rule 3), not fixed inline.

## Symptom

`tests/pi/sync/test_client_config_paths.py::TestValidatorShapeCompatibility::test_validatorOutput_constructsSyncClient`
fails:

```
assert client.baseUrl == "http://10.27.27.10:8000"
E   AssertionError: assert 'http://10.27.27.120:8000' == 'http://10.27.27.10:8000'
```

## Root cause

The test helper `_validatedMinimalConfig` (line 68) sets
`companionService: {"enabled": enabled}` only — no `baseUrl` — so the validator
applies its DEFAULT `pi.companionService.baseUrl`. That default was updated to
`http://10.27.27.120:8000` when **Chi-Srv-01 relocated `.10` → `.120` on
2026-06-18** (MEMORY current-state pointer; also reflected in `config.json` and
`src/common/config/validator.py:215`). The test's literal `.10` assertion (line
111) was never updated, so it has been red since the relocation.

## Not caused by US-391

US-391 (sync quarantine) touches `sync_log.py` / `client.py` / config defaults
for `quarantine*` keys only — it never modifies `baseUrl` or this test. Verified
red independent of the quarantine change.

## Suggested fix

One-line: change line 111 to `"http://10.27.27.120:8000"` (or, better, derive the
expectation from the validator default so it can't drift again — which is exactly
the spirit of **US-392** A-15 address de-dup in this same sprint). Recommend
folding into US-392 or a quick test-only patch.

## Repro

```
python -m pytest tests/pi/sync/test_client_config_paths.py::TestValidatorShapeCompatibility::test_validatorOutput_constructsSyncClient -q
```
