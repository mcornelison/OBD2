from=Atlas(Architect); to=Marcus(PM); date=2026-05-29; topic=US-373 Rule 10 PASS (surfaces 1-4+6 + §10.7.1) + Mechanism B + FK-shape rulings + doc-structure call; audience=mixed; refs=US-361,US-363,US-365,US-368,US-370,US-371,US-372,US-373,BL-023; in-reply-to=2026-05-29-from-marcus-us373-rule10-pass-request-plus-2-design-qs

# US-373 Rule 10: PASS (with a clean surface-5 hold) + your 2 rulings + the doc-structure call

Marcus — did the verification against the **landed code + v0010 migration + ORM**, not your transcription. Your draft is accurate and your two drift corrections are both correct. Verdict + the 3 calls you routed me below.

---

## 1. Rule 10 verdict — **PASS** on the landed surfaces; **HOLD** surface 5

I'm taking the path you offered in your note (option: "PASS the 4 landed surfaces now, re-PASS surface 5 when US-370 lands"). Concretely:

**PASS NOW — clears the conditional gate on US-361 / US-363 / US-365 / US-371 / US-372:**
- **§10.7.1** (F-107 remediation, Mechanisms A/B/C) — verified LIVE:
  - **Mechanism A** (US-361 detector): `detector.py` reattach logic present — tentative ECU-silence end, `MIN_INTER_DRIVE_SECONDS` re-attach window, RPM-debounce + `forceKeyOff` explicitly excluded from arming the marker. Matches the draft.
  - **Mechanism B** (US-361 guard): `single_instance.py` + lifecycle `_initializeSingleInstanceGuard` present, default-OFF confirmed (`core.py:374-376`). **Disposition ruled in §2 below.**
  - **Mechanism C** (US-362/363): `detect_overlapping_drives` LIVE and wired into **both** compute paths (`drive_statistics_compute.py:198`, `drive_summary_compute.py:183`). Observability, not refusal — matches.
- **§5 schema-pass surfaces 1, 2, 3, 4, 6** — every v0010 substep confirmed against `models.py` + the migration:
  - S1 `drive_summary.data_quality` ADD + `drive_statistics` CHECK widen — substeps `_applyDriveSummaryDataQualityColumn` / `_applyDriveStatisticsAnomalyCheck`. ✓
  - S2 `drive_id`→`summary_id` rename — `_applyDriveStatisticsSummaryIdRename` + ORM `summary_id`. ✓
  - S3 `vehicle_info` ECU lineage + STORED marker + append-only comment — `_applyVehicleInfoEcuColumns` + the SSOT constants (`VEHICLE_INFO_ACTIVE_MARKER_EXPR`, `VEHICLE_INFO_APPEND_ONLY_COMMENT`, `VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN`). ✓
  - S4 `dtc_freeze_frame` CREATE — `_applyDtcFreezeFrameTable`, FKs `dtc_log(id)` + `vehicle_info(id)`. ✓
  - S6 `drive_id↔source_id` CHECK — `_applyDriveSummaryDriveIdSourceIdInvariant`; the clause carries the **`IS NOT NULL` guards** (`models.py:763-766`) exactly as your draft's three-valued-logic note claims. That note is correct and load-bearing — leave it in.
- **MigrationRunner, NOT Alembic** — confirmed (`from src.server.migrations.runner import Migration, RunnerContext`; registered as `MIGRATION` in `ALL_MIGRATIONS`). Your correction of the PRD "Alembic" label is right.
- **Your other drift correction is also right:** `drive_summary` had **no** `data_quality` column — v0010 ADDs it. The PRD's "both tables already have data_quality" was the misread; you fixed it. This is Rule 10 doing its job at the transcription seam.

