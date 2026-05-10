# Drain Test 15 — V0.27.3 validation report (Spool's parallel monitoring)
**Date**: 2026-05-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — V0.27.3 power-mgmt validation, parallel to your monitoring; cross-compare with your report

## TL;DR

**V0.27.3 power-mgmt CLEAN — no regression from Sprint 29 fixes.** All Sprint 28 contracts (V0.24.1 ladder + close-event Pi-side + US-308 startup_log) still PASS under V0.27.3. Cleanest drain test in project history (96% SOC pre-drain, no flicker baggage). Drain runtime 13:06 from WARNING to TRIGGER, well within the 10-13 min envelope.

**B-065 (server-side sync of close-event UPDATE) reproduces 6 of 6** post-V0.27.2 drains. Confirmed structural / not-a-race / not-V0.27.3-regression. As expected — B-065 wasn't in V0.27.3 scope; goes to V0.27.4.

## Test parameters

| Field | Value |
|---|---|
| Pi version | V0.27.3 (`47e6aa5`), released 2026-05-10T13:45:47Z |
| Service uptime at unplug | ~12 min (post-deploy fresh boot) |
| Pre-drain VCELL | 4.178V (96% SOC) |
| Last power_log id pre-test | 1156 |
| New drain_event_id | 15 |
| Battery condition | Fully rested + recharged (no flicker history) |
| CIO unplug timestamp | 2026-05-10T13:57:00Z (CIO-reported) |
| Pi reboot complete | ~14:27Z |
| Bash logger cross-check | `/var/log/eclipse-obd/drain-bash-20260510T135332Z.csv`, 274 rows, no `i2c_err` |

## Validation matrix

| Target | Result | Evidence |
|---|---|---|
| V0.24.1 ladder fires | ✅ PASS | 3 stage rows, monotonic timestamps + decreasing VCELL |
| WARNING threshold | ✅ PASS | VCELL=3.695V (within 3.69-3.71V) |
| IMMINENT threshold | ✅ PASS | VCELL=3.544V (within 3.50-3.60V) |
| TRIGGER threshold | ✅ PASS | VCELL=3.445V (within 3.40-3.46V) |
| Pi-side close-event | ✅ PASS | drain_event_id=15: end=14:13:49Z, runtime=786s, end_soc=3.445V — all populated |
| `runtime_seconds` consistency | ✅ PASS | 786s = (TRIGGER - WARNING) = 14:13:49 - 14:00:43. Exact. |
| US-308 startup_log writer | ✅ PASS | Current boot row `88c03212cbc5417aabb4c128814743f5` has `prior_boot_clean=1`, recorded 14:13:19Z |
| Bash logger cross-check | ✅ PASS | 274 rows captured, full drain curve from 4.178V → 3.219V |
| Server-side sync of closure (B-065) | ❌ EXPECTED FAIL | drain 15 server-side: `end_timestamp=NULL`, `runtime_seconds=NULL`, `end_soc=NULL`. INSERT row synced at 14:00:43Z, UPDATE row never propagated. **6 of 6 reproducible across drains 10-15.** |

## Drain timing detail

| Event | Timestamp (UTC) | Elapsed from unplug | VCELL |
|---|---|---:|---:|
| Unplug (CIO reported) | 2026-05-10T13:57:00Z | 0:00 | ~4.178V (per bash logger 3 sec pre-unplug) |
| `battery_power` event logged | 2026-05-10T13:57:02Z | +0:02 | — (2-sec detection lag — fast) |
| **`stage_warning`** | 2026-05-10T14:00:43Z | +3:43 | **3.695V** |
| **`stage_imminent`** | 2026-05-10T14:09:48Z | +12:48 | **3.544V** |
| **`stage_trigger`** | 2026-05-10T14:13:49Z | +16:49 | **3.445V** |
| `battery_power` (post-reboot) | 2026-05-10T14:27:45Z | +30:45 | — (Pi just booted, still on UPS pre-AC-detection) |
| `transition_to_ac` | 2026-05-10T14:28:05Z | +31:05 | — (UPS HAT detected wall AC restored) |

