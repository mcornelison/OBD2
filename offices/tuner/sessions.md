# Spool — Session Log

> Running log of sessions, conversations, and events. For detailed tuning knowledge, see `knowledge.md`.
> For Spool's identity and operational model, see `CLAUDE.md`.

---

## Session 1 — 2026-04-09

**Context**: Spool agent created and onboarded to Eclipse OBD-II project.

### What Happened
- CIO invited Spool to the project as the engine tuning SME
- Created `CLAUDE.md` (agent identity), `knowledge.md` (tuning knowledge base), and this session log
- Set up `inbox/` folder for team communication (CIO also added inboxes to all other agents: pm, ralph, tester)
- Removed `advisories/` outbox — communication model is: drop notes in the recipient's inbox
- Researched project codebase thoroughly: specs, architecture, OBD-II research, PM artifacts, existing agents (Ralph, PM, Tester)
- Studied existing agent patterns for communication conventions and folder structure
- Populated knowledge base (52KB, 894 lines) covering:
  - 4G63 engine specs (bore, stroke, compression, valvetrain, fluids, timing belt)
  - Safe operating ranges by modification level (stock, bolt-ons, 16G, 20G, built)
  - PID interpretation guide for all key OBD-II PIDs
  - Datalog analysis methodology with red flags and trend analysis
  - Fuel trim decision tree
  - Timing and knock analysis
  - Boost and turbo reference (stock TD04-13G through Forced Performance lineup)
  - Cooling system thresholds
  - Fuel system specs and upgrade path
  - ECMLink V3 deep reference (speed density, per-cylinder trim, flex fuel, wideband options, 5-phase tuning procedure)
  - Modification priority path (Phase A through D with costs)
  - Turbo upgrade hierarchy with WHP ranges
  - Built motor specs and costs
  - 7 common failure modes (crankwalk, head gasket, #4 lean, MAF saturation, fuel pump, timing belt, oil starvation)
  - 10 DSM-specific quirks and gotchas
  - Full tuning glossary
- Primary reference source established: DSMTuners.com
- Created `/init-tuner` and `/closeout-session-tuner` slash commands
- Updated auto memory with Agent Team section and Spool memory file

### Key Decisions
- Agent name: **Spool** (turbo spool — when potential becomes power)
- Role: Pure SME — no code, no project management, no QA. Tuning knowledge only.
- Communication: notes in teammates' `inbox/` folders (no outbox)
- Knowledge base structured by topic (not chronological) for easy reference
- Conservative tuning stance until wideband and ECMLink are installed

### Current Vehicle State
- Stock turbo (TD04-13G), stock internals, stock ECU (modified EPROM)
- Current mods: cold air intake, BOV, fuel pressure regulator, fuel lines, oil catch can, coilovers, engine/trans mounts
- No wideband O2, no ECMLink, no aftermarket MAP, no boost gauge
- Limited monitoring via OBD-II only (ISO 9141-2, ~5 PIDs/sec max)
- Car in winter storage, hardware testing planned as weather warms

### Open Items
- ECMLink V3 installation timeline: Summer 2026 (CIO confirmed)
- Need to validate which PIDs the actual car supports (PID 0x00 query during first live connection)
- Timing belt age/mileage unknown — should verify before any tuning work
- Stock turbo designation to verify: TD04-13G vs TD04-09B (check tag on turbo housing)
- CIO needs to order: AEM 30-0300 wideband (~$200), ID550 injectors (~$350-400)

---

## Session 2 — 2026-04-10

**Context**: CIO briefed Spool on full Summer 2026 upgrade plan and big-picture system vision. Major session — vehicle inventory, mod plan, system specs, and project roadmap delivered.

### What Happened
- CIO disclosed full parts inventory: ECMLink V3 (in box, back seat), Walbro GSS342G pump (E85-rated, confirmed), GM flex fuel sensor (in hand), AN-6 E85 lines (already installed)
- CIO had not considered wideband O2 — Spool explained why it's non-negotiable for E85 tuning. CIO agreed to purchase AEM 30-0300 (~$200)
- CIO has not ordered fuel injectors — Spool recommended Injector Dynamics ID550 (550cc) as minimum for E85 on stock turbo
- Spool advised against standalone EBC (GReddy Profec, etc.) — ECMLink handles boost control via stock BCS solenoid. Saved CIO $200-400.
- CIO asked about touchscreen boost control — Spool said no for safety (latency, failure modes, distraction). Agreed on read-only display + pre-set map switching as compromise.
- CIO confirmed Illinois emissions requirement (biennial OBD-II scan) — Spool specified high-flow catted downpipe only, no catless. Keep stock exhaust as fallback.
- Exhaust (downpipe + cat-back) moved from "nice to have" to required — CIO agreed with the physics argument
- Boost gauge + GM 3-bar MAP sensor listed as nice-to-have
- CIO revealed full system vision: Pi 5 with touchscreen + battery in car, WiFi sync to Chi-Srv-01, server-side AI analysis
- CIO reminded Spool to stay in lane — specs and tuning knowledge to PM, no code/architecture. Spool acknowledged.
- CIO authorized Spool to review code output and determine what's working/not from tuning perspective
- Delivered comprehensive tuning specification to PM inbox (PID specs, thresholds, display specs, 6 analysis definitions, 5 numerical examples, 5-phase roadmap)
- Created `/review-stories-tuner` skill for pre-sprint story validation
- CIO confirmed no research needed at this time — Spool's knowledge base is solid for current build

### Vehicle Details Learned
- 76,000 miles, garage kept, summer only — collector-grade condition
- Dealer service early 2025: full timing belt and maintenance check — belt is fresh
- Summer 2025: new Luke clutch (professional install, full "while you're in there" service), new engine mounts, new tie rods
- Coilovers on all four corners
- Car gets attention everywhere — multiple purchase offers at dealership. CIO not selling.
- Currently 36F in Chicago, car in garage with battery charger, Pi on desk unplugged
- CIO can drive at any time (just needs to turn insurance on)

### Key Decisions
- **Install order locked (8-step)**: Pump → sensor wire → exhaust → ECMLink → wideband → pump-gas tune → injectors → E85
- **Wideband O2 approved**: AEM 30-0300 X-Series UEGO
- **Injector target**: ID550 (550cc), not yet ordered
- **Exhaust required**: 3" high-flow catted downpipe + 2.5-3" mandrel-bent cat-back. MUST be catted — Illinois emissions.
- **Boost control**: ECMLink via stock BCS solenoid. No standalone EBC. No touchscreen boost adjustment (safety).
- **Boost gauge + MAP sensor**: Nice-to-have (~$100 total)
- **Illinois emissions**: OBD-II scan only. No catless pipes. No disabled readiness monitors. Stock exhaust kept as fallback.
- **Safety rule**: No E85 in tank until Step 8
- **Spool's role clarified**: Tuning SME sends specs to PM. Can review code output. Stays in lane — no code, no architecture, no PM work.
- **Story review gate**: Spool reviews PM stories before sprint (`/review-stories-tuner`)
- **Foundation first**: Build solid Phase 1 (OBD-II) before Phase 2 (ECMLink)
- **No research needed now**: Knowledge base is solid for stock turbo + E85 build. Research triggers: first real datalog, ECMLink install, turbo upgrade.

### Current Vehicle State
- Stock turbo (TD04-13G), stock internals, stock ECU (modified EPROM)
- 76k miles, garage kept, summer only
- Mechanical baseline solid: fresh belts, fresh clutch, fresh mounts, fresh tie rods, coilovers
- Parts in hand: ECMLink V3, Walbro GSS342G, GM flex fuel sensor
- Parts needed: wideband, injectors, downpipe, cat-back (~$1,050-1,500 remaining)
- Pi 5 on desk, car in garage — not yet connected

### Deliverables
1. **Tuning spec to PM**: `offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md`
   - PID specs (Phase 1 + Phase 2), tiered polling strategy
   - 3-level alert thresholds for all parameters (both phases)
   - Display specs for 3.5" touchscreen (primary + 5 detail pages)
   - 6 server analysis definitions with full input/output examples
   - 5 numerical developer examples with exact inputs and outputs
   - 5-phase tuning roadmap (pre-hardware through edge AI)
2. **Story review skill**: `.claude/commands/review-stories-tuner.md`
   - Pre-sprint validation gate for PM-created user stories
   - Checklist: numbers, units, formulas, edge cases, phases, safety, display, analysis

### Open Items
- CIO needs to order: AEM 30-0300 wideband (~$200), ID550 injectors (~$350-400), 3" high-flow catted downpipe (~$200-400), cat-back exhaust (~$300-500)
- Order downpipe with wideband bung pre-welded (saves exhaust shop trip)
- Stock turbo designation still unverified (TD04-13G vs TD04-09B — check tag on turbo housing)
- ~~PM (Marcus) needs to process the tuning spec and create stories~~ — RESOLVED: Marcus created B-028 through B-032 (32 stories)

---

## Session 3 — 2026-04-12

**Context**: CIO asked Spool to review the PRDs/backlog items Marcus created from the 2026-04-10 tuning spec.

### What Happened
- Reviewed B-028 through B-032 (5 backlog items, 32 stories) against original tuning spec
- Marcus's work quality: excellent. Numerical preservation, rationale, worked examples, ethanol interpolation formula, MDP caveat, phase awareness, safety language — all preserved faithfully.
- Found 3 issues — 2 were my own original spec gaps that Marcus faithfully copied, 1 was a minor inconsistency in B-028 between spec text and test case
- Sent detailed review note to PM inbox: `offices/pm/inbox/2026-04-12-from-spool-review-B028-B032.md`

### Issues Found
1. **RPM threshold gap (7000-7200)** — SPOOL spec error. My original spec had a gap between Caution (6500-7000) and Danger (>7200). B-028 test case extended caution to 7200 (correct), but the spec text still says 6500-7000. Fix: Caution = 6501-7200.
2. **IAT threshold gap (150-160F)** — SPOOL spec error. Similar gap pattern. Fix: Caution = 131-160F, Danger = >160F.
3. **AFR "Normal" range implicit** — Clarity issue in US-113/114. "Normal" was implicitly defined as "not Caution and not Danger" but never explicitly stated. Fix: Add clarifying note.

### Key Decisions
- **Result**: APPROVED WITH CORRECTIONS. All 32 stories ready for sprint.
- **CIO clarified scope**: Spool IS authorized to directly edit PRD/backlog content when the variance is in the tuning domain. Lane rule: PM owns story structure/organization; Spool owns tuning content within stories.
- **Corrections applied directly by Spool** (not punted back to Marcus):
  - B-028 US-110: RPM danger threshold corrected from >7200 to >7000 (factory redline for 97-99 2G). Caution = 6501-7000.
  - B-028 US-112: IAT caution range extended from 130-150F to 131-160F (closes the gap)
  - B-029 US-113/US-114: Added explicit "Normal" range definition and table rows. Rich-of-target at WOT is intentionally safe.
- Also updated original spec document (2026-04-10-from-spool-system-tuning-specifications.md) so source of truth is consistent
- Updated knowledge.md RPM line to match (was already mostly correct, just clarified the boundary)
- Sent updated review note to Marcus indicating no action needed from him

### Open Items
- ~~PM applies 3 corrections~~ — RESOLVED: Spool applied them directly
- ~~Spool to update `/review-stories-tuner` skill~~ — RESOLVED: Added threshold gap check, vehicle-specific value check, code impact check, internal consistency check
- B-028 through B-032 ready for sprint load — Marcus reopened B-028 as in_progress with US-139 hotfix

### Reply From Marcus (Inbox 2026-04-12)
- Marcus received the review and caught an **internal inconsistency** in Spool's review note: the note said "Caution 6501-7200, Danger >7200" but Spool's file edit said "Caution 6501-7000, Danger >7000". Marcus correctly used the file edit values (7000 is the 97-99 2G factory redline).
- Marcus flagged a **code impact** Spool missed: `src/obd_config.json` has `rpm.dangerMin: 7200` committed from sprint 2. The correction requires a runtime code change, not just doc update.
- Marcus created **US-139** as an RPM hotfix story: update config, update tests (7200/7201 assertions → 7000/7001), reopen B-028 as in_progress.
- IAT correction: no code change needed — existing `iat.dangerMin: 160.0` already matches the corrected spec
- AFR corrections: blocked on ECMLink hardware anyway — docs-only clarification
- Sent Spool's ack + ack of code impact back to Marcus with post-mortem thought: sprint 1/2 work may have other spec errors that pre-date the review gate. Consider one-time audit when time permits.

### Sprint 1/2 Code Audit (CIO Request, 2026-04-12)
- CIO asked Spool to audit existing code for tuning-domain values against corrected specs
- Used Explore agent to survey all tuning values in `src/` directory
- **Key finding**: Codebase has TWO parallel threshold systems — (1) `tieredThresholds` section in obd_config.json (mostly correct after US-139 hotfix), and (2) legacy profile-level `alertThresholds` (multiple wrong values, scattered across 7+ files, not updated by US-139)

### Variances Found
**CRITICAL (actively wrong runtime values):**
1. **`coolantTempCritical: 110`** in 6 files (profile system, manager defaults, loader defaults) — 110 is nonsensical regardless of unit (110F = cold engine, 110C = 230F above danger). Should be 220F with explicit unit.
2. **Performance profile `rpmRedline: 7200`** (obd_config.json:118) — Legacy system, US-139 didn't touch it. Should be 7000.
3. **Performance profile `boostPressureMax: 18`** (obd_config.json:121) — Too aggressive for stock TD04-13G. My spec caps at 15 psi for stock turbo.
4. **Display boost stubs** (boost_detail.py:36-37) — `BOOST_CAUTION_DEFAULT: 18.0`, `BOOST_DANGER_DEFAULT: 22.0`. Both dangerously wrong for stock turbo. Should be 14/15.
5. **Display fuel stub** (fuel_detail.py:38) — `INJECTOR_CAUTION_DEFAULT: 80.0`. My spec says 75%. Danger value (85%) is correct.

**MINOR:**
6. Battery voltage boundary at 15.0V is ambiguous (cautionHighMax and dangerHighMin both at 15.0)
7. `profile_manager.py:47` docstring example uses `rpmRedline: 7500` (95-96 2G value, wrong vehicle year for the 1998 Eclipse)

**NON-VARIANCES (correct):** All tiered thresholds (after US-139), all polling tiers, PID definitions, MDP caveat, simulator eclipse_gst profile, display thermal thresholds, drive detection, timing baseline logic

### Hotfix Stories Recommended to Marcus
- **US-140**: Fix legacy profile coolantTempCritical (6 files)
- **US-141**: Complete RPM hotfix in legacy profile (performance profile)
- **US-142**: Correct stock turbo boost pressure limits
- **US-143**: Fix Phase 2 display stub defaults (boost + fuel)
- **US-144**: Clean up profile_manager docstring example

### Audit Deliverable
- Full variance report dropped in PM inbox: `offices/pm/inbox/2026-04-12-from-spool-code-audit-variances.md`
- 5 recommended hotfix stories with specific file paths, line numbers, correct values, and rationale
- Architecture note raised (not a recommendation): consider deprecating legacy profile threshold system in favor of tiered system — dual systems caused the RPM hotfix to miss profile values

### US-139 RPM Hotfix Verification (same day)
- Ralph finished US-139 (commit 7f5a90a on sprint/2026-04-sprint4-hotfix branch)
- Spool verified the hotfix: `src/obd_config.json:195` → `dangerMin: 7000` ✓
- All 28 RPM threshold tests pass (including new boundary cases 7000=caution, 7001=danger)
- US-139 scope was CORRECT AND COMPLETE for what it promised
- **IMPORTANT**: US-139 only fixed the tiered threshold system (obd_config.json tieredThresholds.rpm). My code audit variances (US-140-144 recommended) are a SEPARATE set of issues targeting the legacy profile threshold system and display stubs. Those are still untouched as of this check.

### CIO Feedback: "DO NOT CHANGE" Spec Discipline
- CIO feedback after seeing the drift pattern: specs need explicit `[EXACT: value — DO NOT CHANGE]` markers
- Purpose: zero ambiguity for PM/architect/developer when Spool is source-of-truth authority on a value
- Saved as feedback memory: `feedback_spool_spec_discipline.md`
- Updated `/review-stories-tuner` skill: added "DO NOT CHANGE marker check" and "Legacy system check" to the Numbers and Values section
- Updated `offices/tuner/knowledge.md` front matter with the marker convention so future spec writing uses it
- Going forward: any tuning value in a spec that can cause mechanical damage if wrong must have the marker

### Pi Status Update (2026-04-12)
- CIO reports: Pi 5 is up and running on the network at 10.27.27.28
- Not yet physically connected to the Eclipse OBD-II port
- Car is still in garage, ambient ~36°F (Chicago spring, not warmed up yet)

### Spool's Role When Pi Connects To Car (Clarified by CIO 2026-04-12)
**Spool's job is OBSERVATIONAL, not technical.** When data flows from the car, Spool reviews the data with tuning judgment. He does NOT write PID handshake code, test Bluetooth protocols, or run pytest suites — that's Ralph's work.

**What Spool actually does**:

*On the Pi (when live data flows):*
- Review first live datalog and answer: "does this match a healthy 4G63?"
- Spot physically impossible readings (coolant at 300°F with engine off, etc.)
- Validate warmup curves, idle behavior, closed-loop fueling against 4G63 community norms
- Calibrate alert thresholds against actual vehicle behavior (e.g., if coolant actually runs 205°F in traffic, 210°F caution may be too tight for this specific car)

*On the server (when datalogs sync):*
- Review aggregated analysis output — are the advisories tuning-valid?
- Validate knock correlation, AFR drift, thermal patterns flag real problems not noise
- Tell the team when server is calling a real issue vs. false positive
- Compare baselines to DSMTuners community data

**What Spool is NOT doing**:
- PID handshake protocols, Bluetooth retries, test suites, database schemas, sync pipeline debugging — all Ralph's lane

**When Pi connects**: CIO sends first live datalog to Spool's inbox for tuning validation. Spool reviews the data (not the code).

### Session 3 Closeout Summary

**Major deliverables**:
1. PRD review of B-028 through B-032 (32 stories) — caught 3 issues, 2 were Spool's own spec gaps
2. Code audit of sprint 1/2 delivered code — found 7 variances in legacy profile threshold system and Phase 2 display stubs
3. US-139 RPM hotfix verification — clean pass, 28 tests green
4. Feedback captured: "DO NOT CHANGE" marker discipline + role boundary clarifications
5. Updated `/review-stories-tuner` skill with 4 new checklist items (threshold gap, vehicle-specific, code impact, internal consistency, legacy system, DO NOT CHANGE markers)

**Inbox notes sent to Marcus (PM)**:
- `2026-04-12-from-spool-review-B028-B032.md` — PRD review (approved with corrections, then corrections applied directly)
- `2026-04-12-from-spool-ack-rpm-hotfix.md` — ack of Marcus's catches + closed action items
- `2026-04-12-from-spool-code-audit-variances.md` — 7 variances + 5 recommended hotfix stories (US-140-144)

**Safety advisories issued**:
- `coolantTempCritical: 110` flagged as runtime-wrong (nonsensical value, multiple files)
- `boostPressureMax: 18` flagged as unsafe for stock TD04-13G (should be 15)
- Display boost stubs (18/22 psi) flagged as dangerously wrong for stock turbo
- Factory redline corrected from 7200 (error) to 7000 (97-99 2G) — runtime fix completed via US-139

**Memory updates**:
- `feedback_spool_spec_discipline.md` — DO NOT CHANGE marker format
- `feedback_spool_role_boundaries.md` — updated with scope clarifications (direct edit authority + observational testing)
- Auto-added by system: `project_architecture_tiers.md`, `feedback_ralph_honors_spool_constraints.md`

**Knowledge base updates**:
- knowledge.md front matter: added DO NOT CHANGE marker discipline section
- knowledge.md RPM tiered threshold: clarified 6501-7000 caution boundary

**Vehicle state**: No changes. Car still in garage, ~36°F ambient, battery charger on. Pi 5 up on network at 10.27.27.28 but not yet connected to OBD-II port.

### Open Items for Next Session
- **US-140 through US-144**: 5 hotfix stories recommended in variance report — waiting on Marcus to create and load into sprint
- **Architecture decision**: Whether to deprecate legacy profile threshold system in favor of tiered system (Marcus + architect to decide)
- **Pi/BT integration**: Ralph + CIO working on Bluetooth OBD2 interface. When first real data flows, CIO sends datalog to Spool's inbox for tuning validation.
- **Sprint 1/2 backfill audit**: This session audited threshold values. Other tuning-domain areas in sprint 1/2 code may still contain drift (e.g., analysis formulas, simulator values) — not yet surveyed.
- **Stock turbo designation verification**: Still need to check physical tag on turbo housing (TD04-13G vs TD04-09B) when car comes out of storage

---

## Session 4 — 2026-04-16

**Context**: Short session. CIO confirmed the rollout plan (server good → Pi good → plug into car → establish connection → dial in). Two inbox items from Marcus: Gate 1 display review and AI prompt templates for US-CMP-005 (Sprint 9 Server Run). Both cleared this session.

### What Happened
- **Gate 1 (primary screen parameters)**: Confirmed the defaults as-is — RPM, Coolant, Boost, AFR, Speed, Battery Voltage. No swaps for crawl. Explicitly declined knock count (no PID on stock 2G ECU — ECMLink territory). Flagged that "AFR" in crawl phase is actually narrowband O2 interpretation, not true AFR — gets replaced when AEM UEGO wideband is wired (Phase 2). Response sent: `offices/pm/inbox/2026-04-16-from-spool-gate1-primary-screen.md`.
- **AI prompt templates (US-CMP-005)**: Delivered three files at `src/server/services/prompts/`:
  - `system_message.txt` — Spool-voice invariant context. Hard hardware envelope (no wideband, no ECMLink, no knock count recommendations). 9 classic 4G63 failure modes baked in as a watchlist. Strict JSON output contract: rank/category/recommendation/confidence, max 5, empty array allowed.
  - `user_message.jinja` — Per-drive template consuming all fields Marcus proposed (drive_id, drive_start, duration_seconds, row_count, statistics, anomalies, trend, correlations, prior_drives_count). Baseline-awareness guard: when `prior_drives_count < 5`, model is told to lean "observe and revisit" over "act now."
  - `DESIGN_NOTE.md` — What Ollama is good/bad at on OBD-II data. Six quality gates for Ralph to apply during dev-time review. Failure-mode catalogue.
  - Delivery note to Marcus: `offices/pm/inbox/2026-04-16-from-spool-ai-prompt-templates-delivered.md`.
- CIO confirmed the scope permission: "100% ok to have a SME expert twist on this" — that authorized the Spool-voice system message rather than a generic automotive-expert prompt.

### Key Decisions
- **Crawl display parameters ship as-is.** Simplicity over completeness out of the gate. We iterate after real data flows.
- **Pre-wideband discipline enforced in AI prompts.** The system message explicitly forbids quoting specific AFR numbers from narrowband O2. This is a safety posture — narrowband will mislead the AI into fabricating precise AFR claims from rich/lean swing data.
- **Hardware envelope as a hard wall in the prompt.** Llama 3.1's generic car-tuning training wants to suggest "check your wideband" and "retard timing 2°" because the internet assumes those mods exist. The system message names the absent hardware explicitly and forbids recommendations that depend on it.
- **Cite-the-data rule.** Every recommendation must cite a specific input number. Enforced in both the system message AND the Jinja template (belt-and-suspenders). If a recommendation could apply to any car, it is noise.
- **Schema held to spec.** Did not expand the output schema. `rank / category / recommendation / confidence` — no `severity` field for now. Revisit after first real drives.
- **Prompts loaded as files, not inlined in Python.** Requested explicitly of Ralph — lets Spool iterate on prompts without a code change.

### Current Vehicle State
No change. Car still in garage. Pi at 10.27.27.28 on the network, not yet connected to OBD-II port.

### Open Items for Next Session
- **US-140 through US-144 hotfix stories**: Still waiting on Marcus to load (carried from Session 3).
- **First-drive review ritual**: When US-CMP-005 ships and the first real drive lands, CIO/Marcus/Ralph drops the 4 artifacts (raw stats, rendered user message, raw model response, parsed recommendations) in Spool's inbox for quality grading against the six gates in DESIGN_NOTE.md.
- **Legacy profile threshold architecture decision**: Still pending (carried from Session 3).
- **Stock turbo designation verification**: Still need physical tag check (carried from Session 3).
- **Prompt tuning feedback loop**: Expect to iterate on `system_message.txt` and `user_message.jinja` once real Ollama output quality can be evaluated. The DESIGN_NOTE.md gates define what "good" and "bad" look like.
- **Gate 2 (walk-phase threshold color mapping)** and **Gate 3 (run-phase screen priority + real data review)**: Future actions from Marcus's display review note. Not actionable until Ralph builds those tiers.

---

## Session 5 — 2026-04-19

**Context**: THE milestone session. Pi connected to Eclipse for the first time in Session 23 (PM session number). CIO asked Spool to review the first-ever real Eclipse OBD-II data against Phase 1 tuning spec. Long stretch of deep review + documentation work while waiting for Ralph to work Sprint 14.

### What Happened

**The milestone review** — CIO summoned Spool to grade the Session 23 data (engine cold-start → warm idle → shutdown, ~10 min wall-clock). Pulled data from both Pi SQLite (`chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db`) and chi-srv-01 MariaDB (`obd2db`). Byte-for-byte match — 149 rows in both, 11 statistics rows, 16 connection_log rows, sync batches OK. Pipeline integrity PROVEN end-to-end.

**Key data-integrity finding**: the "10 minutes of idle" experienced by CIO was actually ~23 seconds of OBD-connected data across 2 windows. Connection log showed 5 failed mac-as-path retries (TD-023), then 2 /dev/rfcomm0 successful sessions (1s + 22s). Framed this as a data-quality observation for PM, not a tuning concern.

**Engine health grade (warm idle, 23s)**: HEALTHY. LTFT = 0.00% flat across all 13 samples (tune is genuinely dialed — best signal in the dataset). STFT ±1.5% around zero. O2 switching 0V↔0.82V avg 0.46V (healthy narrowband). MAF 3.49-3.68 g/s tight. RPM 761-852 ±45 (not hunting). Throttle 0.78% flat. Engine Load 19-21%. No impossible readings, no stuck sensors. Two observations worth watching: coolant plateaued at 73-74°C (163-165°F) below full op temp — flag for thermostat on next drill with sustained warmup; timing advance 5-9° BTDC at idle is below community norm (10-15°) but not alarming — revisit at ECMLink baseline.

**Three inbox notes delivered to Marcus**:
1. `2026-04-19-from-spool-real-data-review.md` — full Session 23 first-light grade + 5 CRs (battery voltage gap, longer capture needed post-TD-023, data_source column, timing baseline, obs note on spec doc).
2. `2026-04-19-from-spool-data-collection-gaps.md` — 7 priority-ranked data collection additions (Fuel System Status 0x03, MIL + DTCs Mode 01/03/07, drive_id column, Runtime 0x1F, Barometric 0x33, post-cat O2 0x15, ambient temp proxy). Sprint 14 bundle suggestion.
3. `2026-04-19-from-spool-specs-update-and-dtc-gap.md` — summary of spec changes made + flag that DTC retrieval story is missing from Sprint 14 (MIL bit will be captured but not stored codes). Marcus responded by reserving US-204 for Sprint 15+ as Spool Data v2 Story 3.

**CIO-authorized boundary cross — specs updates** (with explicit permission):
- `specs/grounded-knowledge.md`: new top-level "Real Vehicle Data" section. Authoritative PID support (empirically confirmed), battery voltage alternate path (ELM_VOLTAGE), real-world K-line throughput measurement (6.4 rows/sec matches theoretical), warm-idle fingerprint with interpretation anchors.
- `specs/obd2-research.md`: Session 23 empirical column added to Tier 1 + Tier 2 PID tables; PID 0x0B caveat strengthened (does not respond at all, stronger than prior "may report MDP"); new PID 0x42 section with ELM_VOLTAGE workaround; Session 23 throughput measurement subsection; Sprint 14 polling-design implications for the 6 new PIDs.

**Own knowledge.md updates**:
- New top-level "This Car's Empirical Baseline" section — deeper interpretation layer than the specs/ version. Baseline values + interpretation anchors (LTFT drift thresholds, RPM variation envelopes, thermostat watch criterion, timing observation).
- PID support tables corrected with empirical truth (0x0A, 0x0B, 0x42 confirmed unsupported; 0x42 moved to Tier 2 with unsupported flag).
- Battery voltage via ELM_VOLTAGE subsection added (CR #3 homework done).

**Reusable tooling created**:
- `offices/tuner/scripts/review_run.sh` + `README.md` — parameterized Pi↔server slice review. Repeatable for every future drill: `./review_run.sh --since "YYYY-MM-DD HH:MM:SS"`. Pulls PID coverage, ranges, connection log, sync state from both stores.
- `offices/tuner/drive-review-checklist.md` — 7-section (A-G) structured review framework covering pipeline integrity → idle health → warmup → drive/load → red-flag scan → data quality → reporting. Embeds this car's Session 23 baseline as authoritative comparison anchor. Human-judgment layer that complements the raw-numbers script.

**Sprint 14 peek** — confirmed Marcus has queued all Spool CRs: US-193 (TD-023), US-195 (data_source), US-199 (6 PIDs), US-200 (drive_id). US-202 already passed (TD-027 timestamp). Flagged DTC retrieval gap — Marcus responded by reserving US-204 for Sprint 15+.

**Cross-session "don't forget" persistence** — CIO said rest and wait, but don't forget 2 deferred items. Saved to 3 places: auto memory (`project_spool_pending_research.md` + MEMORY.md index), knowledge.md session log entry.

### Key Decisions

- **Engine graded HEALTHY** on the 23 seconds of real warm-idle data. Grading rests on strong fuel trim signature (LTFT 0% flat, STFT ±1.5%), healthy O2 switching, stable idle behavior, plausible sensor ranges.
- **Thermostat watch item filed** — if next drill shows coolant plateau below 180°F after 5+ min sustained warmup, thermostat (stuck open) is the first suspect. Trivial $15 fix but critical to catch because a cold-running engine fools the ECU into extended warmup enrichment and can mask lean conditions.
- **Timing advance observation filed** — 5-9° BTDC at idle vs community 10-15° norm is noted but not alarming. Revisit at ECMLink baseline session when we have richer data.
- **"Real Vehicle Data" section in specs/grounded-knowledge.md becomes authoritative** — wins over community baselines when they disagree (PM Rule 7: real vehicle data > community consensus). Team-facing source of truth.
- **ELM_VOLTAGE / ATRV becomes the battery voltage path** — PID 0x42 confirmed unsupported. All code, tests, display logic, and fixtures must use adapter-level query instead.
- **Test-timing guidance**: wait for US-193 + US-195 + US-199 + US-200 to all pass before running the next timed cold-start idle test. That's the configuration that makes a 10-min test worth doing.

### Current Vehicle State

- No mechanical changes. Car still in garage at home.
- **Pipeline state changed**: Pi-to-Eclipse OBD connection verified. 2G ECU PID support empirically mapped. End-to-end Pi → Pi SQLite → HTTP SyncClient → chi-srv-01 MariaDB proven byte-perfect.
- Monitoring capability: 11 PIDs confirmed supported at ~0.58 Hz each (wired-equivalent K-line throughput). 3 PIDs confirmed unsupported on this ECU.
- OBDLink LX paired/bonded/trusted as of Session 23, SPP on RFCOMM channel 1.
- Still no wideband, no ECMLink, no aftermarket MAP — stock ECU with modified EPROM remains the envelope.

### Open Items (carried forward)
- **US-140 through US-144 hotfix stories** — Session 3 backlog items still not loaded by Marcus (long-standing carryforward).
- **Stock turbo designation verification** — still need physical tag check (TD04-13G vs TD04-09B).
- **Legacy profile threshold architecture decision** — Session 3 architect decision still pending.
- **Gate 2 / Gate 3 display reviews** — Session 4 future actions, not actionable until Ralph builds those display tiers.

### Open Items (new this session)

- **US-204 DTC retrieval story** — reserved by Marcus for Sprint 15+. Spool Data v2 Story 3 (Mode 03 + Mode 07 + `dtc_log` table). Spool carryforward: 2G DSM DTC interpretation cheat sheet once story lands.
- **Thermostat diagnostic procedure research** — Spool self-assigned, pending. Resolves at next real-drive capture (either coolant climbs past 180°F normally = thermostat OK, or plateaus below = run diagnostic procedure). See `project_spool_pending_research.md`.
- **DSM DTC interpretation cheat sheet** — Spool self-assigned, pending. Blocked on Ralph landing DTC capture (US-204 Sprint 15+). See `project_spool_pending_research.md`.
- **Post-TD-023 longer drill** — awaits Sprint 14 close. Cold-start → sustained warm idle → shutdown, target 10+ min uninterrupted OBD-connected time. First capture that enables actual tuning review beyond pipeline integrity.
- **Tuning-value reviews for US-195, US-199, US-200** — formal `/review-stories-tuner` pass on the tuning-domain stories in Sprint 14 before Ralph locks implementation. Low priority because stories are straightforward, but worth doing once Ralph picks each one up.

### Safety Advisories Issued This Session

- **Coolant plateau watch** — advisory filed with PM (not an alarm yet). If next drill shows coolant staying below 180°F after sustained warmup, thermostat diagnosis kicks in. Stuck-open thermostat fools the ECU and can mask real lean conditions during warmup.
- **Narrowband AFR interpretation discipline reaffirmed** — Spool's grade of "tune is dialed" on Session 23 rests on LTFT + STFT + O2 switching + MAF + Load + RPM consistency, NOT on narrowband O2 voltage numerics. Server AI prompts already forbid numeric AFR claims from narrowband (system_message.txt); the same discipline applies to any code or display logic that interprets O2 voltage.
- **CR #1 battery voltage gap** — primary display has no battery voltage source until US-199 adds ELM_VOLTAGE. Not dangerous (display gauge just shows no data) but flagged to PM so we don't ship car without it.

---

## Session 6 — 2026-04-20 / 2026-04-21 (~6hr span crossing into UTC next day)

**Context**: Marathon session. Sprint 14 shipped 12/12. CIO invoked `/init-tuner`; review of Sprint 15 tuning-domain stories; the Session 23 truncate thread; two live Eclipse drills (thermostat/restart + UPS drain); discovery of existing Pi power-management infrastructure; major course corrections on previously-proposed story scopes. End-of-session the CIO ordered all simulated tests archived.

### What Happened — Sprint 15 grooming work (early session)

- Ran `/review-stories-tuner` retroactively on Sprint 15 pending tuning-domain stories (US-204 DTC retrieval, US-206 drive-metadata capture, US-208 first-drive validation). **APPROVED all three** — no corrections needed. Posted `offices/pm/inbox/2026-04-20-from-spool-sprint15-story-review.md`.
- Drafted US-205 amendment note addressing Ralph's halt finding of 352K Pi rows (not 149 as I originally estimated). Affirmed 352K is correct scope, flagged Pi-side `alert_log` schema difference requiring timestamp/drive_id filter instead of `data_source='real'`. Posted `2026-04-20-from-spool-us205-amendment.md`.
- Filed a standalone benchtest `data_source` hygiene story — root cause of the 352K bloat. Posted `2026-04-20-from-spool-benchtest-data-source-hygiene.md`. Priority reduced later in session once CIO ordered simulate mode archived (pollution pressure drops to near-zero).

### What Happened — Drill 1 (afternoon, 21:22-21:44 Chicago / 02:22-02:44 UTC)

Thermostat warmup + engine-restart drill. CIO ran the 5-phase protocol at the car with the adapter: pre-crank observation → 15-min sustained idle → shutdown → restart → shutdown. Drill card at `offices/tuner/drills/2026-04-20-thermostat-restart-drill.md`.

**Outcome**:
- ✅ **Thermostat CONFIRMED HEALTHY** — CIO's direct observation: internal coolant gauge held normal operating position throughout the 15-min idle. **I-016 CLOSED BENIGN** (annotated directly in the issue file).
- ✅ **Engine mechanically clean** across cold crank → idle → restart cycle. No rough idle, no warning lights, no anomalies.
- ❌ **Zero data captured**. Pi `realtime_data` = empty in the window AND overall. Ralph's earlier 352K rows had been truncated (US-205 had run 3x during the drill for reasons that surfaced below). Pi display showed nothing during the drill — the early warning signal that something was off in the pipeline.

### What Happened — Drill 2 (evening, ~02:05-02:35 UTC)

CIO set up a controlled UPS drain test. Spool built a `ping_monitor.sh` script (saved at `offices/tuner/scripts/`) that pings the Pi every 5s and logs state transitions. CIO unplugged wall power while the monitor watched. Log at `/tmp/pi_ups_drain_20260420.log` (ephemeral on this dev box).

**Timeline**:
| Event | UTC | Chicago |
|-------|-----|---------|
| Power unplugged | ~02:05:42 | 9:05:42 PM |
| Last healthy ping | 02:28:59 | 9:28:59 PM |
| **First ping failure** | **02:29:31** | **9:29:31 PM** |
| Power restored | ~02:33 | 9:33 PM |
| Recovery (ping back) | 02:34:15 | 9:34:15 PM |

- **UPS runtime baseline (new battery, simulate-mode load): 23 min 49 sec**
- **Pi boot-to-network: ~75 sec** after power restore
- **Shutdown was HARD CRASH** — ran battery to zero, no graceful shutdown
- **Evidence for hard crash**: `EXT4-fs (mmcblk0p2): orphan cleanup on readonly fs` on next boot. No `shutdown` in bash history. No UPS-monitor daemon running. Empty pstore dir.

### Big Discoveries Surfacing During Post-Mortem

**1. `eclipse-obd.service` EXISTS and auto-starts** (I was wrong earlier). Named `eclipse-obd.service`, not `obd-collector.service`. Found at `/etc/systemd/system/eclipse-obd.service`. Enabled. Running. But — **configured with `--simulate` flag in ExecStart**, which is why the thermostat drill captured nothing real: the collector was reading the physics simulator, not `/dev/rfcomm0`.

This discovery unified multiple puzzles into one: the 352K rows, the US-205 triple-execution (sim kept regenerating data), today's zero-capture during the real drive — all one root cause.

**2. Substantial Pi power-management infrastructure ALREADY EXISTS** — I didn't know this before tonight. Code map:

```
src/pi/power/power.py           (~780+ lines — PowerManager, onTransition callbacks)
src/pi/power/power_db.py        (power_log writes)
src/pi/power/power_display.py   (display integration)
src/pi/power/readers.py         (MAX17048 I2C)
src/pi/hardware/ups_monitor.py  (~750+ lines — UpsMonitor.getPowerSource())
src/pi/hardware/shutdown_handler.py
src/pi/alert/tiered_battery.py
```

`getPowerSource()` returns BATTERY/EXTERNAL/UNKNOWN via CRATE + VCELL-slope inference (US-184). But during tonight's drain test **none of this fired** — reason unknown, needs audit next session.

**3. `Restart=on-failure` not `Restart=always`** on the service — subtle but material. Clean exits don't trigger restart. Insufficient for BT-flap resilience.

### CIO Directives Locked In This Session

1. **STAGED SHUTDOWN APPROVED**: warning 30% → imminent 25% → trigger 20%. Conservative, LiPo-safe.
2. **STAGE BEHAVIORS APPROVED**:
   - Warning (30%): flag DB, stop drive_id minting, force sync push if network
   - Imminent (25%): stop OBD polling, close BT, force KEY_OFF on active drive
   - Trigger (20%): `systemctl poweroff`
3. **MONTHLY DRAIN TESTS during driving season** (May-Sept). Storage period (Oct-Apr) cadence TBD (I suggested quarterly or pre-season; CIO didn't explicitly confirm).
4. **ALWAYS-ON HDMI DISPLAY with dashboard default** — placeholder, detailed design deferred.
5. **BATTERY HEALTH TRACKING** with future alert when runtime drops materially (I'm calling this ~30% below baseline; CIO agreed in principle).
6. **STOP ALL SIMULATED TESTS. ARCHIVE SIM INFRASTRUCTURE.** `--simulate` flag comes out of production `eclipse-obd.service` ExecStart. Simulator code stays in repo for dev/CI, doesn't run by default.

### Comprehensive Handoff to Marcus

Final inbox note: `offices/pm/inbox/2026-04-20-from-spool-session6-findings-and-directives.md` — supersedes (partially) the earlier `2026-04-20-from-spool-pi-collector-resilience-story.md` story proposal. Contains:
- CIO directives (the 6 items above)
- Drill summaries with evidence
- Three amended story scopes:
  - **Story 1 (S)**: Pi hotfix bundle — persistent journald + Restart=always + drop `--simulate`
  - **Story 2 (M)**: BT-resilient capture loop (scope narrowed — daemon exists, just needs resilience logic)
  - **Story 3 (L, DEFERRED pending audit)**: Power-down orchestrator — existing code may already do most of this
- Session 6 durable findings for project memory
- Explicit list of what Spool is NOT doing this session (no direct service changes, no architecture.md rewrite — batch with audit work)

### Durable Knowledge Updates

- **I-016**: annotated CLOSED BENIGN with evidence
- **knowledge.md "Real Vehicle Data" reframe**: Session 23 coolant is mid-warmup snapshot, NOT steady-state healthy baseline. Batch with specs/grounded-knowledge.md update next session.
- **Memory**: three memory files created/updated (see below)

### Memory Updates
- NEW `project_pi_collector_not_persistent.md` — corrected later in session (the collector IS a service, just in simulate mode)
- NEW `project_i016_thermostat_closed_benign.md` — thermostat disposition
- UPDATED `project_spool_pending_research.md` — thermostat research item CLOSED
- Session 6 will also need a new memory for "simulate mode archived, real mode is default" once Story 1 ships, plus "UPS 24-min baseline" as reference fact

### Open Items for Next Session

1. **AUDIT `src/pi/power/` and `src/pi/hardware/ups_monitor.py`** — understand what exists, what's wired, what's not fired. This is the gate for B-043 PowerLossOrchestrator story scoping.
2. **Verify Story 1 landing** — once Ralph ships the `--simulate` removal + Restart=always, watch for any regressions.
3. **Real-mode drain test** — once Story 1 lands and collector is in real-OBD mode, redo the UPS drain drill to capture a real-production baseline (probably different from the simulate-mode 23:49).
4. **Real-data drill retry** — any cold-start drill on the Eclipse post-Story-1 produces Spool's first usable digital warm-idle data (supersedes Session 23 for the warm-idle fingerprint).
5. **US-204 / US-206 / US-208 execution** — Spool stands ready to review real drive data when it flows.
6. **Archive sim infrastructure** — confirm the CIO directive lands cleanly in Story 1's scope.

### Safety Advisories This Session
None new. Thermostat concern retired. Engine health confirmed good. No tuning-domain anomalies found (we had no real data to review anyway).

### Session 6 Stats
- 2 live drills executed
- 1 issue closed (I-016 benign)
- 5 inbox notes delivered to Marcus (story review, US-205 amendment, benchtest hygiene, collector resilience v1, Session 6 findings v2)
- 2 inbox notes to Ralph (US-200 backfill resolution)
- 3 direct file edits (I-016 annotation, sessions.md, drill protocol file)
- 1 reusable script added (`offices/tuner/scripts/ping_monitor.sh`)
- 3 memory files touched
- 2 significant misdiagnoses corrected mid-session (collector service existence, power-management code existence) — lesson for next session: grep the codebase before proposing to build something.

---

## Session 7 — 2026-04-23 → 2026-04-29 (multi-day, six calendar days)

**Context**: Power audit → Sprint 17 + 18 + 19 planning across multiple sprint cycles. First real-engine test data captured (Drives 3, 4, 5). Drain tests 2, 3, 4 (US-216 architectural failure mode confirmed across three independent tests). Sprint 19 consolidated ask delivered. Reusable tooling extracted from inline patterns.

### What Happened

**Power audit (2026-04-23, US-216 scoping)**
- Marcus requested audit per Session 6 commitment. Read ~2,500 lines across `src/pi/power/` + `src/pi/hardware/` (power.py, battery.py, ups_monitor.py, shutdown_handler.py, battery_health.py, etc.).
- Surfaced major finding: **most of the power-mgmt code is dead** — `PowerMonitor` (783 lines) and `BatteryMonitor` (690 lines) never instantiated in production; both have `enabled=false` defaults and zero orchestrator code paths.
- Found two latent hardware mismatches: BatteryMonitor's 11.0/11.5V thresholds are 12V-class for hardware that's actually 1S LiPo (3.0–4.3V via MAX17048); `lifecycle.py:450` reads `config.hardware.enabled` but config.json puts it under `pi.hardware.enabled` — silent misread.
- Filed `2026-04-21-from-spool-power-audit.md` (113 lines) — recommended US-216 stays L, listed 5 TDs (A–E).

**Drive 3 — first real Eclipse data (2026-04-23 16:36–16:46 UTC, 9.5 min)**
- CIO performed first physical engine test post-deploy. drive_id=3 minted, 3,272 rows tagged `data_source='real'`, full cold-start 20°C → 80°C warmup curve captured.
- **Engine graded EXCELLENT**: thermostat opens cleanly at 80°C (independent digital confirmation of I-016 benign close from Session 6), no DTCs/MIL, LTFT quantized at -6.25%, STFT actively closed-loop, O2 stoich switching, timing advance 4–18° BTDC progression, battery 13.4–14.4V healthy charging.
- Two bugs surfaced from Drive 3: `drive_summary` row exists but ALL THREE sensor metadata fields NULL (US-206 timing bug); `drive_end` event never fired because `BATTERY_V` via `ELM_VOLTAGE` kept ticking adapter-level after engine-off (drive_detector edge case).

**Sync pipeline diagnosis**
- CIO noticed `obd2db` empty in DBeaver. Confirmed: Pi `sync_log.last_synced_at = 2026-04-19T13:48:05Z` — nothing synced for 4 days. Server uvicorn up + reachable; `pi.sync` config key missing entirely from deployed config.
- Diagnosed Hypothesis 2 (sync wiring broken). Filed as P0 in Sprint 17 consolidated note. Ralph fixed via US-226 same day with auto-interval + drive_end + flush-on-boot triggers (annotated on Spool note inline).

**Sprint 17 / 18 / 19 grooming notes (chronological)**
1. `2026-04-22-from-spool-sprint16-release-readiness.md` — graded Sprint 16 stories: 4 GREEN (US-210, 212, 217, 219), 1 YELLOW (US-211 integration gap)
2. `2026-04-22-from-spool-sprint17-tuning-priorities.md` — Sprint 17 priorities (later superseded)
3. `2026-04-23-from-spool-post-deploy-system-test-findings.md` — found 4 deploy gaps post-Sprint-16 deploy
4. `2026-04-23-from-spool-sprint17-consolidated.md` — final Sprint 17 ask (CIO confirmed Sprint 17 launched same day; subsequent items rolled to Sprint 18)
5. `2026-04-23-from-spool-ups-drain-test-2-findings.md` — drain test 2 hard-crash analysis
6. `2026-04-23-from-spool-sprint18-design-nuances.md` — short note: 5 Sprint 18 design nuances from CIO conversation about car-off/sync flow
7. `2026-04-29-from-spool-sprint19-consolidated.md` — final Sprint 19 ask (152 lines)

**Drain test 2 (2026-04-23, post-Sprint-16 deploy)**
- US-216 deployed in config (30/25/20 SOC ladder), but PowerSource never flipped to BATTERY during 14:26 of real-OBD drain. Pi hard-crashed at SOC=63%, VCELL=3.364V. Same EXT4 orphan cleanup as Session 6.
- Filed extensive findings note with root cause analysis (UpsMonitor heuristic broken + MAX17048 SOC% mis-calibrated) and recommended trigger-source change SOC → VCELL.

**Drain tests 3 + 4 (2026-04-29)**
- Two more drain tests post-Sprint-18 deploy. Same hard-crash signature both times. Pi runtimes 10:14 (drain 3) and 10:02 (drain 4). PowerSource never flipped to BATTERY in either. **Four drain tests across 9 days, identical failure mode.**
- Sprint 18 didn't include US-216 trigger fix or UpsMonitor detection fix despite my Sprint 18 findings note.

**Drives 4 + 5 (2026-04-29)**
- Drive 4 (10:47 min): sustained warm idle while CIO recharged Eclipse battery after using it to jump another car. Post-jump-start alternator behavior captured. drive_summary metadata STILL NULL (third occurrence — US-228 broken).
- Drive 5 (17:39 min): full cold-start (31°C) → warm-idle (89°C) cycle. **drive_end fired cleanly on engine-off (second consecutive validation of US-229)**. LTFT_1 showed real variance for the first time (-7.03 to -4.69, 3 quantized notches) — almost certainly post-jump ECU adaptation reset. drive_summary metadata STILL NULL (fourth occurrence).

**Reusable tooling (CIO standing directive)**
- Created `offices/tuner/scripts/pi_state_snapshot.sh` — replaces 6+ inline SSH+sqlite bursts. Section flags: `--power --drive --conn --sync --service --fingerprint --drive-id N`.
- Created `offices/tuner/scripts/ups_drain_monitor.sh` — replaces 4 inline drain-monitor loops. Args: `--cadence`, `--mark`, `--tail`, `--stop`.
- Updated `offices/tuner/scripts/README.md` to point at both.

### Key Decisions

- **US-216 trigger source must change SOC → VCELL.** SOC% on this hardware shows 40-percentage-point error vs. true VCELL. Recommended VCELL thresholds (derived from 4 drain tests' empirical data): WARNING ≤ 3.70V, IMMINENT ≤ 3.55V, TRIGGER ≤ 3.45V (90s headroom before buck dropout at ~3.36V).
- **US-228 fix needs Option (a), not Option (b).** Sprint 18's UPDATE-backfill is empirically dead across 4 drives. Defer drive_summary INSERT until first IAT/BARO/BATTERY reading captured.
- **UpsMonitor BATTERY-detection needs additional rule.** Add `VCELL < 3.95V sustained 30s → BATTERY` as third detection rule. Drop CRATE rule if unreliable on this configuration.
- **MAX17048 calibration learning run is now Sprint 19 P1.** Calibration error is severe enough that SOC% is unusable as ladder-trigger source (motivates Decision #1).
- **LTFT post-jump adaptation behavior is HEALTHY**, not a defect. Track across next 3-5 drives.
- **Drive 5 supersedes Drive 3 as authoritative warm-idle baseline** in `knowledge.md` (longer capture, full cold→warm progression, post-jump alternator behavior context).
- **Pi display layout feedback** (CIO noted dashboard occupies ~1/3 of 3.5" screen): logged as Sprint 17/18/19 P3 — Ralph's lane, not safety-critical. Power-source indicator behavior validated correct.

### Current Vehicle State

- Stock turbo (TD04-13G), stock internals, stock ECU (modified EPROM). Mechanical baseline solid.
- **Three drives now captured on real Eclipse data**: Drive 3 (cold→warm 9.5min), Drive 4 (warm idle 10:47min post-jump), Drive 5 (full cold→warm 17:39min cycle).
- **CIO used Eclipse battery to jump another car on 2026-04-29.** Eclipse alternator now actively recharging. ECU's long-term fuel trim adaptation appears to have been reset (Drive 5 showed live LTFT trimming). Worth tracking next 3-5 drives for new learned-trim value.
- **Engine health graded EXCELLENT** across all three drives. No DTCs, no MIL, thermostat opens cleanly at 80°C (triple-confirmed — I-016 fully closed benign).
- Pi remains on UPS battery + wall power. Not yet wired to car accessory line (B-043 hardware task still pending).

### Open Items

- **Sprint 19 must-ship (3 P0s)**: US-216 SOC→VCELL trigger change + UpsMonitor BATTERY-detection fix + actually-fix-US-228 (Option a). All scoped in consolidated note.
- **MAX17048 calibration learning run protocol** (P1): Spool to author procedure spec, Ralph implements scripts.
- **UPS charge-path audit** (P1): Investigate whether wall charger actually brings VCELL to 4.200V at terminal.
- **Drive_summary sync still failing** (status=failed in sync_log) — separate from US-228 metadata bug. Worth flagging to Ralph.
- **Track LTFT post-jump adaptation** — Spool deliverable, watch next 3-5 drives for new learned-trim notch value.
- **DSM DTC interpretation cheat sheet** — long-running carryforward, unblocked by US-204 shipping. Documentation task. Post-drill priority.
- **Telemetry logger → UpsMonitor audit** (TD-E from power audit): Spool's 20-min audit owed.
- **Update knowledge.md "Real Vehicle Data" section** with Drive 5 fingerprint as new authoritative baseline. Done partially this closeout; full integration TBD next session.

### Session 7 Stats

- 8 inbox notes filed to Marcus (1 power audit + 7 sprint notes spanning Sprint 16/17/18/19)
- 4 drain tests run (drains 1 of Session 6 not counted; drains 2, 3, 4 this session — all hard-crash, US-216 architectural failure confirmed)
- 3 drives graded (Drives 3, 4, 5 — all engine-health EXCELLENT)
- 2 reusable scripts extracted (`pi_state_snapshot.sh`, `ups_drain_monitor.sh`)
- 6 calendar days, multi-sprint planning span (Sprints 16/17/18/19)
- Sprint 17 launched mid-session; Sprint 18 launched + shipped 8/8 mid-session; Sprint 19 scoped at session close

---

## Session 8 — 2026-05-01 → 2026-05-06 (multi-day, six calendar days)

**Context**: The 9-drain saga ran its course this session. Started with Sprint 21 (US-252) deployed but Drain 6 hard-crashing the same as Drains 1-5; ended with V0.24.1 hotfix closing the saga and a separate P0 regression discovered (engine telemetry capture has been broken since Drive 5 on April 29). One inflection-point session: ladder works, primary mission was silently broken behind it.

### What Happened

**Drain Test 6 (2026-05-01 21:58–22:19 CDT, V0.20.2 → Sprint 21 US-252 deployed)**
- Sixth consecutive hard-crash. Pi died at LiPo dropout knee with `power_log` containing only one `battery_power` row across the 21-min battery window. ZERO `STAGE_*` rows. US-252's "decouple tick from display" patch had no observable effect on production behavior.
- Sent two consolidated spec notes to Marcus: Sprint 22 (forensic logger US-262 + tick health-check US-263 + dashboard US-264 + boot-reason US-265 + 3 hypothesis discriminator stories US-266/267 + hygiene). Acceptance gate = Drain Test 7.

**Drain Test 7 (2026-05-02, V0.22.0 → Sprint 22 deployed)**
- First forensic-instrumented drain. Mid-test discovered `drain-forensics.timer` had not been auto-installed; manually patched the systemd unit (added `PYTHONPATH`) live to capture data. Ladder still didn't fire (zero STAGE rows) but the CSV ratified two big findings: (1) `throttled_hex=0x0` for entire 16 min — **CIO's Pi5-brownout hypothesis disproven**; (2) buck-converter dropout knee reproducibly at VCELL ≈ 3.30V. Documented as authoritative baseline in `knowledge.md`.

**Drain Test 8 (2026-05-03 morning, V0.23.0)**
- Tick-internal instrumentation (US-265) gave the discriminator data Sprint 23 was designed for. Result: tick was firing, thread was healthy, BUT every tick bailed with `reason=power_source!=BATTERY` while UpsMonitor's polling thread had clearly logged the BATTERY transition. Spool diagnosed as a Hypothesis 2 (gating-logic) bug; sent Sprint 24 P0 spec note (US-279 event-driven callback path + US-280 state-file silent-fail diagnose + US-281 anti-pattern doc + US-282 commit-vs-claim verifier + US-283 startup_log audit).

**Drain Test 9 (2026-05-03 evening, V0.24.0)**
- Sprint 24 deployed. Same hard-crash signature as Drain 8. Spool diagnosed as `_subscribeOrchestratorToUpsMonitor` silently bailing on `getattr(hardwareManager, 'powerDownOrchestrator', None) → None`; sent technical + stakes-context + bash-baseline-logger inbox notes to Ralph for an interactive debugging session. **Spool's diagnosis was wrong.**

**V0.24.1 Hotfix (2026-05-03 evening, CIO + Ralph interactive session)**
- Real root cause: **cross-module Python module identity.** `src.pi.hardware.ups_monitor` loaded twice via different `sys.path` prefixes produced distinct enum classes; `A.PowerSource.BATTERY != B.PowerSource.BATTERY` — every comparison False, every tick bailed. Hid for 4 sprints because tests import via single consistent path; only production has both prefixes loaded simultaneously.
- Fix shipped: self-aliasing module guard + import normalization + boot-time canary `_verifyOrchestratorCallbackWiring` + WARNING-level loud bails for required wiring + bash baseline-truth logger + integration test that exercises the dual-import asymmetry. Spool's "next fix is the last fix" framing in the stakes-context note ratified Ralph's discipline (silent-bail anti-pattern + dual-path integration test + bash logger).

**Drain Test 10 (2026-05-04, V0.24.1)**
- All six acceptance criteria from Spool's stakes-context note green: `stage_warning` at 3.689V, `stage_imminent` at 3.508V, `stage_trigger` at 3.41V, `systemctl poweroff` within 5s, graceful boot-table advance, no orphan rows. **9-drain saga officially closed.** Bonus: deploy-mid-drain restart at 08:28:33 served as a useful stress test — boot canary PASSED on the new PID, ladder re-fired NORMAL → TRIGGER under fall-through.
- Three additional graceful-shutdown cycles followed (May 4 14:09, May 4 14:39, May 5 23:59 → May 6 00:10 UTC). VCELL trigger threshold range 3.41 – 3.44V. Buck-dropout safety margin realized: 80 – 180 mV (≈ 30 – 90s drain time).

**Engine Telemetry P0 Regression Discovered (2026-05-05 / 2026-05-06)**
- CIO ran the 4G63 with ignition-on for the May 4 + May 5 test cycles. Both produced `connect_success` rows in `connection_log` but **zero `drive_start` events, zero new `drive_summary` rows, zero new `realtime_data` PID samples.** Engine-data tables frozen since Drive 5 (April 29). 5+ days of broken capture hidden behind the saga.
- Diagnosed via boot-1 journal: `_initializeConnection` blocks the orchestrator init thread for 27 HOURS on boot -1 (vs documented 30-sec timeout) and 82 minutes on boot 0. DriveDetector + OBD polling loop never start in time. Sent Sprint 26 P0 spec note to Marcus (6 stories) — Marcus folded it into Sprint 25 (`sprint/sprint25-engine-telemetry`, US-284–291).

**Knowledge Base Update (2026-05-05, Spool-side, per Marcus's standing invitation)**
- Appended two subsections to `knowledge.md` "UPS HAT Dropout Characteristics" section: (1) "Drain 7 baseline ratified — Drains 8, 9, 10" — `throttled_hex=0x0` confirmed across ~50 min combined battery runtime, brownout hypothesis conclusively buried; (2) "Post-fix signature — Drain Test 10 + May 4-5 cycles (V0.24.1 onward)" — table of 4 graceful-shutdown cycles with TRIGGER firing 3.41-3.44V, post-fix runtime envelope **10-13 min from key-off to graceful poweroff** (vs prior 16-min hard-crash budget). Updated References section + Session Log entry.

**Inbox Notes Filed (Spool → others)**
- Marcus: Sprint 22 spec (drain-forensics + 3 hypothesis discriminators), Sprint 23 spec (tick-instrumentation + ladder fix discriminator-trio), Sprint 24 spec (event-driven callback fix + carryforward audit), Sprint 26 P0 spec (engine telemetry regression — became Sprint 25).
- Ralph: Drain 9 technical analysis (the wrong-diagnosis note), why-the-ladder-matters stakes context, bash baseline-truth logger spec.

**Inbox Notes Received (others → Spool)**
- Marcus 2026-05-03: Sprint 24 grooming response + carryforward audit confirmation + standing invitation to update UPS HAT doc with Drain 8+ data.
- Ralph 2026-05-04: V0.24.1 Drain 10 PASSED + correction to Spool's Drain 9 misdiagnosis + acknowledgment of stakes-context discipline that landed in V0.24.1.

### Key Decisions

- **Spool diagnosed Drain 9 incorrectly.** Claimed `_subscribeOrchestratorToUpsMonitor` silently bailed on a None-attribute check (Candidate 3 hypothesis). Actual root cause was one layer below the wiring: cross-module Python enum identity. Ralph's correction received gracefully and saved as a feedback memory (`feedback_cross_module_enum_identity.md`) to prevent repeating the interpretation pattern. Lesson: when a guard against an enum value always bails despite the value being clearly right, suspect dual import paths producing distinct enum classes BEFORE diagnosing at the wiring layer.
- **Pi5-brownout hypothesis is now conclusively dead.** ~50 min combined battery runtime across Drains 7+8+9 with `throttled_hex=0x0` for every sample. Any future hard crash with `throttled_hex != 0x0` is a different bug class.
- **Post-V0.24.1 in-car operational envelope: 10-13 min from key-off to graceful `systemctl poweroff`.** Updated `knowledge.md` to supersede the prior 16-min hard-crash budget.
- **Stage state-machine has a non-load-bearing latching bug.** Fluctuating VCELL near thresholds re-fires WARNING/IMMINENT rows; TRIGGER is atomic. Logged as Sprint 25 US-288 (P2). Pollutes analytics but doesn't compromise safety.
- **`battery_health_log` column semantics are wrong.** `start_soc` / `end_soc` columns hold VCELL voltage (3.4-4.2V range) not SOC percentage. Logged as Sprint 25 US-289 (P2). Recommended rename rather than data-shape fix since SOC is known-broken anyway.
- **Engine telemetry P0 regression takes priority over all other Sprint 25 items.** The Pi's primary mission (capture engine data) has been broken for 5+ days. Sprint 25 US-284 + US-285 are the gate to any further drive captures.

### Current Vehicle State

- Stock turbo (TD04-13G), stock internals, stock ECU (modified EPROM). No mechanical changes this session.
- **Last captured drive remains Drive 5 (April 29).** No new engine data despite two ignition-on cycles (May 4 + May 5).
- **Engine health LAST GRADED EXCELLENT** at Drive 5. No new diagnostic data this session — the saga consumed all the test cycles and they were all on-bench (engine off) for the drain tests, plus the two ignition-on cycles produced zero data due to the orchestrator-init regression.
- **LTFT post-jump adaptation tracking is paused** until Sprint 25 unblocks engine telemetry capture. Last data point: Drive 5 showed -7.03 to -4.69 (3 quantized notches actively re-learning).
- **Pi power-management is now solid.** V0.24.1 ladder has fired graceful shutdowns 4 times. Boot canary running every restart.
- **Pi NOT yet wired to car accessory line** — bench setup unchanged. Wire-in task still pending CIO hardware step. Now unblocked from the safety side; blocked on the engine-telemetry-capture side until Sprint 25 lands.

### Open Items

- **Sprint 25 P0 (in progress)**: Ralph diagnosing/fixing `_initializeConnection` blocker (US-284), restoring engine telemetry capture (US-285), shipping bench-test harness for engine+OBD path (US-286). Drive 6 gated on this.
- **`startup_log` writer (US-287, P1)**: schema shipped Sprint 22, audit closure Sprint 24, but no rows ever written. Boot-reason post-mortem currently requires manual `journalctl --list-boots` parsing every drain.
- **Drain 10 forensic CSV `pd_stage=unknown / pd_tick_count=-1`**: minor state-file-writer artifact. Production runtime path was correct; not load-bearing but worth investigating in a future sprint to make forensic logger column completeness load-bearing again.
- **LTFT post-jump adaptation tracking** — Spool deliverable, paused waiting for Drive 6+. Need 3-5 more drives to confirm new LTFT lock value.
- **DSM DTC interpretation cheat sheet** — long-running Spool research carryforward, still pending.
- **Telemetry logger → UpsMonitor audit** (TD-E from prior power audit): Spool's 20-min audit still owed. Lower priority now that V0.24.1 + boot canary make the wiring robust.
- **`offices/tuner/scripts/pi_state_snapshot.sh` + `ups_drain_monitor.sh`** — reusable scripts from Session 7 still useful; not exercised this session because the forensic-logger CSV gave better data.

### Diagnostic Record (honest disclosure)

Spool's diagnostic accuracy this session was mixed:
- ✅ Drain 7 forensic logger spec — correctly identified what data we needed; columns landed and proved load-bearing for Drain 8 diagnosis.
- ✅ Pi5-brownout hypothesis testing — `throttled_hex` column called out as the discriminator; data conclusively buried CIO's hypothesis.
- ✅ Stakes-context framing for Ralph — three of three principles in the "why-the-ladder-matters" note landed in V0.24.1 (silent-bail anti-pattern, integration-test-that-catches-wiring-bugs, bash baseline-truth logger).
- ❌ Drain 9 misdiagnosis — wrong layer (wiring vs module-identity). The "next engineer who reads the inbox notes" warning Ralph wrote in his closeout note is the right framing. Memory saved to prevent repeat.
- ✅ Engine telemetry regression diagnosis — boot journal evidence (27-hour gap on boot -1) is reproducible by Ralph on the bench in under 60 seconds; hypothesis about which sprint introduced it (Sprint 20 US-244 non-blocking BT-connect) explicitly disclaimed as still hypothesis until Ralph confirms.

### Session 8 Stats

- 7 inbox notes filed (4 to Marcus: Sprints 22/23/24/26-→25 + 3 to Ralph: Drain-9 technical, stakes-context, bash logger spec)
- 5 drain tests run (Drains 6, 7, 8, 9, 10 — Drain 10 the closure event)
- 0 drives graded — capture pipeline broken for entire session
- 1 hotfix shipped + validated (V0.24.1)
- 1 P0 regression diagnosed (engine telemetry capture)
- 2 auto-memory entries saved (`feedback_cross_module_enum_identity.md`, MariaDB CLI Windows-side reference)
- 1 knowledge.md substantive update (UPS HAT Dropout Characteristics, two new subsections)
- 6 calendar days, three-sprint span (Sprint 22 deployed → Sprint 23 deployed → Sprint 24/V0.24.1 deployed → Sprint 25 loaded)
