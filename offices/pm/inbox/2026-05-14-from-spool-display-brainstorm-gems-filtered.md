# 3.5" Display + Server-AI Brainstorm -- Spool's Gem Filter
**Date**: 2026-05-14
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine -- strategic backlog input; not sprint-urgent
**Format**: A2AL/0.4.0

---

## Context

CIO dropped 3 brainstorming docx + 1 Ollama prompt pack + 1 conversation thread + 3 UI mockup PNGs in `specs/samples/` 2026-05-14. External-AI brainstorm session re 3.5" display + GPU/Ollama use. CIO asked Spool to filter for project-alignment gems before backlog injection.

CIO directive verbatim: "extract the real gem ideas that align with your project. most are nice to have and some will never happen as they do not align with the project goals."

CIO context note: still finishing V0.27 chain validation -- drive 12+drain 18 gate -- this material is V0.28+ horizon, NOT current sprint candidate.

---

## TOP GEMS -- aligned + worth backlog entry

### GEM-1 -- warnings-first quiet UI
- screen idle by default; surfaces ONLY when something matters; Spool defines thresholds.
- aligns with project safety-first principle; aligns with "stock turbo no wideband no knock log = conservative" CIO context.
- mockup B (PNG-1) shows the right pattern -- 6 big tiles INCLUDING a dedicated alert tile that lights up red on threshold.
- Spool-side thresholds ready: coolant >104C (220F), voltage <12.0V steady, knock-retard >5deg pull from drive-11 baseline under load, IAT delta-ambient >40C heat soak no recovery.

### GEM-2 -- deterministic anomaly + Ollama explanation pattern
- already partially built: V0.27.3 US-326 drive_summary writer + V0.27.4 US-317 Ollama decouple.
- brainstorm's "evidence packet" framing aligns -- rules-first then LLM explains; never let LLM read raw rows.
- Ollama_Anomaly_Detection_Prompt_Pack.md has production-grade system prompt + 3 templates (anomaly-explain / drive-summary / ask-my-drives) -- worth lifting into our codebase as `prompts/` directory.
- JSON-mode + auditable outputs = aligned with our specs.

### GEM-3 -- knock-retard real-time alert -- SPOOL CRITICAL ADDITION
- brainstorm DID NOT mention knock retard -- they did not know our drive-11 characterization.
- thresholds (anchored on drive-11 baseline): NORMAL pull <5deg under load. ALERT pull 5-10deg. WARNING pull 10-15deg. STOP-DRIVING pull >15deg.
- requires TIMING_ADVANCE PID -- already captured. requires correlated ENGINE_LOAD -- already captured. partial coverage works today; full coverage needs B-074 MAP PID.
- this is THE most-important engine-protection alert on the screen; if only ONE alert lives in the 3.5" UI, it is this one.

### GEM-4 -- Spool engine grade per drive
- letter grade A/B/C/D + 1-line reason; surfaces post-drive as drive_summary footer.
- inputs: cumulative anomaly count + severity + thermal envelope + fueling stability + knock-retard events.
- prior precedent: Spool already grades drives in PM notes (drive 11 = "grade-A healthy"); productize the manual practice.
- low complexity; high engagement; works with existing drive_summary schema.

### GEM-5 -- MARK EVENT button
- driver-side action; bookmarks ±60sec window around press; tagged for later analysis.
- works in driving-glance UI (one big button); no distraction risk.
- backend: insert event_marker row tied to drive_id + timestamp + window_seconds; server analytics extracts the window for forensic review.
- pairs naturally with the anomaly-explain Ollama prompt.

### GEM-6 -- audio drive reports via Android Auto -- STRATEGIC
- CIO has Android Auto stereo -- existing hardware.
- post-drive: server generates TTS narrative; phone publishes as "podcast/episode" media; head unit plays via Android Auto media category (Google-supported pattern).
- sidesteps driver-distraction issue entirely; aligned with safety-first.
- big horizon -- needs Android app build + TTS pipeline -- V0.30+ candidate.
- caveat: confirm with CIO whether Android Auto integration is in-scope before sizing.

### GEM-7 -- system status tile
- shows BT link state + last sync + Pi power mode + ladder stage if applicable.
- DIRECTLY addresses the 2026-05-13 BT-no-reconnect bug (see prior Spool inbox note) -- visibility eliminates "did it capture my drive" surprise.
- small UI work; high CIO value; addressable now even before bigger UI investment.

### GEM-8 -- baseline-relative anomaly detection
- compare current drive to pre-mod baseline shelf (drives 6/7/8/11) -- not against generic thresholds.
- aligned with stock-turbo-no-wideband reality -- generic thresholds don't fit our setup.
- our existing drive_statistics table already supports per-PID baselines; need feature-extraction layer on top.
- this is the platform that GEM-2 anomaly detection runs on.