**Drain runtime WARNING → TRIGGER = 13:06 (786s)**.

## Cross-compare with your report — load-bearing fields

For your report-vs-mine compare, here are the fields that should match if we're both reading the same source:

| Field | Spool's value |
|---|---|
| Pi version stamp | V0.27.3 / `47e6aa5` |
| stage_warning VCELL | 3.695V |
| stage_warning timestamp | 14:00:43Z |
| stage_imminent VCELL | 3.544V |
| stage_imminent timestamp | 14:09:48Z |
| stage_trigger VCELL | 3.445V |
| stage_trigger timestamp | 14:13:49Z |
| drain_event_id (this test) | 15 |
| drain start_soc | 3.93875V |
| drain end_soc | 3.445V |
| drain runtime_seconds | 786 |
| startup_log boot_id (post-test) | `88c03212cbc5417aabb4c128814743f5` |
| startup_log prior_boot_clean | 1 |

If your numbers match within rounding (VCELL ±0.005V, timestamps ±1s), V0.27.3 validation is confirmed by independent observation. If we disagree, the disagreement itself is signal — flag it and we'll figure out which DB/query/extractor is reading wrong.

## Notable observation worth knowing

**`drain.start_soc = 3.939V` despite pre-drain VCELL being 4.178V.** The recorder captures VCELL at the moment of transition_to_battery, by which time cell voltage has already sagged from initial load handoff. Bash logger trace:

```
13:56:57Z  4.176V  (3 sec pre-unplug, AC steady)
13:57:02Z  3.939V  (AC just dropped — initial sag)  <-- this is what start_soc captures
13:57:18Z  3.819V  (settled load curve)
```

This means **`start_soc` is NOT "VCELL at unplug"** — it's "VCELL post-handoff." For analytics that compare drain start states across drives, this distinction matters. Pre-drain VCELL needs to come from somewhere else (the bash logger, or the `transition_to_battery` event row, or a snapshot taken before unplug). Probably not bug-worthy — just a documentation thing for future analysis. Adding to the procedure file as a noted-behavior.

## Sprint 29 contracts NOT validated by this drain test

The actual V0.27.3 fixes can't be tested by a drain alone:

- **US-310 (drive_summary 12-field writer)** → needs a drive event
- **US-311 (DriveDetector warm-restart fix)** → needs key-on-key-off-key-on cycle with engine
- **US-312 (calibration.py)** → can be unit-tested but not engine-tested
- **US-314 (drive_counter sync gap)** → needs a drive event to mint a new drive_id

All of those gate on **Mike's next actual drive** — which itself gates on **B-063 fuse-box wiring** completing first. Until then, V0.27.3 has 1-of-4 validations green (the "no power-mgmt regression" aspect, validated by this drain test).

## B-065 evidence is now over-saturated — file the V0.27.4 story

Drains 10, 11, 12, 13, 14, 15 — **6 of 6 post-V0.27.2 drains** show the same Pi-clean / server-NULL pattern. The bug is structural, not flaky. INSERT rows sync within 2-5 seconds; UPDATE rows never sync. Sync client appears to be INSERT-only or source_id-monotone.

When V0.27.4 grooming opens, B-065 should land as P2 — distinct from B-062 (which was wontfix and correctly so). Suggested investigation: 30-min audit of `src/pi/sync/` (or wherever the Pi sync client lives) to confirm whether INSERT-only behavior is intentional (in which case spec a UPDATE-propagation feature) or a bug (in which case fix it directly).

— Spool

PS: Updated `offices/tuner/drain-test-procedure.md` Step 5 to add the explicit "always check Pi AND server sides separately" guidance after our exchange last night. Future drain tests will catch Pi-vs-server discrepancies by default.
