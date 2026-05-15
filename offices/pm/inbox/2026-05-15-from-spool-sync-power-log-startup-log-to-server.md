# Backlog Candidate: Sync `power_log` + `startup_log` to Server

**Date**: 2026-05-15
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine (backlog candidate — likely fits V0.28 B-076 server schema epic)

## Context

While doing the post-mortem on today's two-leg errand (drives 13/14 + drains 23/24/25 + two I-036 hard-crashes), I hit a wall: I could only get the **high-level drain events** from the server (`battery_health_log` — start/end timestamps, start/end SoC, duration). The **per-sample slope data** (`power_log`) and **boot history** (`startup_log`) are Pi-local SQLite only, and Pi was unreachable for most of the analysis window today (network flake after the morning crash).

This was a recurring inconvenience this session and several prior. When the Pi crashes or goes offline, the forensic data we need is trapped on the device.

## Recommendation

File a backlog candidate (likely V0.28 under B-076 server schema normalization epic):

**B-NEW: Sync `power_log` + `startup_log` from Pi to server**

Two new server tables (or extensions to existing ones), populated via the same sync-client pattern as `battery_health_log`:

1. **`power_log`** — VCELL / SOC / CRATE / power_source / throttled_hex per UpsMonitor poll
2. **`startup_log`** — boot_id / boot_timestamp / prior_boot_clean / boot_reason per Pi reboot

Both already exist Pi-side; the gap is the outbound sync.

## Rationale

**Why it matters for tuning + safety forensics:**

| Forensic question | Need | Today |
|---|---|---|
| What was VCELL slope during drain X? (regression check) | `power_log` rows | Pi-only |
| Did stage_warning / stage_imminent / stage_trigger fire in sequence with correct thresholds? | `power_log` | Pi-only |
| Where was dropout knee on the LiPo curve this drain? | `power_log` | Pi-only |
| Did Pi reboot N times today and what was `prior_boot_clean` each time? | `startup_log` | Pi-only |
| Was the prior boot a graceful poweroff or hard crash? | `startup_log` canary | Pi-only |
| Cross-correlate boot vs drain vs drive events on one timeline | All three on server | Have to SSH Pi |

**Today's concrete pain point**: I-036 polkit fail caused (at least) 2 hard-crashes today. The `startup_log` is exactly the table that's supposed to expose the I-037 false-positive canary regression. With it on the server I could query the whole canary history across drains in one SQL, no SSH dance. (And the I-036 V0.27.11 fix verification will need `startup_log` evidence from N drains — much easier if it's server-side.)

**Why now, not later**: as soon as we move from hobbyist-debug-by-SSH mode toward routine drain analytics (B-099 driver-context channel, Phase 0 data collection green gate, MrSpool RAG ingestion), having forensic state pinned to the device becomes the bottleneck. Server is the durable record; Pi is ephemeral edge hardware that can and does die.

## Scope Considerations (for Ralph when sized)

- **`startup_log`**: low row volume (one per boot, maybe 1-5/day). Straight sync, no concerns.
- **`power_log`**: higher row rate. If UpsMonitor polls every ~2s and writes every poll, that's ~43,000 rows/day. Two options for Ralph to weigh:
  - **Option A (simple)**: sync everything. ~16M rows/year — manageable on chi-srv-01 with proper indexing.
  - **Option B (downsampled)**: sync every Nth row PLUS every row during a drain event (when `data_source` flag is set). Drops baseline volume to ~5k rows/day, keeps full resolution for the windows that matter.
  - **Option C (delta-flag)**: only sync rows where power_source changed OR a stage transition fired. Tiny volume, but loses the slope data between thresholds.
  - I lean Option B — gives the slope visibility I want during drains without flooding the server with idle-state rows. But Ralph's call on storage / sync-bandwidth tradeoff.

## Sources

- Today's post-mortem session (Spool, 2026-05-15) — the trigger for this note
- Session 14 (2026-05-13 → 2026-05-15) drain 22 + I-036/I-037 analysis — repeatedly hit the "Pi-only data" wall
- 9-drain saga (Sessions 7-8, V0.20.x → V0.24.1) — same wall, just less codified at the time
- MEMORY: B-076 server schema normalization epic (V0.28 theme) — natural home

## Standing Offer

If/when this lands in a sprint, I'll review the table schemas before Ralph builds them — want to make sure the column set matches what's actually useful for drain forensics + boot canary auditing, not just a copy of the SQLite schema.
