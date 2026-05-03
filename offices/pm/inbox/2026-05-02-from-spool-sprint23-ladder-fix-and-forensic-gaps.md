# Sprint 23 Spec — Ladder Fix Discriminator + Forensic Logger Gap Closure
**Date**: 2026-05-02
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important

## Context — Drain Test 7 Verdict

Drain Test 7 (2026-05-02 18:56 → 19:15 CDT, ~16 min on battery) ran with full Sprint 22 deployed (forensic logger US-262 + tick-thread health-check US-263 + dashboard stage label US-264). **The ladder STILL did not fire** — `power_log` has zero STAGE_* rows for the 7th consecutive drain. But this time we have data, and the data is decisive.

### What Drain 7 PROVED

| Question | Answer | Evidence |
|---|---|---|
| Did the tick thread start? | **YES** | `_checkTickThreadHealth` log: `tickCount=181 → 337 across drain, delta=12/60s, on BATTERY` |
| Did the tick run continuously? | **YES** | tickCount monotonically increased every 60-sec health check |
| Did VCELL cross all stage thresholds? | **YES** | T+0=3.57V, declined to 3.27V at last sample (crossed 3.70/3.55/3.45 cleanly) |
| Did Pi5 brown out under load? (CIO hypothesis) | **NO** | `throttled_hex` stayed `0x0` for entire 16-min drain — bit 0 (NOW) and bit 16 (since boot) never tripped. CPU 38-40°C, load 0.06-0.42 |
| Did `_enterStage` ever execute? | **NO** | Zero stage-transition log lines in journalctl, zero STAGE_* rows in `power_log` |

### What killed the Pi
Buck converter on UPS HAT lost 5V regulation around VCELL ~3.30V (the LiPo dropout knee). Expected, normal hardware behavior. Not a Pi5 issue. **The Pi died because the ladder didn't gracefully shut down before VCELL hit the buck-converter dropout floor.**

### Hypothesis status post-Drain-7

- **H1 (tick thread never started): ELIMINATED** — Story 4/US-263 proved the thread runs
- **H2 (tick runs but gating logic bails): MOST LIKELY** — `_enterStage` was never called despite all thresholds crossed
- **H3 (tick runs, stages advance, write path drops rows): UNLIKELY** — if H3 were true, we'd see `_enterStage` log lines (those go through `logger.info()`, not the DB). Absence of any stage-related log line says the code path is unreachable, not that writes are failing.

## Sprint 22 Retro

| Story | Status | Notes |
|---|---|---|
| US-262 Forensic logger | ✓ shipped, ⚠ deploy gap | Files deployed, systemd install steps require manual operator sudo. Spool ran them mid-drain. Sprint 23 should auto-wire this. |
| US-263 Tick thread health-check | ✓ shipped, working perfectly | Gave us the smoking-gun heartbeat log. Story DELIVERED VALUE. |
| US-264 Dashboard VCELL/SOC + stage label | ✓ shipped | Stage label "NORMAL" visible in tonight's screenshot. SOC still shows the lying calibration value — minor follow-up. |
| US-265 Boot-reason detector | ✓ shipped | `startup_log` table exists in SQLite. Not yet exercised post-drain — verify on next session. |
| US-266 Tick gating logic audit | **DID NOT FIX** | Either the audit missed a case or the wrong code path was changed. Sprint 23 needs deeper instrumentation to find what's wrong. |
| US-267 fsync stage-row writes | Untested | Write path was never reached. Defer-validation until tick reaches `_enterStage`. |
| Other hygiene (TD-042, TD-044, phantom-path) | Confirm shipped status | Marcus to audit |

## Sprint 23 Recommended Stories

### Story 1 (S, P0) — Tick-Internal Instrumentation (THE DISCRIMINATOR)
**File:** `src/pi/power/orchestrator.py::PowerDownOrchestrator.tick()`

**Behavior:** every call to `tick()` while on battery, emit ONE log line at INFO level with the full decision-relevant state:
```
PowerDownOrchestrator.tick: vcell=3.276 currentStage=NORMAL
  thresholds={WARNING:3.70, IMMINENT:3.55, TRIGGER:3.45}
  willTransition=False reason=<one of: power_source!=BATTERY | vcell_none | already_at_stage | threshold_not_crossed | OK>
```

**Why this is the discriminator we need:**
- If we see `willTransition=False reason=threshold_not_crossed` while VCELL is clearly below threshold → comparison logic bug (sign error, units mismatch, etc.)
- If we see `vcell_none` or `power_source!=BATTERY` while we KNOW we're on battery → state caching bug
- If we see `willTransition=True` repeatedly but no `_enterStage` log line → state machine bug (transition decision made but action not taken)
- If we see `OK` and stage advances → ladder works, the bug is downstream in `_enterStage` (actual H3)

**Acceptance:** drain test (or simulate-mode test) shows one such log line per tick. Ralph can write a unit test that asserts the log message format.

