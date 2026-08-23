# TD-082 — `test_allAcceptedTables` enumerates the sync table set by hand and went stale when `pi_state` was added

- **Filed:** 2026-08-21 by Rex (Ralph, Agent 1) during US-563 (Sprint 75 / V0.29.30)
- **Class:** test brittleness / silent-RED (full-suite is a PM integration gate, so this went RED unnoticed in-loop)
- **Severity:** low (test-only; no production impact) — but it is the *same shape* as TD-062 and hides real drift
- **Scope note:** OUT of US-563's scope-fence (Refusal Rule 3). Flagged, not fixed, per the "drift spotted outside current scope → TD" rule.

## The failure

```
FAILED tests/server/test_sync.py::TestSyncRequestValidation::test_allAcceptedTables
E   AssertionError: assert frozenset({...}) == {...}
E   Extra items in the left set:
E   'pi_state'
```

`tests/server/test_sync.py:187` asserts `ACCEPTED_TABLES == { ...hand-written literal set... }`. `ACCEPTED_TABLES` derives from `_TABLE_REGISTRY` in `src/server/api/sync.py`, so appending a table to the registry breaks the test unless someone remembers to edit the literal too.

## Verified PRE-EXISTING — not caused by US-563

US-563 modified `sync.py`, so the obvious suspicion is that it caused this. It did not, and this was checked rather than assumed:

- US-563's `sync.py` diff changes **only** the `"drive_summary"` registry entry, adding the `ambient_temp_at_start_c → intake_air_temp_at_start_c` rename shim. It adds no table.
- `git show HEAD:src/server/api/sync.py` has `"pi_state": (PiState, ())` already at **line 214**, added by **US-453 (D-7 / F-082)**.

So the test has been RED since `pi_state` landed, independent of this sprint.

## Why it is worth fixing rather than re-pinning

This is TD-062's pattern in a second location: a test that re-states a value the production code already owns, with nothing forcing the two to reconcile when the production side moves. Re-typing the literal with `pi_state` added would restore green and leave the trap armed for the next table.

Preferred fix — assert the *invariant*, not the *inventory*:

```python
# ACCEPTED_TABLES is DERIVED; assert the derivation, not a copy of the answer.
assert ACCEPTED_TABLES == frozenset(_TABLE_REGISTRY)
# ...then pin the properties that actually matter, e.g.:
assert 'realtime_data' in ACCEPTED_TABLES        # load-bearing members
assert 'schema_migrations' not in ACCEPTED_TABLES  # never syncable
```

If the intent really is "no table joins the sync surface without a human noticing", that is a legitimate goal — but it should be stated as such (an explicit allow-list with a comment saying *why* each entry is safe to accept), not as an incidental equality check that reads like a typo when it fails.

## Recommendation

- Re-point `test_allAcceptedTables` to assert the derivation plus the load-bearing membership facts.
- Fold into the same sweep as **TD-062** — both are "a test hand-copied a set/ordering the production code owns". Fixing them together, and adding the grep guard TD-062 already recommends, is one small job.

## Full-suite state at US-563 close (for PM's integration gate)

`pytest tests/server` = **3 failures, all verified pre-existing, none from US-563**:

| Test | Covered by |
|---|---|
| `test_migration_0015...::test_registryStaysSortedWithV0015AtTail` | TD-062 |
| `test_pi_state_sync.py::test_v0019IsLastInAscendingOrder` | TD-062 |
| `test_sync.py::test_allAcceptedTables` | **TD-082 (this file)** |

Both tail-pin failures now read `'0024'` instead of `'0023'` because US-563 appended v0024 — the *value* changed, the *failure* did not.
