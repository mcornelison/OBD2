# Post-Drive Anomaly Engine — Design

| Field    | Value                                                              |
|----------|--------------------------------------------------------------------|
| Date     | 2026-05-21                                                         |
| Author   | Spool (Tuning SME)                                                 |
| Status   | Design — awaiting CIO sign-off before writing-plans handoff        |
| Theme    | Sub-thread A of broader brainstorm (post-drive analytics)          |
| Scope    | V1.0 MVP (3 detectors fully wired) → V1.0 Full (9 detectors) → V2+ |
| Branch   | sprint/sprint41-bugfixes-V0.27.17 (work targets V0.29+ post chain) |

---

## 1. Overview + Scope

### What we're building

A post-drive anomaly engine that runs server-side after every drive's `drive_summary` is computed, scans the drive's raw `realtime_data` against per-detector rules, classifies events into severity tiers, persists them in `anomaly_log`, computes a per-drive letter grade, and surfaces results in two places: a terse Pi parked-mode tile and a server-side CLI detail view.

### V1.0 MVP (3 detectors, fully wired end-to-end)

**Rationale**: the V0.27.7 → V0.27.16 false-pass class (3 sprints, same bug shipping three times) cost too much to repeat. Shipping 9 detectors before the end-to-end plumbing is proven would re-litigate that exact lesson. MVP-first vertical slice covers the entire architectural surface (data → compute → DB → UI tile → server view → grade → recompute) with 3 representative detectors. Remaining 6 are mechanical adds.

MVP-3 detectors:

1. **Knock retard** (4-tier safety; fixed thresholds + context gate) — exercises 4-tier safety severity path + Drive 11 baseline lookup + load-band context gate
2. **Coolant temperature** (4-tier safety; fixed thresholds + Spool-rule downgrade) — exercises fixed-threshold safety + Spool-rule override mechanism
3. **LTFT drift** (3-tier drift; statistical + Spool-rule upgrade) — exercises hybrid baseline math + 3-tier drift severity + Spool-rule lean-asymmetry upgrade

### V1.0 Full (deferred — characterized only)

Same architecture, mechanical adds once MVP plumbing is proven:
4. Battery voltage (safety / fixed)
5. IAT heat-soak (safety / fixed)
6. STFT drift (drift / statistical)
7. Timing-advance drift (drift / statistical)
8. MAF voltage drift (drift / statistical)
9. Idle stability (drift / statistical)

### V2+ (out of scope for this spec)

- **Real-time alerts during driving** — B-088 GEM-3 (different surface)
- **Ollama narrative generation** — V0.34+ horizon per CIO A3 2026-05-14
- **Cross-drive trend detection beyond rolling-5** — sub-thread C (predictive)
- **Two-pass overnight batch re-classification** — V2 enhancement
- **Acknowledgment / dismissal UI** — schema reserves `acknowledged_at` column; no UI in v1
- **HTML server-side detail view** — v1 stays CLI; HTML deferred to B-052 territory
- **Maintenance-domain anomalies** (oil interval, fluid changes) — sub-thread B
- **Data-integrity anomalies** (BT-drop gaps, sync inconsistencies) — Tester lane

### Constraints

- B-104 architectural shift in force: server is analytics authority; Pi is mirror consumer
- Sprint 41 / V0.27.17 must land first (provides `drive_summary` + `drive_statistics` server-side compute paths to ride)
- US-355 deploy-context drive simulator from Sprint 41 is the structural integration-test gate (no synthetic seam mocks)
- Targets V0.29+ per the 2026-05-14 phasing (Phase-2 engine protection)
- No new PIDs required for v1 — all 3 MVP detectors run on PIDs already captured (TIMING_ADVANCE, COOLANT_TEMP, LONG_FUEL_TRIM_1, ENGINE_LOAD, RPM, VEHICLE_SPEED)

---

## 2. Detector Inventory (MVP-3, fully specified)

### MVP-1: Knock Retard

| Field | Value |
|---|---|
| **PID source** | `TIMING_ADVANCE` (0x0E) — derived: `knock_retard = baseline_timing(rpm_band, load_band) - observed_timing` |
| **Method** | Fixed Spool thresholds + Spool-rule override for context gating |
| **Severity tiers** | 4-tier safety (CIO A6 locked 2026-05-14) |
| **Baseline source** | Drive 11 mean timing per (rpm_band × load_band) — authoritative knock-retard reference per knowledge.md |
| **Context gate** | Only fires when `ENGINE_LOAD ≥ 50%` (low-load decel-retard is closed-throttle noise, not knock) |
| **Tier thresholds** | NORMAL: <5° pull · ALERT: 5–10° (yellow + single chime) · WARNING: 10–15° (orange + triple chime) · STOP-DRIVING: >15° (red flashing + continuous chime) |
| **Sample window** | ≥3 consecutive samples (~3s on K-line cadence) to filter single-tick OBD anomalies |
| **Known-good test cases** | Drive 11 = NORMAL (baseline) · Drive 15 ~20s pull at 91–100% load, 12–18° timing = NORMAL (matches Drive 11 envelope) · Drive 18 98% load / 3937 RPM peak = NORMAL |
| **Known-bad simulated** | 8° sustained pull at 70% load + 3500 RPM warm = ALERT |

