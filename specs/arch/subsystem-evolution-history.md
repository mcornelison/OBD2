# Subsystem Evolution History — Shutdown Sequencer + Data Pipeline (B-104)

> Extracted from `specs/architecture.md` §10.6 + §10.7 on 2026-06-01 to keep the
> main spec focused on current behavior. Verbatim: the superseded designs, the
> Sprint-40 F-7/F-8 bug-fix narratives, the retired-writer cross-links, the
> point-in-time empirical-status snapshots, the retrospective lessons, and the
> Atlas Rule-10 gate records. The **current** sequencer flow + pipeline design +
> architectural invariants stay in architecture.md §10.6/§10.7.

## §10.6 Shutdown Sequencer — superseded design + F-7/F-8 fix history + Rule-10 gate

### Superseded design history (retained for the lesson, not as current behavior)

The text below documents the deleted `PowerDownOrchestrator` design and the
40-pt MAX17048 SOC% calibration finding that drove the US-234
SOC%→VCELL-volts switch. **The calibration lesson stands.** The ladder as a
shutdown mechanism does NOT — Phase-2 T9 deleted it in favor of the
ShutdownSequencer above (deterministic GPIO6 trigger + bounded task window,
no VCELL-based decision tree). Treat everything that follows as historical
context for the SOC% calibration discovery, not as current production
behavior. None of the `PowerDownOrchestrator`, its state machine, the VCELL
ladder thresholds, its callbacks, `suppressLegacyTriggers`, the
`_powerDownTickLoop`, the stage-behavior wiring, or the `stage_*` event
types in `power_log` are live anymore. The `battery_health_log` schema
(US-217) is unchanged and still in use; only the orchestrator that wrote to
it from a VCELL ladder is gone.

**The calibration lesson worth keeping.** US-216 originally compared
MAX17048 SOC% against a 30/25/20 ladder. Across 4 drain tests over 9 days
(Drains 1-4) the ladder NEVER fired: the Pi hard-crashed at VCELL
3.36-3.45V every test while MAX17048 SOC% reported 57-63%. Spool's
analysis identified a **40-pt SOC% calibration error on this MAX17048
unit** — the gauge reads ~60% when VCELL indicates near-empty. US-234
switched the trigger source to VCELL volts read directly from the cell,
removing the chip-level SOC%-vs-VCELL calibration error from the path.
The calibration lesson stands: **on this hardware, MAX17048 SOC% is
unreliable for safety-critical thresholds; VCELL volts are the source of
truth.** This lesson carries over into ShutdownSequencer's `vcellFloorVolts`
emergency backstop, which uses VCELL volts directly (the calibration
error never enters the safety path).

**Why the ladder itself was deleted.** Beyond the calibration finding, the
ladder *as a shutdown mechanism* was the wrong architecture: it inferred
power-source events from a battery-health trend (the same anti-pattern
that bricked the Pi 2026-05-18 in a different form). Phase-2 T9 deleted
the entire `PowerDownOrchestrator` subsystem (commit `9adb0fb`: −1230 LOC
`orchestrator.py` + ~10,829 deletions across `hardware_manager.py`,
`lifecycle.py`, and 25 test files) and replaced it with the
ShutdownSequencer above — a deterministic GPIO6-triggered, smoothing-
debounced, bounded task window. The old VCELL ladder, state machine
diagram, hysteresis tuning, `suppressLegacyTriggers` race fix
(US-216/TD-D), `_powerDownTickLoop` decoupling (US-252), stage-behavior
wiring (US-225/TD-034), `stage_*` event types in `power_log`, and per-stage
callbacks (`onWarning` / `onImminent` / etc.) are **not live**. The
`battery_health_log` schema (US-217) is unchanged and still in use — it is
written by the SyncWithServerTask path, not by a stage-based ladder.

For the full historical record of the deleted design, see the git history
prior to `9adb0fb` (`git log --reverse -p -- src/pi/power/orchestrator.py`)
or this architecture file at any tag ≤ V0.27.13.

*Detailed ladder design — state machine diagram, VCELL thresholds + hysteresis,
the legacy-timer-suppression race fix (US-216/TD-D), the
`_powerDownTickLoop` display-decoupling (US-252), the
stage-behavior wiring (US-225/TD-034), and the `stage_*` `power_log` event
types — is all retired and not reproduced here. See the linked git history
above if reconstructing the deleted design is ever necessary.*

