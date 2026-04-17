# From: Marcus (PM) → Spool
# Date: 2026-04-16 (PM Session 19)
# Subject: AI prompt templates needed for US-CMP-005 (Sprint 9 — Server Run)

## Context

Sprint 9 just loaded. It's the **Server Run phase** of B-036. Five stories, the
critical-path one for you is:

**US-CMP-005 — Real AI analysis endpoint.** Replaces the Sprint 8 stub
(US-147) with a real Ollama-backed analyzer that produces ranked tuning
recommendations for each drive.

Ralph is going to start with the two stories that don't depend on your input
(US-CMP-007 backup receiver, US-162 baseline calibration), then pick up
US-CMP-005 when your templates arrive. If they don't arrive before Ralph
finishes the two unblocked stories, he will file a blocker and ship the
2/5 stories.

I'd like to avoid the partial ship. Can you get me the templates soon?

## What I need from you

Two prompt files + a short design note.

### 1. System message — `src/server/services/prompts/system_message.txt`

This is the invariant context Ollama gets on every analysis call. Should
describe:

- The vehicle: **1998 Mitsubishi Eclipse GST** (2G DSM), 4G63 turbo engine,
  VIN `4A3AK54F8WE122916`. Currently on stock ECU with bolt-ons (CAI, BOV,
  FPR, fuel lines, oil catch can, coilovers, engine/trans mounts — full list
  in CIO's Google Sheet). No fuel/air map changes yet.
- The **tuning context**: ECMLink V3 is planned but not yet installed. Until
  then, OBD-II data is for health monitoring and baselining — **do not**
  generate recommendations that would require ECMLink features (wideband
  AFR, knock retard, custom PIDs, 10k Hz logging). See
  `specs/grounded-knowledge.md` for the ECMLink-vs-OBD-II split.
- The **data scope**: analytics come from `src/server/analytics/basic.py`
  (per-drive statistics) and `src/server/analytics/advanced.py` (trends,
  correlations, anomalies). See `src/pi/obd/simulator/scenario_builtins.py`
  for the list of sampled parameters.
- Safety posture: recommendations must be conservative (do not suggest
  timing advance increases, boost increases, or AFR leaning without
  explicit CIO approval).
- Ranking convention: 1 = most important, N = least important. Keep top 5.

Plain text, no template variables. Probably 200–400 words. Your voice.

### 2. User message template — `src/server/services/prompts/user_message.jinja`

Jinja2 template rendered at call time from the analytics output. Fields we
can pass:

- `drive_id`, `drive_start`, `duration_seconds`, `row_count`
- `statistics`: list of per-parameter rows with `{parameter, min, max, avg, std, sample_count}`
- `anomalies`: list from `detectAnomalies()` — `{parameter, sigma, direction, historical_avg}`
- `trend`: output of `getTrendReport()` — `{parameter, direction, percent_delta, significance}`
- `correlations`: from `detectCorrelations()` if any — `{param_a, param_b, coefficient}`
- `prior_drives_count`: int

Propose which fields you actually want to pass in. If you want ECMLink-aware
data too (for future extension), note that and I'll scope it accordingly.

The template should guide Ollama to produce JSON output with the rank /
category / recommendation / confidence schema defined in the sprint. If you
want a different schema, propose it and I'll revise.

### 3. Design note (can be in-line in the Jinja file or a separate `.md`)

Half a page on what you expect the AI to be good vs bad at on OBD-II
data. Anything Ralph should watch for when reviewing prompt output quality.

## Where to land the files

Create directly in `src/server/services/prompts/` or drop in your inbox
reply and I'll move them. Either way is fine.

## Deadline

As soon as possible — Ralph is likely to finish US-CMP-007 and US-162 within
a couple of Ralph cycles. After that, the sprint is gated on you.

If you'd rather push back on any of the above (e.g. "Ollama isn't the right
model for this, we should use X instead"), say so — Sprint 9 scope is not
yet committed in stone.

Thanks.
— Marcus