### MVP-2: Coolant Temperature

| Field | Value |
|---|---|
| **PID source** | `COOLANT_TEMP` (0x05) |
| **Method** | Fixed Spool thresholds + Spool-rule downgrade (no statistical component — head gasket failure mode is absolute) |
| **Severity tiers** | 4-tier safety |
| **Baseline source** | Spool knowledge.md hard limits (4G63 head bolt stretch + MLS gasket clamp loss above 220°F / 104°C) |
| **Context gate** | Skip first 5 min of drive (cold-start warmup); skip cold-start if `coolant_temp_at_start < 30°C` |
| **Tier thresholds** | NORMAL: <96°C · ALERT: 96–100°C · WARNING: 100–104°C · STOP-DRIVING: >104°C (220°F+) |
| **Sample window** | ≥60s sustained above threshold (single-sample sensor glitch filtered) |
| **Spool-rule override** | If `speed == 0` AND `elapsed_above_threshold_sec < 600` → downgrade one tier (idle heat-soak signature; benign on 4G63) |
| **Known-good test cases** | Drive 18: 92°C max = NORMAL · Drive 15: 97°C max during idle heat-soak (speed=0, <10 min) = ALERT downgraded to NORMAL by Spool-rule |
| **Known-bad simulated** | 105°C sustained 60s while moving = STOP-DRIVING |

### MVP-3: LTFT Drift

| Field | Value |
|---|---|
| **PID source** | `LONG_FUEL_TRIM_1` (0x07) — drive-aggregate avg |
| **Method** | 2σ statistical (hybrid baseline) + Spool-rule lean-asymmetry upgrade |
| **Severity tiers** | 3-tier drift |
| **Baseline source** | Hybrid: Drive 11 mean ± std_dev AND rolling-5 prior drives |
| **Context gate** | None at drive-aggregate level (per-drive average is the comparable unit) |
| **Tier thresholds** | NORMAL: within both Drive 11 ±2σ AND rolling-5 ±2σ · WATCH: outside one of the two envelopes · INVESTIGATE: >3σ from Drive 11 anchor (boiling-frog escape) |
| **Sample window** | Drive-aggregate avg; minimum 200 LTFT samples in drive (otherwise UNKNOWN — no row written) |
| **Spool-rule override** | `event.observed_value >= 2.0` (lean side) → upgrade to WATCH even when stats said NORMAL (lean = detonation risk on stock-turbo 4G63) |
| **Rolling-5 semantic** | "5 drives chronologically prior to current drive." If <5 prior drives exist, use available (min 3). If <3 prior drives exist, anchor-only against Drive 11 with `spool_rule_id="stat:anchor_only_fallback_thin_history"` |
| **Known-good test cases** | Drive 17 LTFT avg -0.58 = NORMAL · Drive 18 LTFT avg -1.65 = NORMAL · Drive 14 LTFT avg -3.36 = WATCH (Drive 11 anchor ~2.9σ — outside 2σ envelope but below 3σ INVESTIGATE threshold; rolling-5 thin at drive 14 fires the "outside one envelope" rule) |
| **Known-bad simulated** | LTFT avg +5.0 (lean) = WATCH from Spool-rule, regardless of statistical envelope |

### V1.0 Full — Deferred 6 (characterized; full spec at expand-time)

| # | Detector | Class | Method | Trigger |
|---|---|---|---|---|
| 4 | Battery voltage | Safety / 4-tier | Fixed | ALERT: <12.0V sustained 30s charging-on · STOP: <11.5V |
| 5 | IAT heat-soak | Safety / 4-tier | Fixed | ALERT: IAT-ambient delta >40°C sustained 5 min with no recovery |
| 6 | STFT drift | Drift / 3-tier | 2σ statistical | WATCH: STFT not centering when LTFT stable |
| 7 | Timing-advance drift | Drift / 3-tier | 2σ statistical | WATCH: timing under-load drifts >2σ from Drive 11 per bucket |
| 8 | MAF voltage drift | Drift / 3-tier | 2σ statistical | WATCH: MAF/MAF-g/s ratio drifts per RPM bucket (sensor health proxy) |
| 9 | Idle stability | Drift / 3-tier | 2σ statistical | WATCH: RPM std-dev at idle when warm drifts >2σ from baseline |