### Boot-grace latch defect + level-based post-grace fix (US-344, Sprint 40 / V0.27.16, F-7)

V0.27.15 shipped the ShutdownSequencer above with a **boot-grace latch
defect** in the GPIO6 PLD watch loop (`src/pi/power/power_watch/__main__.py`
post-fix at `_runPldWatchLoop`; pre-fix at the inline closure on lines
301-322 of the V0.27.15 tip). The loop used **edge-only** loss detection
(`lost AND not prevLost`) for the post-boot-grace trigger. When a PLD loss
event fired *inside* the 120 s boot-grace window AND the X1209-HAT
subsequently latched GPIO6 LOW after the transient resolved, `prevLost`
advanced to `True` and the loop's level-stuck-LOW state went silently
unhandled — the sequencer was blind to a perfectly live power-loss signal
for the remainder of the service lifetime, unless GPIO6 toggled HIGH again
(which only happens if the HAT recovers external-power-detection, e.g.
under alternator load).

**Bug bound (conjunction; all three required to reproduce):**

1. Service is inside the 120 s boot-grace window, AND
2. A PLD power-loss event occurs during that window (engine crank transient
   is the canonical in-car trigger; bench-time HAT switchovers, USB-C
   unplug/replug, or relay bounces also produce it), AND
3. The HAT latches LOW after the transient and does not recover to HIGH
   before key-off.

Reproduced live in-car 2026-05-20 (Atlas + CIO Test 2): brief engine crank
inside boot-grace → journal `"PLD power-loss 42s into boot-grace (120s) --
ignoring"` → sequencer silent for 5.5 minutes while GPIO6 stayed `lo` for
638 consecutive samples and VCELL drained 3.810V → 3.734V. The morning's
3-of-3 Cycle-A drills + Bench Check A + Bench Check B all happened to dodge
the failure conjunction (no in-grace transients during those drills) — the
externally-observable V0.27.15 IRL ACCEPTANCE PASS verdict stands on its own
facts, but the bench gate's coverage of the in-grace-transient case was a
known-incomplete artifact.

**The fix (US-344, level-based post-grace check):** the watch loop now
treats `lost AND not firedAlready` as the post-boot-grace trigger condition,
not `lost AND not prevLost`. A loss event ignored during boot-grace
therefore re-fires correctly the first post-grace tick if the line is still
LOW; `firedAlready` is a same-cycle re-entry guard (the sequencer's own
state-tracking is the authoritative re-entry surface). Inside boot-grace
the trigger stays edge-based so the *"ignoring"* log fires once per fresh
in-grace transient, not repeatedly per tick. The smoothing path inside
`ShutdownSequencer.handleOnBattery` is preserved unchanged and remains the
abort surface for transient glitches that resolve mid-window — the watch
loop only owns trigger detection, not blip rejection.

To make this unit-testable, the closure body was extracted into a
module-level `_runPldWatchLoop` with injected `isPowerLostFn` / `stop` /
`monotonicFn`; the closure in `main()` reduces to a thin delegation call
with no behavior change in production wiring. The "already handling --
ignoring" log line from the V0.27.15 code is gone — it was unreachable in
practice (single-threaded loop; `handleLock` always acquires on first try)
and `firedAlready` now provides cleaner re-entry semantics.

**Architectural invariants preserved by the fix:**

