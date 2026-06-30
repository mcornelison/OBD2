# PRD: Sprint 50 / V0.29.4 — EDR sensor-reader (hardware-deferred) + next-step drain

| Field | Value |
|---|---|
| Sprint | 50 |
| Version | V0.29.4 (patch on the V0.29 chain) |
| Branch | `sprint/sprint50-V0.29.4` (forks from `dev`; dispatches AFTER Sprint 49 lands) |
| Theme | EDR sensor-reader, built hardware-deferred + a curated backlog drain |
| Validation | **BENCH ONLY** — CIO waived drive drills for the V0.29 chain. Mock-sensor rigs, idle-soak log audits, DB-column checks. |
| Story range | US-408 … US-417 (10 stories) |
| Design gate | **APPROVED (decision level) — Atlas 2026-06-30** (`offices/pm/inbox/2026-06-30-from-atlas-edr-gate-sprint50-APPROVAL.md`): scope + approach + all 5 items ruled (A-14 gates #1/#2). EDR stories are groomable against his rulings; the **concrete DDL + bus message framing + per-channel cadence numbers come in his ADR — a CIO sit-down deliverable produced next**. Gate #1 bus-contract design also at `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`. |

---

## 1. Introduction / Overview

Two threads in one sprint:

**(A) EDR sensor-reader — built hardware-deferred.** The EDR (Event Data Recorder) epic adds two I²C sensors — an **ICM-20948 9-DoF IMU** (`0x69`) and a **TSL2591 light sensor** (`0x29`) — on bus 1, alongside the existing MAX17048 UPS gauge (`0x36`). The CIO's directive: *"build E-006, but wire/connect to the sensors when I wire them up."* So this sprint builds the **reader + persistence code with graceful sensor-absence** — it probes for each sensor, reads it if present, logs-and-skips if absent, and **never crashes** when the hardware isn't wired. The code builds and bench-tests today with no sensors attached; when the CIO physically wires them, the same code connects and data flows. Everything ships **dark behind a flag** (the F-110 `pi.bus.enabled` pattern), so it's inert in production until validated.

**(B) Next-step backlog drain.** Six curated, ready, bench-validatable items that have been queued behind the V0.29 chain: two server-sync coverage gaps, a batched idle-log-noise/cadence hygiene fix, a clock-drift guard, and two small Pi-UI cards that ride the Sprint-49 carousel (LTFT trend + power-mode badge).

**The problem it solves:** the EDR hardware is wired-and-ready but has no software; and a backlog of small data-integrity/hygiene papercuts has accumulated. This sprint clears both without needing a drive.

## 2. Goals

- Land the EDR **single-reader extension** for IMU + light with deterministic graceful-absence, so the CIO can wire sensors at his convenience and get data with no further code.
- Persist raw sensor samples to a **versioned schema** (Atlas-designed) that does **not** repeat the Pi↔server schema-divergence class, shipped dark.
- Preserve the **F-110 byte-identical `realtime_data` golden-master** — sensor channels are strictly additive.
- Close the **server-sync coverage gaps** (power_log, startup_log, drive_counter) so the server mirror is complete.
- **Quiet the idle chatter** in `connection_log` / `sync_history` and fix the `sync_history` timezone mismatch.
- Add two **carousel cards** (LTFT trend, power-mode badge) building on the Sprint-49 dashboard.
- Zero drive drills — everything verifiable on the bench.

## 3. User Stories

> **EDR design status:** Atlas's gate is **APPROVED** with rulings on all 5 items (folded into US-408–410 below). The **shape is locked**; the only thing still pending is the **concrete DDL + bus message frame + per-channel cadence numbers**, which arrive in Atlas's ADR (CIO sit-down). Stories are groomable now; the literal table columns / cadence constants finalize when the ADR lands (before freeze).

---

### US-408: EDR IMU + light sensor readers (graceful-absence, publish to bus)
**Description:** As the system, I want a single threaded reader to probe and read the ICM-20948 IMU and TSL2591 light sensor and publish their samples to the dedicated-reader bus, so that motion/light data is captured when the sensors are wired — and the code runs harmlessly when they are not.

**Acceptance Criteria:**
- [ ] A source-reader probes for each sensor at startup (ICM-20948 @ `0x69`, fallback `0x68`; TSL2591 @ `0x29`) on `/dev/i2c-1`.
- [ ] **Sensor present** → reader publishes `Sample` envelopes on `raw.imu.<channel>` (accel x/y/z, gyro x/y/z, mag x/y/z, temp) and `raw.light.<channel>` (lux, visible, infrared, full_spectrum) with `source` set to `imu` / `light`.
- [ ] **Sensor absent (Atlas item 3):** probe-at-init marks the channel `status: sensor_absent`, then **skips publish AND skips persist** — the reader **never emits null/zero samples** (a downstream consumer must not mistake "not wired" for a real zero-g / zero-lux reading). One startup log line, no crash, no spam. Connect-when-wired = the probe succeeds on the next reader restart and the channel goes live with **no code change**.
- [ ] **QoS (Atlas item 1):** IMU (~50–100 Hz) and light (~1–5 Hz) are heterogeneous-rate **STREAM/LOSSY** topics — bounded per-consumer queue, **producer-never-blocks, drop-oldest**. The OBD/sync path stays on its **separate lossless/durable** QoS lane (sensor channels are strictly additive; they must NOT perturb `raw.obd.*` or the F-110 golden master).
- [ ] **Sample rate decoupled from persist rate (Atlas item 1):** the reader may sample at full rate but persistence runs at a configured (lower) cadence; full-raw-rate retention is an F-115 event-window concern, not this phase.
- [ ] **Dark-ship flags (Atlas item 4):** per-sensor `pi.sensors.imu.enabled` + `pi.sensors.light.enabled`, **each requiring `pi.bus.enabled`**; both default OFF. (Per-sensor so the CIO enables each as he wires it.)
- [ ] Unit tests cover the present (mock-sensor) and absent (`sensor_absent`, no fabricated sample) paths.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Adds `raw.imu.*` / `raw.light.*` topics to the bus. No existing subscriber consumes them yet (additive). Must not change `raw.obd.*` behavior.

---

### US-409: EDR raw-sensor persistence subscriber + versioned schema — **Pi-local, dark-ship**
**Description:** As the system, I want a persistence subscriber that drains the IMU/light topics and writes them to a versioned **Pi-local** raw-sensor schema, so that sensor data is durably recorded on the Pi once enabled.

> **Atlas item 2 — Pi-LOCAL ONLY this phase.** Raw IMU at ~100 Hz is too voluminous to sync and isn't needed server-side until the event-vault/display phase (F-115). **No server table and no sync path in this sprint.** The future server schema (F-115) will derive from the **same `src/common/` definition**, so there's zero divergence by construction.

**Acceptance Criteria:**
- [ ] New subscriber (modeled on `PersistenceSubscriber`) subscribes to `raw.imu.*` / `raw.light.*` and writes samples to a **versioned Pi-local SQLite table**, with sample timestamp, `drive_id`, and an explicit **`schema_version`** column.
- [ ] **Schema SSOT (Atlas item 2):** the table is defined under the versioned `src/common/` contract discipline; the Pi DDL is generated from that single definition (NOT hand-written) so a future F-115 server table derives from the same source. Migration is **forward-only**.
- [ ] **`drive_id` NULL-latch (Atlas item 2):** `drive_id` FK is stamped **NULL explicitly when no RUNNING drive** — do NOT inherit a stale `_currentDriveId` (same latch discipline as the A-9 gap-fence and the DTC KOEO `drive_id=NULL` rule).
- [ ] Persistence runs at the **configured (lower) cadence**, decoupled from the reader's sample rate (per US-408).
- [ ] Pi-side table created and verified (schema introspection shows expected columns + `schema_version`).
- [ ] Entire path ships **dark** behind the per-sensor flags; with both OFF, no table writes occur and the inline OBD path is byte-for-byte unchanged.
- [ ] Subscriber observability: depth / dropped-count exposed via the existing `SubStats`.
- [ ] **Exact column list + types finalize with Atlas's ADR** (CIO sit-down); the shape above is locked.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** One new Pi-local table; no existing table altered; **no server/sync change** (deferred to F-115).

---

### US-410: EDR bench harness + golden-master regression + connect-when-wired drill
**Description:** As the developer, I need a mock-sensor harness and a regression that proves the OBD golden-master is untouched, so that the EDR build is verifiable with no hardware and safe to ship dark.

**Acceptance Criteria:**
- [ ] Mock-sensor harness feeds synthetic IMU + light readings through the reader → bus → persistence subscriber; rows land in the Pi-local EDR table with correct shape.
- [ ] **Absent-path test:** with no sensors and the per-sensor flags ON, the system starts, marks each channel `sensor_absent`, writes **zero EDR rows**, and **emits no null/zero samples** (assert: not a single fabricated reading) — without error.
- [ ] **Golden-master regression:** with the flags OFF (and ON, OBD-only), `realtime_data` rows are **byte-identical** to the pre-bus inline path (reuses the F-110 golden-master test discipline).
- [ ] Documented **connect-when-wired bench drill**: flip `pi.sensors.imu.enabled` / `pi.sensors.light.enabled` on a Pi with sensors physically attached, confirm `i2cdetect -y 1` shows `29 … 69`, and confirm EDR rows accumulate — recorded as the acceptance drill (run when the CIO wires the sensors; not a sprint blocker).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Test-only; no production code paths changed beyond test hooks.

---

### US-411: Sync `power_log` + `startup_log` from Pi to server
**Description:** As the CIO, I want the Pi's `power_log` and `startup_log` mirrored to the server, so that power/boot history is queryable server-side alongside the rest of the telemetry.

**Acceptance Criteria:**
- [ ] Server tables `obd2db.power_log` and `obd2db.startup_log` exist (new migration); **deployed AND verified** via `INFORMATION_SCHEMA`.
- [ ] Pi-side sync coverage extended to push both tables (idempotent; catches up on reconnect) following the `battery_health_log` sync pattern.
- [ ] After a sync, server rows match Pi rows for both tables (row counts + spot-checked values).
- [ ] `power_log` sync respects a defined volume strategy (raw-every-poll vs sampled/state-change-only) — **decide at story time and document the choice** (the table grows fast at the UpsMonitor poll cadence).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Two new server tables; sync-batch + schema-FK conventions (B-076 family) apply. No existing table changed.

---

### US-412: `drive_counter` server-side sync gap fix
**Description:** As the CIO, I want the server's `drive_counter` to track the Pi's, so that the server's last-drive-id isn't stale (Pi at 10, server at 3).

**Acceptance Criteria:**
- [ ] Root cause identified: the mirror writer isn't running OR `drive_counter` isn't covered by the sync set — **enumerate and state which** (`rg drive_counter src/pi/`).
- [ ] After fix + a sync cycle, `obd2db.drive_counter.last_drive_id` equals the Pi's current value.
- [ ] Idempotent (re-sync doesn't double-count or regress the server value).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Touches the sync coverage set (shared with US-411 — coordinate so both land in one coherent sync change if they share a writer).

---

### US-413: Idle log-noise + sync-cadence hygiene (batched)
**Description:** As the CIO, I want the Pi to stop writing chatty `connection_log` / `sync_history` rows at idle and to write `sync_history` timestamps in one timezone, so the tables don't grow ~24/7 and the data is trustworthy.

> **Verify-first (pre-condition):** re-query the deployed Pi before fixing. Some of these may have been partially addressed by prior backoff work (V0.27.6 US-325, V0.27.8 US-332). For each sub-item: if the live table is already healthy, **close it as already-fixed with the evidence** rather than changing code.

**Acceptance Criteria:**
- [ ] **(F-077 / F-058)** Enumerate every `connection_log` writer (`rg connection_log src/pi/`). At idle (engine-off, no ECU), connection_log growth drops to a defined healthy rate (target: well under the current ~6 rows/min; goal-state from F-058 was an 80%+ reduction vs the pre-V0.27.1 baseline). If already healthy on a quiet-day re-query, close with evidence.
- [ ] **(F-078)** At idle, `sync_history` stops accumulating ~1.5 rows/min — either the engine-off poll loop is slowed/batched (10–30s vs 2–3s) or a dedicated `pi_state.sync_idle` flag gates the cadence controller (do **not** reuse the `no_new_drives` drain gate — that was the wrong V0.27.8 fix). Verify with an idle-soak: row growth materially reduced.
- [ ] **(F-079)** `sync_history.started_at` and `completed_at` are written in the **same timezone (UTC, canonical ISO-8601 per `specs/standards.md`)** — the current exact-5h CDT/UTC mismatch within a single row is gone for new rows.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Touches the engine-off poll loop / sync cadence controller / connection + sync writers. **Must not** suppress real connection or sync events — only idle noise. **Known split-candidate** at resize (3+ concerns; intentionally batched per CIO "batch the small hygiene" directive).

---

### US-414: Pi post-reboot clock-drift guard (code angle)
**Description:** As the CIO, I want post-reboot Pi log timestamps to be sane (not jumped ~23h forward), so power/boot history isn't corrupted by RTC drift.

> **Scope note:** the root cause may be a dead RTC coin-cell or `systemd-timesyncd` ordering — **those are ops/hardware actions tracked separately** (see Action Items). This story owns only the **code-side guard**.

**Acceptance Criteria:**
- [ ] **Verify-first:** re-query the Pi (`timedatectl`, `hwclock`, `systemctl status systemd-timesyncd`, recent `power_log` timestamps) and record the current behavior. If the clock is already sane post-reboot (RTC/timesyncd fixed out-of-band), close the code story as not-needed with evidence.
- [ ] If still drifting: the `startup_log` / `power_log` timestamp writers gain a **boot-time sanity guard** — the first post-boot row's timestamp is validated against an NTP-confirmed / monotonic source, and a drift beyond a threshold is flagged (`data_quality='clock_unsynced'` or equivalent) rather than silently written as truth.
- [ ] A unit test simulates a pre-NTP-sync boot timestamp and asserts the guard flags (not crashes).
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Adds a quality flag to power/startup rows; analytics consumers should treat `clock_unsynced` rows as suspect.

---

### US-415: LTFT multi-drive trend card (carousel)
**Description:** As the CIO, I want a carousel card showing long-term fuel trim across recent drives, so I can watch LTFT migrate toward 0 (healthy, post-jump-start) vs drift beyond ±10% (concerning).

> **Depends on:** the Sprint-49 carousel shell (US-399) being on `dev` — guaranteed since Ralph is serial and Sprint 49 merges before Sprint 50 dispatches.

**Acceptance Criteria:**
- [ ] A new carousel card renders an LTFT trend across the last N drives (multi-drive view, not per-drive), sourced from the LTFT PID in `realtime_data` (confirm the exact PID/source at story time per Spool's S-2 note).
- [ ] The card distinguishes healthy migration-toward-0 from drift beyond ±10% (color/threshold per the honest-instrument carousel convention — never green-when-stale).
- [ ] Empty/insufficient-data state renders gracefully (no crash when a drive lacks LTFT samples).
- [ ] Bench-validatable via fixture/DOM test against canned multi-drive LTFT data.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** New carousel card; rides the F-103 states-dir + eclipse-states-http runtime. No data writes.

---

### US-416: Power-mode badge — in-car vs wall-power indicator (carousel)
**Description:** As the CIO, I want a small corner badge showing whether the Pi is in normal in-car mode or wall-power debug mode, so the analytical-guardrail confusion (power_log only reflecting engine state in in-car mode) is eliminated at the UI level.

> **Depends on:** the Sprint-49 carousel shell (US-399) on `dev`.

**Acceptance Criteria:**
- [ ] A small persistent badge on the dashboard shows the current power mode (in-car / wall-power-debug), sourced from the existing power-source/mode detection (`src/pi/power/` — confirm the SSOT provider at story time; do not add a second acquisition path per the SSOT design directive).
- [ ] The badge updates when the mode changes (e.g., switching to a wall adapter).
- [ ] Honest-instrument: if the mode can't be determined, the badge shows "unknown" — never a confident wrong state.
- [ ] Bench-validatable via fixture/DOM test with mocked mode states.
- [ ] `ruff check` passes on modified files.

**Downstream impact:** Read-only consumer of the power-mode provider; new badge on the dashboard.

---

### US-417: Sprint Documentation Sync
**Description:** As the PM, I need all spec/architecture docs to reflect the system after this sprint's changes.

**Acceptance Criteria:**
- [ ] Review all files changed in this sprint.
- [ ] `specs/architecture.md` EDR-bus section (the F-110 dedicated-reader subsection) extended with the **sensor-channel contract** + a **new raw-sensor-schema subsection** (Atlas item 5, Rule-10 — in-sprint).
- [ ] `specs/ssot-design-pattern.md` gains the EDR raw-sensor schema as the **worked anti-divergence example** (Atlas A-14 gate #4).
- [ ] New Pi-local EDR table documented (schema + ownership + per-sensor dark-ship flags) in the appropriate schema/architecture doc; any sync-coverage changes (US-411/412) documented.
- [ ] `CLAUDE.md` updated if new config keys (`pi.sensors.enabled` etc.) or commands were added.
- [ ] `regression_manifest.json` reflects the new/changed features (F-113/F-114 EDR; F-101/F-064 sync; F-096/F-098 UI).
- [ ] All spec docs reflect current state (no stale references).

**Downstream impact:** Docs only.

## 4. Functional Requirements

- FR-1: A single threaded source-reader probes ICM-20948 (`0x69`/`0x68`) + TSL2591 (`0x29`) on `/dev/i2c-1` and publishes `raw.imu.*` / `raw.light.*` samples to the dedicated-reader bus.
- FR-2: Sensor absence is non-fatal — probe, log once, skip; the process runs normally with no sensors wired.
- FR-3: A persistence subscriber writes IMU/light samples to a versioned **Pi-local** SQLite table (`drive_id` NULL-when-no-drive stamped explicitly; `schema_version` stamped), defined from a single `src/common/` source; **no server/sync this phase** (deferred to F-115).
- FR-4: All EDR functionality ships dark behind **per-sensor flags** (`pi.sensors.imu.enabled` / `pi.sensors.light.enabled`, each requiring `pi.bus.enabled`); flags OFF ⇒ zero behavioral change, `realtime_data` byte-identical to the pre-bus path.
- FR-5: Server gains `power_log` + `startup_log` tables; Pi sync coverage pushes both idempotently with reconnect catch-up.
- FR-6: `drive_counter` mirror is fixed so the server's `last_drive_id` tracks the Pi.
- FR-7: Idle `connection_log` / `sync_history` growth is materially reduced; `sync_history` timestamps are single-timezone UTC.
- FR-8: Post-reboot timestamp writers flag clock-unsynced rows rather than writing drifted time as truth.
- FR-9: Two new carousel cards (LTFT trend, power-mode badge) render against the Sprint-49 dashboard runtime, honest-instrument styled.

## 5. Non-Goals (Out of Scope)

- **F-112 (ECMLink datastream feasibility spike)** — ECMLink isn't installed; out this sprint (pending Atlas confirm).
- **F-115 (EDR display surfaces / event-vault triggers / on-Pi triggers + raw-sensor SERVER sync)** — later phase; this sprint is reader + **Pi-local** persistence only. Per Atlas, raw-sample server sync is explicitly an F-115 concern (with a downsample/event-window policy reusing the same `src/common/` schema).
- **F-061 (drop battery_health legacy SOC columns)** — **blocked**: depends on F-060 (SOC% wiring) being merged + prod-validated first. Deferred; groom F-060 ahead of it.
- **Physically wiring the sensors** — the CIO does this on his schedule; the connect-when-wired drill (US-410) runs then.
- **The hardware/ops half of F-080** (RTC coin-cell replacement, timesyncd ordering config) — tracked as action-items, not sprint code.
- **No drive drills** — bench validation only.

## 6. Design Considerations

- **Bus model is settled:** topics are `raw.<source>.<channel>`; `Sample` is a frozen envelope with `source`/`driveId`/`seq`; subscribers run on their own threads with per-QoS bounded queues. Sensor channels are purely additive — no change to `raw.obd.*`.
- **Honest-instrument carousel convention** (from Sprint 49): never green-when-stale; unknown states render as "unknown," not a confident wrong value. Applies to US-415/416.
- **SSOT design directive:** US-416 consumes the existing power-mode provider; it must not introduce a second mode-acquisition path.

## 7. Technical Considerations

- **Atlas's gate is APPROVED** (2026-06-30); the design shape is locked. The remaining dependency is his **ADR** (concrete table DDL, bus message frame/encoding, per-channel cadence numbers, `architecture.md` prose) — a **CIO sit-down deliverable** produced next. US-409's literal columns + the persist-cadence constant finalize when the ADR lands; everything else is groomable now.
- **Golden-master discipline (F-110):** the OBD `realtime_data` write path must remain byte-identical; the EDR work is strictly additive and flag-gated. US-410 enforces this with the existing regression.
- **Verify-first items (US-413, US-414):** prior backoff/cadence work may have already fixed some idle-chatter; re-query the live Pi and close-with-evidence rather than re-fixing. The Pi may be off wall-power at points — coordinate the re-query window with the CIO.
- **Sync conventions:** US-411/412 follow the B-076 schema-FK + sync-batch conventions and the `battery_health_log` sync pattern.
- **Serial dispatch ordering:** Sprint 49 (carousel + DTC) merges to `dev` before Sprint 50 dispatches, so US-415/416 have the carousel shell available.

## 8. Success Metrics

- EDR reader + persistence build green and bench-pass with **no sensors wired**; connect-when-wired drill documented for the CIO.
- `realtime_data` golden-master regression: **0 byte differences** flag-OFF and OBD-only.
- Server `power_log` / `startup_log` populated post-sync; `drive_counter.last_drive_id` matches Pi.
- Idle-soak: `connection_log` + `sync_history` growth materially reduced (or closed-as-already-healthy with evidence); `sync_history` rows single-timezone.
- Two new carousel cards render correctly in fixture/DOM tests.

## 9. Open Questions

1. ✅ **RESOLVED (Atlas)** — raw samples are **Pi-local only** this phase; server sync deferred to F-115.
2. ✅ **RESOLVED (Atlas)** — **per-sensor flags** `pi.sensors.imu.enabled` / `pi.sensors.light.enabled`, each requiring `pi.bus.enabled`.
3. **(US-411)** `power_log` volume strategy — raw-every-poll vs sampled/state-change-only? (Table grows fast.) Decide at story time.
4. **(Spool, US-415)** Exact LTFT source — which PID in `realtime_data` (or a derived table)? Confirm before build.
5. **(Resize)** US-413 is a deliberate 4-item batch — accept as one story, or split the TZ fix (F-079) out? Decide at `/resize-sprint`.
6. **(Atlas ADR / CIO sit-down)** Concrete EDR table DDL + per-channel persist cadence numbers + bus message frame — needed before freeze; not blocking grooming.

---

## Action Items (NOT sprint stories — ops/hardware, per dev-only sprint scope)

- **AI-1 (F-080 ops half):** Check the Pi RTC coin-cell; replace if dead. Verify `systemd-timesyncd` runs early enough on boot (ordering/config). CIO + ops.
- **AI-2 (US-410 acceptance):** Physically wire the ICM-20948 + TSL2591, then run the connect-when-wired drill to close the EDR acceptance. CIO's schedule.
