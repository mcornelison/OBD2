# TD-062 — Brittle absolute-tail assertions in migration tests silently go RED on every registry append

- **Filed:** 2026-07-05 by Rex (Ralph, Agent 1) during US-458 (Sprint 55 / V0.29.9)
- **Class:** test brittleness / silent-RED (full-suite = PM integration gate, so these went RED unnoticed in-loop)
- **Severity:** low (test-only; no production impact) but recurring — it has bitten this sprint already (US-454 de-brittled a sibling)
- **Scope note:** OUT of US-458's scope-fence (Refusal Rule 3). US-458 appended `v0023` to `ALL_MIGRATIONS` but did NOT newly break these — both were already RED before v0023 (see below). Flagged, not fixed, per the "drift spotted outside current scope → TD" rule.

## The pattern

Several migration test files assert `versions[-1] == '<their own version>'` (the migration registry's *absolute tail*). This is only true until the NEXT migration is appended, after which it silently goes RED. Because Ralph runs only TARGETED tests in-loop (full `pytest tests/` is a PM/integration gate, TD-059), these REDs are invisible until PM runs the full suite at sprint close.

## Currently-RED instances (verified pre-existing, independent of US-458's v0023)

1. **`tests/server/test_migration_0015_foreign_vehicle_data_quality.py:196`**
   `test_registryStaysSortedWithV0015AtTail` asserts `versions[-1] == '0015'`.
   RED since **v0016** (Sprint 52 / V0.29.6) — has been broken for 3 sprints.

2. **`tests/server/test_pi_state_sync.py:119`**
   `test_v0019IsLastInAscendingOrder` asserts `versions[-1] == '0019'`.
   RED since **v0020** (US-454, same Sprint 55) — a same-sprint regression: US-453 shipped v0019 as the tail, then US-454/455/451 appended v0020/21/22.

## The established fix (precedent in-sprint)

US-454's completionNotes record de-brittling the **identical** trap in `test_migration_0018`:
> "de-brittled test_migration_0018::test_v0018RegisteredLastAndSorted — its `versions[-1]=='0018'` absolute-tail assertion went silently RED when US-453 appended v0019. Re-pointed to assert v0018 PRESENT + sorted + directly-after-v0017 (the real invariant)."

v0020/0021/0023's own registration tests already use the de-brittled form (present + sorted + directly-after-predecessor). The fix for the two RED files above is the same one-line re-point:

```python
versions = [m.version for m in ALL_MIGRATIONS]
assert versions == sorted(versions)
assert '00NN' in versions
assert versions[versions.index('00NN') - 1] == '00<NN-1>'
```

## Recommendation

- Re-point the two assertions above to the de-brittled form (present + sorted + directly-after-predecessor), which is the real invariant each test intends.
- Optionally add a lint/grep guard (or a single shared registry-ordering test) so `versions[-1] == '<literal>'` cannot be reintroduced — this pattern has recurred at least 3× (v0015, v0018, v0019).
