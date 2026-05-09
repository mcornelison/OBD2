# Drive 6 + Drive 7 graded — engine HEALTHY across full envelope including WOT
**Date**: 2026-05-08
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (sprint validation milestone + new bug + knowledge.md update + spec recommendation)

## TL;DR — major milestone day

After 3 engine-on attempts today, Mike got Drive 6 + Drive 7 captured cleanly post-V0.27.1 hotfix.

- **Drive 6** (16 min, cold-start city, drive_id=6): engine HEALTHY warmup + light city
- **Drive 7** (10 min, highway + WOT, drive_id=7): **first under-load capture in project history** — engine HEALTHY through 100%-engine-load event at 84 mph / 5379 RPM
- **Sprint 27 V0.27.1 hotfix EMPIRICALLY VALIDATED in production** — reconnect path successfully closed the gap between Mike's two engine-off stops without manual intervention (38s reconnect time)
- **One new bug surfaced**: `drive_summary` writer regression — last row written is drive_id=5; Drives 6+7 produced `drive_end` events but no summary rows
- **Long-running carryforward CLOSED**: LTFT post-jump-start adaptation tracking — ECU re-locked at -6.25% baseline (same notch as pre-jump)
- **Knowledge.md updated** with Drive 6 + Drive 7 baselines and Drive 7 designated as the new authoritative UNDER-LOAD baseline

## Drive 6 — 2026-05-08 00:41:54Z → 00:57:32Z (16 min, cold-start city)

Cold start at ambient ~20°C → 16 min city drive (max 46 mph, max 3367 RPM, max 21% throttle). Full cold→warm cycle (coolant 38°C → 89°C). 7,085 captured rows across 16 PIDs.

**Engine grade**: HEALTHY warmup + light city drive.

| Critical signal | Drive 6 | Verdict |
|---|---|---|
| Coolant ramp | 38°C → 89°C | Thermostat opens cleanly at 80°C — **4th confirmation across drives 3/4/5/6** |
| LTFT_1 (idle cell) | -6.25% locked | **Post-jump adaptation re-converged to pre-jump baseline** ✓ |
| STFT_1 | -7.03 → 9.38, avg 1.82 | Active closed-loop, healthy |
| O2_B1S1 / B1S2 | Full sweep / damped | Sensors healthy, cat lighting off normally |
| Timing | 3-32° | Full healthy range |
| Battery | 14.27V avg | Alternator strong |
| DTC / MIL | 0 / 0 | Clean |

## Drive 7 — 2026-05-08 01:37:27Z → 01:47:12Z (10 min, **HIGHWAY + WOT**) 🔥

Mike's second segment, ~40 min after Drive 6 ended (engine restart triggered new drive_id). **First WOT/100%-engine-load capture in project history.** Highway speed 84 mph reached, max RPM 5379, MAX MAF 158.69 g/s.

**Engine grade: HEALTHY UNDER FULL LOAD ENVELOPE.**

| Critical signal | Drive 7 | Verdict |
|---|---|---|
| Max engine load | **100%** | **WOT / full boost event survived clean** |
| Max MAF | **158.69 g/s** | Above NA peak (~120) — turbo making boost (~10-12 psi est) |
| Max RPM | 5379 | Within healthy stock 4G63 range |
| Max speed | 84 mph | Highway pull confirmed |
| Coolant under sustained load | max 91°C (196°F) | **Stayed below 220°F danger ceiling** ✓ |
| IAT under load | max 26°C (79°F) | **No heat-soak under load** ✓ |
| Timing under load | up to 34° | Full ECU range exercised; **no knock-pull events flagged** ✓ |
| LTFT under load | -7.81 → 0.78, avg -3.89 | Load-cell drift, normal |
| STFT under load | -12.5 → 14.06, avg 0.17 | Wide swings (normal for WOT enrichment + transients), net averages out ✓ |
| DTC / MIL | 0 / 0 | Engine survived clean across the WOT pull ✓ |

## What this means tuning-wise

**The engine is mechanically certified HEALTHY across the full operational envelope as it sits today.** Idle, cold-start warmup, light city driving, sustained highway speed, AND wide-open-throttle under boost.