---

## 3. Architecture + Data Flow

### Compute location

Server-side. Per B-104 architectural principle: Pi emits canonical events; server is sole analytics authority. Anomaly compute is a sibling of US-350 `drive_summary_compute` — same trigger, parallel module structure, runs immediately after `drive_summary_compute` for the same drive_id.

### Data flow

```
┌───────────────────────────── Pi (chi-eclipse-01) ──────────────────────────────┐
│                                                                                 │
│  OBD-II live capture  ──► realtime_data (SQLite)                                │
│                              │                                                  │
│  drive boundary events ──► drive_summary (Pi event-log fields only:             │
│                              drive_start_timestamp, ambient_temp_at_start_c,    │
│                              starting_battery_v, data_source)                   │
│                              │                                                  │
│              Pi sync client ─── HTTP POST /api/v1/sync ───────────────────────► │
│                                                                                 │
│  Pi sync RECEIVES server response payload:                                      │
│              ◄── updated_drive_summaries (grade_letter + grade_reason)          │
│              ◄── new_anomaly_log_rows                                           │
│                              │                                                  │
│                              ▼                                                  │
│  Pi-local mirror tables (read-only consumers of server-authoritative data)      │
│                              │                                                  │
│                              ▼                                                  │
│  Pi parked-mode carousel cell renders from Pi-local mirror (offline-capable)    │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────── Server (chi-srv-01) ───────────────────────────────────┐
│                                                                                 │
│  /api/v1/sync handler ─► raw realtime_data + Pi event-log fields persisted     │
│                              │                                                  │
│  Compute trigger (US-350 path, extended):                                       │
│    1. drive_summary_compute(drive_id)     [US-350; Sprint 41]                  │
│    2. anomaly_compute(drive_id)           [NEW — V1 MVP scope]                  │
│         ├── reads realtime_data for the drive                                   │
│         ├── reads Drive 11 baseline tables                                      │
│         ├── reads rolling-5 prior drives' drive_statistics                      │
│         ├── reads spool_rules/rules.yaml registry                               │
│         ├── runs 3 MVP detectors                                                │
│         ├── applies rule overrides                                              │
│         ├── computes drive_score → grade_letter                                 │
│         ├── writes anomaly_log rows (with spool_rule_id traceability)           │
│         └── updates drive_summary.grade_letter + grade_reason                   │
│                              │                                                  │
│  Sync response builder includes computed drive_summary + new anomaly_log rows   │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                  On-demand recompute CLI
                  (parallel to US-352 backfill path):
                  python -m server.cli.recompute_anomalies --drive 14
                  python -m server.cli.recompute_anomalies --range 11-20
```

### Module layout

Server-side:
```
src/server/analytics/
├── drive_summary_compute.py        # Sprint 41 US-350 — existing
├── drive_statistics_compute.py     # Sprint 41 US-351 — existing
├── anomaly_compute.py              # NEW — orchestrator
├── detectors/
│   ├── __init__.py                 # Detector registry
│   ├── base.py                     # Detector ABC + DetectionResult dataclass
│   ├── knock_retard.py             # MVP-1
│   ├── coolant_temp.py             # MVP-2
│   └── ltft_drift.py               # MVP-3
├── spool_rules/
│   ├── __init__.py
│   ├── registry.py                 # Loads + validates rules.yaml at startup
│   └── rules.yaml                  # Human-editable rule + config registry
├── baselines/
│   ├── __init__.py
│   ├── drive_11_anchor.py          # Drive-11 (rpm_band × load_band → timing) lookup
│   └── rolling_window.py           # rolling-5-prior-drives baseline computation
└── helpers.py                      # Existing — computeBasicStats, classifyDeviation
```

CLI:
```
src/server/cli/recompute_anomalies.py     # NEW — mirrors US-352 shape
src/server/cli/show_drive_anomalies.py    # NEW — server-side detail view (v1)
```

Pi-side (minimal — Pi is read-only consumer):
```
src/pi/display/screens/anomaly_tile.py    # NEW — parked-mode carousel cell renderer
src/pi/obdii/database_schema.py           # UPDATE — add anomaly_log mirror table + drive_summary grade columns
src/pi/obdii/sync_client.py               # UPDATE — consume new fields in sync response payload
```

### Schema deltas

**`anomaly_log` table** (server + Pi mirror) — base columns exist; add:
- `spool_rule_id VARCHAR(64) NULLABLE` — comma-separated chain of rules that fired (e.g., `"stat:2sigma_drive11_anchor,spool.coolant.idle_heatsoak_downgrade"`)
- `context_rpm_band VARCHAR(16) NULLABLE` — `"idle"` / `"cruise"` / `"midload"` / `"wot"`
- `context_load_band VARCHAR(16) NULLABLE` — `"low"` / `"mid"` / `"high"` / `"peak"`
- `context_warm BOOLEAN NULLABLE` — `TRUE` after coolant > 70°C
- `acknowledged_at DATETIME NULLABLE` — reserved for v2 (not used in v1)