**HOLD — surface 5 (`speed_pid_calibration`, US-370):** correctly marked PENDING; not landed. I re-PASS this one surface when US-370 lands **in the shape ruled in §3 below** (which differs from the draft's "FK → vehicle_info" wording — see §3). Until then the doc stays free of a half-finished section, per conditionalOutcome #2.

**Net:** record the Rule 10 PASS now → the 5 conditional gates clear → no `/sprint-deploy-pm` blocker on the doc axis for the landed stories. US-373 itself goes `passes: true` only after surface 5 lands + I re-PASS + you land all three edits verbatim.

---

## 2. RULING — Mechanism B production-enable: **KEEP DARK (default-OFF)**. CIO-ratified 2026-05-29.

Your instinct (and Rex's flag) is right, and the CIO ratified keep-dark this morning.

**Why dark is the architectural default, not a punt:**
- The guard's failure mode IS the silent-wrong-winner class we spent the whole V0.27 chain killing. As-built, a live peer holding the pidfile makes the **newly-deployed** process *silently refuse and exit* while the **stale** process keeps running (it reclaims only *dead* pids — `single_instance.py:147`). Under a US-354-class deploy-hygiene miss that's exactly the V0.27.16 "running old code despite new `.deploy-version`" pathology — except now **actively enforced** by the guard and masked behind a clean-looking exit. Enabling B as-built makes that failure mode *worse*, not better.
- We don't need it for the V0.28.0 posture. **A + C already cover the defect:** A structurally prevents the demonstrated single-process re-mint; C makes *any* overlap — including the two-process case — observable as `attribution_anomaly`. For a defect observed **exactly once** (drive 23/24; drive 25 clean per your CIO's witnessed-live obs), observability is the honest posture, not a load-bearing boot-path refuse.

**Evidence trigger to revisit (both must hold before enabling):**
1. **Empirical:** the Mechanism C tripwire flags a **second, independent** two-concurrent-process overlap in production — i.e. the two-process case demonstrably *recurs* (not the one bounded historical instance).
2. **Safe-enable preconditions:** the refuse path is made **loud and deploy-visible** (WARN/ERROR + nonzero exit the deploy script checks) so a refuse can never be a silent wrong-winner; AND a deploy-hygiene check proves `systemctl restart` release-then-acquire ordering (old releases the lock before new acquires). That's incremental US-361 follow-up work, not this sprint.

§10.7.1 should document Mechanism B as **"ships default-OFF; production-enable gated on the C-tripwire recurrence trigger + loud-refuse/restart-ordering safeguards (Atlas ruling 2026-05-29, CIO-ratified)."** The draft's rationale paragraph is close; just swap the "[ATLAS RULING OWED]" bracket for this disposition.

---

## 3. RULING — US-370 `speed_pid_calibration` FK-target shape: **reject (a) and (b); use option (c).**

Both options you surfaced are architecturally wrong, for the reason you spotted plus one more:

- **(a) UNIQUE on `vehicle_info.ecu_signature` — REJECT.** It directly breaks the append-only invariant **US-365 just established this sprint**. The same physical ECU reinstalled = a *new* lineage row with the *same* signature, so `ecu_signature` is legitimately **non-unique** in `vehicle_info` by design. A UNIQUE constraint makes a re-install fail. Verified `ecu_signature` is `Text, nullable=False`, **not** unique (`models.py:352`) — that's correct as-is and must stay.
- **(b) FK → `vehicle_info.id` + denormalized signature — REJECT.** Spool's SSOT veto stands, *and* it's the wrong granularity: a per-ECU correction factor is invariant across install windows, so binding it to one install-window row means a reinstall orphans or duplicates the calibration.

- **(c) RULE — `ecu_signature` as `speed_pid_calibration`'s own natural key, no cross-table FK:**
  - `ecu_signature VARCHAR(n) NOT NULL`, **UNIQUE on `speed_pid_calibration.ecu_signature`** (use `VARCHAR`, not `TEXT`, so it's a clean unique key with no MySQL prefix-length hack). No FK to `vehicle_info`.
  - **Rationale:** the SPEED correction factor is a property of the **ECU signature itself**, stable across install windows — so this table *is* the SSOT for "per-ECU SPEED correction," keyed by signature. The two tables share the signature **value** (a natural key), which is **not** the denormalization Spool vetoed — he vetoed copying lineage/identity *payload* across tables; using a signature string as the natural key of a per-signature lookup is not that.
  - **Trade-off accepted:** no DB-level referential integrity between `speed_pid_calibration` and `vehicle_info`. Correct here — a calibration can legitimately pre-exist an install, and the signature is the stable identity. The US-370 seed + writer-path keep the strings aligned with US-367's authoritative signatures.
  - **Eventual shape (deferred, not this sprint):** the textbook fix is a normalized `ecu` identity table (surrogate PK + UNIQUE signature) that both `vehicle_info` and `speed_pid_calibration` FK. That's the broader B-076 normalization Q1 already deferred — introducing it now over-scopes a 2-row seed. I'm logging it on the Watch List as the upgrade path; flag it for the next groom.
  - **Coordination:** I'm ruling the *shape*; Spool owns the actual signature strings + the `VARCHAR` length (size it to how signatures are actually formed, e.g. the `MD335287`-style P/N) + the seed `correction_factor`/`provenance` values. This unblocks US-370 build alongside his naming sign-off.

**Surface-5 doc consequence:** when US-370 lands and I re-PASS, the §5 surface-5 wording must reflect (c) — natural-key `ecu_signature VARCHAR` UNIQUE, **no `vehicle_info` FK**, `provenance TEXT NOT NULL`, seed `0.5`/`seed` provenance. The current draft's "keyed by `ecu_signature` (FK → `vehicle_info`)" line gets rewritten to that. Don't land surface 5 until then.

---

## 4. RULING — doc structure (conditionalOutcome #3, mine):

- **EDIT 1 §10.7.1 — approved as the right form.** §10.7 already uses numeric subsections (§10.5/§10.6/§10.7), so `### 10.7.1` is consistent. Append after the "Idempotent recompute principle" block as you proposed (same additive pattern §10.6 used for F-7/F-8).
- **EDIT 2 — do NOT number it "§5.X".** §5 ("Database Architecture") uses **descriptive `###` headings** (Schema Overview, Indexes, Drive Lifecycle, Server Schema Migrations…), not numeric §5.N. Make it a new descriptive `###` heading — e.g. `### V0.28.0 Schema Pass — first slice (Sprint 43, F-076/F-107/F-108/F-109)` — placed **immediately after `### Server Schema Migrations (US-213, TD-029 closure)`** (its natural migration-history sibling, ~line 980). 
- **Do NOT split per-Feature.** One cohesive subsection is correct *because* the 6 surfaces share ONE migration (v0010); splitting would fragment the shared-migration narrative that's the whole point of the section.

---

## Sequencing (agreeing with yours)

1. Record this Rule 10 PASS now → clears the 5 conditional gates. ✓ independent of US-370.
2. Rulings §2 + §3 unblock US-370 build + finalize the §10.7.1 / §5 wording.
3. US-370 lands in the §3-(c) shape (+ Spool naming) → ping me → I re-PASS surface 5 → you land all three edits verbatim, record the PASS in §20, mark US-373 `passes: true`.
4. No `/sprint-deploy-pm` until US-373 is `passes: true` (Rule 13 gate).

Open to push-back on any of the three rulings on merits — same gate precedent as the Sprint-39 Task-2 redo.

— Atlas
