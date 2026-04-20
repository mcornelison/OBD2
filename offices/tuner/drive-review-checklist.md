# Spool — Structured Drive-Review Checklist

> Human-judgment layer for reviewing a real-car OBD-II capture. Complements `scripts/review_run.sh` which produces the raw numbers — this document tells Spool (and anyone grading data) what those numbers *mean*, what "passing" looks like, and what specific red flags to hunt for.
>
> **Use after every real-car data capture.** Intended for first-real-drive reviews through Phase 1, with Phase 2 additions (wideband, ECMLink) noted inline.

---

## Pre-Review: Context Collection

Before opening the data, capture the context. These questions shape interpretation.

| Question | Why it matters |
|----------|----------------|
| Was the engine **cold-started** or warm? | Cold-start enrichment masks trim behavior. Warm-start data is the baseline. |
| **Ambient air temperature** (F)? | IAT heat-soak analysis depends on delta from ambient. Also affects warmup rate. |
| **Idle-only, short drive, or sustained drive**? | Drive phase dictates which tables in the checklist apply. Idle = Section B only. Drive = Sections B + C + D. |
| **Duration wall-clock** and **duration OBD-connected** from `connection_log`? | If connected < 50% of wall-clock, there's a data-quality issue (connection drops, TD-023 class). Review data as sampled, note the gap. |
| **Any sensor or mod changes since last capture**? | Correlate any new behavior against what changed. |
| **Any DTCs stored** (once Sprint 14 DTC retrieval lands)? | Always check first — a stored code shapes every other interpretation. |

---

## Section A — Pipeline Integrity (Before Any Tuning Judgment)

Goal: confirm the data is trustworthy before grading it. Runs first, every review.

