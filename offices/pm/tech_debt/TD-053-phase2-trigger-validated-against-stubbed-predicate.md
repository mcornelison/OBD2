# TD-053 — Phase-2 safety trigger must be validated against the real signal, not a stubbed predicate

**Status**: Open (test-hardening; V0.28+ / re-deploy-gate candidate)
**Filed**: 2026-05-18 (Session 38, Marcus/PM — at Ralph's explicit recommendation)
**Origin**: I-038 (Phase-2 powerwatch self-bricking regression, SEV-1)

## The debt

The Phase-2 `eclipse-powerwatch` trigger shipped a bricking regression to real
hardware (I-038) because its safety-critical input — "on battery, sustained,
debounced" — was **never exercised against the real `UpsMonitor` boot/transient
signal behavior**. The T8 "real-invocation guard" test passed because it
**stubbed `isOnBattery=True`**; it did NOT exercise the VCELL-trend heuristic's
boot-sag transient (which falsely reports BATTERY within ~2 poll ticks even on
external power). A green test suite + green ruff + green `validate_config`
therefore certified a build that bricked the Pi on first IRL contact.

## Required remediation

A Phase-2 trigger regression test that exercises the **real** (or
faithfully-replayed) `UpsMonitor`/GPIO signal under:
- Boot-time VCELL sag on external power (must NOT trip the trigger).
- Failed/late I2C VCELL read at boot (must NOT force poweroff — uncertain
  direction is no-op, per the `84b5469` reversal).
- Genuine sustained on-battery (MUST trip, after `bootGraceSec` +
  `confirmWindowSec`).
- Transient battery blip (must abort with no poweroff).

The hotfix (`84b5469` debounce + `4edbdc1` GPIO6 ground-truth) adds regression
tests for the transient-blip / failed-vcell cases; this TD tracks closing the
**general** gap: safety triggers are validated against the real signal's
transient/boot behavior, never a stubbed boolean predicate.

## Generalized rule (see feedback memory)

A spec invariant (here: "debounced") must be **implemented and tested against
the real signal**, not assumed to be implied by a dependency and asserted via a
stubbed predicate. Cross-ref:
[[feedback-spec-invariant-validated-against-real-signal]],
[[feedback-inventory-first-before-first-dispatch]] (the T9 sibling lesson).

## Related

- I-038 (the incident this debt enabled)
- BL-018 (Spool empirical tuning of the new debounce/grace bounds)
