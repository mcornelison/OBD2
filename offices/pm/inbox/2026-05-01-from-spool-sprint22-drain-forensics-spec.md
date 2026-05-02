# Sprint 22 Spec — Drain Forensics + Best-Guess Ladder Fix
**Date**: 2026-05-01
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important

## Context

Drain Test 6 (tonight, 21:58–22:19 CDT) was the **6th consecutive hard-crash**. US-252's "decouple tick from display loop" patch did NOT fix the underlying problem.

Forensic data:
- `power_log` has exactly ONE row in the 21-min drain window: `id=106, 2026-05-02T02:58:21Z, battery_power, battery, vcell=NULL`
- Zero `STAGE_WARNING`, `STAGE_IMMINENT`, `STAGE_TRIGGER` rows
- Zero `_enterStage` log lines in journalctl
- Zero graceful-shutdown sequence (boot table shows hard crash at 22:19:03)
- `vcell` column is present in schema (US-252 migration applied) but never populated

We do NOT know yet WHY the ladder didn't fire. CIO selected Option B (logger + best-guess fix in same sprint). Sprint 22 ships both, then Drain Test 7 (CIO-driven) validates which fix(es) were needed.

## Sprint 22 Story Recommendations (raw spec — convert to US-262+ in sprint.json)

### Story 1 (M) — Drain Forensics Logger
**File:** `scripts/drain_forensics.py` + `deploy/drain-forensics.timer` (systemd) + `deploy/drain-forensics.service`

**Behavior:**
- Activates when `PowerSource == BATTERY` is detected
- Writes one CSV row every 5 seconds to `/var/log/eclipse-obd/drain-forensics.csv`
- Append-mode + `os.fsync()` after every line (no buffered data lost on hard crash)
- Stops on AC restoration, opens new file on next battery transition (rotate by timestamp suffix)

**CSV columns (14, all required):**
| Column | Source | Purpose |
|---|---|---|
| `timestamp_utc` | `utcIsoNow()` | Wall-clock anchor |
| `seconds_on_battery` | monotonic since transition | Drain curve x-axis |
| `vcell_v` | MAX17048 reg 0x02 | Primary trigger value |
| `soc_pct` | MAX17048 reg 0x04 | Trend tracking (calibration broken but useful) |
| `crate_pct_per_hr` | MAX17048 reg 0x16 (signed) | **Discharge rate — smoking gun for load spikes** |
| `cpu_temp_c` | `vcgencmd measure_temp` | Correlates with current draw |
| `core_v` | `vcgencmd measure_volts core` | Pi rail health |
| `sdram_c_v` | `vcgencmd measure_volts sdram_c` | " |
| `sdram_i_v` | `vcgencmd measure_volts sdram_i` | " |
| `sdram_p_v` | `vcgencmd measure_volts sdram_p` | " |
| `throttled_hex` | `vcgencmd get_throttled` | **Bit 0=undervoltage NOW, bit 16=undervoltage since boot** |
| `load_1min` | `/proc/loadavg` | Process load proxy for current draw |
| `pd_stage` | `PowerDownOrchestrator.currentStage` | NORMAL/WARNING/IMMINENT/TRIGGER |
| `pd_tick_count` | counter incremented in `tick()` | **PROVES whether tick() is running** |

**Why these two columns are critical:**
- `throttled_hex` — if bits 0 or 16 light up, Pi5 itself browns out before VCELL hits thresholds. CIO's hypothesis confirmed.
- `pd_tick_count` — if it stays at 0 or stops incrementing, the daemon thread never started or died.

**Acceptance:** logger CSV produced from a bench run on battery (do NOT need full drain — just confirm rows are written every 5s and all columns populated).

### Story 2 (S) — Boot-Reason Detector
**File:** `src/pi/diagnostics/boot_reason.py` + new SQLite table `startup_log`

**Behavior:**
- At every Pi startup, parse `journalctl --list-boots` for the prior boot
- Determine: clean shutdown (graceful poweroff record) vs hard crash (no shutdown record)
- Write `startup_log` row: `boot_id, prior_boot_clean (bool), prior_last_entry_ts, current_boot_first_entry_ts`

**Why:** Right now post-mortem requires manual `journalctl --list-boots` inspection every drain. This makes "did the prior shutdown crash?" queryable.

**Acceptance:** restart Pi cleanly, verify `startup_log` shows `prior_boot_clean=true`. Hard-crash sim (kill -9 systemd-journald or pull power), verify `prior_boot_clean=false` on next boot.

### Story 3 (S) — Dashboard VCELL Promotion + SOC Demotion
**File:** `src/pi/display/dashboard.py` (or wherever the power card layout lives — likely `dashboard_layout.py` from Sprint 21 US-257)