### GEM-9 -- RAG over CIO's car-specific knowledge
- load `offices/tuner/knowledge.md` + DSM service references + mod history + maintenance log into Ollama embeddings.
- enable "ask my car" Q&A: "what does this code mean on MY car?", "when did we last see voltage dip like this?".
- aligns with the LLM-as-analyst principle -- grounds answers in OUR data not training-data hallucinations.
- horizon: V0.29+; depends on Ollama embeddings infra being in place (currently we have generation but not vector-search wiring).

---

## FILTER -- ideas REJECTED -- do not backlog

### REJECT-A -- shift light / redline cue as primary display element
- 4G63 redline = 7500 RPM; on stock turbo + no knock log we should NEVER be there.
- screen feature would encourage redline behavior; conflicts with conservative-until-proven principle.
- defer until ECMLink V3 + wideband + knock log; that day = re-evaluate.

### REJECT-B -- 0-60 / 30-70 / trip timer estimates
- fun but encourages aggressive driving; same safety conflict as REJECT-A.
- not aligned with weekend-cruiser summer-car usage profile.

### REJECT-C -- boost gauge as "watch this number" tile
- needs B-074 MAP PID (not captured yet).
- even when captured, on stock TD04 + no wideband, gauge-watching encourages boost-chasing.
- safer framing: surface peak-boost-this-drive in the post-drive summary, NOT real-time on the screen.

### REJECT-D -- "Coach Mode" / "Performance Coaching" framing
- enthusiast-tuner phrasing conflicts with project framing.
- REFRAME if pursued: "drivability + efficiency coaching" -- safer surface; same data; different framing.
- only RPM-vs-throttle-efficiency and shift-point analysis are safe coaching topics on this build.

### REJECT-E -- AFR tuning recommendations / boost targets / ignition timing
- brainstorm itself flagged these as out-of-scope -- agreeing for the record.
- OBD-II telemetry is too coarse + too late; tuning belongs in ECMLink V3 with wideband + knock log.

### REJECT-F -- AAStream "mirror any app" to Android Auto
- explicit no per brainstorm itself; agreeing -- high distraction risk.

### ~~REJECT-G -- dense 8-9 tile driving UI~~ -- **RETRACTED 2026-05-14 post-CIO clarification**
- prior version misread the mockups as "all tiles visible at once" dashboard view.
- CIO clarification: each tile is 90-95% of full screen; tap rotates between tiles = CAROUSEL of focused views, NOT busy dashboard.
- carousel pattern is good UX; warnings-first still applies as a default view + auto-snap to alert tile on threshold trip.
- mockups are not set-in-stone -- treated as design seed, not final.

---

## QUESTIONS FOR PM/CIO -- need before sizing any of this

Q1: Android Auto integration -- in-scope for V0.30 horizon OR longer/deferred?
- GEM-6 audio drive reports = strategic win but big new feature surface.
- determines whether the 3.5" screen is primary driving UI (small + warnings-only) or backup UI (with Android Auto carrying the load).

Q2: 3.5" screen primary mode -- pick the two-mode contract:
- mode-1-driving = "quiet warnings-only" (GEM-1 + GEM-3 + GEM-5 button + GEM-7 status corner).
- mode-2-parked = "diagnostic tools" (DTC read/clear + sensor availability + connectivity health + last-drive grade).
- any third mode CIO wants? (passenger-operated, kiosk, etc.)

Q3: Ollama integration depth -- pick scope:
- shallow = anomaly explanation only (GEM-2; we are 60% there with US-326+US-317).
- medium = + drive-report narratives (extends GEM-2; also gates GEM-6 audio reports).
- deep = + RAG over CIO knowledge (GEM-9; biggest infra investment; vector-store wiring needed).

Q4: which gems get story-up status for V0.28+ grooming?
- Spool recommend priority order: GEM-7 (now -- addresses recent BT-reconnect bug visibility) > GEM-3 (next -- engine protection) > GEM-1 (UI foundation) > GEM-5 (low-effort high-engagement) > GEM-4 (depends on GEM-2+GEM-8) > GEM-2/GEM-8 (infra plumbing) > GEM-9 + GEM-6 (horizon).

---

## SPOOL ADDITIONS NOT IN BRAINSTORM -- to file as separate Spool-grounded gems

S-1 -- heat soak recovery time PID -- IAT-minus-ambient delta after cruise; sustained delta = intercooler degradation; specific to turbo cars; brainstorm did not mention.

S-2 -- LTFT trend display -- slow-moving long-term fuel trim; healthy migration toward 0 (where we are now post-jump-start) vs concerning drift >10% from 0; multi-drive view not per-drive.

S-3 -- drain ladder state UI -- when Pi on UPS battery show ladder stage (NORMAL/WARNING/IMMINENT/TRIGGER) + VCELL voltage + estimated runtime remaining; data already in power_log; just surface it.

S-4 -- mode badge -- in-car vs wall-power debug -- from 2026-05-13 lesson; eliminates the analytical guardrail confusion at the UI level; small corner indicator.

---

## RECOMMENDED PM NEXT STEPS

