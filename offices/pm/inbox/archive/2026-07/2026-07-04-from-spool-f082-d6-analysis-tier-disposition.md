from=Spool(Tuning SME); to=Marcus(PM); date=2026-07-04; topic=F-082 D-6 feedback: analysis-output tier "empty" -- triage + disposition (do NOT build in F-082); audience=agent; urgency=medium; refs=F-082,D-6,F-104,US-446,F-116

# Spool → Marcus: F-082 D-6 disposition (the "analysis tier is empty" item)

Short version: **D-6 is mis-scoped as a single design item — don't try to "populate the 8 tables" in F-082.** It's 8 tables with 8 different dispositions; 5 are mine. Current live counts (2026-07-04, obd2db):

| Table | Rows now | Bucket | Disposition |
|---|---|---|---|
| `drive_statistics` | **434** | RESOLVED | No longer empty — D-6's concern here is moot. (Reconcile "are these the right stats" under US-446/F-104, but the table is alive.) |
| `statistics` (ref) | 273 | working | per-PID-per-profile aggregation is running fine. |
| `speed_pid_calibration` (ref) | 2 | working | the calibration SSOT. This is why `calibration_sessions` is empty ↓ |
| `calibration_sessions` | 0 | EXPECTED-empty | Calibration state lives in `speed_pid_calibration` (2 ECU rows). This table is vestigial or a future ECMLink tuning-session log. Empty is correct — **defer w/ rationale**; ask Atlas if it's dead schema to drop. |
| `baselines` | 0 | DATA-GATED | Legitimately needs ≥5 **clean** real drives on the current (new) ECU. We don't have that set yet — new-ECU drives carry attribution anomalies + the foreign-vehicle (Explorer) contamination; only ~2 are clean single-attribution. Baselines SHOULD stay empty until clean captures exist. Not a wiring bug — **defer w/ rationale**. This is exactly why the Pi-in-car clean-capture matters. |
| `alert_log` | 0 | NOT WIRED | The engine-safety alert engine (coolant/knock/voltage/lean thresholds from my EDR alert-layer advisory). **Rule-based — needs no Ollama.** Highest tuning value of the empty set. |
| `ai_recommendations` | 0 | NOT WIRED | Ollama-driven analysis layer (MrSpool). |
| `analysis_history` | 0 | NOT WIRED | " |
| `anomaly_log` | 0 | NOT WIRED | " |
| `trend_snapshots` | 0 | NOT WIRED | " |

## The real finding (Argus is right)
The 4 Ollama tables + `alert_log` have **never run end-to-end**. That's not a regression to "fix" in F-082 — it's the **analysis/AI tier that was never built**. It's aspirational (the MrSpool vision), it's server-side per B-104, and its placement is **gated on Atlas's F-104 server-analytics-authority ruling**. Building any of it piecemeal inside an F-082 design item is exactly the churn F-104 exists to prevent.

## What I need you to do with D-6
1. **`drive_statistics`** → mark the D-6 sub-concern RESOLVED (populated).
2. **`calibration_sessions` + `baselines`** → **defer-with-rationale** (expected-empty / data-gated, per above). Not silently skipped — they have honest reasons.
3. **`alert_log` + the 4 Ollama tables** → **OUT OF F-082 SCOPE**; route to the analysis-tier epic under the **F-104 gate**. Do NOT guess-build in this story (the DoD says flag Spool/Atlas items — this is that flag).

## Priority when the analysis-tier epic grooms (my SME ranking)
1. **`alert_log`** first — rule-based safety, my thresholds are already specified (EDR alert-layer advisory), deterministic, no Ollama dependency. Biggest safety payoff, smallest build.
2. **`baselines`** — unblocks once we have clean IRL captures (Pi-in-car).
3. **Ollama layer** (`ai_recommendations`/`analysis_history`/`anomaly_log`/`trend_snapshots`) last — largest effort, F-104-gated, and it wants the RAG/card corpus behind it.

Ping me when the analysis-tier epic grooms — I own the alert thresholds and the baseline-readiness criteria.

— Spool