Specifically:
1. **No knock event** flagged during the WOT pull (timing didn't drop below 0° BTDC, no DTC set). Stock 4G63 with TD04-13G + modified EPROM appears to be tuning safely under boost.
2. **Cooling system is adequate** for this turbo + driving profile. Future hot-day or sustained-WOT drives could change this story; for now we have a "passes 91°C max under 10-min mixed load" baseline.
3. **Fueling is balanced** under load. STFT swings to ±12-14% during WOT are EXPECTED behavior (closed-loop momentarily out of authority during enrichment); the fact that average STFT is +0.17% across the drive means net the mix balanced cleanly.
4. **LTFT load-cell shape is now mapped**: idle cell -6.25%, light-load 0.0%, heavy-load -7.81%. Future drives should show the same general shape; deviation = adaptation to changed conditions.
5. **Pre-mod baseline shelf has its first complete entry.** Drive 7 is the foundation. 2-4 more drives across May-June would lock the shelf before any mods touch the car this summer (per my Sprint 26 priorities note).

## Operational milestone — V0.27.1 hotfix VALIDATED in production

Connection_log between Drive 6 end and Drive 7 start:
```
00:57:32Z  drive_end (Drive 6, drive_id=6)
01:36:18Z  connect_attempt
01:36:56Z  connect_success  ← 38 seconds to reconnect post-engine-on
01:37:27Z  drive_start (Drive 7, drive_id=7)
```

**Mike's second engine-on cycle reconnected automatically. No manual intervention.** This is US-301 (heartbeat with single-flight lock) + US-302 (data logger restart-on-restore) + Ralph's V0.27.1 thread-safety fix all working as designed in the wild.

**The reconnect path can be trusted going forward.** Sprint 27 + V0.27.1 hotfix officially validated against the real engine-on workflow. Per the new validation workflow (`/sprint-validated`), this should advance Sprint 27's `validatesFeatures` last-validated dates in `regression_manifest.json`.

## NEW BUG — `drive_summary` writer regression (Sprint 28 P2 candidate)

`drive_summary` table — last row written is `drive_id=5` from April 29.

**Drive 6 produced `drive_end` event at 00:57:32Z. NO `drive_summary` row written.**
**Drive 7 produced `drive_end` event at 01:47:12Z. NO `drive_summary` row written.**

`realtime_data` capture is fine (7,085 rows for Drive 6, ~3,000+ for Drive 7); only the summary roll-up is missing. This is US-228 / US-237 territory (drive_summary metadata write path) and looks like a regression — Drives 3+4 historically had this same bug (4 occurrences before US-237 reconciled it Sprint 19), so this is the same bug class re-emerging.

**Severity**: P2 — data-integrity for analytics layer, not safety-critical. Realtime data + connection_log are both clean, so we have full visibility on what happened during the drives. We just don't have the convenience roll-up for analytics queries.

**Recommended Sprint 28 ask**: Investigate whether US-237's reconciler is firing OR whether the defer-INSERT path from US-236 has a regression. Could be a session-level issue with how `drive_summary` rows get minted on the new V0.27.x deploy.

## Knowledge base updates done this session

`offices/tuner/knowledge.md`:
- Added Drive 6 baseline section (cold-start city, supersedes nothing but adds cold→warm continuity data)
- Added Drive 7 section as NEW AUTHORITATIVE UNDER-LOAD BASELINE
- Added Drive 7 interpretation anchors (MAF ceiling under boost, STFT WOT-swing range, timing-under-load expected range, coolant thermal envelope, LTFT load-cell shape)
- Added Drive 7 diagnostic gaps still outstanding (sustained WOT, hot-soak/restart, cold-ambient WOT)
- Marked LTFT post-jump-start adaptation tracking as CLOSED with resolution note (re-locked at -6.25%)

## Recommended Marcus-actionable items

1. **Mirror Drive 7 baseline into `specs/grounded-knowledge.md`** — the "Real Vehicle Data" section authored Session 5 currently anchors on Drive 5 idle. Drive 7 is the first under-load entry and belongs in the team-facing source-of-truth doc. I didn't directly edit specs/ this session per closeout protocol; recommend a Sprint 28 small story or my next session.
2. **Groom drive_summary regression** as Sprint 28 P2 (above)
3. **Per new validation workflow**: if this drive cycle satisfies Sprint 27's `validatesFeatures` clauses in `regression_manifest.json`, run `/sprint-validated` to advance Sprint 27 to merged state.

## Cross-references

- Today's earlier P0 notes: `2026-05-08-from-spool-engine-on-test-blocked-2-p0-bugs.md` + `2026-05-08-from-spool-engine-on-test-2-blocked-us301-stacking-bug.md`
- Ralph's hotfix spec: `offices/ralph/inbox/2026-05-08-from-spool-us301-hotfix-stacking-connects.md`
- LTFT post-jump tracking origin: Session 7 (2026-04-29 Drive 5 grade)
- `knowledge.md` Drive 5 + Drive 6 + Drive 7 sections (this update)
- `drive-review-checklist.md` updated this session with Pre-Capture pipeline pre-flight (5 checks including the heartbeat-stalled-too-long check that would have caught BUG-3 pre-engine-on)

— Spool

PS: Three engine-on attempts today, three sibling bugs surfaced, three sibling bugs fixed. Net 2 healthy drive grades. The tooling is paying off — heartbeat instrumentation made all three diagnoses fast (5 minutes vs. 11 hours). The spec-discipline lesson from BUG-3 (5s timeout was too tight for K-line because I didn't check the empirical 8s baseline) is on me; saving as feedback memory next session.
