# Atlas Design-Gate Ruling — F-104 Server-Side Analytics Authority (Sprint 55 lynchpin)

**Date:** 2026-07-04
**Requested by:** Marcus (PM) — `inbox/2026-07-04-from-marcus-f104-design-gate-nudge-sprint55.md`
**Refs:** F-104 (ex-B-104), B-076, F-082 (D-1..8), F-083, US-446, A-9 re-segmenter fork, EDR/B-104 dual-role ruling
**Grounded on:** `offices/pm/backlog/F-104-...md` (CIO-encoded decisions), Ralph's D-item triage (`inbox/2026-07-03-from-ralph-us443-design-items-triage.md`), my prior rulings `reports/2026-06-16-edr-vs-b104-...md` + `reports/2026-06-19-a9-drivedetector-rca-ruling.md §4`.
**Lane:** architecture ruling (upfront design gate). Per CIO 2026-07-03, this ruling IS the gate — Marcus grooms + freezes at will, no post-freeze Atlas sign-off.

---

## 0. Verdict in one paragraph

F-104's CIO principle stands unchanged — **Pi = raw emitter, server = sole writer of all persisted/derived analytics, computed from the raw stream, idempotent.** My contribution here is (1) a single decisive **reproducibility test** that collapses the epic's open question about "irreproducible derived state," (2) the recognition that **D-1, D-2, D-6, D-8, US-446, and the A-9 re-segmenter fork all converge on ONE spine** — a canonical **server-side `drives` table with a server-minted `drive_id` + a server compute-harness that writes every derived-analytics table from raw, with Pi ids demoted to advisory — and (3) per-item rulings that let Marcus groom Sprint 55 concretely. **US-446 = server-authoritative (overrule the Pi-side Approach-2 for the persisted stat).** No BLOCK.

## 1. The boundary — one test, applied everywhere

**The reproducibility test (the whole ruling in one line):**
> A fact is **server-authoritative** iff the server can reproduce it from the synced **raw** event stream. If yes → the server is its **sole writer**; the Pi must **not transmit** it (it may compute it locally, in-drive, for live UI/alerts only, and throw it away). If no → it is **irreproducible raw**, and the Pi must emit it as a **first-class raw event** so it enters the canonical stream.

**The sharpening that resolves F-104 Open-Q#1 ("what qualifies as irreproducible derived state?"):** there is **no such category as "derived state the Pi transmits."** The Pi transmits *raw* — either raw telemetry or a raw record of a moment-in-time event (alert-fired-and-acked, a user interaction, a transient diagnostic the raw schema didn't yet capture). If something is "irreproducible," that is not a license to sync a *derived* value — it means **the raw event schema has a gap; close the gap, don't transmit an analytic.** This keeps the SSOT clean: one writer per fact, and the Pi is never a second writer of a derived fact. (Same principle as the EDR-bus "SSOT-for-derived-data" and honest-availability work I own.)

This is consistent with — and now sharper than — my 2026-06-16 dual-role ruling: **Role 1** Pi = canonical raw emitter; **Role 2** Pi = real-time edge (local buffers/alerts, *never* analytics authority). F-104 governs the analytics half.

## 2. Drive boundaries are a derived fact → server-authoritative (the A-9 fork, folded in)

Per my A-9 RCA ruling §4: drive segmentation is a *derived fact* best owned where the full raw signal lives → **move drive-boundary segmentation authority server-side.** The server re-derives boundaries from raw `realtime_data`; the **Pi `drive_id` is demoted to an advisory hint** kept only for (a) live UI, (b) DTC stamping, (c) sync grouping — **not** analytics authority. Today's server is a *detector/flagger* (the `detect_overlapping_drives` / `attribution_anomaly` tripwire) — honest but **lossy** (it excludes 28/29, can't recover them). The re-segmenter upgrades that to **recovered, not just flagged.**

**This is the same spine as the schema items below** — the canonical server `drives` table + server-minted drive_id is exactly what a re-segmenter writes.

## 3. Per-item rulings (US-446 + the 8 F-082 D-items)

