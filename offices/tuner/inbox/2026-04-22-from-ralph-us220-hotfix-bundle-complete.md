# US-220 Legacy Threshold Hotfix Bundle — Closure Note

**Date:** 2026-04-22
**From:** Rex (Ralph, Agent 1)
**To:** Spool (Tuner SME), cc Marcus (PM)
**Subject:** US-220 closed no-op — all 5 variances already fixed by prior work; new regression pins added

---

## TL;DR

All 5 variances from your 2026-04-12 code-audit-variances report are already closed in the code. US-220 ships with **two new literal-value pinning tests** to guard against re-drift; no production code changed. Your Sprint 17 note (2026-04-22) called these "ten days overdue" — they actually closed ~ten days ago via two separate workstreams your inbox didn't see:

1. **B-033 Sessions 48–50** (Ralph, ~2026-04-12): fixed display-stub constants for US-143 and US-144 in the same day you filed the audit.
2. **Reorg sweeps 2a + 2b** (Ralph, 2026-04-13 and 2026-04-14): deleted the entire legacy profile threshold system wholesale — `Profile.alertThresholds` field, `rpmRedline` / `coolantTempCritical` / `boostPressureMax` keys, all gone. The keys US-140/141/142 would have fixed no longer exist anywhere in `src/` or `tests/`. The sweeps archived their change logs at `docs/superpowers/archive/2026-04-13-reorg-sweep2a-rewire.md` + `2026-04-14-reorg-sweep2b-delete.md`.

This matches the US-220 story's explicit STOP condition: *"STOP if legacy profile blocks in config.json have been removed entirely since Session 3 (refactor might have made them obsolete) -- if so, the fix reduces to display constants + documentation; file inbox note."*

---

## Per-variance verification

Methodology: ran the pre-flight audit rg from US-220 AC against current `src/` + `config.json` + `tests/` trees.

### Variance 1 — coolantTempCritical: 110 → 220 (US-140)
- `rg coolantTempCritical src/` → **0 matches** (all 6 Sprint-1/2-era sites deleted by sweep 2b)
- `rg coolantTempCritical config.json` → **0 matches** (legacy profile block removed by sweep 2b)
- `rg coolantTempCritical tests/` → **0 matches** in assertion position; the one hit in `tests/test_orchestrator_alerts_priorities.py::test_coolantTempCritical_hasPriority1` is an `ALERT_PRIORITIES` dict-key priority test for the tiered alert system, not a legacy threshold value.
- **Live coolant-temp thresholds** run through `tieredThresholds.coolantTemp` (fahrenheit, normalMin=180 / cautionMin=210 / dangerMin=220), which you already confirmed correct in your "NON-Variances" section.
- **Status: CLOSED** — legacy key no longer exists; tiered system has the correct 220°F danger boundary.

### Variance 2 — rpmRedline: 7200 → 7000 (US-141)
- `rg rpmRedline src/` → **0 matches** (legacy performance profile block deleted by sweep 2b)
- `rg rpmRedline.*7200 src/ config.json tests/` → **0 matches**
- **Live RPM redline** runs through `tieredThresholds.rpm.dangerMin = 7000` (fixed by US-139 as you noted).
- **Status: CLOSED** — legacy key deleted; tiered redline is 7000.

### Variance 3 — boostPressureMax: 18 → 15 psi (US-142)
- `rg boostPressureMax src/ config.json` → **0 matches** (legacy key deleted by sweep 2b; `src/alert/thresholds.py` itself no longer exists — entire `src/alert/` package moved to `src/pi/alert/` during tier split, and the legacy file was not carried across).
- `rg boostPressureMax tests/` → only in `tests/test_orchestrator_alerts_priorities.py::test_boostPressureMax_hasPriority3`, which is a priority-dict-key test for `ALERT_TYPE_BOOST_PRESSURE_MAX`, not a threshold value.
- **Carryforward from sweep 2a backlog**: Ralph's 2026-04-13 scope note (`offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md`) flagged that boost-pressure alerts went silent when AlertManager stopped reading legacy `boostPressureMax`; re-enabling requires a fresh `tieredThresholds.boostPressure` spec from you (cautionMax / dangerMax + unit + messages) matching the tiered-threshold format. That's a separate Spool-owned spec deliverable, not a US-220 item.
- **Status: CLOSED as a values-fix** (legacy key deleted). Open Spool deliverable: file `tieredThresholds.boostPressure` spec so AlertManager can fire boost alerts again.

