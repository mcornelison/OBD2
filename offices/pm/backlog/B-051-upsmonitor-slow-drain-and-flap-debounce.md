# B-051: UpsMonitor slow-drain detection + flap-debounce (Sprint 19 US-235 RESCOPE)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P0 for Sprint 20) — supersedes Sprint 19 US-235 |
| Status       | Pending grooming       |
| Category     | code / pi-power-mgmt   |
| Size         | S                      |
| Related PRD  | None (Sprint 20 candidate; couples with B-049, B-050) |
| Dependencies | None                   |
| Filed By     | Marcus from Spool inverted-power drill 2026-04-29 |
| Created      | 2026-04-29             |

## Description

**Spool's prior US-235 diagnosis was wrong.** On 2026-04-29 in `from-spool-sprint19-consolidated.md`, Spool recommended dropping the CRATE rule and replacing with VCELL slope. That recommendation was based on 4 drain tests where UpsMonitor never fired BATTERY transitions.

The 2026-04-29 inverted-power drill **overturns that diagnosis**: UpsMonitor logged 8 transitions in 9 minutes during dynamic events (engine cranking, alternator on/off, physical movement). The CRATE rule **does fire correctly** in the dynamic case. **Dropping it would regress the working detection.**

The actual failure mode is **slow gradual drain** (idle Pi sitting on a desk, drawing constant ~500mA, VCELL declining at <0.001V/min). In that regime, CRATE may stay near zero or below the heuristic's noise floor — and the heuristic never crosses the threshold to fire BATTERY.

**Corrected scope**: keep CRATE, add a slow-drain rule, add flap suppression.

This story **supersedes US-235 in Sprint 19 sprint.json** if US-235 is deferred (Spool's recommendation; PM decision pending). If US-235 ships in Sprint 19 with corrected scope inline, B-051 closes as duplicate.

## Acceptance Criteria

- [ ] CRATE rule preserved (works in dynamic case — validated by 2026-04-29 inverted drill)
- [ ] **NEW slow-drain rule**: if `VCELL declining > 0.005V over 5 minutes AND not-currently-flagged-BATTERY` → flag BATTERY. Threshold tuning via config.
- [ ] **NEW flap suppression / debounce**: ignore transitions that flip back within 30 seconds (config-tunable). Tonight's data: 4 transitions in 45 seconds during physical movement = heuristic noise.
- [ ] Synthetic test: mock VCELL stair-stepping slow decline (4.05V → 4.04V → 4.03V over 5 min mocked time); assert BATTERY flag fires (per `feedback_runtime_validation_required.md` — mocks at MAX17048.readVCell level)
- [ ] Synthetic test: mock 4 rapid power_source flips within 45 seconds; assert only 1 transition emitted post-debounce
- [ ] Synthetic test: mock alternator-on transition after slow-drain BATTERY flag; assert state returns to EXTERNAL correctly (no flap-debounce stuck-state)

## Slow-drain telemetry reference (from drain tests 1-4)

| Drain | Pi runtime | VCELL start | VCELL crash | Decline rate |
|---|---|---|---|---|
| Drain 1 (Session 6 sim) | 23:49 | unknown | unknown | unknown |
| Drain 2 (Sprint 17 deploy) | 14:26 | unknown | 3.364V | unknown |
| Drain 3 (Sprint 18 deploy) | 10:14 | unknown | 3.446V | unknown |
| Drain 4 (Sprint 18 deploy) | 10:02 | 3.720V | 3.376V | ~0.034V/min ≈ 0.0006V/sec |

A `>0.005V over 5 min` threshold (= 0.001V/min sustained) is well above sensor noise floor and fires within the first ~2 minutes of any real drain. Tuning may shift this to 0.01V over 5 min if false positives appear.

## Flap-debounce reference (from 2026-04-29 inverted drill)

```
20:47:13  external -> battery       <-- flap
20:47:18  battery -> external       <-- flap back (5s)
20:47:53  external -> battery       <-- flap
20:47:58  battery -> external       <-- flap back (5s)
```

4 transitions in 45 seconds, all back-and-forth. Real power-state changes don't flap. 30s debounce window suppresses these without missing any real transition (real transitions in the drill were spaced ≥2 minutes apart).

## Validation Script Requirements

- **Input**: Pi running, simulated slow-drain VCELL trace mocked into MAX17048.readVCell()
- **Expected Output**: BATTERY flag fires within 5-7 minutes of trace start; flap suppression visible in journal as "transition suppressed by debounce"
- **Database State**: `power_log` (post-B-050) shows transition rows matching real changes only, no flap rows
- **Test Program**: pytest mocking MAX17048 register reads; assert UpsMonitor state transitions match expected timeline

## Related

- **Sprint 19 US-235** — original mis-scoped story; this backlog item is the corrected scope. PM decides: rescope inline, defer to Sprint 20, or both
- **B-049** (drive_detect idle-poll gap) — sister Sprint 20 candidate; possibly bundle
- **B-050** (PowerMonitor DB-write activation) — sister Sprint 20 candidate; B-051 is upstream of B-050's writes
- **US-234** (SOC→VCELL trigger source) — orthogonal; both needed for US-216 to actually fire
- **TD-016** (UPS-monitor MAX17048 register map) — historical reference for MAX17048 specifics
- **Source note**: `offices/pm/inbox/2026-04-29-from-spool-inverted-power-drill-findings-and-us235-correction.md` Section 4

## Notes

- **Sprint 19 contract change required if Spool's defer-to-Sprint-20 recommendation is accepted**: edit US-235 in sprint.json to either `status: deferred` with link to this B-051, or rewrite intent/scope/acceptance to corrected scope. PM decision.
- **Bundle decision** for Sprint 20: Spool suggests B-049/B-050/B-051 may go as a single "power-mgmt revision bundle"
- **Don't drop CRATE** — that was the wrong call from the original US-235 diagnosis. CRATE is doing useful work.