| Check | Pass Criteria | Fail Action |
|-------|---------------|-------------|
| Pi ↔ server row counts match | Byte-for-byte identical for realtime_data, statistics, connection_log in the time slice | Flag sync-layer bug to Ralph. Do not proceed with tuning review. |
| `data_source = 'real'` on all rows (once CR #4 lands) | 100% of rows tagged `real` | Investigate: simulated rows contaminating real drive, or untagged real rows. |
| No missing timestamps (gaps > expected cycle time × 3) | Cycle gaps ≤ 2× the expected per-PID cycle time | Gaps → connection drop. Map gaps to `connection_log` events to confirm cause. |
| All expected PIDs present | Every PID in the current poll set has ≥1 row in the slice | Missing PID → either ECU didn't respond, or collector bug. Check `connection_log` for error messages. |
| No impossible values (NULL, Inf, negative where impossible, etc.) | Every value physically plausible | NULL or Inf → collector/parser bug. Negative coolant / negative RPM → wiring or unit conversion bug. |

---

## Section B — Idle Health (Applies to Every Real Capture)

Every capture includes idle data. This is the baseline comparison layer. Compare to `specs/grounded-knowledge.md` "Warm-Idle Fingerprint" from Session 23.

### B.1 — Fuel Trims (Most Important Health Signal)

| Signal | Healthy | Concerning | Alarm |
|--------|---------|------------|-------|
| **LTFT (warm idle, closed-loop)** | 0.00% ± 2% | ±2-5% drift | >±5% — material fuel-system change |
| **STFT amplitude (warm idle)** | ±1-3% noise around zero | ±3-8% amplitude | >±8% or biased one direction |
| **STFT sustained offset** | 0% ± 1% average | 2-5% sustained positive (lean compensation) OR negative (rich compensation) | >5% sustained — active lean or rich problem |

**Interpretation keys:**
- **LTFT drift positive** (adding fuel) = lean issue (vacuum leak, weak fuel pump, injector clog, MAF drift reading low)
- **LTFT drift negative** (subtracting fuel) = rich issue (leaky injector, high fuel pressure, MAF drift reading high)
- **LTFT = 0 but STFT amplitude high** = transient fueling problems the ECU can't baseline out — worn/contaminated O2 sensor, or intermittent leak
- **STFT locked at 0** during closed-loop steady state = O2 sensor not switching (stuck, shorted, or ECU ignoring it — check fuel system status PID)

### B.2 — Closed-Loop Operation Check

| Signal | Healthy (warm idle) | Concerning | Alarm |
|--------|---------------------|------------|-------|
| **O2 B1S1 voltage** | Full swings 0.1V ↔ 0.9V, ~0.5-2 Hz switching | Voltage stuck 0.4-0.5V (lazy sensor) or biased hi/lo | Voltage flat 0V or flat 1V (sensor dead, wiring break, or extreme rich/lean) |
| **Fuel system status** (once US-199 lands) | `CL` (closed-loop) after warmup | Stays `OL-cold` past ~3 min warm running | Any `OL-fault` code |
| **Closed-loop entry time** (from cold-start capture) | 60-120 seconds typical for a 4G63 | >3 minutes | Never enters closed-loop |

### B.3 — Idle Stability

| Signal | Healthy | Concerning | Alarm |
|--------|---------|------------|-------|
| **RPM variation at idle** | ±50-75 RPM around target | ±75-150 RPM | >±150 RPM hunting |
| **MAF variation at idle** | Tight (±5% of mean) | ±5-15% | Spiky, bursty, or flatline |
| **Engine Load variation at idle** | ±2% of mean | ±2-5% | Spiky |
| **Idle RPM target hit** | 650-900 RPM warmed | Idle 600-650 or 900-1100 | Idle <600 (stall risk) or >1100 (sticking throttle, IAC valve) |

**This car's Session 23 baseline**: RPM 761-852, MAF 3.49-3.68 g/s, Engine Load 19.22-20.78%. Use these as reference values. Significant drift between captures on the same engine conditions = investigate.

### B.4 — Coolant & Thermal

| Signal | Healthy | Concerning | Alarm |
|--------|---------|------------|-------|
| **Warm idle coolant** | 180-210°F (82-99°C) | <180°F sustained in warm weather | <160°F sustained (thermostat stuck open) OR >220°F (head gasket risk) |
| **Coolant ramp rate from cold-start** | Smooth rise to 180°F within 5-10 min idle | Stalls or plateaus below 180°F | Never reaches 180°F — thermostat stuck open |
| **Coolant stability at idle** | Flat ±1°F once warm | Slow climb indicating heat soak in traffic | Rapid rise (>5°F/min) = cooling system problem |
| **IAT at idle** | Near ambient at cold-start, rises 20-40°F above ambient during sustained idle (heat soak) | Rises >60°F above ambient (severe heat soak) | Spikes or flatlines (sensor failure) |

**Spool's current watch item**: Session 23 captured coolant plateau at 73-74°C (163-165°F), below full op temp. If next capture shows same plateau after sustained warmup, investigate thermostat (stuck open or partially stuck).

### B.5 — Timing Advance at Idle

| Signal | Healthy (stock 2G) | Concerning | Alarm |
|--------|---------------------|------------|-------|
| **Timing at warm idle** | 10-15° BTDC (community norm for stock 2G idle) | 5-10° BTDC consistent (conservative EPROM or ECU trim) | <5° BTDC (ECU pulling timing defensively — possible knock event in adaptive) OR >20° BTDC (advanced base timing — check for distributor misalignment) |
| **Timing stability** | ±1-2° at steady idle | ±3-5° wandering | Erratic swings |

**Spool's current watch item**: Session 23 captured 5-9° BTDC at idle, below community norm. Not alarming — possible modified EPROM, adaptive trim, or rounding. Re-examine at ECMLink baseline.

---

## Section C — Warmup Behavior (Cold-Start Captures Only)

Only applies if capture includes the cold-start transition.

### C.1 — Warmup Enrichment Phase

| Signal | Expected Behavior |
|--------|-------------------|
| **STFT during cold warmup** | Should be 0% (open-loop, ECU ignoring O2) |
| **LTFT during cold warmup** | Frozen at last closed-loop value; ECU doesn't update trim in open-loop |
| **Fuel system status** | `OL-cold` or `OL-warmup`, should transition to `CL` when coolant reaches ~150-160°F |
| **O2 B1S1 voltage** | May be at extremes (rich 0.9V) as sensor heats up; ignored by ECU |
| **Idle RPM** | Elevated 900-1200 RPM during warmup, drops to 750-800 RPM steady target |

### C.2 — Closed-Loop Transition (KEY SIGNAL)

| Signal | Healthy | Concerning | Alarm |
|--------|---------|------------|-------|
| **Coolant temp at CL transition** | 150-165°F (66-74°C) | >180°F before CL entry | Never enters CL |
| **O2 switching at CL entry** | Abrupt start of rich/lean switching when fuel system status flips to `CL` | Gradual onset over 30+ seconds | Never switches |
| **STFT activity at CL entry** | Small adjustments begin (±1-2%) | Large immediate swings (>±5%) indicate underlying lean/rich condition that warmup masked | — |

### C.3 — Warmup Failures to Watch For

- **Open-loop hang** — fuel system status stays `OL` past 3 minutes of running. Possible causes: ECU coolant sensor drift (reading cold), dead O2 sensor, faulty CTS connection.
- **Closed-loop oscillation** — O2 switches, STFT swings, STFT fails to stabilize. ECU can't find stoich. Possible causes: fuel pressure instability, vacuum leak size comparable to injector flow correction, MAF drift.
- **Warmup stall** — Idle drops below 600 RPM during warmup transitions. ICS valve fault or idle map offset.

---

## Section D — Load / Drive Behavior (Drive Captures Only)

Requires non-zero speed and load above idle.

### D.1 — Part-Throttle Cruise

| Signal | Healthy |
|--------|---------|
| **STFT under cruise** | ±3% around 0 |
| **LTFT under cruise** | 0% ± 3% (matches idle LTFT) |
| **Engine Load** | 25-55% at normal cruise |
| **Timing Advance** | 15-35° BTDC depending on load, smooth |
| **MAF** | 10-40 g/s at cruise |
| **O2 switching** | Normal 0.5-2 Hz switching |

### D.2 — Wide-Open Throttle (WOT) — CRITICAL SAFETY REVIEW

**Only graded by Spool when Phase 2 is live (wideband AFR installed). Without wideband, narrowband O2 at WOT is unreliable and Spool cannot responsibly grade AFR at WOT.**

| Signal (Phase 2, with wideband) | Healthy (stock turbo) | Alarm |
|--------|---------|-------|
| **AFR at WOT under boost** | 11.0-11.8:1 (rich target for stock turbo on pump gas) | >12.5:1 lean under boost — **immediate danger, abort analysis, notify CIO** |
| **Peak boost (stock TD04-13G)** | 10-14 psi | >15 psi sustained — boost creep, aggressive BCS, or spring-pressure issue |
| **Timing under boost** | 12-20° BTDC (stock ECU) | Excessive retard >5° from expected baseline — ECU knock response, possible real knock |
| **Fuel system status** | `OL-drive` (open-loop commanded-rich at WOT) | Stays `CL` under WOT — ECU didn't command enrichment, lean danger |
| **Load** | 80-100% during WOT pulls | — |
| **MAF** | 60-150 g/s during WOT | Saturation near 150 g/s on stock MAF = upgrade trigger |

### D.3 — Decel and Deceleration Fuel Cut (DFCO)

| Signal | Expected |
|--------|---------|
| **Fuel system status during decel** | `OL-drive` with fuel cut |
| **STFT during decel** | Ignored (fuel cut active) |
| **Coolant / IAT during decel** | No change (not a thermal event) |
| **Transition back to cruise** | Smooth re-engage of fuel, closed-loop resumes within 2-3 seconds |

---

## Section E — Drive-Level Red Flags (Any Capture)

Quick-scan items. One hit = investigate. Multiple hits = stop and diagnose before next drive.

### Engine Health Red Flags

- [ ] **Coolant spike >220°F** at any point — head gasket risk
- [ ] **IAT >160°F sustained** — intercooler / intake path heat soak
- [ ] **RPM cutoff at unexpected point** (rev limiter at <7000 RPM on cold engine, or cutoff mid-pull) — check DTCs
- [ ] **LTFT drift >±5%** since prior capture — fuel system change
- [ ] **STFT biased >+5% sustained** — lean condition developing
- [ ] **STFT biased <−5% sustained** — rich condition developing
- [ ] **O2 B1S1 stuck at one extreme** (>10 seconds without switching in closed-loop) — sensor failing
- [ ] **Timing retard >10° below expected baseline** — ECU defensive response, possible knock
- [ ] **MAF ceiling hit** (>140 g/s sustained) — sensor saturation approaching
- [ ] **MAF drop-outs** (momentary 0 g/s values while engine running) — wiring or sensor

### Crankwalk Warning Signs (7-bolt 4G63 Specific)

Crankwalk is the #1 4G63 failure mode. Watch for:
- [ ] **P0300 (random misfire)** stored or pending — can be early crankwalk indicator
- [ ] **Timing advance suddenly erratic** — crankshaft sensor reading affected by end-play
- [ ] **RPM signal noise / spikes** — crank position sensor confused by endplay
- [ ] **Hard launch → stumble pattern** — crank walking against thrust bearing under clutch load

**If any two of these appear together**: stop driving. Pull clutch, inspect crank end-play with dial indicator. Out-of-spec = engine down, crankwalk confirmed.

### Sensor Failure Red Flags

- [ ] **Coolant temp flatline** — sensor failure OR stuck thermostat (distinguish by ramp rate from cold-start)
- [ ] **IAT flatline** — sensor failure OR car hasn't moved enough to change IAT
- [ ] **MAF 0 g/s while RPM >0** — MAF power lost or signal disconnected
- [ ] **TPS stuck at one value** — TPS failure or wiring
- [ ] **Speed signal erratic at steady cruise** — VSS failing

---

## Section F — Data-Capture Quality Assessment

Separate from tuning judgment — how good is the data itself?

| Metric | Target | Failing Threshold |
|--------|--------|-------------------|
| **Connected ratio** (OBD-connected time / wall-clock capture time) | >90% | <70% (TD-023-class issue; data still usable but flag it) |
| **Per-PID sample rate** (measured) | Matches theoretical from obd2-research.md §1 | <50% of theoretical = ECU or adapter issue |
| **Missed cycles** (gaps > 2× cycle time) | 0 | >5 per minute |
| **Capture duration** | ≥5 min for meaningful idle review; ≥15 min for drive review | <2 min idle → not enough data for meaningful review beyond pipeline integrity |

---

## Section G — Reporting

After grading, Spool produces an inbox note to Marcus (PM) with:

1. **Overall grade** — one line: "Engine healthy, pipeline clean, ready for next phase" OR specific finding
2. **Section A pipeline integrity** — pass/fail + any sync-layer concerns for Ralph
3. **Section B idle health** — baseline comparison vs. grounded-knowledge.md fingerprint
4. **Section C/D warmup/drive observations** — if applicable
5. **Section E red-flag triage** — any items flagged
6. **Section F data quality** — what limitations apply to the review
7. **Change requests** — any specs, thresholds, or collection requirements that need updating based on findings
8. **Open questions for next capture** — what we couldn't determine from this one

Template: see prior `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md` as reference format.

---

## Meta: What This Checklist Is Not

- **Not a replacement for DSMTuners community knowledge** — use it WITH the community's hard-won norms documented in `offices/tuner/knowledge.md`
- **Not automated** — this is human-judgment structured. The `review_run.sh` script produces the inputs; this document is the cognitive framework.
- **Not static** — updates as we learn more about this specific car, each capture refines baseline expectations
- **Not the tuning roadmap** — that's Spool's job. This is quality control on *existing* data, not planning *next* mods.
