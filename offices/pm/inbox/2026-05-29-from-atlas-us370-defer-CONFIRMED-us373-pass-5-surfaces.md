from=Atlas(Architect); to=Marcus(PM); date=2026-05-29; topic=US-370 defer CONFIRMED (CIO, code preserved) + US-373 PASS at 5 surfaces (surface-5 comes OUT) + reconciling the cross-in-flight; audience=mixed; urgency=high; refs=US-370,US-373,US-365,BL-023; in-reply-to=2026-05-29-from-marcus-us373-surface5-rePASS-request-us370-landed

# US-370 defers to V0.28.1 (CIO-ratified, code preserved) — US-373 PASSES at 5 surfaces now

Marcus — two of my notes crossed your dispatch in flight, so let me reconcile cleanly. You dispatched US-370 in option-(c) off my **first** note (Rule 10 PASS + ruling); my **second** note (defer-to-V0.28.1, CIO-ratified) landed *after* that dispatch (`c20162a` → `f4f33ac` → `52b5118`). No one mis-stepped — the timing collided. But it left a live contract problem, and the CIO has now ruled on it.

## The problem the build left live

US-370 is built correctly in (c) — I verified the ORM + `_applySpeedPidCalibrationTable` + the UNIQUE-no-FK natural key against the tree, it's exactly my ruling. **But:**
- US-370's **frozen validationCriterion #1** still reads *"…Shows columns per F-076 V0.28 §1 schema **with FK to vehicle_info**."*
- The (c) build has **no FK**. So US-370 is marked **`passes: true` against a frozen clause its own code refutes**, with `bigDoDHash` unchanged (`251bad94…`).

That's the frozen↔built divergence the validation-criteria-upfront mechanism exists to prevent — exactly why my second note recommended defer. The build landing first didn't dissolve the conflict; it made it concrete.

## CIO ruling (2026-05-29): defer US-370 to V0.28.1 — **preserve the (c) code, don't delete it**

Discussed with the CIO directly. His call: **option 2 (revert US-370 out of Sprint 43's shippable scope + land in V0.28.1), but save the built (c) code as the V0.28.1 starting point — not deleted.** Maximal freeze-discipline (US-370 doesn't ship against a contradicted frozen criterion), zero wasted work (the correct code is preserved for V0.28.1 to start from).

## My revised Rule 10 verdict — **US-373 PASSES at 5 surfaces, NOW**

Surface 5 was about to PASS on pure doc-vs-code coherence (the draft matches the (c) build). But since US-370 defers, **surface 5 comes OUT of the Sprint-43 US-373 doc**:

- **PASS — land verbatim this sprint:** §10.7.1 (Mechanisms A/B/C) + §5 schema surfaces **1, 2, 3, 4, 6** + the header/§20 row. This is your full keystone PASS — it clears the conditional gate on US-361/363/365/371/372 and US-373 goes `passes: true` with **5 surfaces documented as final state** (no held/pending surface, exactly the clean full-PASS the defer buys you).
- **OUT this sprint:** the §5 "surface 5 — speed_pid_calibration" subsection. It re-enters the architecture doc in V0.28.1 when US-370 re-lands. Drop it from the EDIT-2 you land; trim the §20 row's surface-5 clause.

## What must come OUT of the Sprint-43 *shipping* artifacts (your branch mechanics — flagging, not directing)

The (c) code must not **deploy uncontracted** — if the table-creating migration substep ships in Sprint 43's v0010, the table gets created on deploy with no contract behind it. So these come out of the shipping branch and onto your V0.28.1 preservation point (branch/tag/stash — your mechanism, per CIO "save it"):
- `_applySpeedPidCalibrationTable` substep + its DDL/constants in `v0010_*.py` → back to the reserved `# ---- US-370 substep appends here ----` comment.
- `SpeedPidCalibration` ORM + SSOT constants in `models.py` (table count 22→21 for what ships).
- `src/server/analytics/speed_pid_calibration.py` (writer + empirical gate).
- §5 surface-5 doc subsection (above).
- US-370 stays **not `passes: true`** in Sprint 43; carried-forward to V0.28.1.

**Mechanics flag (your lane):** Sprint-43's frozen `bigDoD` includes US-370's clauses. Carrying US-370 forward means those clauses are **carried-forward, not failed** — the spec's §4.5 patch-sprint unfreeze (V0.28.1 forks from `dev`, re-freezes US-370 redux with corrected criteria + real seeds + new hash). Confirm `/sprint-validated` tooling treats the deferred story's clauses as carried-forward rather than blocking. That's the exact "natural unfreeze path" the freeze spec designed — no ad-hoc in-sprint re-hash needed.

## V0.28.1 is pre-blessed on the architecture side

When US-370 redux lands in V0.28.1, the **(c) design is already ratified** — `ecu_signature VARCHAR(32) NOT NULL UNIQUE`, no FK, `provenance TEXT NOT NULL`, seeds `MD346675`/1.0 + `MD335287`/0.5 (Spool's signatures now final, both real P/Ns). Freeze US-370's criteria to (c) **from the start** (criterion #1 → "UNIQUE natural key, no FK" not "FK to vehicle_info"), and my re-PASS will be fast (design + code already verified this session).

## Two loose threads, both → V0.28.1 (not Sprint 43)

- **Your TEXT-vs-VARCHAR(32) seam** (`vehicle_info.ecu_signature` TEXT ↔ `speed_pid_calibration` VARCHAR): moot for Sprint 43 now (speed_pid_calibration leaves the sprint). My lean for V0.28.1 is **(b) ALTER `vehicle_info.ecu_signature` → VARCHAR(32)** for a type-clean natural-key join — but it touches a landed US-365 surface, so decide it at V0.28.1 grooming alongside the US-370 redux. Folds into the same B-076 `ecu`-identity-table watch item.
- **Ralph's `capture_method='gear_math'` judgment call** (vs CO#2's `'default'`): I concur it's the more truthful tag — re-apply it in the V0.28.1 build; no need to re-litigate.

## Root cause stands (A-11)

This all traces to freezing US-370 with an **unrendered Atlas ruling** baked into criterion #1 as a placeholder. Grooming rule for V0.28.1+ and beyond: **don't freeze a Story whose load-bearing criterion depends on an unrendered ruling** — render pre-freeze, or freeze it explicitly as "shape pending ruling, build blocked." Logged on Watch List A-11.

Net for you: land US-373 at 5 surfaces now (full PASS), pull US-370 to a V0.28.1 preservation point, ship Sprint 43's other 14 stories. Only US-364 + US-367 (IRL/CIO drill) remain between there and `/sprint-deploy-pm`.

— Atlas (CIO-ratified 2026-05-29)
