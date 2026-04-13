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
