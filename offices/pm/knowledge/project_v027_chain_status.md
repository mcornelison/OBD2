---
name: project-v027-chain-status
description: "Current state of the V0.27 chain (Sprints 27-36 / V0.27.0 thru V0.27.10) — what's deployed, what's IRL-validated, what gates remain. Updated 2026-05-14 Session 34."
metadata: 
  node_type: memory
  type: project
  originSessionId: 2ddd576b-e9d6-4ce5-a624-18f342635e8a
---

# V0.27 chain status (Session 34 / 2026-05-14)

Per Mike 2026-05-08 chain-end-merge rule: main = "fully validated stable." Sprint
branches stay deployed-but-pre-merge; whole V0.27 chain merges TOGETHER via
`/chain-validated` after IRL drills pass. See [[project-workflow-chain-end-merge]].

## Session 38 (2026-05-18) — V0.27.14 Phase-2 power-watch DEPLOYED → SELF-BRICKED IRL → CIO BIG FAIL; hotfix pushed, NOT re-deployed (AUTHORITATIVE)

> This block is the current truth. The "Session 37 CLOSEOUT" block below is
> SUPERSEDED by this one (kept for DOA + gate-fail lineage audit trail).

- **What deployed:** V0.27.14 = the Phase-2 power-watch body (`d049e30..d204dec`):
  `eclipse-powerwatch` = sole shutdown decider (legacy `PowerDownOrchestrator`
  ladder deleted, 9adb0fb); bounded VCELL-floor pre-shutdown pipeline +
  shutdown-type/WiFi-aware `sync_with_server`; interim `pi.powerWatch.*` bounds.
  PM commits `17625d5`/`0125417`/`8c5dc51`; Pi + chi-srv-01 both verified
  V0.27.14 @ `0125417` (CIO directed Pi+server scope). Plan-driven, NO
  sprint.json; `sprint_lint` 1 ERROR = expected dead-Sprint-37 drift (not
  mutated).
- **IRL RESULT = SELF-BRICK / BIG FAIL.** CIO ran the power on/off test;
  `eclipse-powerwatch` powered the Pi OFF ~10-15s after **every** boot, even
  with external power ON (3× repeated; Pi unusable — worse than I-036/I-037).
  **Root cause:** trigger acted on `UpsMonitor.getPowerSource()` — a VCELL-trend
  HEURISTIC, not ground-truth — which reports BATTERY on the normal boot VCELL
  sag within ~2 ticks (~10s); the controller acted on that first unconfirmed
  BATTERY (spec sec 6.2 "sustained, **debounced**" was under-implemented).
  Aggravator: the T4 fail-safe treated a failed boot-time VCELL read (I2C
  settles late) as floor → instant poweroff (catastrophic default direction).
  **CIO verdict: Sprint 38 / Phase-2 = BIG FAIL** — bricking regression shipped
  to hardware on first test; the hotfix does not erase the FAIL.
- **Recovery:** sshd comes up before powerwatch; CIO masked
  `eclipse-powerwatch.service` (retry-loop, `OK_MASKED`); collector
  `eclipse-obd` untouched; **Phase-1 EEPROM unattended-wake NOT implicated,
  still valid**. Pi/server still run the bricking `0125417`.
