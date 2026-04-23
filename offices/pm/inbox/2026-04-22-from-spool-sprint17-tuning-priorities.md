# Sprint 17 — Tuning-Domain Priorities

**Date:** 2026-04-22
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Routine — for Sprint 17 grooming

## Context

CIO asked for my Spool-perspective on what Sprint 17 should carry. This note is input to your sprint planning, not a scope directive. You own the sprint contract; I own the tuning-domain rationale behind each item. Final scope is your call against capacity.

Ties together with my two earlier notes today:
- `2026-04-21-from-spool-power-audit.md` — 5 TDs (A–E) filed from the power audit
- `2026-04-22-from-spool-sprint16-release-readiness.md` — 3 Sprint 17 candidates filed from the Sprint 16 grade

Below is a ranked consolidation + the standing Session 3 carryforwards.

## MUST-SHIP (can't keep slipping)

### 1. US-140 through US-144 — Legacy threshold hotfix bundle ⚠️ AGED

**Session 3 (2026-04-12) carryforward, ten days overdue.** Five hotfixes I recommended after auditing sprint-1/2 code against corrected specs. None are loaded into a sprint yet. All are dormant-but-dangerous — no runtime impact today because the legacy profile threshold system isn't consulted, but any future use would trigger unsafe behavior:

| ID | Fix | Safety weight |
|----|-----|---------------|
| **US-140** | `coolantTempCritical: 110` nonsense value in 6 files → 220F with explicit unit | HIGH — value is physically impossible regardless of unit |
| **US-141** | Legacy profile `rpmRedline: 7200` → 7000 (completes US-139 which only fixed tiered system) | HIGH — factory redline for 97-99 2G is 7000 |
| **US-142** | Legacy profile `boostPressureMax: 18` psi → 15 psi | HIGH — unsafe for stock TD04-13G |
| **US-143** | Display boost stubs `BOOST_CAUTION=18.0` + `BOOST_DANGER=22.0` psi → 14/15 | HIGH — dangerously wrong for stock turbo |
| **US-144** | Display fuel stub `INJECTOR_CAUTION=80.0%` → 75% (danger 85% already correct) | MEDIUM |

Full variance report: `offices/pm/inbox/2026-04-12-from-spool-code-audit-variances.md`. Recommend bundling as a single Sprint 17 cleanup story.

### 2. US-216 Power-Down Orchestrator

If Ralph doesn't pick it up before Sprint 16 closes, it anchors Sprint 17. L-sized per my audit. Sprint 15+16 fielded the battery infrastructure (battery_health_log, drain metrics, UPS baseline) — not wiring the orchestrator leaves all of that stranded. Details in the power audit note.

### 3. US-211 BT-resilience integration wiring

S, high. The Sprint 16 US-211 shipped the classifier + reconnect loop + new `handleCaptureError()` entry point, but **did not wire it into `data_logger.py`'s capture loop** (Ralph flagged this in his completion note §"What I did NOT do"). Until the wiring lands, there's no real-drive BT-flap resilience; every live drill still runs on US-210's `Restart=always` systemd-level bounce. Should ship before the next live drive beyond tomorrow's paper tests.

## HIGH VALUE

### 4. First real-drive review ritual execution

Post-tomorrow's drill, **IF** it produces captured data, I run the US-219 ritual against a real `drive_id`, grade Ollama output against the 6 quality gates in `src/server/services/prompts/DESIGN_NOTE.md`, and deliver findings. Likely drives prompt iteration (`system_message.txt` / `user_message.jinja`). Track as a Spool deliverable in the sprint so it doesn't fall through the cracks — not a code story, but real sprint work.

### 5. Delete dead BatteryMonitor + battery.py + battery_log table

TD-B from the power audit. ~700 lines with thresholds (11.0V/11.5V) designed for 12V automotive / 3S Li batteries, but the actual hardware is a 1S LiPo (3.0-4.3V via MAX17048). False-confidence risk: if anyone flips `pi.batteryMonitoring.enabled=true` expecting protection, they get zero. Removing dead code reduces audit surface + closes an obvious hazard. S.

### 6. `pi.hardware.enabled` key path fix

TD-A from the power audit. MEDIUM. `lifecycle.py:450` reads `self._config.get('hardware', {}).get('enabled', True)` — top-level `hardware`, but config.json puts it under `pi.hardware`. Silent misread. Currently harmless (default `True` so missing key = enabled) but any future attempt to disable hardware via config fails quietly. One-line fix. Could ride with any sprint that has spare capacity.

## MEDIUM / OPPORTUNISTIC

### 7. `record_drain_test.py` CLI default flip

`--load-class` defaults to `production`; flip to `test`. Manual CLI invocation is almost always a CIO-driven drill, not a real power-loss event; production rows should come from US-216's orchestrator auto-writing them. One-line change, prevents baseline pollution. S.

### 8. Telemetry logger → UpsMonitor audit follow-up

TD-E from the power audit. 20-min audit I owe. Checks whether `telemetry_logger.py` (which is wired to UpsMonitor at `hardware_manager.py:339`) was actually logging during the 2026-04-20 drain. Findings shape US-216 testing strategy. My deliverable, not Ralph's.

### 9. DSM DTC interpretation cheat sheet

My Session 3/5 carryforward, unblocked now that US-204 shipped in Sprint 15. Documentation work, not code. Post-drill priority (once tomorrow produces real data to anchor the cheat sheet examples). S.

## DEFER — not Sprint 17

| Item | Reason |
|------|--------|
| connection_log DEFAULT hardening | Low risk after US-210 took simulate out of production (noted in US-212 completion) |
| `tiered_battery.py` wire-or-delete (TD-C) | Second-gen cleanup, doesn't block anything |
| Gate 2/3 display reviews | Blocked on Ralph building those display tiers |
| Always-on HDMI dashboard | Needs PRD grooming first — Spool happy to contribute when you write it |
| B-043 PowerLossOrchestrator full lifecycle | Blocked on CIO car-accessory wiring (hardware task) |
| B-041 Excel export CLI | Needs PRD grooming |
| Parts-ordering / ECMLink install | CIO hardware lane, Summer 2026 timeline |

## Three non-negotiables

If capacity forces trimming, the three items I'd fight hardest to keep:

1. **US-140–144** — safety debt aged too long
2. **US-216 OR US-211-integration** — whichever didn't land in Sprint 16
3. **First real-drive review** — the whole point of last sprint's data-collection work

Everything else can slide.

## What I need from you

- Sprint 17 scope decision when you're ready — I'll run `/review-stories-tuner` on any tuning-domain stories before Ralph picks them up
- Confirmation on US-140–144 bundle shape (one L story? five S stories?) — your call on packaging
- If US-216 slipped from Sprint 16, let me know whether my audit note's scope recommendation still holds or you'd like me to refine

— Spool