- The SSOT `PowerSourceProvider` remains the only power-acquisition site
  (criterion #3); the watch loop reads through it, the sequencer's smoothing
  window reads through it. F-7 was downstream of the SSOT in the consumer's
  trigger logic, not in the source of truth.
- Boot-grace duration is unchanged. The timer was correct; the post-grace
  re-entry logic was the defect.
- GPIO6 acquisition + polarity (`pldPowerPresentHigh=true`) are unchanged
  (validated by Bench Check A + Test 1 control + Test 2 phase 2 recovery).
- EEPROM `POWER_OFF_ON_HALT=1` (Sprint 39 SS-T8) preserved.
- ShutdownSequencer pipeline / window cap / smoothing semantics preserved.

**Lesson worth keeping (carries beyond power_watch):** *boot-grace was
intended as time-bounded silence, not as permanent silence after an
in-grace event.* Edge-only state-transition logic in a polling consumer
that can ignore events during a startup grace window must re-evaluate the
**level** on grace expiry, or it latches the consumer blind. The same
class of bug can recur in any consumer that pairs an ignore-during-grace
window with edge-only post-grace triggering — the SSOT design pattern
([[ssot-design-pattern]]) is about acquisition; consumer-side state
machines need their own design discipline.

### Boot-progress instrument + ExecStop transaction-membership fix (US-345, Sprint 40 / V0.27.16, F-8)

The Sprint 38 T11 honest-instrument layer (`deploy/boot-progress-arm.service`
+ `deploy/boot-progress-finalize.service` + `src/pi/diagnostics/boot_progress.py`)
classifies prior-boot outcomes by writing a ladder of breadcrumb rungs at
shutdown — only the final `CLEAN_COMPLETE` rung, written by
`boot-progress-finalize.service`'s ExecStop, distinguishes a clean
sequencer-driven shutdown from a hard power-yank. The next boot's
arm-unit reads the ladder file and writes `startup_log.prior_boot_clean` +
`prior_boot_last_stage` + `prior_boot_reason` accordingly. Design intent:
*absence of CLEAN_COMPLETE means crash, presence means clean.*

**The empirical defect (F-8):** V0.27.13 → V0.27.15
`boot-progress-finalize.service`'s ExecStop **never fired during a real
shutdown.** The unit declared `DefaultDependencies=no` + `Before=shutdown.target`
but no directive that pulled it into the shutdown transaction. systemd
brought it up at boot (via `WantedBy=multi-user.target`) but never included
it in the shutdown transaction, so its ExecStop was silently skipped, the
`CLEAN_COMPLETE` rung never written, and every clean shutdown — including
direct CIO-observed sequencer poweroffs — got classified
`crashed_during_operation` on the next boot.

Empirically proven 2026-05-20: Test 1 + Test 2 of the in-car drill (both
direct-observed gentle 5s smoothing → systemd poweroff → all dark) both
produced `prior_boot_clean=0, last_stage=RUNNING, reason=crashed_during_operation`
on the following boot. The instrument was lying. This finding was also the
mechanical inflation behind Spool's Finding C "12 boots crashed today"
headline — many of those 12 were almost certainly clean sequencer
shutdowns mis-labeled by the broken finalizer.

**The fix (US-345, one-line systemd directive):** add
`Conflicts=shutdown.target` to the `[Unit]` section of
`deploy/boot-progress-finalize.service`. This pulls the unit into the
shutdown transaction (its stop-job becomes a member of the transaction
that activates `shutdown.target`), preserving the existing `Before=` ordering
within that transaction. `DefaultDependencies=no` had stripped the
auto-synthesized `Conflicts=` that systemd would otherwise have provided —
the user-added `Before=shutdown.target` re-established the *ordering*
intent but not the *activation* intent, and `Before=` alone is an ordering
directive (*"if both are being acted on, do me first"*), not an activation
directive (*"include me in the transaction"*). The bug was a systemd
semantics subtlety, not a design defect in the boot_progress ladder
itself — the ladder, the arm/finalize split, and the
"only CLEAN_COMPLETE means clean" invariant are all sound.

**Architectural invariants preserved by the fix:**

- ExecStart / ExecStop command bodies unchanged (only the systemd
  dependency graph is fixed).
- `boot_progress` writer code path (`src/pi/diagnostics/boot_progress.py`)
  unchanged — `CLEAN_COMPLETE` emission logic is correct; it now actually
  runs.
- `startup_log` schema (`prior_boot_clean` / `last_stage` / `prior_boot_reason`
  columns) preserved unchanged.
- Sprint 38 T11 ordering frame (`DefaultDependencies=no` + `After=eclipse-obd.service
  drain-forensics.service` + `Before=shutdown.target`) preserved unchanged.
- V0.27.12-DOA `PYTHONPATH=repo:repo/src` invariant in the
  finalize unit preserved unchanged.
- Other systemd units untouched (only `boot-progress-finalize.service` had
  this defect class; pre-flight scan of `deploy/*.service` confirms it is
  the only unit with the `DefaultDependencies=no + Before=shutdown.target +
  no Conflicts=` pattern).

**Sequencing relationship to F-7:** F-7 + F-8 are independent root causes
shipped in the same V0.27.16 bug-fix release. F-7 (chain-blocking) closes
the actual operational failure — sequencer silence post in-grace transient.
F-8 (parallel, not chain-blocking) closes the classifier-honesty defect
that was independently inflating Spool's Finding C "12 boots crashed today"
number. Until F-8 ships, `startup_log.prior_boot_reason` is **advisory
only** as an acceptance signal — direct journal-shutdown-sequence
observation (CIO eyewitness + `journalctl` `shutdown.target`/`poweroff.target`
lines) is the authoritative source of truth for "was this a clean
shutdown." Post-F-8, the column becomes reliable again and counting future
`crashed_during_operation` rows becomes meaningful evidence for regression
gates.

**Lesson worth keeping (carries beyond boot-progress):** a service-unit
`Before=shutdown.target` line with `DefaultDependencies=no` is *not*
sufficient to wire the unit into the shutdown transaction. Activation
(`Conflicts=` / `RequiredBy=` / `WantedBy=`) and ordering (`Before=` / `After=`)
are independent axes in systemd's dependency model — a unit can be ordered
relative to a target it is never asked to stop, and the stop-job simply
never runs. Any future shutdown-time instrument that opts out of
`DefaultDependencies` must explicitly re-declare its shutdown-transaction
membership.

### Gate ratification (Atlas / Rule 10)

The F-7 + F-8 amendments above are the Sprint 40 / V0.27.16 PM Rule 10
design-gate DoD deliverable for §10.6 (power/shutdown subsystem — the
load-bearing subsystem touched by US-344 + US-345). Atlas-gated per the
2026-05-18 design-gate governance rule (architect owns the gate; spec
update lands in-sprint with the load-bearing code change, not as
follow-up). See
`offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md`
+ `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md`
for the full finding-of-record bodies; the §10.6 text above is the
canonical architecture-spec digest.

---


## §10.7 Data Pipeline — retired writers + V0.27.17 empirical-status snapshot

### What's retired (cross-links for archival traceability)

The following trigger-seam writer architectures and their wiring are
retired in V0.27.17:

| Surface | Sprint / Version | Anchor commit | Disposition |
|---|---|---|---|
| US-326 server `_writeDriveAnalytics` keyed on `connection_log` sync receipt | Sprint 33 / V0.27.7 | `76aa773` (V0.27.7 ship); `0599d24` (grooming) | **Superseded** by `compute_drive_summary` reading raw `realtime_data` directly. |
| US-328 Pi-side `drive_statistics` Option C (schema-only, no writer) | Sprint 33 / V0.27.7 | `76aa773`; `1c01ec0` (BL-015 Option C unblock) | **Retired** — Pi-side table dropped by `ensureDriveStatisticsRetired()`. |
| US-348 V0.27.16 server writer redo (dual-seam: sync receipt + drive_summary payload trigger) | Sprint 40 / V0.27.16 | `c04d36e` (V0.27.16 ship); `b26344e` (integration); `5fb7cdc` (scope expansion) | **Superseded** — false-pass recurred; trigger seam deleted from `sync.py`. |
| US-349 V0.27.16 Pi-side `drive_statistics` writer + `DriveDetector._endDrive` wiring | Sprint 40 / V0.27.16 | `c04d36e`; `b26344e`; `5fb7cdc` | **Retired entirely** — Pi-side module + table + wiring removed in US-351. |

Sprint 41 / V0.27.17 anchor: `e6c49e6` (sprint spin); US-350 / US-351 /
US-352 / US-356 land on the `sprint/sprint41-bugfixes-V0.27.17` branch
prior to chain-end merge per the Mike 2026-05-08 / 2026-05-10
chain-end-merge rule.

### Empirical status (honest, V0.27.17 IRL pending)

The compute path is **synthetically validated** at the time this
section lands:

- US-350 unit tests (`tests/server/analytics/test_drive_summary_compute.py`)
  10/10 GREEN — fixture-based compute against real ORM + real INSERTs
  on in-memory SQLite (no seam mocks per I-040 discipline).
- US-351 unit tests
  (`tests/server/analytics/test_drive_statistics_compute.py`) 14/14
  GREEN; Pi-side retirement regression suite
  (`tests/pi/obdii/test_drive_statistics_pi_table_migration.py`) 7/7
  GREEN.
- US-352 deploy-script suite
  (`tests/deploy/test_deploy_server_backfill_drives_11_20.py`) 13/13
  GREEN.
- Full server suite (`pytest tests/server/ -m "not slow"`) 777
  passed / 12 skipped (no regressions). Pi suite
  (`pytest tests/pi/ -m "not slow"`) 1513 passed / 16 skipped.

The compute path is **IRL-pending** until V0.27.17 deploys to
chi-srv-01 + the Pi and an actual drive's raw rows are computed
through the new path. The empirical-gate to clear:

1. Deploy Step 4.9 backfill of drives 11-20 produces 10
   `drive_summary` rows with NON-NULL analytics columns + 10 drives'
   worth of positive-`sample_count` `drive_statistics` rows
   (`data_quality=full` for drives with ≥100 `realtime_data` rows
   per PID). Drive 11 inclusion (Spool FLAG-2 / Argus DB-check
   outcome (a) 2026-05-21) preserves the 93-octane knock-retard
   reference baseline.
2. Idempotent re-run produces zero diff in either table's data
   values; `drive_statistics.computed_at` advances; no PK violations.
3. Post-deploy real drive (engine on through key-off via sequencer
   poweroff) produces a `realtime_data` block that the nightly timer
   (or on-demand `--drive-id N`) computes through to NON-NULL
   analytics columns — the V0.27.16 reproducer scenario that the
   V0.27.7 + V0.27.16 trigger seams failed.

Until that drill clears, this section describes the **deployed
architecture intent**, not the validated production state. The
distinction is the load-bearing one: prior cycles shipped through
exactly because synthetic-seam-mock passes were misread as production
proof. The empirical falsifier for "Pi-side drive-end signal no
longer load-bearing" is the on-demand backfill of drive 20 producing
`drive_summary.row_count=3808` (per Argus's V0.27.16 drill evidence)
from the existing raw `realtime_data` on the server.


## §10.7 Data Pipeline — retrospective lesson + Rule-10 gate

### Lesson worth keeping (carries beyond drive analytics)

*The V0.27.7 → V0.27.16 → (would-have-been) V0.27.17 redo cycle shipped
three times because the test fixtures used in Ralph's TDD did not
reproduce deploy-time runtime conditions — specifically the
sequencer-driven drive termination that prevents the drive-end signal
from firing.* The structural close is two-part: (a) move the writer
to a tier where the bug class is impossible (this section), and (b)
build a deploy-context test surface that exercises the integrated
orchestrator + DriveDetector + recorder + sync + server compute path
against a real database (US-355, I-040 structural close, V0.27.17
seed harness). Synthetic-seam-mock passes are not proof of production
behavior; a real-data round-trip + DB read-back is the gate. The
discipline lesson is: when a writer is tier-coupled to a signal that
may not fire under the real termination path, the architectural fix
is to read the canonical data on the other tier, not to harden the
signal.

### Gate ratification (Atlas / Rule 10)

This §10.7 amendment is the Sprint 41 / V0.27.17 PM Rule 10
design-gate DoD deliverable for the data-pipeline subsystem (the
load-bearing subsystem touched by US-350 + US-351 + US-352).
Atlas-gated per the 2026-05-18 design-gate governance rule
(architect owns the gate; spec update lands in-sprint with the
load-bearing code change, not as follow-up). The architectural
verdict on B-104 Step 1 advance (sound; per-task gates pre-registered
for US-350..US-356) is recorded in
`offices/pm/inbox/2026-05-21-from-atlas-sprint41-per-task-gates-preregistered.md`;
the SSOT-pattern-load-bearing observation is recorded in
`offices/pm/inbox/2026-05-21-from-atlas-ssot-pattern-load-bearing-observation.md`.
The §10.7 text above is the canonical architecture-spec digest;
V0.27.17 IRL acceptance + Atlas Rule-10 sign-off close the gate.