### Story 2 (S, P0) — Wire Orchestrator State File for Forensic Logger
**File:** `src/pi/power/orchestrator.py` + `src/pi/obdii/orchestrator/lifecycle.py`

**Behavior:** PowerDownOrchestrator writes `/var/run/eclipse-obd/orchestrator-state.json` on every tick, atomic-rename, with at minimum:
```json
{
  "tickCount": 337,
  "currentStage": "NORMAL",
  "lastTickTimestamp": "2026-05-03T00:15:08Z",
  "lastVcellRead": 3.305,
  "powerSource": "BATTERY"
}
```

**Why:** the forensic logger (US-262) already reads this file. The reading-side is built. The writing-side is the documented gap. Without it, the logger's `pd_stage` and `pd_tick_count` columns are `-1`/`unknown` and we lose half the diagnostic value of the logger.

**Acceptance:** drain-forensics CSV from a battery test shows real values in pd_stage/pd_tick_count columns. /var/run/eclipse-obd/orchestrator-state.json exists and is readable, mtime within 10s of last tick.

### Story 3 (M, P0) — The Actual Ladder Fix (DEPENDS ON STORY 1)
**Sequencing:** Story 1 ships first (or same time), then Drain Test 8 runs, then Spool reads the new `tick:` log lines and identifies the exact failure mode. Ralph implements the fix BASED ON THE EVIDENCE, not a guess.

This story may end up being trivial (one-line bug) or may decompose into multiple sub-stories depending on what Story 1's instrumentation reveals. Marcus may want to defer this story's full spec until post-Drain-8.

### Story 4 (S) — Auto-Wire Forensic Logger systemd Install in deploy-pi.sh
**File:** `deploy-pi.sh` (or wherever `deploy_pi` orchestration lives)

**Behavior:** after `sync_tree`, if `/etc/systemd/system/drain-forensics.service` is older than `deploy/drain-forensics.service` (or absent), re-install:
```bash
sudo cp deploy/drain-forensics.service /etc/systemd/system/
sudo cp deploy/drain-forensics.timer /etc/systemd/system/
sudo install -d -o mcornelison -g mcornelison /var/log/eclipse-obd
sudo install -d -o root -g root /var/run/eclipse-obd
sudo systemctl daemon-reload
sudo systemctl enable --now drain-forensics.timer
```

**Why:** Spool had to manually run these mid-drain because Sprint 22 left it as an "operator post-deploy hook." Should be idempotent and auto-wired. Should ALSO include the PYTHONPATH env that Spool patched live (current unit file ships without it; without PYTHONPATH the script no-ops because UpsMonitor import fails).

**Bonus fix to include:** add `Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01` to `deploy/drain-forensics.service`. (Spool already patched the live `/etc/systemd/system/` copy but the repo file is unchanged.)

**Acceptance:** fresh `deploy-pi.sh` run on a Pi without the systemd unit installed → next AC→BATTERY transition writes a CSV row with valid VCELL/SOC. No manual sudo needed.

### Story 5 (S) — Hardware Limit Documentation
**File:** new `offices/tuner/knowledge/ups_hat_dropout_characteristics.md`

**Behavior:** document the empirically-confirmed UPS HAT dropout knee (~3.30V VCELL) and the 16-min runtime under typical load (Pi5 idle, BT scan, HDMI display, ~0.06-0.42 load avg, 38-40°C ambient). Reference Drain Test 7 CSV. Useful for future tuning decisions and for car-wiring scope (US-169 / US-189 / US-190 will reference this).

**Acceptance:** Spool's knowledge folder has the document. Cross-link from MEMORY.md power-mgmt section.

### Story 6+ (Carryforward Audit)
Marcus to verify Sprint 22 actually shipped:
- TD-042 (release schema theme-field break, 24 test failures) — if not, carry to Sprint 23
- TD-044 (test_migration_0005 v0006 break) — if not, carry to Sprint 23
- Phantom-path drift fix in sprint.json template-generator — if not, carry

## Sources / Rationale Recap

- Drain 7 CSV: `/var/log/eclipse-obd/drain-forensics-20260502T235909Z.csv` on Pi (CIO has copy on Windows box at `drain7-forensics.csv`)
- Drain 7 journalctl: `journalctl -b -1 -u eclipse-obd` on Pi (boot -1 from current boot, after the test ended)
- 7 consecutive drain hard-crashes (1-5 pre-instrumentation, 6 post-US-252 patch, 7 post-Sprint-22)
- Pi5 brownout hypothesis (CIO's, 2026-05-01) DISPROVEN by Drain 7 throttled_hex column
- Tick-thread-not-running hypothesis (Spool's, 2026-05-01) DISPROVEN by Drain 7 health-check logs

---

I need Story 1 + Story 2 minimum for Drain Test 8 to be diagnostically useful. Story 4 makes the deploy story not-painful. Story 3 IS the fix but should not be specced concretely until Drain 8 reveals which gating-logic mode is failing. Story 5 is housekeeping but valuable.

Let me know if you want me to elaborate on any of the spec items or if you have questions on the discriminator design for Story 1.
