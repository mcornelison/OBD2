# Spool — Spec Invariant Must Be Validated Against the Real Signal

> Spool persona / feedback. Migrated 2026-05-18 from `~/.claude/.../feedback_spec_invariant_validated_against_real_signal.md` per CIO directive.

When a spec states a safety invariant on an input (e.g. sec 6.2 "on battery, sustained, **debounced**"), that invariant must be **implemented in the trigger and tested against the real signal's transient/boot behavior** — not treated as implied by a dependency and not validated by a test that stubs the predicate True. Green unit suite + green ruff + green validate_config can certify a build that bricks hardware on first IRL contact.

**Why:** I-038 (Session 38, V0.27.14 Phase-2 `eclipse-powerwatch`). The trigger acted on `UpsMonitor.getPowerSource()` — a VCELL-trend heuristic — whose boot VCELL-sag falsely reports BATTERY within ~10s even on external power. The "debounced" invariant was assumed implied by the dependency; the T8 "real-invocation guard" passed only because it stubbed `isOnBattery=True` and never exercised the real transient. Result: the Pi self-powered-off ~10–15s after every boot, 3× repeated → CIO verdict **Sprint 38 / Phase-2 = BIG FAIL**, a bricking regression shipped to real hardware. Same family as "inventory-first" (T9 lesson): a spec requirement treated as already-handled rather than executed + verified.

**How to apply:**
- For any safety-critical or destructive trigger (poweroff, shutdown, delete, send), the validating test MUST drive the **real or faithfully-replayed signal** through its known nasty regimes (boot transient, late I2C, blip, sustained), not a stubbed boolean.
- When a spec uses words like "sustained / debounced / confirmed / after grace", treat each as a concrete, separately-tested code path — never "the dependency does that."
- Default the uncertain/failed-read branch to the SAFE (no-op) direction, never the catastrophic one — extends `retry-path-defaults-to-uncertain-not-success`.
- PM: when grooming/accepting runtime-safety stories, require the acceptance to name the real-signal regimes the test exercises; a stubbed-predicate guard is not IRL validation. Cross-ref TD-053.
