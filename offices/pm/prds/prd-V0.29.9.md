---
sprint: 55
version: V0.29.9
status: draft
createdAt: 2026-07-04
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev
epic: E-002, E-OPS
feature: F-104, B-076, F-075, F-082
theme: F-104 Server-Side Analytics Authority spine -- canonical drives + server drive_id + compute-harness + schema normalization
validationMode: BENCH ONLY (DB introspection + INFORMATION_SCHEMA + idempotency re-run + tripwire-fixture + compute-vs-raw equivalence tests) -- NO drive drills; F-083 held post-capture
selectedStories: [US-448, US-449, US-450, US-451, US-452, US-453, US-454, US-455, US-456, US-457]
---

# PRD: Sprint 55 / V0.29.9 — F-104 Server-Side Analytics Authority spine

| Field | Value |
|---|---|
| Sprint | 55 |
| Version | V0.29.9 (patch on the V0.29 chain) |
| Branch | `sprint/sprint55-V0.29.9` (forks from `dev`) |
| Validation | **BENCH ONLY** — DB introspection, idempotency re-runs, tripwire fixtures, compute-vs-raw equivalence. No drive drills. |
| Story range | US-448 … US-457 (10 stories) |
| Design authority | **Atlas F-104 ADR** `offices/architect/reports/2026-07-04-f104-server-analytics-authority-design-gate-ruling.md` — the binding architecture. Every story implements it; do NOT deviate. |

## 1. Introduction / Overview

Atlas's F-104 ruling reframed 7 scattered items (US-446, D-1/2/6/7/8, F-083, the A-9 re-segmenter) into **one architecture**: a canonical server-side `drives` table + **server-minted `drive_id`**, written by a **single idempotent server compute-harness** that derives every persisted-analytics table **from synced raw**; Pi ids demote to advisory `source_*`. **B-076 = schema · F-104 = authority + writers.**

**The boundary rule (applies to every item):** a fact is *server-authoritative* iff the server can reproduce it from synced raw → server sole-writer, Pi does NOT transmit it (may compute locally for live UI, thrown away). If irreproducible → it's raw → Pi emits it as a first-class raw event. **No "derived state the Pi transmits."**

