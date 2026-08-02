# I-041 — US-505 broke two `system_status_emitter` tests (sprint-branch red)

- **Filed:** 2026-08-02 by Ralph (Rex), during US-518
- **Severity:** Medium — 2 red tests on `sprint/sprint69-V0.29.24`; **will fail the PM
  integration gate at sprint close**
- **Introduced by:** `65de58d` `feat: [US-505] last-drive-summary producer…`
- **Not introduced by:** US-518 (my story). Filed under the scope fence rather than
  fixed inline.

## Symptom

```
FAILED tests/pi/splash/test_system_status_emitter.py::test_buildSystemStatusState_a3Schema_hasExactShape
FAILED tests/pi/splash/test_system_status_emitter.py::test_emitter_writesSystemStatusFile_andComputesStale
```

Both are the same cause — the built state now carries one extra key:

```
{'drive': {'driveId': 27, 'lastDrive': None, 'state': 'recording'}}
        != {'drive': {'driveId': 27,          'state': 'recording'}}
```

## Root cause

US-505 added the `drive.lastDrive` block to `buildSystemStatusState`
(`src/pi/splash/system_status_emitter.py`, last changed by `65de58d`) but did **not**
update `tests/pi/splash/test_system_status_emitter.py`, whose last commit is still
`f929ed8` (US-480-a). Those two tests assert the **EXACT** shape of the emitted state,
so adding any key to `drive` breaks them by design — that is the guard working, not a
bad test.

## Why it was not caught in-loop

US-505's `completionNotes` record the in-loop gate as
`tests/pi/splash/test_system_status_last_drive.py` — the story's **new** test file — plus
`tests/pi/obdii`, `tests/pi/orchestrator` and `tests/ui`. The **pre-existing** splash
test file that pins the schema was not in the scoped selection, so the regression was
invisible at the point it was introduced.

Generalisable: when a story adds a key to a shared state contract, the scoped in-loop
selection must include the **existing** exact-shape guards for that contract, not only
the new story's own tests. `tests/pi/splash/` as a whole would have caught this.

## Suggested fix (PM/Ralph, ~2 lines)

Add `'lastDrive': None` to the two expected `drive` dicts in
`tests/pi/splash/test_system_status_emitter.py` (lines ~64 and ~295). The production
behaviour is correct and intended per US-505 — only the expectations are stale.

Worth a moment's thought on whether the `lastDrive` key should be asserted as
*always present* (US-505's notes state it is deliberately always a key, null when
unknown, so a renderer cannot fall through to a wrong branch). If so, the fix should
pin that explicitly rather than just absorbing the new key.

## Cross-reference

Same shape as **TD-073** (filed by US-517): a pre-existing red on this sprint branch
that the per-story scoped gate cannot see, surfacing only at the integration gate.
Two now on one branch — worth a look at whether sprint close should run the full suite
earlier than close, or whether TD-059's in-loop/PM-gate split needs a middle tier.
