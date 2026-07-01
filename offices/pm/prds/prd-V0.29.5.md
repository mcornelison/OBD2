---
sprint: 51
version: V0.29.5
status: draft
createdAt: 2026-07-01
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev
epic: E-002, E-001, E-OPS, F-116
feature: F-101, F-077, F-058, F-080, F-096, F-098, F-060, F-061, F-116
theme: Data-integrity + sync-pattern completion + battery/UI hygiene
validationMode: BENCH ONLY (fixture/DOM tests + Pi bench rigs + DB-column checks + live-Pi re-query for verify-first items -- NO drive drills)
selectedStories: [US-416, US-417, US-418, US-419, US-420, US-421, US-422, US-423, US-424, US-425]
---

# PRD: Sprint 51 / V0.29.5 — Data-integrity + sync-pattern completion + battery/UI hygiene

| Field | Value |
|---|---|
| Sprint | 51 |
| Version | V0.29.5 (patch on the V0.29 chain) |
| Branch | `sprint/sprint51-V0.29.5` (forks from `dev`) |
| Validation | **BENCH ONLY** — fixture/DOM, Pi bench rigs, DB-column checks, live-Pi re-query for verify-first items. No drive drills. |
| Story range | US-416 … US-425 (10 stories — filled to cap) |

## 1. Introduction / Overview

Sprint 51 clears the deferred hygiene backlog behind the V0.29 chain and completes two half-finished threads:

