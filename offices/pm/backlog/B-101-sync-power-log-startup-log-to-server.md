# B-101: Sync `power_log` + `startup_log` from Pi to server

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (V0.28+ candidate; forensic-access gap — becomes a bottleneck as drain analytics goes routine) |
| Status       | Pending (V0.28+ candidate) |
| Category     | server / sync / forensics / new-tables |
| Size         | M (two new server tables + ORM models + sync-client wiring; `power_log` needs a volume strategy decision) |
| Related PRD  | None |
| Dependencies | B-076 (server schema normalization epic — natural home; new tables should land in the same FK/`vehicle_id` convention); B-099 (Telegram driver-context — same "move forensics off the ephemeral Pi" motivation); existing `battery_health_log` sync = the reference pattern |
| Created      | 2026-05-15    |

## Description

Spool's 2026-05-15 post-mortem hit a recurring wall: high-level drain events (`battery_health_log`) sync to the server, but the **per-sample slope data (`power_log`)** and **boot history (`startup_log`)** are Pi-local SQLite only. When the Pi crashes or goes offline (e.g. the I-036 hard-crashes today, plus the network flake after the morning crash), the forensic data needed for drain/canary analysis is trapped on the device. This wall recurred across the 9-drain saga and the Drain 22 I-036/I-037 analysis.

Add two new server tables (or extensions), populated via the same sync-client pattern as `battery_health_log`:

1. **`power_log`** — VCELL / SOC / CRATE / power_source / throttled_hex per UpsMonitor poll
2. **`startup_log`** — boot_id / boot_timestamp / prior_boot_clean / boot_reason per Pi reboot

Both already exist Pi-side; the gap is purely the outbound sync.

Concrete near-term payoff: the I-036/I-037 fix verification (V0.27.11 → Drain 23) needs `startup_log` evidence across N drains. Server-side `startup_log` makes the canary-history audit (US-343) a single SQL query instead of an SSH dance.

## Acceptance Criteria

- [ ] `startup_log` rows sync Pi→server (low volume, ~1-5/day — straight sync, no volume concern)
- [ ] `power_log` rows sync Pi→server per the chosen volume strategy (see Notes — Option A/B/C decision required at grooming)
- [ ] Server tables follow the B-076 FK/`vehicle_id` convention if B-076 has landed, OR are designed forward-compatible if B-101 ships first
- [ ] Cross-correlation query works: boot vs drain vs drive events on one server-side timeline, no SSH required
- [ ] Sync is idempotent + survives Pi-offline windows (catch-up on reconnect, same as `battery_health_log`)

## Validation Script Requirements

- **Input**: a drain event + a Pi reboot, then a sync window
- **Expected Output**: server `power_log` has the per-poll slope rows for the drain window; server `startup_log` has the boot row with correct `prior_boot_clean`
- **Database State**: `SELECT … FROM power_log WHERE <drain window>` returns the VCELL slope; `SELECT … FROM startup_log` returns one row per Pi boot
- **Test Program**: post-drain reconciliation — assert server `power_log` row count for the drain window matches Pi-side, and the `startup_log` canary value matches the Pi-side ground truth

## Notes

- Spool note: `offices/pm/inbox/2026-05-15-from-spool-sync-power-log-startup-log-to-server.md` (2026-05-15)
- Spool explicitly scoped this OUT of V0.27.11 (backlog candidate, not chain-blocking).
- **`power_log` volume decision (Spool laid out 3 options, leans B):**
  - **Option A (simple)**: sync everything. ~43k rows/day, ~16M/year — manageable on chi-srv-01 with indexing.
  - **Option B (downsampled — Spool's lean)**: every Nth row PLUS every row during a drain event (`data_source` flag set). ~5k rows/day baseline, full resolution where it matters.
  - **Option C (delta-flag)**: only rows where `power_source` changed OR a stage transition fired. Tiny, but loses inter-threshold slope.
  - PM note: Option B aligns with the drain-forensics use case (slope visibility during drains is the whole point) without flooding idle-state rows. Final call is Ralph's on storage/sync-bandwidth tradeoff at grooming.
- Spool standing offer: will review the table schemas before Ralph builds (column set matched to drain-forensics + boot-canary auditing, not a naive SQLite-schema copy).
- Sequencing: could land independently OR fold into B-076 (it adds tables rather than normalizing existing ones, so it's additive — lower coupling risk than the rename work).

## Source

Spool 2026-05-15 post-mortem (the trigger); Drain 22 I-036/I-037 analysis (repeatedly hit the Pi-only wall); 9-drain saga (same wall, less codified).