**`drive_summary` table** (server, Pi mirror via sync) — add:
- `grade_letter VARCHAR(4) NULLABLE` — `"A"` / `"A-"` / `"B+"` / `"B"` / `"B-"` / `"C"` / `"D"`
- `grade_reason VARCHAR(255) NULLABLE` — one-line human-readable summary

**Spool-rule registry** — `src/server/analytics/spool_rules/rules.yaml`:
- Human-editable file under git
- Owned by Spool per `.github/CODEOWNERS`
- Loaded + validated at server startup
- Recompute reads current file state

### Sync-back wiring (new infrastructure)

Existing Pi → server sync is one-way push. We extend the existing `POST /api/v1/sync` endpoint with a richer response payload:

```
POST /api/v1/sync
Request:  { Pi-side raw rows since last_sync_id }
Response: {
    accepted: { ... },                          # existing
    updated_drive_summaries: [ ... ],           # NEW — server-computed analytics rows
    new_anomaly_log_rows: [ ... ]               # NEW — events server detected
}
```

Pi sync client consumes the response and upserts into Pi-local mirror tables. Mirror tables are **read-only** on the Pi (write code path retired by B-104). Pi parked-mode UI reads only from local mirror.

Consequences:
- **Offline-capable**: car parked at curb with no WiFi still displays last-drive grade + anomaly count from Pi-local mirror.
- **Eventually-consistent**: server analytics changes (rule update + recompute) propagate to Pi at next successful sync. Brief stale display is acceptable.

### On-demand recompute

```
python -m server.cli.recompute_anomalies --drive 14
python -m server.cli.recompute_anomalies --range 11-20
python -m server.cli.recompute_anomalies --since 2026-05-01
```

Idempotent: same raw data + same `rules.yaml` state + same detector code = same `anomaly_log` + same grade. Re-running over already-computed drives produces zero diff.

When Spool updates `rules.yaml` (new domain rule from knowledge.md → YAML entry), on-demand recompute re-flags history. This is the **MrSpool override surface**: Spool's knowledge becomes runtime policy without a Ralph code dispatch.

---

## 4. Engine Grade + Severity Rubric

### Two-stage math

**Stage 1** — per-event scoring: `event_score = tier_points × signal_weight`

| Severity | Tier set | Points |
|---|---|---|
| NORMAL | both | 0 (no row written) |
| WATCH | 3-tier drift | 1 |
| INVESTIGATE | 3-tier drift | 3 |
| ALERT | 4-tier safety | 2 |
| WARNING | 4-tier safety | 5 |
| STOP-DRIVING | 4-tier safety | 15 |

**Signal weights:**

| Detector | Weight | Rationale |
|---|---|---|
| Knock retard | 3.0 | Catastrophic failure mode; #1 engine-damage signal |
| Coolant temperature | 2.5 | Head gasket; high cost, high recoverability if caught early |
| Battery voltage | 2.0 | (V1 Full) Charging system / battery health |
| IAT heat-soak | 2.0 | (V1 Full) Intercooler / heat-cycle risk |
| Timing-advance drift | 1.5 | (V1 Full) Baseline-side complement to knock-retard |
| LTFT drift | 1.0 | Drift signal; informational, not safety-critical alone |
| MAF voltage drift | 1.0 | (V1 Full) Sensor health proxy |
| STFT drift | 0.8 | (V1 Full) Secondary to LTFT |
| Idle stability | 0.8 | (V1 Full) Drivability, not safety |

**Stage 2** — per-drive grade: `drive_score = sum(event_scores in drive)`

| `drive_score` | Grade | Meaning |
|---|---|---|
| 0 | **A** | Clean drive, all detectors normal |
| 0.1 – 1.0 | **A-** | One minor drift watch |
| 1.1 – 2.5 | **B+** | One drift signal flagged, otherwise clean |
| 2.6 – 5.0 | **B** | Multiple watches OR one alert |
| 5.1 – 8.0 | **B-** | Notable issue — investigate |
| 8.1 – 15.0 | **C** | Real problem — prompt action |
| 15.1+ | **D** | Severe |
| ANY single STOP-DRIVING | **D** | Override regardless of score |

### Validation against existing drives