**Held out of this sprint:** F-083 (Mahalanobis) — needs clean post-capture baselines (the car re-gate must prove F-117 first) → Sprint 56. The analysis/AI tier (`alert_log` + the 4 Ollama tables) — a separate epic on top of this authority → Sprint 56+ (Spool's priority: `alert_log` first).

## 2. Goals

- Establish the **canonical `drives` table + server-minted `drive_id`** as the single drive-identity SSOT.
- Make the **server compute-harness the sole writer** of persisted analytics, deriving from raw (idempotent) — **reusing the existing V0.29.7 harness, not a parallel one**.
- Move `drive_statistics` (US-446) to server-authoritative on the spine.
- Normalize the schema debt (D-1/D-3/D-4/D-7) migration-first; resolve D-5.
- **Zero regression** to the attribution-anomaly tripwire or existing drive attribution.
- No drive drills.

## 3. User Stories

> **STRICT DEPENDENCY CHAIN for the spine:** US-448 (identity schema + tripwire) → US-449 (harness) → US-450 (drive_statistics on it) → US-451 (id-family collapse). US-452–456 are independent schema/data items. **Two non-negotiable Atlas groom-checks, baked into the ACs below:** (1) **reuse the existing V0.29.7 server derived-signals harness** — do NOT stand up a parallel one; (2) **re-point the `detect_overlapping_drives` attribution tripwire to the new identity BEFORE any `connection_log` rename** (A-11).
>
> **All code stories:** `ruff` clean in-loop; `mypy` (strict) is the PM/integration gate (not installed in Ralph's env). Every migration is **forward-only** and **deployed-AND-verified via `INFORMATION_SCHEMA`**.

---

### US-448: Canonical `drives` table + server-minted `drive_id` (identity SSOT; D-2 schema half) — MIGRATION-FIRST
**Description:** As the system, I want a server-owned canonical `drives` table with a server-minted `drive_id` as the single drive-identity SSOT, so all analytics reference one authoritative identity instead of Pi-minted ids.

**Acceptance Criteria (specific):**
- [ ] New server table `obd2db.drives` (forward-only migration `v00NN`) with columns: server-minted **`drive_id` INTEGER PK AUTOINCREMENT** (the SSOT identity), `source_device VARCHAR`, `source_drive_id INTEGER NULL` (the Pi's advisory id — nullable), `start_time DATETIME`, `end_time DATETIME NULL`, `data_source`, `data_quality`. Exact column set confirmed against the F-104 ADR §"drives" at story time.
- [ ] The `drives` rows are derived **from synced raw** (`connection_log` lifecycle spans + RPM>threshold per the existing DriveDetector semantics) by the server harness (US-449) — **NOT written by the Pi**; the Pi's `drive_id` is recorded only as advisory `source_drive_id`.
- [ ] **TRIPWIRE RE-POINT (load-bearing, do FIRST): `detect_overlapping_drives`** (the `data_quality='attribution_anomaly'` backstop) is re-pointed to the new `drives` identity **before** any `connection_log` column is renamed/removed. **Verify:** a fixture with a known overlapping-drive pair still trips `attribution_anomaly` against the new schema (regression test), and the tripwire references `drives`, not the old path.
- [ ] Deployed AND verified: `SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='drives'` returns the expected columns; the tripwire fixture test passes.
- [ ] `ruff` clean; mypy at PM-integration.

**Downstream impact:** New identity SSOT; the spine foundation. US-449/450/451 build on it. Touches the attribution tripwire (backstop must not regress).

---

### US-449: Server compute-harness = sole writer, derives-from-raw, idempotent (F-104 authority) — deps US-448
**Description:** As the system, I want ONE server compute-harness to be the sole writer of persisted analytics, deriving every such table from synced raw idempotently, so there is a single source of authority.

**Acceptance Criteria (specific):**
- [ ] **REUSE the existing V0.29.7 server harness** (`src/server/analytics/` — the derived-signals/`compute_drive_summary` path from Sprint 53's US-436). **Do NOT create a parallel harness.** Confirm the exact existing entry point at story time (Atlas groom-check #1).
- [ ] The harness mints `drives` rows (US-448) + is the **sole writer** of the persisted-analytics tables it owns (drive_summary, drive_statistics, statistics, …) — **re-running it on the same raw produces byte-identical rows** (idempotent; assert by a re-run-and-diff test).
- [ ] It reads ONLY synced raw (`realtime_data`, `connection_log`, etc.) — never Pi-transmitted derived state.
- [ ] A documented "which tables the harness owns" registry (the authority manifest) so consumers know server-authoritative vs raw.
- [ ] Deployed AND verified: harness re-run on an existing drive is idempotent (0 row diffs); `ruff` clean; mypy PM-integration.

**Downstream impact:** The authority layer. US-450 registers into it. Must not double-write with any Pi path.

---

### US-450: `drive_statistics` = server-authoritative on the spine (US-446, overrules Pi-side) — deps US-449
**Description:** As Spool, I want `drive_statistics` computed server-side from raw by the harness, so it's authoritative and reproducible (not Pi-minted).

**Acceptance Criteria (specific):**
- [ ] `compute_drive_statistics` added to the US-449 harness (mirrors `compute_drive_summary`), keyed on the server `drive_id`, deriving per-drive stats from raw `realtime_data`. **Atlas OVERRULES the Pi-side Approach-2** (US-349 superseded) — the persisted stat is **server-only**.
- [ ] Pi-side compute of these stats is permitted **only if NOT synced** (live dashboard, thrown away) — no Pi→server `drive_statistics` write path.
- [ ] Excludes `data_source!='real'` (F-116 foreign-guard — drive 33 out).
- [ ] Idempotent (re-run = 0 diffs); guards zero/gap data.
- [ ] Deployed AND verified: `drive_statistics` rows computed for existing drives, keyed on server `drive_id`; `ruff` clean; mypy PM-integration.

**Downstream impact:** First computer on the spine; retires the Pi-side approach.

---

### US-451: Collapse drive-identity id-families → one server `drive_id`; Pi ids → advisory `source_*` (D-8) — deps US-448
**Description:** As the system, I want a single drive identity everywhere, so `drive_summary` id-families + `drive_annotations` FKs reference the server `drive_id`, not Pi-minted ids.

**Acceptance Criteria (specific):**
- [ ] `drive_summary` + `drive_annotations` (+ any table carrying a drive id) reference the server `drive_id` as the FK; the Pi's id is retained as advisory `source_drive_id` (nullable) — **one identity, no id-families**. Forward-only migration.
- [ ] Existing rows are back-mapped: each existing `drive_summary`/`drive_annotations` row is re-keyed to the correct server `drive_id` (via `source_device` + `source_drive_id` match), or flagged if unmappable (never silently dropped).
- [ ] Deployed AND verified: FK integrity check passes (no orphaned drive refs); a sample drive resolves one identity end-to-end.
- [ ] `ruff` clean; mypy PM-integration.

**Downstream impact:** Drive identity collapse; coordinate with US-448 (the identity source).

---

### US-452: Reconcile `statistics` (rollup/view) vs `drive_statistics` (granular SSOT) — no dual-write (D-1)
**Description:** As the system, I want `statistics` and `drive_statistics` to have clear non-overlapping roles, so there's no dual-write.

**Acceptance Criteria (specific):**
- [ ] `drive_statistics` = the granular per-drive SSOT (US-450); `statistics` = a rollup/aggregate VIEW or harness-derived rollup — **both server-derived by the US-449 harness, NEVER dual-written** (no path writes the same fact to both independently).
- [ ] Documented which is authoritative for which fact; a test asserts no independent dual-write.
- [ ] Deployed AND verified; `ruff` clean; mypy PM-integration.

**Downstream impact:** Analytics table roles; deps US-450.

---

### US-453: Extend raw-sync scope — `power_log` + `pi_state` as raw (D-7)
**Description:** As the system, I want irreproducible Pi-only forensic tables synced as raw, so the server has them (it does not recompute them).

**Acceptance Criteria (specific):**
- [ ] Reproducibility test applied: `power_log` + `pi_state` are **irreproducible raw** → they sync Pi→server as raw (via the `SNAPSHOT_SYNC` natural-key path from US-416 where TEXT-PK, or the delta path where integer-PK — confirm per table). `startup_log` is already synced (US-416) — verify, don't redo.
- [ ] The server does NOT recompute these (they're raw, not derived).
- [ ] Deployed AND verified: post-sync, server rows match Pi for both tables; idempotent.
- [ ] `ruff` clean; mypy PM-integration.

**Downstream impact:** Sync scope; server gains raw forensic tables.

---

### US-454: O2 sensor name normalization — one canonical name/sensor (D-3, migration-first)
**Description:** As the system, I want each O2 sensor to have one canonical name, so analytics don't fragment across name variants.

**Acceptance Criteria (specific):**
- [ ] One canonical name per O2 sensor (enumerate the current variants first); forward-only migration re-maps existing rows.
- [ ] **Update the US-229 fixture in lockstep** (Atlas) so tests reflect the canonical names.
- [ ] Deployed AND verified: `SELECT DISTINCT` on the O2 name column returns only canonical names; `ruff` clean; mypy PM-integration.

**Downstream impact:** `realtime_data` O2 naming; US-229 fixture.

---

### US-455: Unit-string canonicalization — `volt` not `V` (D-4, migration-first)
**Description:** As the system, I want canonical unit strings, so analytics treat `unit` as a typed label consistently.

**Acceptance Criteria (specific):**
- [ ] Canonicalize the unit STRING (e.g. `volt` not `V`); **keep the python-obd native enum overload** (do not remove the overload). Forward-only migration re-maps existing rows.
- [ ] Analytics treat `unit` as a **typed label, never a numeric** (assert no code parses `unit` numerically).
- [ ] Deployed AND verified: `SELECT DISTINCT unit` returns canonical strings; `ruff` clean; mypy PM-integration.

**Downstream impact:** Unit strings across `realtime_data`.

---

### US-456: `static_data` disposition + TD-061 (D-5, CIO-decided)
**Description:** As the CIO, I want `static_data` honestly handled — it can't hold a VIN (the ECU is Mode-09-silent).

**Acceptance Criteria (specific):**
- [ ] Per Atlas: `static_data` is NOT F-104 (CIO/hardware). Since VIN is un-gettable (Mode-09-silent on MD326328): either **drop the table** (forward-only migration; requires TD-061 filed) OR keep **honest-empty** with a documented reason. **Decide + document the choice.**
- [ ] If dropped: TD-061 filed + the drop migration deployed AND verified (table gone). If kept: a doc note why it's honest-empty.
- [ ] `ruff` clean; mypy PM-integration.

**Downstream impact:** Removes/annotates a dead table.

---

### US-457: Sprint 55 documentation sync + Rule-10 (server-authority spine)
**Description:** As the PM, I need the server-authority architecture documented.

**Acceptance Criteria (specific):**
- [ ] `specs/architecture.md` gains a **server-analytics-authority section**: the boundary rule, the canonical `drives`/server-`drive_id` SSOT, the sole-writer harness + owned-table registry, Pi-ids-as-advisory. Cross-links B-076 (schema) + F-104 (authority).
- [ ] `specs/ssot-design-pattern.md` gains the server-authority boundary as a worked example.
- [ ] `regression_manifest.json` reflects F-104/B-076 + the changed features.
- [ ] No stale references (esp. any "Pi computes/transmits derived X" prose now false).

**Downstream impact:** Docs only.

## 4. Non-Goals (Out of Scope)

- **F-083 (Mahalanobis)** — needs clean post-capture baselines (car re-gate must prove F-117 first) → Sprint 56.
- **Analysis/AI tier** (`alert_log` + the 4 Ollama tables) — a separate epic on top of this authority → Sprint 56+ (Spool priority: `alert_log` first, rule-based safety, no Ollama).
- **The A-9 re-segmenter BUILD phases** — only its SCHEMA (US-448 `drives`) lands here; the behavioral re-segmentation writer is a later phase behind the tripwire.
- **`/chain-validated`** — still gated on the two car drills (F-117 capture + Bug-3a display).
- **No drive drills.**

## 5. Open Questions (for Atlas's review)

1. **US-448 identity minting** — autoincrement server `drive_id` vs a deterministic natural-key mint? Confirm from the ADR.
2. **US-451 back-map** — any existing rows expected unmappable (pre-connection_log-era)? How to flag.
3. **Sequencing risk** — the spine (US-448→451) is a strict chain touching identity + the tripwire; confirm the 4-story split is right vs a tighter/looser cut.

## Action Items (NOT sprint stories)

- **Backlog hygiene (PM, at freeze):** file the D-item dispositions on F-082 (D-1→US-452, D-2→US-448, D-3→US-454, D-4→US-455, D-5→US-456, D-6→resolved/deferred per Spool, D-7→US-453, D-8→US-451); file **TD-061** (static_data drop) if US-456 chooses drop.
- **New epic to file (Sprint 56):** analysis/AI tier — `alert_log` (Spool's specified thresholds, rule-based) then the Ollama layer; on top of the F-104 authority.