- **Hotfix (Ralph, committed, pushed at Session-38 closeout, NOT re-deployed):**
  `84b5469` debounced sustained-confirmation gate (BATTERY must hold across
  `confirmWindowSec` re-sampled at `confirmPollSec`; transient blip aborts, no
  poweroff) + `bootGraceSec` boot-grace + reversed uncertain-VCELL direction
  (failed read never forces poweroff). `4edbdc1` = trigger on **X1209 GPIO6 PLD
  ground-truth** instead of the VCELL heuristic (more fundamental fix).
  `3047673` = RCA/recovery/**GPIO6 open question** handoff. New config
  (Spool-tunable): `bootGraceSec=120`/`confirmWindowSec=20`/`confirmPollSec=5` +
  regression tests. Ralph's full not-slow pi-suite gate status unknown at
  closeout.
- **Record correction:** `deploy-pi.sh` US-253 step DOES enforce EEPROM
  `POWER_OFF_ON_HALT=0` (this run rewrote 1→0) — the earlier "deploy does not
  touch firmware / wake already applied separately" framing was WRONG. The wake
  enable IS the deploy step (persists across reboots), not a separate manual op.
- **Re-deploy gate (the next signal):** ALL of — (a) Ralph hotfix-verification
  complete (pi suite + runsheet "deploy-safe" line); (b) **GPIO6 open question**
  resolved; (c) CIO direction → `/sprint-deploy-pm` Phases 4–7 (V0.27.14→
  **V0.27.15**) + `systemctl unmask eclipse-powerwatch.service` + corrected
  runsheet (must add "boot N× on external power, Pi STAYS UP >
  bootGrace+confirmWindow ~3 min, no self-poweroff" precondition BEFORE
  on-battery cycles). Then Drain 27 (≥8h-rested) + chain bigDoD.
- **Filed:** I-038 (SEV-1 bricking regression) + TD-053 (T8 real-invocation
  guard stubbed `isOnBattery=True`; trigger never exercised the real
  transient/boot-sag signal) + feedback memory
  `[[feedback-spec-invariant-validated-against-real-signal]]`.
  regression_manifest F-008/F-011/F-012 STAY FROZEN. Chain merge BLOCKED. Still
  owed: Ralph Case-1 forced-low-VCELL induction cmd; BL-018 (now also covers the
  new debounce/grace bounds); Drive 12 retest + US-338/339/340/340b IRL.

## Session 37 CLOSEOUT (2026-05-18) — V0.27.13 deployed; instrument hotfix VALIDATED; 2 gate fails; CIO power-mgmt-101 reset (SUPERSEDED by Session 38 above)

> SUPERSEDED by the Session 38 DEPLOY block above (kept for DOA + gate-fail
> lineage audit trail). The "Session 37 update (2026-05-17)" block further
> below is also SUPERSEDED.

- **Lineage:** Drain 26 FAILED V0.27.11. V0.27.12 = honest boot-progress
  instrument (plan-driven, NO sprint.json per CIO; design+1441-line plan on
  branch = contract of record) deployed `9060b75` — but **DOA**: boot-progress
  units' PYTHONPATH lacked `<repo>/src` → bare `from pi.X` ModuleNotFoundError
  caught fail-safe → `startup_log` write + `ADD COLUMN` migration silently
  skipped. Same class as 9-drain cross-module-identity / `[[feedback-path-convention-no-src-prefix]]`.
- **V0.27.13 hotfix `d049e30`** (Ralph `f55b364` + PM RELEASE_VERSION bump):
  units mirror `src/pi/main.py` PYTHONPATH (`src/`+root); drop Pi-side
  `--nas-enabled` (`/mnt/projects` is chi-srv-01-only); add systemd-invocation
  guard test. Deployed to Pi only (CIO-scoped). PM commits this session:
  `ac6ca32`, `9060b75`, `519dec1`, `d049e30`.
- **V0.27.13 instrument import/schema hotfix = VALIDATED** (Spool post-clean-
  reboot read-only re-verify: arm runs clean, real 32-hex boot_id,
  `prior_boot_last_stage`/`prior_boot_reason` columns present, verdict-readback
  works, stale 64 KB trail rotated). That layer is DONE.
- **3-case drill → 2 gate fails; CIO STOPPED drill:**
  - **Finding A** — clean `systemctl poweroff` → next-boot verdict
    `0/RUNNING/crashed_during_operation`; `CLEAN_COMPLETE` rung never
    written/honored (ExecStop-at-shutdown semantics suspect). "Loud-and-safe"
    (safe direction, still fails gate). RCA = Ralph's.
  - **Finding B (CIO TOP PRIORITY)** — Pi5 PMIC soft-off after `poweroff` +
    UPS-HAT holds the 5V rail → PMIC never sees a power-cycle edge → Pi will
    NOT auto-boot on wall/car-power return; only a physical button press.
    In-car = bricks after every clean shutdown. **Worse than original I-036.**
    Grounded in on-Pi EEPROM truth (RPi 5 Model B Rev 1.1; `POWER_OFF_ON_HALT`
    /`WAKE_ON_GPIO` unset = Pi5 firmware defaults; EEPROM update available +
    uninstalled).
- **CIO power-management-101 phased reset (THE plan):** Phase 1 = prove
  unattended graceful-shutdown→auto-boot loop, zero human press (THE gate;
  subsumes Finding B). Phase 2 = server-sync determined by shutdown-type +
  WiFi. Phase 3 = BT/OBD reconnect on car/wall power. Sequence: fix B → then A
  → re-run 3-case drill → Drain 27 (≥8h rested pack, no rest-shortcuts).
  Bug-1 (real I-036 I/O-storm shutdown) stays DEFERRED behind a trusted
  instrument. Spool-proposed Phase-1 acceptance = 5 clean unattended cycles
  (CIO to ratify). Ralph already started Phase-2 power_watch (unpushed T3–T9;
  conservative interim bounds → `BL-018`, Spool empirical tuning owed, gated
  behind Phase 1).
- **Open CIO Qs** (PM surfaced, not answered): exact UPS-HAT model/vendor +
  PG-pin broken out + auto-on register? GPIO3-wake hardware mod acceptable?
  Phase-1 acceptance count = 5? Plus: Ralph owes Case-1 forced-low-VCELL
  induction cmd; EEPROM update should be installed before designing the wake fix.
- regression_manifest F-008/F-011/F-012 FROZEN (not re-validated). Chain merge
  BLOCKED on Finding B then A. PM closeout commit/push this session; nothing
  merged to main.

## Session 37 update (2026-05-17) — V0.27.12 DEPLOYED, chain still BLOCKED [SUPERSEDED by 2026-05-18 closeout above]

- **Drain 26 (2026-05-15) FAILED V0.27.11.** Controlled wall-disconnect, engine
  off, cleanest possible. Pre-verif all green (US-341/342 src + polkit + pkcheck
  exit 0) — deploy sound, failure downstream. I-037 still broken, NOT
  battery-confounded (logic fact: poweroff-accepted marker count=0 yet new-boot
  canary wrote prior_boot_clean=1). I-036 unproven — Spool overrode the ≥8h rest
  rule (pack took drains 22/23/24/25 + 3 hard crashes same day); runtime delta
  leans real-fault but Drain 27 on rested pack is the arbiter. Spool gave NO RCA
  hypothesis (wrong twice this chain); routed full evidence + RCA ownership to
  Ralph. Marcus sent Ralph the definitive V0.27.x close-out validation gate set
  (`offices/ralph/inbox/2026-05-15-from-marcus-v027x-closeout-validation-gates.md`).
- **V0.27.12 = Sprint 38, branch `sprint/sprint38-bugfixes-V0.27.12`** (off the
  V0.27.11 chain tip), HEAD `9060b75`. **NO sprint.json — by CIO direction**;
  Ralph plan-driven deep-RCA (design doc `docs/.../2026-05-15-honest-boot-progress-instrument-design.md`
  + 1441-line plan; T1–T15 + review commits + L9 real-chain integration).
  Docs are the contract of record.
- **What V0.27.12 is:** the "honest boot-progress instrument." Architectural RCA
  — the shutdown/canary subsystem was "fixed" 4× (US-308/330/341/342) and Drain
  26 still failed: the signature of an architectural root cause. The journal-scan
  boot canary is **removed, not repaired** (its witness is destroyed by the very
  I/O-storm crash it must detect). Replaced by a dirty-by-default append-only SD
  breadcrumb file + a systemd finalizer where `CLEAN_COMPLETE` is written by
  exactly one ExecStop writer = positive proof only; absence ⟺ crash, highest
  milestone says where it died. New Pi units: `boot-progress-arm.service` +
  `boot-progress-finalize.service` (installed, enabled, active).
- **Bug split (critical for honest reporting):** V0.27.12 fixes **Bug 2 only**
  (the instrument lied → it now tells the truth). **Bug 1** — the Pi physically
  fails to power off under I/O contention at TRIGGER (the real I-036) — is the
  **explicitly named follow-on, NOT closed by V0.27.12.** V0.27.12 makes Bug 1
  measurable; it does not fix it.
- **Verification:** Pi suite `pytest tests/pi/ -m "not slow"` exit 0. Both
  targets independently verified V0.27.12 @ 9060b75, services active. PM
  committed deploy artifacts (`ac6ca32`) + RELEASE_VERSION bump (`9060b75`),
  branch pushed w/ upstream.
- **IRL gate now:** Drain 27 on a rested ≥8h pack (NO shortcuts — D26 confound
  was the rest-rule override). Honest-instrument acceptance = clean→reports
  clean / crash→reports exact rung. That verdict then exposes the Bug-1 truth.
  Chain bigDoD also still open: Drive 12 retest + US-338/339/340/340b IRL.
  Per Spool: do NOT bump regression_manifest F-008/F-011/F-012 (not re-validated).

## What's deployed (sprint branches; not yet on main)

| Sprint | Branch | Version | Status | IRL gate |
|---|---|---|---|---|
| 27 | merged to main 2026-05-09 | V0.27.1 | VALIDATED ✅ | Drive 6 + Drive 7 + Drain 8 (9 of 11 features) |
| 28 | sprint/sprint28-bugfixes-V0.27.2 | V0.27.2 | DEPLOYED 2026-05-10 | Drive 12 + Drain 18 pending; validatesFeatures = [F-005] |
| 29 | sprint/sprint29-bugfixes-V0.27.3 | V0.27.3 | DEPLOYED 2026-05-10 | Drive 11 + Drain 15 (Drain 15 PASSED 4/5) |
| 30 | sprint/sprint30-bugfixes-V0.27.4 | V0.27.4 | DEPLOYED 2026-05-10 | Drive 11+ + calibration.py CLI |
| 31 | sprint/sprint31-bugfixes-V0.27.5 | V0.27.5 | DEPLOYED 2026-05-11 | smoke-tested; Drive 11+ |
| 32 | sprint/sprint32-bugfixes-V0.27.6 | V0.27.6 | DEPLOYED 2026-05-11 | included orphan cleanup; race-guard added by V0.27.7 |
| 33 | sprint/sprint33-bugfixes-V0.27.7 | V0.27.7 | DEPLOYED 2026-05-12 | Drive 11 captured clean; server-side analytics-tier fix |
| 34 | sprint/sprint34-bugfixes-V0.27.8 | V0.27.8 | DEPLOYED 2026-05-13 | superseded by V0.27.9 for I-031/US-331 |
| 35 | sprint/sprint35-bugfixes-V0.27.9 | V0.27.9 | DEPLOYED 2026-05-13 | I-031/I-032 closed; IRL gate GREEN |
| **36** | **sprint/sprint36-bugfixes-V0.27.10** | **V0.27.10** | **Ralph SHIPPED 2026-05-14 @ `6184a7f` (4 stories US-338/339/340/340b; 285 tests; lint clean)** | **NOT YET DEPLOYED — top Session 35 task** |

## Sprint 36 / V0.27.10 — Ralph's 4 stories

Implements the 3 bugs surfaced by Drive 12 pharmacy-run 2026-05-13 + 1 CIO mid-sprint
add:

| Story | Bug | Fix |
|---|---|---|
| US-338 | I-033 BT-no-reconnect after engine cycle | `_handleReconnectionFailure` spawns daemon `runReconnectHeartbeat` (US-301/V0.27.1/US-325 machinery, exponential backoff up to 15-min cap) instead of giving up silently. Fix direction B per Spool's tech note. |
| US-339 | I-034 SQLite `disk I/O error` flood | `contextlib.closing` around `sqlite3.connect()` in `pushDelta` + `pushDriveCounter`; eliminates ~13-fd-per-sweep leak. |
| US-340 | I-035 drive-time HTTP retry waste / WiFi-soft-off | `SyncClient.hasRouteToServer()` + orchestrator gate skips `pushAllDeltas` when no route; eliminates ~84s of doomed TCP SYNs per ACTIVE-mode cadence tick. |
| US-340b | (CIO mid-sprint add) | `connection_log` state-change-only dedup — ~99% row-volume reduction during sustained outages (was ~2000 rows/day). |

Sprint 36 has **no sprint.json on disk** (interactive-was-a-one-off from Session 33 — reverted by CIO).
Top Session 35 task: generate sprint.json retroactively from Ralph's inbox notes + the
2026-05-14 `from-ralph-v028-backlog-research-findings.md` report; mark all 4 stories
`passes:true`; sprint_lint clean; THEN `/sprint-deploy-pm` Phase 0 will pass.

## IRL validation gates outstanding

Once V0.27.10 deploys, CIO runs these:

- **US-338 IRL**: 2-leg pharmacy pattern → drives 13+14 both materialize with >100 rows + correct `drive_id`
- **US-339 IRL**: 6h+ bench soak → zero `disk I/O error` lines; fd count for `eclipse-obd` PID stays flat ~5-10 (not climbing)
- **US-340 IRL**: 10-min drive → server-side `connection_log` + `sync_history` row counts during drive should be near-zero
- **US-340b IRL**: post-deploy bench soak → `connection_log` row volume during sustained adapter outage ~5-10 total (not 2000)
- **Drive 12 retest** (V0.27 chain bigDoD): server `drive_summary` analytics fields populated within 30s of drive_end (US-326); Approach-1 `drive_statistics` rows for canonical PIDs (US-328); verify via `mysql chi-srv-01` post-drive
- **Drain 18+** (V0.27 chain bigDoD): clean `startup_log` with `prior_boot_clean=1` after V0.27.7 US-330 race-guard + V0.27.8 US-333 TZ + US-334 IO-class stress

## Outcome branches (CIO 2026-05-14 directive)

- **All green** → `/sprint-validated` Sprint 36 + `/chain-validated` whole V0.27 chain V0.27.1…V0.27.10 → main + cut **V0.28.0**
- **Any red** → file I-### bug(s) + open **V0.27.11** bug-fix sprint + loop until validated

## V0.28+ queue (post-chain-merge feature work)

**Theme: B-076 server schema normalization epic (CIO-confirmed 2026-05-14)**.

Filed V0.28+ backlog items in `offices/pm/backlog/`:

- B-074 (MAP PID 0x0B), B-075 (drive_statistics Approach 2), B-076 (schema epic), B-077 (connection_log idle chatter), B-078 (sync_history idle chatter), B-079 deferred TZ, B-080 (Pi clock drift)
- B-081 (Spool ATRV engine-state proxy), B-082 (tester findings rollup; 16 sub-items via reference)
- B-083 (Mahalanobis baseline scoring — Ralph HIGH-priority V0.28.0), B-084 (PID probe + opt-in PIDs), B-085 (BNO055 IMU)
- B-086..B-094 (Spool 9 GEMs: warnings-UI / Ollama / knock-retard / grade / MARK button / Android Auto / status-tile / baseline-anomaly / MrSpool RAG)
- B-095..B-098 (Spool 4 S-additions: heat-soak / LTFT trend / drain-ladder UI / mode-badge)

Active backlog 60 → 56 items after Session 34 grooming pass (-22 archived + 18 new + reframes/status edits).

## Cross-references

- [[project-v0-27-chain-history]] — per-sprint detail for closed Sprints 27-35
- [[project-workflow-chain-end-merge]] — Mike directives + ritual reference
- [[project-pi-power-state]] — B-063 fuse-box context
- [[project-drive-history]] — Drive 12 + earlier drives
- [[project-drain-test-history]] — Drains 14/15/16/19
- [[project-tuning-state-drive-11-baseline]] — knock-retard characterization