| Drive | Detectors that hit | drive_score | Grade | grade_reason |
|---|---|---|---|---|
| 11 | none (IT is baseline) | 0 | **A** | "Authoritative baseline; all detectors normal" |
| 14 | LTFT WATCH (anchor ~2.9σ, just below INVESTIGATE; rolling-5 thin) | 1.0 | **A-** | "1 watch: LTFT drift -3.36 (Drive 11 anchor ~2.9σ; rolling-5 baseline thin)" |
| 15 | coolant ALERT → Spool-rule downgrade → NORMAL | 0 | **A** | "Clean drive; coolant 97°C idle heat-soak correctly classified benign by Spool rule" |
| 17 | none | 0 | **A** | "Clean cold-start drive; LTFT -0.58 well within baseline" |
| 18 | none | 0 | **A** | "Clean drive; near-WOT pull, LTFT -1.65 within envelope, knock-retard in Drive 11 envelope" |

Grade math reproduces Spool's PM-note grading judgment. Locked as regression fixtures (Section 6 testing).

### Edge cases

| Case | Behavior |
|---|---|
| <3 MVP detectors could run (PIDs missing whole drive) | `grade_letter = NULL`, `grade_reason = "insufficient data: only N detectors ran"` |
| <3 prior drives for LTFT rolling-5 baseline | Fall back to Drive 11 anchor-only; row gets `spool_rule_id="stat:anchor_only_fallback_thin_history"` |
| Drive < 60 seconds total (idle / instrument check) | Skip anomaly compute; `grade_letter = NULL`, `grade_reason = "micro-drive (<60s); analytics skipped"` |
| Drive 11 itself | Grade always = **A** by spec (it IS the baseline; can't be anomalous against itself); documented exception |
| Re-grade on rule update | Idempotent: same raw + same rules = same grade |

### Config knobs in `rules.yaml`

```yaml
grade_thresholds:
  A: [0, 0]
  A-: [0.1, 1.0]
  B+: [1.1, 2.5]
  B: [2.6, 5.0]
  B-: [5.1, 8.0]
  C: [8.1, 15.0]
  D: [15.1, null]

signal_weights:
  knock_retard: 3.0
  coolant_temp: 2.5
  ltft_drift: 1.0
  # V1 Full additions land here

tier_points:
  WATCH: 1
  INVESTIGATE: 3
  ALERT: 2
  WARNING: 5
  STOP_DRIVING: 15
```

Spool re-balances rubric via PR to `rules.yaml` → on-demand recompute → history re-graded. No Ralph code dispatch needed.

---

## 5. Spool-Rule Override Mechanism

### Purpose

Statistical math is half the answer. Domain wisdom is the other half. Without an override mechanism, every knowledge.md update requires a Ralph code change. With `rules.yaml`, Spool publishes a rule + on-demand recompute re-flags history.

### Rule schema

```yaml
rules_version: 1

rules:
  - id: spool.coolant.idle_heatsoak_downgrade
    detector: coolant_temp
    description: |
      Stationary heat-soak under 10 minutes is benign on the 4G63.
      Thermal mass holds the gauge briefly above operating band when
      idle; only sustained-while-moving cases are engine-damage risk.
    triggers_on:
      severity_emitted: [ALERT, WARNING]
    conditions:
      - field: context.speed_mph
        op: eq
        value: 0
      - field: event.elapsed_above_threshold_sec
        op: lt
        value: 600
    action: downgrade
    action_param: 1
    rationale: |
      Drive 15 observed 97°C idle heat-soak; Spool classified benign
      in PM notes 2026-05-15. This rule encodes that judgment.

  - id: spool.ltft.lean_asymmetry_upgrade
    detector: ltft_drift
    description: |
      LTFT positive (lean) is more dangerous than negative on a stock
      turbo — lean = detonation risk under boost.
    triggers_on:
      severity_emitted: [NORMAL]
    conditions:
      - field: event.observed_value
        op: gte
        value: 2.0
    action: upgrade
    action_param: 1
    rationale: |
      Stock-turbo no-wideband no-knock-log 4G63: LTFT crossing positive
      by 2.0% or more is a leading lean signal. Detonation risk under
      boost elevates faster than statistical envelope catches it.

  - id: spool.knock.low_load_suppress
    detector: knock_retard
    description: |
      Closed-throttle decel timing retard is not knock. Detector already
      gates load >= 50%; this is belt-and-suspenders + spool_rule_id
      traceability if a sample slips through.
    triggers_on:
      severity_emitted: [ALERT, WARNING, STOP_DRIVING]
    conditions:
      - field: context.load_band
        op: in
        value: [low]
    action: suppress
    rationale: |
      Documented for traceability — spool_rule_id appears in any
      anomaly_log row where this fires, so we can audit any
      gate-bypass case.
```

### Field grammar

| Namespace | Fields | Source |
|---|---|---|
| `event.*` | `severity_emitted`, `observed_value`, `deviation_sigma`, `elapsed_above_threshold_sec` | Detector output before rule pass |
| `context.*` | `rpm_band`, `load_band`, `warm`, `speed_mph`, `elapsed_sec_from_drive_start` | Computed during detector run |
| `drive.*` | `duration_seconds`, `row_count`, `drive_id`, `ambient_temp_at_start_c`, `starting_battery_v`, `data_source` | `drive_summary` lookup |
| `baseline.*` | `anchor_mean`, `anchor_sigma`, `rolling_mean`, `rolling_sigma`, `rolling_window_size` | Baseline lookup for drift detectors |

### Operators

`eq`, `neq`, `lt`, `lte`, `gt`, `gte`, `in`, `not_in`. All conditions AND-ed. For OR semantics, write multiple rules with same action.

### Actions

| Action | Effect |
|---|---|
| `upgrade` | Bump severity up N tiers (e.g., NORMAL → WATCH) |
| `downgrade` | Bump severity down N tiers (e.g., ALERT → NORMAL) |
| `suppress` | Don't count toward drive_score, but **write sentinel row** with `severity=SUPPRESSED` + `spool_rule_id` for audit trail |
| `flag` | Severity unchanged; attach `spool_rule_id` for traceability only |

### Resolution order

1. Detector emits candidate event with statistical-only severity (`spool_rule_id = "stat:..."`). Call this the **current severity**.
2. Rules with matching `detector` evaluated in **file order**.
3. For each rule:
   - `triggers_on.severity_emitted` is matched against the **current severity at that point in the evaluation chain** (not the original statistical severity). So a rule can fire on a severity another rule already produced.
   - If the rule matches `triggers_on` AND all `conditions`: rule fires; action modifies current severity; rule id appended to chain.
   - If not: rule skipped.
4. After all rules evaluated, the final current severity is the outcome.
5. Every rule that fired during evaluation is in the `spool_rule_id` chain (comma-separated, in fire order).
6. Final severity decides whether the row is written + what `tier_points` contributes to `drive_score`.

This semantic means **rules can cascade** — Spool can author a rule that further upgrades a previously-upgraded event. In practice this is rare; for V1 MVP each rule targets a different starting state. Documented explicitly so the behavior is unambiguous when needed.

### Validation + loading

- Server startup loads `rules.yaml`, validates against pydantic schema
- Invalid file → **server fails to start** with explicit error pointing to offending rule (no silent fallback)
- Each rule's `detector` validated against `detectors/__init__.py` registry
- Test suite asserts: file loads, every rule has required fields, every condition references valid field/operator combo

### Governance

- `rules.yaml` under git; PRs to this path require Spool sign-off via `.github/CODEOWNERS`:
  ```
  src/server/analytics/spool_rules/* @spool
  ```
- `rules_version` field supports future schema migration
- Recompute CLI logs `rules_version` it ran against → version mismatch warns (not errors)

### Edge cases

| Case | Behavior |
|---|---|
| Condition references field that's null for this event | Rule SKIPS (treats as non-match), does not error |
| Two rules apply (upgrade + downgrade) | Last-applicable wins (file order); both rule ids in `spool_rule_id` |
| Rule fires but action produces same severity | Row still written; rule traced; useful for audit |
| `rules.yaml` updated mid-run | New rules don't apply until next recompute; current run uses snapshot loaded at process start |
| YAML syntax error | Server start fails; no degraded mode |

---

## 6. Surfaces + Testing

### Pi parked-mode tile (carousel cell)

One carousel cell. Two within-tile states: SUMMARY (default) + DETAIL (tap to expand).

**SUMMARY state — clean drive example:**

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  LAST DRIVE          Drive #18 · 41m · warm cont │
│                                                  │
│              ┌────┐                              │
│              │  A │                              │
│              └────┘                              │
│                                                  │
│  Clean drive — all detectors normal              │
│  knock-retard envelope ok · LTFT -1.65           │
│  coolant peak 92°C                               │
│                                                  │
│  ───────────────────────────────────             │
│         3 detectors ran · 0 anomalies            │
│                                                  │
│                                    [tap detail]  │
└──────────────────────────────────────────────────┘
                  480 × 320 OSOYOO
```

**SUMMARY state — anomaly present:**

```
┌──────────────────────────────────────────────────┐
│                                                  │
│  LAST DRIVE          Drive #14 · 8m · errand     │
│                                                  │
│              ┌─────┐                             │
│              │ A-  │                             │
│              └─────┘                             │
│                                                  │
│  1 watch: LTFT drift -3.36                       │
│  (Drive 11 anchor 3.0σ, rolling-5 thin)          │
│                                                  │
│  ───────────────────────────────────             │
│         3 detectors ran · 1 watch                │
│                                                  │
│                                    [tap detail]  │
└──────────────────────────────────────────────────┘
```

**DETAIL state — tap to expand:**

```
┌──────────────────────────────────────────────────┐
│  ‹ back            ANOMALIES — Drive #14         │
│                                                  │
│  ┌─ WATCH ─────────────────────────────────────┐ │
│  │ LTFT drift     -3.36  ← drive avg           │ │
│  │ vs Drive 11   3.0σ above envelope           │ │
│  │ vs rolling-5  baseline window thin (N=3)    │ │
│  │ rule:  stat:3sigma_anchor_only_escape       │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  (no other events)                               │
│                                                  │
│                                       [tap back] │
└──────────────────────────────────────────────────┘
```

**Auto-snap behavior**: if `grade == "D"` (any STOP-DRIVING), tile auto-snaps to red flashing with offending event highlighted. Overrides carousel last-shown cell. Aligned with B-086 GEM-1 alert behavior.

**Refresh / staleness**:
- Tile reads Pi-local mirror (populated by sync-back per Section 3)
- Header shows `last_synced` timestamp; if > 1 hour since last sync, dim grade letter + show "(stale, waiting for sync)"
- After engine-off + sync round-trip completes, mirror is fresh; tile updates on next render cycle

### Server-side detail view (v1 = CLI)

```bash
# View a specific drive's anomalies + grade
python -m server.cli.show_drive_anomalies --drive 14

# Grade trend across recent drives
python -m server.cli.show_drive_anomalies --range 11-20 --grade-only

# Filter by severity
python -m server.cli.show_drive_anomalies --since 2026-04-01 --severity WATCH,WARNING

# JSON output for downstream tooling (future MrSpool feed)
python -m server.cli.show_drive_anomalies --drive 14 --json
```

**Sample output:**

```
DRIVE 14 — 8.4 min · errand · 13:30 CDT 2026-05-13

  Grade: A-   "1 watch: LTFT drift -3.36"
  Detectors: 3 ran (knock_retard, coolant_temp, ltft_drift)

  ANOMALIES:
  ─────────────────────────────────────────────────────────────
  WATCH    ltft_drift     observed=-3.36   σ_anchor=3.0
                          baseline_drive11=-1.81 ± 0.52
                          rolling5_window=N=3 (thin)
                          spool_rule_id: stat:3sigma_anchor_only_escape
                          detected: drive-aggregate
  ─────────────────────────────────────────────────────────────

  drive_score: 1.0
```

v1 = CLI only. Server-side HTML deferred to B-052 territory. CLI output IS the structured view; copyable into PM notes; JSON output feeds future Ollama / MrSpool pipeline.

### Testing approach

**Unit tests** (per detector):
- Synthetic fixture tests for every severity tier (NORMAL through STOP-DRIVING)
- Boundary tests at tier edges (95.9°C → NORMAL, 96.1°C → ALERT)
- Spool-rule trigger tests (97°C + speed=0 + duration<10min → downgrade fires)
- Context-gate tests (knock-retard at low-load → suppressed)
- Missing-PID tests (detector returns NULL gracefully if PID absent)

**Integration tests** (against real drives — regression fixtures):

Drives 11-20 raw data become locked regression fixtures. Test suite asserts each known drive produces expected grade + anomaly set:

```python
@pytest.mark.parametrize("drive_id,expected_grade,expected_anomaly_count", [
    (11, "A", 0),    # baseline — must always be A by spec
    (14, "A-", 1),   # LTFT WATCH (anchor ~2.9σ outside 2σ envelope; rolling-5 thin)
    (15, "A", 0),    # 97°C idle heat-soak correctly downgraded
    (17, "A", 0),    # cold-start clean
    (18, "A", 0),    # warm continuation clean
])
def test_anomaly_compute_against_real_drive(drive_id, expected_grade, expected_anomaly_count):
    ...
```

Any future change to detector code or `rules.yaml` that breaks these fixtures = test failure = explicit Spool re-baseline sign-off required.

**Idempotency tests**:
- Run `anomaly_compute` twice on same drive → zero diff in `anomaly_log`
- Locks in B-104 idempotency invariant

**Spool-rule lifecycle tests**:
- Load every rule in `rules.yaml` (asserts schema validity)
- Validate each rule's `detector` exists in registry
- Trace test: every `anomaly_log` row produced in fixtures has `spool_rule_id` populated (never NULL)
- Conflict test: two rules upgrade + downgrade same condition → assert last-wins behavior

**Deploy-context integration** (rides US-355):

Once Sprint 41's US-355 drive simulator harness lands, `anomaly_compute` runs in that harness against real Pi SQLite + server MariaDB, end-to-end, with the actual deploy artifact. This is the **structural answer to the V0.27.7 → V0.27.16 false-pass class** — no synthetic seam mocks, real DBs, real sync, real compute. MVP-3 ships through this gate, not unit tests alone.

---

## 7. V1.0 MVP Acceptance Criteria

- [ ] 3 detector modules implemented + unit-tested (knock_retard, coolant_temp, ltft_drift)
- [ ] `rules.yaml` registry loads + validates at server startup; example rules for each MVP-3 detector
- [ ] `anomaly_compute(drive_id)` wired into US-350 sync trigger; runs after `drive_summary_compute`
- [ ] On-demand recompute CLI `recompute_anomalies` works for `--drive`, `--range`, `--since` modes
- [ ] Server detail view CLI `show_drive_anomalies` produces clean output (text + `--json`)
- [ ] `anomaly_log` schema extensions (`spool_rule_id`, context fields, `acknowledged_at` reserved) deployed via Sprint 41-style migration
- [ ] `drive_summary` schema extensions (`grade_letter`, `grade_reason`) deployed
- [ ] Sync-back response payload includes `updated_drive_summaries` + `new_anomaly_log_rows`
- [ ] Pi sync client consumes payload + upserts into local mirror tables
- [ ] Pi parked-mode anomaly tile renders SUMMARY + DETAIL states; auto-snaps on grade=D
- [ ] Drive 11-20 regression fixtures pass (locked grades match Spool PM-note judgment)
- [ ] Idempotency test: recompute over any drive produces zero diff
- [ ] Spool-rule trace test: every `anomaly_log` row has non-null `spool_rule_id`
- [ ] US-355 drive-simulator integration: MVP-3 ships through harness, not unit tests alone
- [ ] CODEOWNERS gate: `rules.yaml` changes require Spool sign-off
- [ ] Documentation: rules.yaml has comments per rule; `docs/anomaly-engine-operator-guide.md` covers CLI usage + rule-authoring

## 8. Open Questions / Followups

1. **B-074 MAP PID dependency for knock-retard accuracy**: V1 MVP uses ENGINE_LOAD for load-band context. MAP would give richer load signal. Not a blocker; MAP can be added to load-band computation when B-074 lands without changing detector contract.
2. **Drive-summary `data_source` filter**: should anomaly compute include `data_source='simulator'` drives (e.g., test fixtures synced from CI runs)? Recommend NO for production grade computation; YES for unit tests. Wire via a `--include-source` CLI flag.
3. **Re-baseline Drive 11 procedure**: if Drive 11 is ever superseded (e.g., post-ECMLink V3 install), how does the anchor swap? Recommend explicit `baseline_anchor_drive_id` config in `rules.yaml`; migration story for v2.
4. **Drives 6/7/8 backfill**: pre-mod shelf drives are not in current V1 fixture scope (V0.27 baselines start at drive 11 per Sprint 41 backfill scope drives 12-20). Spool's Sprint 41 audit flag FLAG-2 suggested widening US-352 to drive 11; if accepted, V1 fixtures might add drive 11. If pre-mod-shelf backfill (drives 6/7/8) lands later, integrate as v1.1 fixtures.
5. **Pi UI scope overlap with B-086**: This spec defines a parked-mode anomaly tile that overlaps with B-086 GEM-1 (warnings-first quiet UI carousel). Coordinate at PRD-grooming time to ensure single carousel cell ownership and consistent tap/auto-snap behavior.

## 9. Related Backlog Items

- **B-086** GEM-1 warnings-first quiet UI — carousel pattern this tile lives in
- **B-088** GEM-3 knock-retard real-time alert — sibling surface (real-time vs post-drive)
- **B-089** GEM-4 Spool engine grade per drive — this spec IS the implementation of this gem
- **B-093** GEM-8 baseline-relative anomaly detection — this spec implements the per-drive form
- **B-094** GEM-9 MrSpool RAG digital twin — V3.0 narrative layer consumes `--json` output
- **B-104** Server-side analytics authority — architectural foundation this spec rides
- **US-355** Sprint 41 deploy-context drive simulator — structural integration test gate
- **B-074** MAP PID — V1 Full enhancement for richer load context

---

## Spec Provenance

- 2026-05-21 — Brainstorm session with CIO via Spool. Six design sections approved one-at-a-time. MVP-first scope reframe ratified at CIO request. Spec drafted to this file.
- Source materials: prior gem brainstorm `offices/pm/inbox/2026-05-14-from-spool-display-brainstorm-gems-filtered.md`; Sprint 41 sprint.json + B-104 backlog item; existing server schema `src/server/db/models.py:546-702`; existing `helpers.py:57-103` outlier methodology; Drives 11-20 raw data + Spool PM-note grades.