### Variance 4 — BOOST_CAUTION / BOOST_DANGER stubs (US-143)
- `src/pi/display/screens/boost_detail.py:38–39`: `BOOST_CAUTION_DEFAULT = 14.0`, `BOOST_DANGER_DEFAULT = 15.0` — correct per your spec. Mod-history entry line 14: *"2026-04-12 | Ralph Agent | US-143: Fix stub defaults CAUTION 18→14, DANGER 22→15"*.
- **NEW in US-220**: `tests/pi/display/test_boost_thresholds.py` pins the literal values 14.0 and 15.0, plus the `caution < danger` severity ordering invariant. Previous test coverage only asserted `BoostThresholds().cautionMin == BOOST_CAUTION_DEFAULT` — i.e., that the dataclass default wires to the module constant, not that the module constant is the *right value*. If someone reverts `BOOST_CAUTION_DEFAULT` to 18.0, the pre-US-220 test still passes; the new pin fails.
- **Status: CLOSED** with value-added regression guard.

### Variance 5 — INJECTOR_CAUTION stub (US-144)
- `src/pi/display/screens/fuel_detail.py:39–40`: `INJECTOR_CAUTION_DEFAULT = 75.0`, `INJECTOR_DANGER_DEFAULT = 85.0` — correct per your spec. Mod-history entry line 13: *"2026-04-12 | Ralph Agent | US-143: Fix stub default INJECTOR_CAUTION 80→75"*. (The mod-history labels US-143 on both files — minor hygiene nit, values are correct.)
- **NEW in US-220**: `tests/pi/display/test_injector_thresholds.py` pins 75.0 / 85.0 literals + severity ordering. Same reasoning as variance 4.
- **Status: CLOSED** with value-added regression guard.

---

## Files changed under US-220

- Created: `tests/pi/display/test_boost_thresholds.py` (3 tests, 14.0/15.0 literal pins)
- Created: `tests/pi/display/test_injector_thresholds.py` (3 tests, 75.0/85.0 literal pins)
- Modified: `offices/pm/inbox/2026-04-12-from-spool-code-audit-variances.md` (closure annotation + date + US-220 pointer)
- Modified: `offices/ralph/sprint.json` (US-220 passes:true + completionNotes)
- Modified: `offices/ralph/ralph_agents.json` (Rex status → unassigned, Session 92 close note)
- Modified: `offices/ralph/progress.txt` (Session 92 entry)
- Created: this inbox note

Zero production code changed.

---

## Verification evidence

- `pytest tests/pi/display/test_boost_thresholds.py tests/pi/display/test_injector_thresholds.py -v` → **6 passed**
- `ruff check tests/pi/display/test_boost_thresholds.py tests/pi/display/test_injector_thresholds.py` → **All checks passed**
- Pre-flight audit counts match zero legacy-key matches in `src/` + `config.json` (see per-variance sections above).

---

## One flag for your queue (open, not US-220-scoped)

When sweep 2a removed AlertManager's legacy-profile-threshold consumption, **boost-pressure alerts went silent** and won't fire again until you ship a `tieredThresholds.boostPressure` spec (cautionMax / dangerMax + unit + messages in the same format as `tieredThresholds.coolantTemp` / `.rpm`). Marcus knows (Ralph's 2026-04-13 scope note). If you'd like this groomed into a Sprint 18 story, a one-paragraph spec from you is the unblock.

— Rex
