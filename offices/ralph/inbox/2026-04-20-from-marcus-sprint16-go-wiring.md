# From Marcus (PM) → Rex — Sprint 16 loaded. GO when CIO gives shell-side go.

**Date:** 2026-04-20
**Branch:** `sprint/wiring` (from main@3198d1e)
**Baseline:** fastSuite=2806, ruffErrors=0

## Theme: Wiring — make what we built actually run in production

Every story either (a) fixes a Spool Session 6 finding, (b) consolidates Sprint 15 work, or (c) wires existing pieces into a runnable whole. Zero new feature surface beyond what CIO directives explicitly require.

## 10 stories (1L + 3M + 6S = ~22 points)

**P0 — make the Pi actually run in production** (sequential via deps):
1. **US-210** Pi Collector Hotfix (S) — drop `--simulate` + `Restart=always` + journald persistent
2. **US-211** BT-Resilient Collector (M, deps US-210) — reconnect loop + error classification + event types
3. **US-212** Benchtest `data_source` hygiene (S, deps US-210)
4. **US-213** TD-029 close — deploy-time server migration gate (M)

**P1 — consolidate Sprint 15**:
5. **US-214** US-206 dual-writer reconciliation (M, deps US-213) — Ralph's Option 1
6. **US-215** TD-019/020/021/022 pygame close-audit bundle (S)

**P2 — gated + housekeeping + monthly-drain enablement**:
7. **US-216** Power-Down Orchestrator (L, **SPOOL-AUDIT-GATED**) — staged 30/25/20 SOC shutdown + battery_health_log
8. **US-217** Battery health tracking schema (S) — can land INDEPENDENTLY of US-216; gives monthly drain test a home
9. **US-218** I-017 close — specs/standards.md ↔ agent.md dedup (S)
10. **US-219** US-175 Spool data-quality review ritual (S) — wire `report.py` + prompts + checklist

## US-216 gate (read this carefully)

**Do NOT start US-216 until `offices/pm/inbox/<DATE>-from-spool-power-audit.md` exists.** Spool's next session is auditing ~1530 lines of existing power-mgmt code at `src/pi/power/` + `src/pi/hardware/ups_monitor.py`. Part of US-216 may already be implemented and just needs wiring. Running without the audit risks rewriting working code.

**Gate behavior**:
- If Spool's audit lands before you reach US-216 in the queue → pick it up normally.
- If you reach US-216 position and audit isn't there → file `offices/ralph/progress.txt` entry "US-216 gate not met; waiting on Spool audit; picking up next story" → skip to whatever's next available. **Slip to Sprint 17 is acceptable.**

US-217 (battery_health_log schema) can land independently — grab it even if US-216 is gated.

## Spool-finding mapping (traceability)

| Spool Session 6 finding | Addressed by |
|---|---|
| Service running `--simulate` | US-210 |
| BT drop kills collector | US-211 |
| Pi hard-crashes at zero SOC | US-216 (gated) |
| Benchtest rows tagged 'real' | US-212 |
| Power-mgmt code audit needed | Spool's deliverable (not a Ralph story) |
| `eclipse-obd.service` Restart=on-failure should be always | US-210 (bundled) |
| No persistent journald | US-210 (bundled) |
| I-016 thermostat | CLOSED BENIGN (no story needed) |
| UPS drain 23:49 baseline | US-217 enables monthly cadence per CIO directive 3 |

Plus Ralph's own: TD-029 (US-213), I-017 (US-218), US-206 reconciliation (US-214), TD-019/020/021/022 (US-215).

## Sprint Contract v1.0 shape

All 10 stories have: intent + priority + deps + scope {filesToTouch, filesToRead, doNotTouch} + groundingRefs + acceptance (pre-flight audit first) + verification + invariants + stopConditions + `passes: false` + `feedback` scaffold. US-216 has `pmSignOff`. 0 lint errors (29 informational sizing warnings, acceptable per calibration feedback).

## Story counter

nextId = **US-220** (US-210 through US-219 consumed Sprint 16).

## Ralph's Session 71 drift-observation rule active

If you observe drift outside current story scope: file a TD immediately (don't fix inline). If inside current scope: fix inline, note in completionNotes.

## Sprint-close payoff

After Sprint 16 ships, CIO's next real drive produces clean end-to-end data that lands on server, runs through analytics, produces a Spool review — the full pipeline runs uncoached. US-208 validator finally has something real to validate.

## Go when CIO says go

`./offices/ralph/ralph.sh N` from CIO's shell.

— Marcus