**Behavior:** in the Power card, swap the prominence of VCELL and SOC.
- VCELL: large font, primary number
- SOC: small font, secondary line, with `(uncalibrated)` annotation
- Stage label still drives NE-quadrant tinting per US-257

**Rationale:** SOC is known broken (40+ point drift). Tonight's display showed 96% while VCELL was approaching the WARNING threshold. The dashboard must not mislead.

**Acceptance:** screenshot of dashboard on bench, VCELL is the largest number in the power card.

### Stories 4, 5, 6 (M, M, S) — Three Discriminator Fix Stories
**Don't make Ralph pick one hypothesis** — implement all three. They're cheap, additive, and the forensic logger will tell us post-drain which one (or which combination) was the real bug.

**Story 4 (M) — Verify tick thread starts**
- Audit `_powerDownTickThread` instantiation in `src/pi/obdii/orchestrator/lifecycle.py` and `core.py`
- Confirm `thread.start()` is called and `daemon=True`
- Add startup log line: `"PowerDownOrchestrator tick thread started, tid=<id>"` to confirm in journalctl
- Add health-check assertion: every minute, log `pd_tick_count` value to journalctl. If it's not incrementing, RAISE alarm.
- Hypothesis discriminator: if logger's `pd_tick_count` column stays at 0 throughout drain, THIS was the bug.

**Story 5 (M) — Audit tick() gating logic**
- Read `PowerDownOrchestrator.tick()` end-to-end
- Look for early-returns: `if not on_battery`, `if vcell is None`, `if power_source != BATTERY`, etc.
- Each guard: log a DEBUG line with the value that caused the early-return
- Look specifically for: stale-cached VCELL values, `getPowerSource()` returning UNKNOWN, threshold comparison with NoneType
- Hypothesis discriminator: if `pd_tick_count` increments but `pd_stage` stays NORMAL when `vcell_v < 3.70`, THIS was the bug.

**Story 6 (S) — Add fsync to stage-row writes + audit error handling**
- In `power_db.py::logShutdownStage`: add `conn.commit()` immediately followed by `os.fsync(conn.fileno())` (if SQLite supports — else use PRAGMA synchronous=FULL for that connection)
- Wrap the INSERT in try/except that logs at ERROR level and re-raises (do NOT swallow)
- Hypothesis discriminator: if `pd_stage` advances in CSV but `power_log` has no STAGE_* rows, THIS was the bug.

### Story 7 (S) — Phantom-Path Drift Fix
**You (Marcus)** know this one — 8-session pattern of `sprint.json scope.filesToTouch` containing paths that don't exist. Template-generator audit. Fix on PM side during sprint creation.

### Story 8 (M) — TD-042
Release schema theme-field break, 24 pre-existing test failures in `tests/pi/update/*` + `tests/server/test_release_*`. Already a Sprint 22 candidate per memory.

### Story 9 (S) — TD-044
`test_migration_0005` asserts literal last version, broken by v0006. S-size hygiene per memory.

## Total Sprint Shape

9 stories: 1×M (logger) + 3×fix-discriminator (M+M+S) + 3×hygiene (S+M+S) + 2×my-recommendation (S+S) = clean overnight Ralph run.

## CIO-Action Item (NOT in sprint, separate action list)

Drain Test 7 — CIO pulls wall power after Sprint 22 is deployed. Forensic logger captures the data. Spool reads CSV + `power_log` post-test, calls verdict on which hypothesis was correct.

## Discriminator Truth Table (for post-drain analysis)

| pd_tick_count | pd_stage advances? | power_log STAGE_* rows? | Verdict |
|---|---|---|---|
| Stays 0 | No | No | Story 4 was the fix (thread never started) |
| Increments | No | No | Story 5 was the fix (gating logic) |
| Increments | Yes | No | Story 6 was the fix (write path) |
| Increments | Yes | Yes | All three needed; ladder works |

## Sources / Rationale

- 6 consecutive drain test hard-crashes (Drains 1-5 documented, Drain 6 tonight)
- US-252 patch shipped Sprint 21 — did not fix the bug per tonight's data
- LiPo voltage sag under load + Pi 5 buck converter dropout (~3.0-3.2V) is a known failure mode that CIO flagged tonight; the `throttled_hex` column will confirm whether this is a contributor
- `power_log` schema verified post-test: `vcell` column present, US-252 migration applied — the column exists but isn't being written

---

I'm available for follow-up questions on the spec or for post-drain CSV analysis. Ladder behavior is engine-safety-adjacent (Pi must shut down cleanly to preserve sync of analytics + drive_summary rows that downstream tuning recommendations depend on) — this is in my lane to advocate for.