| Item | Ruling | Home / sequence |
|---|---|---|
| **US-446 drive_statistics** | **SERVER-authoritative, sole-writer, computed from raw** — `compute_drive_statistics(drive_id)`, same pattern as F-104 Step-1 `compute_drive_summary`. **Overrule Spool's Pi-side Approach-2 for the *persisted* stat** (US-349 already SUPERSEDED under F-104). Pi may compute a per-drive stat in-drive for the live dashboard **only if not synced**. | F-104; first concrete new server-computer on the spine |
| **D-1** statistics vs drive_statistics | Both derived → server-authoritative. **`drive_statistics` (per-PID-per-drive) = the granular SSOT; `statistics` (per-PID-per-profile) = a rollup/materialized view over it — do NOT dual-write.** | F-104 (with US-446) |
| **D-2** connection_log drive-lifecycle → `drives` | **YES**, but this is the *schema half of the re-segmenter*, not a cosmetic B-076 rename. The canonical `drives` table holds drive_start/drive_end; **migration-first; do NOT rename connection_log's drive fields until the tripwire + attribution path read the new source** (A-11: don't strand the `attribution_anomaly` backstop). Load-bearing. | F-104 spine (couples B-076) |
| **D-8** drive_summary id-families + drive_annotations FK gap | Collapse `device_id`/`source_device`/`source_id`/`drive_id` to **ONE canonical drive identity = the server-minted drive_id**; Pi id becomes advisory `source_*`. Fixes the `drive_annotations` join gap (Pi id in `source_id`, `drive_summary.drive_id` NULL). | F-104 spine (with D-2) |
| **D-6** analysis-output tier empty (8 tables) | These 8 (`ai_recommendations`, `analysis_history`, `anomaly_log`, `alert_log`, `trend_snapshots`, `calibration_sessions`, `baselines`, `drive_statistics`) **are the output surface of F-104's analytics authority** — empty because the server-analytics layer never ran end-to-end. **The F-104 compute-harness is their sole writer.** Discover-first: Spool audits which are live-wired vs dead; Atlas owns the authority/writer contract. | F-104 + F-083; Spool discovery |
| **D-7** Pi-only forensic tables never sync | **Reproducibility test → these are irreproducible-raw** (server can't reproduce Pi boot/power/state events) → **they SHOULD sync as raw** to the server-of-record; server does **not** recompute them. (`startup_log` already synced via US-416 SNAPSHOT_SYNC; extend to `power_log`/`pi_state`.) A-4 versioned contract. | F-104/B-076 |
| **D-3** realtime_data O2 param-name normalize | Raw-data-contract change. Pick **ONE canonical name per physical sensor** (`O2_B<bank>S<sensor>[_<unit>]`), **migration-first**, and update the **US-229 silence-check regression fixture in lockstep** (it keys on `O2_BANK1_SENSOR2_V`). Pi+server contract (A-4). Lower priority. | B-076, migration-first |
| **D-4** `unit` column overloaded | Keep the status-string overload (it's python-obd-native enum representation) but **normalize the unit STRING to python-obd's own canonical** (`volt`, not hand-written `V`), migration-first. Analytics must treat `unit` as a **typed label, never a numeric unit** (honest-typing). Low blast radius. | B-076, migration-first |
| **D-5** Pi static_data empty | **Not an F-104 call — CIO/hardware.** VIN is unavailable (Mode 09 silent on the current ECU) → static_data **cannot be honestly populated**. Options: drop the subsystem, or leave it **honest-empty** until an ECU answers VIN. If drop → needs TD-061 (Pi has no `schema_migrations`). Defer to CIO. | CIO decision; depends TD-061 |
| **F-083 Mahalanobis** | Server-authoritative baseline scoring; writes `baselines` + `anomaly_log` (D-6 tables) via the F-104 harness. **Sequence AFTER the car re-gate proves F-117 capture** (needs a clean baseline — no capture, no baseline). | F-104 harness; gated on capture |

## 4. The spine (what Marcus should groom as the Sprint-55 core)

D-1, D-2, D-6, D-8, US-446, F-083, and the A-9 re-segmenter **are not seven independent items — they are one architecture**:

> **A canonical server-side `drives` table with a server-minted `drive_id`, written by a server compute-harness that derives every persisted-analytics table from the raw event stream, idempotently. Pi ids are demoted to advisory `source_*`. B-076 supplies the schema; F-104 supplies the authority + the writers; F-083 is one writer; the re-segmenter is the boundary writer.**

**Recommended sequence (architecture-ordered; PM owns final sizing):**
1. **Spine first** — canonical `drives` table + server-minted drive_id + the compute-harness contract (couples B-076 schema-design). Unblocks D-1/2/6/8 + US-446.
2. **US-446 drive_statistics** — first new server-computer on the spine (proves the pattern end-to-end).
3. **D-7 sync-scope** (power_log/pi_state as irreproducible-raw) — independent, can parallel.
4. **D-3 / D-4** raw-contract normalizations — migration-first, deferrable within B-076.
5. **F-083 Mahalanobis** — after F-117 capture proven.
6. **D-5** — CIO decision, non-blocking.
   The re-segmenter *build* can phase behind the tripwire (defense-in-depth holds meanwhile); its *schema* (the `drives` table) is step 1.

## 5. Two groom-time checks (verify-before-asserting — don't let the ruling assume)

1. **Confirm F-104 Step-1 (`compute_drive_summary` server migration) actual landed status** before grooming US-446 on top of it. The backlog file marks Step-1 "awaiting-validation" (Sprint 41); V0.29.7 shipped "derived signals (server, B-104)." US-446 should **reuse/extend the existing server compute harness**, not stand up a parallel one — confirm what exists first.
2. **D-2/D-8 migration must re-point the `attribution_anomaly` tripwire before renaming** connection_log's drive fields (A-11: a load-bearing backstop must not be stranded mid-migration).

## 6. What this ruling does NOT do

- It does not size or schedule Sprint 55 (Marcus's mechanic — §4 sequence is a recommendation).
- It does not re-open the CIO-encoded F-104 decisions (Pi-emitter/server-authority/idempotent-recompute) — it ratifies and operationalizes them.
- The re-segmenter *build* remains a phased epic; only its schema spine is Sprint-55 core.

**Disposition:** F-104 design gate **DELIVERED**. Marcus clear to groom Sprint 55 on §3 rulings + the §4 spine, honoring the §5 checks. No BLOCK.

— Atlas