- **Sync-pattern completion** — build the **general natural-key snapshot-sync path** Atlas ruled for US-416 (the TEXT-PK path `startup_log` needs, which F-115's EDR event-vault will reuse), then register `startup_log` onto it.
- **Data-integrity** — a boot-time clock-drift guard, and the **foreign-vehicle contamination** marker + ingest guard (drive 33 = a Ford Explorer logged as Eclipse data).
- **Idle-log hygiene** — quiet the `connection_log` / `sync_history` chatter (verify-first — some may already be fixed).
- **Battery cleanup** — finally wire UpsMonitor SoC% through to the recorder (F-060), which unblocks dropping the legacy `battery_health_log` SoC columns (F-061).
- **UI** — two carousel cards now that the dashboard is on `dev`: the LTFT trend and the power-mode badge.

## 2. Goals

- Complete the TEXT-PK sync story: a reusable `SNAPSHOT_SYNC` mechanism + `startup_log` as its first consumer (finishes Sprint 50's carve-out).
- Stop writing drifted post-reboot timestamps as truth; flag clock-unsynced rows.
- Honestly mark + guard against foreign-vehicle contamination.
- Quiet idle DB/log growth (or close as already-healthy with evidence).
- Retire the legacy `battery_health_log` SoC columns once SoC% is wired.
- Ship the LTFT + power-mode carousel cards.
- Zero drive drills.

## 3. User Stories

> **Design refs:** US-416/417 build to Atlas's ruling `offices/architect/reports/2026-07-01-us416-startup-log-snapshot-sync-ruling.md`. US-424 (F-116) is **design-pending Atlas** — routed `offices/architect/inbox/2026-07-01-from-marcus-f116-foreign-vehicle-design-gate.md`; its acceptance finalizes when his ruling lands (before freeze).

---

### US-416: General natural-key snapshot-sync path + `SNAPSHOT_SYNC` registry (Atlas-ruled)
**Description:** As the system, I want a reusable table-parameterized snapshot-sync mechanism for TEXT-PK / insert-once tables, so `startup_log` (and F-115's event-vault) can sync without the integer-delta cursor.

**Acceptance Criteria:**
- [ ] Pi `SNAPSHOT_SYNC` registry `{table -> (naturalKeyCols, cursorCol)}` + a snapshot reader that deltas by an explicit **`recorded_at`** cursor (per table, tracked in `sync_log`) — NOT full-snapshot, NOT rowid (TEXT-PK tables have no stable rowid).
- [ ] Server natural-key upsert **parameterized by `naturalKeyCols`** → `UNIQUE(source_device, *naturalKeyCols)` + ON-CONFLICT; a NEW pattern, distinct from the `id->source_id` registry path.
- [ ] **A-4 guard:** each table's `naturalKeyCols` defined **once**, referenced by both tiers (shared contract, not two drifting lists).
- [ ] Does NOT touch / refactor `dtc_freeze_frame`'s FK-resolution special-case (leave shipped code alone).
- [ ] Unit tests: idempotent re-sync on the natural key; cursor bounds volume.
- [ ] `ruff check` passes.

**Downstream impact:** New sync mechanism; F-115 event-vault will register into it (Atlas owns that gate).

---

### US-417: Register `startup_log` onto the snapshot path (deps US-416)
**Description:** As the CIO, I want `startup_log` mirrored to the server, so boot history is server-queryable.

**Acceptance Criteria:**
- [ ] `startup_log` registered in `SNAPSHOT_SYNC` with `naturalKeyCols=(boot_id)`, cursor `recorded_at`.
- [ ] Two migrations: Pi `recorded_at` column (if absent); server `UNIQUE(source_device, boot_id)` — deployed AND verified via `INFORMATION_SCHEMA`.
- [ ] Post-sync, server `startup_log` rows match Pi; idempotent on re-sync.
- [ ] `ruff check` passes.

**Downstream impact:** Closes BL-013 / the US-412 carve-out.

---

### US-418: Idle log-noise + sync-cadence hygiene (F-077 + F-078 + F-058, verify-first)
**Description:** As the CIO, I want the Pi to stop writing chatty `connection_log` / `sync_history` rows at idle, so the tables don't grow 24/7.

> **Verify-first:** re-query the deployed Pi first. Prior backoff/cadence work (US-325/US-332) may have already fixed some of these. For each sub-item: if the live table is healthy, **close as already-fixed with evidence** rather than changing code.

**Acceptance Criteria:**
- [ ] **(F-077/F-058)** enumerate every `connection_log` writer; idle growth drops to a defined healthy rate (or close-with-evidence).
- [ ] **(F-078)** at idle, `sync_history` stops accumulating ~1.5 rows/min — slow/batch the engine-off poll loop OR a dedicated `pi_state.sync_idle` gate (NOT the `no_new_drives` drain gate — that was the wrong US-332 fix). Verify via idle-soak.
- [ ] Must NOT suppress real connection/sync events — only idle noise.
- [ ] `ruff check` passes.

**Downstream impact:** Engine-off poll loop / cadence controller / connection+sync writers. Known resize split-candidate.

---

### US-419: Pi post-reboot clock-drift guard (F-080, code angle)
**Description:** As the CIO, I want post-reboot log timestamps to be sane, so power/boot history isn't corrupted by RTC drift.

> **Scope:** the RTC coin-cell / `systemd-timesyncd` ordering fix is **ops (AI-1)**, tracked separately. This story owns only the code-side guard.

**Acceptance Criteria:**
- [ ] **Verify-first:** re-query the Pi (`timedatectl`, `hwclock`, `systemctl status systemd-timesyncd`, recent `power_log` timestamps); if the clock is sane post-reboot (fixed out-of-band), close as not-needed with evidence.
- [ ] If still drifting: the `startup_log`/`power_log` timestamp writers gain a **boot-time sanity guard** — the first post-boot row's timestamp is validated against an NTP-confirmed/monotonic source; drift beyond threshold flags `data_quality='clock_unsynced'` rather than silently writing drifted time as truth.
- [ ] A unit test simulates a pre-NTP-sync boot timestamp and asserts the guard flags (not crashes).
- [ ] `ruff check` passes.

**Downstream impact:** Adds a quality flag; analytics treat `clock_unsynced` rows as suspect.

---

### US-420: LTFT multi-drive trend card (F-096, carousel)
**Description:** As the CIO, I want a carousel card showing long-term fuel trim across recent drives, so I can watch LTFT migrate toward 0 (healthy) vs drift beyond ±10%.

> **Depends on:** the Sprint-49 carousel shell (US-399, on `dev`).

**Acceptance Criteria:**
- [ ] New carousel card renders an LTFT trend across the last N drives (multi-drive, not per-drive), sourced from the LTFT PID in `realtime_data` (confirm exact PID/source per Spool's S-2 note).
- [ ] Distinguishes healthy migration-toward-0 from drift beyond ±10% (honest-instrument color/threshold — never green-when-stale).
- [ ] Empty/insufficient-data state renders gracefully.
- [ ] Bench-validatable via fixture/DOM test against canned multi-drive LTFT data.
- [ ] `ruff check` passes.

**Downstream impact:** New carousel card; rides the F-103 states-dir + eclipse-states-http runtime.

---

### US-421: Power-mode badge — in-car vs wall-power (F-098, carousel)
**Description:** As the CIO, I want a corner badge showing in-car vs wall-power-debug mode, so the power_log analytical-guardrail confusion is eliminated at the UI.

> **Depends on:** the Sprint-49 carousel shell (US-399, on `dev`).

**Acceptance Criteria:**
- [ ] A small persistent badge shows current power mode, sourced from the existing power-mode SSOT provider (`src/pi/power/` — confirm the provider; do NOT add a second acquisition path per the SSOT directive).
- [ ] Updates on mode change; honest-instrument: undeterminable → "unknown", never a confident wrong state.
- [ ] Bench-validatable via fixture/DOM test with mocked mode states.
- [ ] `ruff check` passes.

**Downstream impact:** Read-only consumer of the power-mode provider; new dashboard badge.

---

### US-422: Wire UpsMonitor SoC% through orchestrator to recorder (F-060)
**Description:** As the system, I want the MAX17048 SoC% wired end-to-end into `battery_health_log`, so SoC% is recorded (the prerequisite to retiring the legacy columns).

**Acceptance Criteria:**
- [ ] UpsMonitor SoC% flows through the orchestrator to the recorder and lands in `battery_health_log` (start/end SoC% via the register, not derived from voltage).
- [ ] A bench drill (UPS-drain rig) shows SoC% populated on a closed `battery_health_log` row.
- [ ] `ruff check` passes.

**Downstream impact:** Unblocks US-423 (BL-013-family cleanup chain).

---

### US-423: Drop legacy `battery_health_log` SoC columns (F-061, deps US-422)
**Description:** As the system, I want the legacy `start_soc`/`end_soc` columns dropped once SoC% is wired, so there's one source of truth.

**Acceptance Criteria:**
- [ ] Pi SQLite migration (CREATE-AS-SELECT-DROP-RENAME — SQLite has no ALTER DROP) removes `start_soc`/`end_soc`; server MariaDB `ALTER TABLE ... DROP COLUMN`; both **deployed AND verified** via schema introspection.
- [ ] All consumers migrated to `start_vcell_v`/`end_vcell_v` (+ the US-422 SoC%); lock-down tests updated to drop the removed-column refs.
- [ ] `ruff check` passes.

**Downstream impact:** Schema change on both tiers; all consumers listed + updated in-sprint.

---

### US-424: Foreign-vehicle contamination marker + ingest guard (F-116) — design-pending Atlas
**Description:** As the CIO, I want foreign-vehicle rows honestly markable and prevented from recurring, so the Explorer (drive 33) can't pollute real-data tuning queries.

> **Design-pending Atlas** (routed 2026-07-01): the marker-enum semantics + guard mechanism + where-it-lives. Acceptance finalizes when his ruling lands.

**Acceptance Criteria (shape; finalizes on Atlas ruling):**
- [ ] Marker enum added (`data_source='foreign'` and/or `data_quality='foreign_vehicle'` per Atlas) — forward-only CHECK migration on both tiers; drive 33's 1,364 rows re-tagged via Spool's SQL.
- [ ] Ingest guard (Atlas-decided; lead = bus-rate sanity check > ~7 samples/sec = impossible on the Eclipse K-line → flag/quarantine) — prevents recurrence. **No VIN guard** (Eclipse ECU is Mode 09 silent).
- [ ] Guard placement (Pi quarantine vs server tripwire) per Atlas.
- [ ] `ruff check` passes.

**Downstream impact:** CHECK-constraint change both tiers; ties loosely to A-9 (distinct concern — cross-vehicle identity).

---

### US-425: Sprint 51 documentation sync (Rule-10)
**Description:** As the PM, I need docs to reflect the sprint's sync/schema/UI changes.

**Acceptance Criteria:**
- [ ] `specs/architecture.md` sync section updated for the `SNAPSHOT_SYNC` mechanism (Rule-10, in-sprint).
- [ ] Any new config/enum/schema changes documented (battery_health_log columns, foreign marker, clock_unsynced flag).
- [ ] `regression_manifest.json` reflects new/changed features (F-101/060/061/077/078/080/096/098/116).
- [ ] All spec docs reflect current state; no stale references.

**Downstream impact:** Docs only.

## 4. Non-Goals (Out of Scope)

- **F-100 (drive_summary writer broken)** — VERIFIED STALE (drive_summary is healthy; no `summary_text` column exists). **Archive candidate, not a build.**
- **RTC coin-cell / timesyncd ordering** (F-080 ops half) — action item AI-1, not sprint code.
- **F-115** (EDR event-vault, display, server sync of raw samples, vehicle-frame transforms) — later phase.
- **No drive drills.**

## 5. Open Questions

1. **(Atlas, US-424)** marker enum semantics + guard mechanism + placement — pending his ruling.
2. **(Resize)** US-418 is a deliberate multi-item batch (F-077/078/058) — accept as one or split? US-416 (general mechanism) may also warrant a look.
3. **(Spool, US-420)** exact LTFT PID/source — confirm before build.

## Action Items (NOT sprint stories)

- **AI-1 (F-080 ops half):** check/replace the Pi RTC coin-cell; verify `systemd-timesyncd` boot ordering. CIO + ops.
- **AI-2:** archive F-100 (verified-stale drive_summary bug) at grooming hygiene.