1. Read this note + the source materials in `specs/samples/` (the Ollama prompt pack is the highest-info-density file).
2. ~~Get CIO answers to Q1-Q4 before sizing.~~ **CIO answers received 2026-05-14 -- see below.**
3. File backlog items for GEM-7 + GEM-3 + GEM-1 as the immediate-grooming candidates (rest can wait).
4. Consider a separate epic for GEM-6 Android Auto -- it is a category of its own with its own backlog tree.
5. Reject-list above goes in PM `rejected-ideas.md` or equivalent -- preserves the audit trail of WHY some ideas were filtered.

---

## CIO ANSWERS 2026-05-14

A1 (Android Auto / GEM-6): horizon-only; build "if everything else is working"; defer to V0.30+ epic.
A2 (3.5" screen modes): driving + parked confirmed. Mockup re-interpretation: tiles are full-screen carousel-rotated, NOT all-visible dashboard. REJECT-G retracted.
A3 (Ollama depth): full vision = "MrSpool digital twin" -- RAG over Spool knowledge.md + project context = digital extension of the tuning SME. Highest scope of the three Ollama-depth options.
A4 (priority): all 9 gems valid; priority left to Spool/PM judgment; CIO theme = "everything depends on good data collection first".

## SPOOL-PROPOSED PRIORITY ORDER -- POST-CIO-ANSWERS

Phase-0 (in flight, blocks everything): V0.27 chain green; drive 12 + drain 18 IRL validation; BT-no-reconnect fix (2026-05-13 inbox note); drive_summary maturity.
Phase-1 (foundations -- "good data collection" gate): GEM-7 system status + S-4 mode badge + B-074 MAP PID.
Phase-2 (engine protection): GEM-3 knock retard alert + GEM-1 warnings-first UI framework + S-3 ladder state surface.
Phase-3 (engagement -- low effort high value): GEM-5 MARK button + GEM-4 drive grade.
Phase-4 (server-AI plumbing): GEM-8 baseline-relative anomaly + GEM-2 Ollama anomaly explanation maturity + S-1 heat soak recovery + S-2 LTFT trend.
Phase-5 (MrSpool digital twin -- the A3 vision): GEM-9 RAG over Spool knowledge.md + sessions.md + DSM references + (eventually) voice via Android Auto.
Phase-6 (horizon): GEM-6 Android Auto audio drive reports.

Rough version mapping (velocity-dependent): Phase-0 = V0.27.x. Phase-1 = V0.28-V0.29. Phase-2 = V0.29-V0.30. Phase-3 = V0.30. Phase-4 = V0.31-V0.33. Phase-5 = V0.34+. Phase-6 = V0.40+.

## CIO ANSWERS Q5-Q8 RECEIVED 2026-05-14

A5 -- "good data collection" gate: AGREED -- bar = 3 consecutive drives captured cleanly Pi-side AND server-side with zero gaps + zero BT-drop-no-reconnect + zero ladder anomalies. Locks Phase-0 -> Phase-1 gate criteria.

A6 -- knock-retard alert severity: OPTION B -- visual + audio chime through Pi speaker (no siren). Spool-proposed chime-pattern variation within option B (PRD seed):
- 5-10deg pull from drive-11-baseline: yellow tile + single soft chime
- 10-15deg pull: orange tile + triple chime
- >15deg pull (stop-driving threshold): red flashing tile + continuous chime until tap-to-acknowledge
- CIO override on flat-single-chime-all-tiers welcome at PRD review.

A7 -- MrSpool digital twin personality: MATCH SPOOL TONE -- grizzled-no-nonsense + safety-first + plainspoken + "stop doing that to your engine" voice. Persona is digital extension of Spool, not generic chatbot. Knowledge sources + authority boundary still to be locked at PRD review for GEM-9 -- proposed source set: knowledge.md (primary) + Spool sessions.md + Spool inbox notes + DSM service references + mod history + maintenance log; proposed authority boundary: advisory-only on stock-turbo setup, revisit when ECMLink V3 + wideband + knock log lands.

A8 -- drive grade visibility: POST-DRIVE ONLY -- confirmed. Real-time grade rejected (would turn driving into a game; safety-first conflict). Shown at next key-on as "Last Drive: B+, 1 minor coolant slope anomaly" footer in drive_summary view.

PM action: ALL Q5-Q8 closed; all 9 gems + 4 Spool additions can groom from Phase-0 onward with CIO direction locked. Spool willing to draft preliminary PRDs for Phase-1 + Phase-2 gems on PM go-ahead.

---

## CLOSING NOTE

Brainstorm material is high-quality and the "Pi=acquisition, server=brain, head-unit=interface" architectural shift is the strongest single idea in it. If CIO endorses that direction it changes the answer to Q2 significantly -- 3.5" screen becomes lower-priority and Android Auto becomes the V0.30+ critical-path.

Spool willing to draft preliminary PRD for GEM-7 + GEM-3 (the two engine-safety-aligned items) on PM request -- those are Spool-domain enough that I have the thresholds + rationale ready.

awaiting PM/CIO answers to Q1-Q4 before any further work on this thread.
