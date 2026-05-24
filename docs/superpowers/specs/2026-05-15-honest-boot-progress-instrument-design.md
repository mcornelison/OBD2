# Honest Boot-Progress Instrument — Design Spec

- **Date:** 2026-05-15
- **Author:** CIO (Mike) + Claude (interactive brainstorming session)
- **Status:** Approved design — pending spec review → implementation plan
- **Related issues:** I-036 (systemctl poweroff PolicyKit/I-O-wedge), I-037 (prior_boot_clean canary false-positive)
- **Supersedes:** the V0.27.11 US-342 approach to the boot canary (journal-grep repointing). The journal-scan canary is **removed**, not repaired.
- **Scope of this spec:** the *honest forensic instrument* only (the "truth" half). The actual shutdown failure under I/O contention ("Bug 1", below) is an explicitly named **follow-on**, measured by this instrument — out of scope here.

---

## 1. Problem & RCA summary

The V0.27 line is a 10-sprint unbroken bug-fix chain. The shutdown/poweroff/canary subsystem has been "fixed" four times — US-308 (ladder grep probe), US-330 (list-boots retry), US-341 (polkit + raise), US-342 (grep repoint) — and **Drain 26 (2026-05-15) still failed**. The failure recurs through a *new door* after every fix. That is the signature of an architectural root cause, not a string bug.

There are **two distinct bugs**, and conflating them is part of why this won't die:

- **Bug 1 — the machine doesn't shut down (the one that matters).** Since the V0.24.1 deploy every real power-loss has ended in a hard crash at the battery floor. Drain 26 evidence: at the TRIGGER moment the single SD card is saturated (drain-forensics every 5s + sync + DB writes + journald), the box is I/O-locked, journald dies (16:27:34), `systemctl poweroff` cannot execute, the Pi runs until the battery physically dies. The V0.27.11 polkit fix is real but now beside the point (`pkcheck` exits 0).
- **Bug 2 — the instrument lies (the one that hid Bug 1).** The boot canary reads the *prior boot's journal* to decide "did it crash?". But (a) the journal is destroyed by the very crash it must detect (the I/O storm kills journald; `journalctl -b -1` is truncated), and (b) `_hasShutdownMarker` is a naive over-broad substring scan, so on a truncated journal full of ordinary app logs it can match the wrong line and report "clean". Bug 1 was therefore invisible for 11 days, and every prior fix was graded by a lying instrument.

**Architectural root cause:** the canary is a journald-based crash detector whose witness is destroyed by the failure it must detect. US-308 → US-330 → US-342 each just changed *which needle to grep for in a haystack the crash burns down*. No needle works when the haystack is gone.

**Compounding root cause:** the only gate that exercises the real failure is the physical drain — days-late, once, non-reproducible, battery-confounded — and no in-repo test reproduces the real failure shape (hard-crash-truncated record + silent orchestrator + I/O storm). Every sprint shipped green synthetic tests that proved author intent, never the production failure shape.

The codebase already implements the correct safe-default pattern elsewhere (`derivePowerSource → UNKNOWN` on no signal) and has written-down lessons for exactly this class (retry/uncertainty must default to UNCERTAIN never SUCCESS; verify diagnostic premises; pin emitter↔detector contracts; only real-chain integration tests catch this). This design applies those lessons to this path instead of re-deriving them story by story.

## 2. Goal — the perfect outcome

- **Layer 1 (the real job):** when the car loses power, the Pi powers itself off cleanly within a few seconds of TRIGGER, **every time**, before the battery dies — systemd brings services down in order, SQLite flushes, the SD syncs, nothing corrupts. *(This is Bug 1; the follow-on.)*
- **Layer 2 (this spec):** the next boot records **one unambiguous, queryable truth** about whether Layer 1 worked, and it is **never a false "clean."** A false clean is worse than no record.
- **End state that closes the chain:** a rested-battery drain shows the Pi powering off ≤~5s after TRIGGER and the next boot honestly reports clean; combined with the Drive-12 analytics gate, the V0.27 chain can finally merge to main (rule: *main = a fully functional, trustworthy system*).

We are ultimately fixing Bug 1. **This spec delivers Bug 2's fix because we cannot trust any Bug-1 fix until the instrument stops lying.** Truth first, then fix the machine, measured against the now-honest instrument.

## 3. Key decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| Sequencing | **Truth first** — honest instrument before touching the shutdown path | Can't fix what you can't honestly measure; the lying canary is *the* reason this became a 10-sprint chain |
| Fidelity | **Full forensic fidelity** — a progress breadcrumb trail, not a binary bit | Every future Bug-1 attempt must show *exactly which rung* it died on, not pass/fail |
| Durable medium | **SD-card only for the live witness; NAS (`/mnt/projects/O/...`) for archival when home** | The NAS is unreachable exactly when the crash happens (Pi mobile/offline mid-drive; mount hangs as the box wedges) |
| Architecture | **Approach ① — dedicated append-only breadcrumb file + systemd shutdown-finalizer** | SD-only, journal-free, crash-proof *by construction* (absence of the final flip = proof of crash), bench-verifiable. Rejected: SQLite progress table (puts the witness back inside the contended DB — the I-034 family); kernel pstore/watchdog (doesn't survive a battery power-cut; pulls Bug-1 work forward) |
| Config boundary | Operational params in `config.json`; the writer↔reader **contract** (stage vocabulary + sentinel) stays a single shared **code constant + contract test** | Making the contract config-mutable re-creates the exact US-308/US-342 silent-drift bug this effort exists to kill |

## 4. Design

### 4.1 Core model & invariants

One small file on the SD card — `data/boot_progress` (path is config) — records the furthest milestone the shutdown sequence reached this boot. A focused new module `src/pi/diagnostics/boot_progress.py` (tiny API: `markMilestone(stage, vcell)` / `readPriorThenArm()` / a `--finalize` entrypoint) hooks the seams that already exist in `orchestrator.py` and `shutdown_handler.py` via the same DI/parameter patterns those modules use.

- **Dirty-by-default.** The first thing the Pi does each boot — before the orchestrator, before any drive — overwrites the file with `boot_id, RUNNING, ts` + `fdatasync`. From that instant the file asserts "this boot has not cleanly shut down." It can only ever say "clean" if something explicitly flips it.
- **Monotonic milestone ladder.** Each milestone is written *immediately before* the contended action it precedes (durable even if that action then wedges the box), each `fdatasync`'d, one appended line per milestone. Milestones only advance; the reader trusts the highest one that reached disk.
- **Crash-proof invariant.** `CLEAN_COMPLETE` is written by exactly ONE writer — a systemd unit whose `ExecStop` runs at the end of a real shutdown transaction, after the I/O-storm units are stopped. A hard crash (battery death, wedged box, killed journald) never runs the shutdown transaction, so `ExecStop` never fires, so `CLEAN_COMPLETE` never appears.

> **Invariant:** file contains `CLEAN_COMPLETE` ⟺ a graceful shutdown actually completed. Anything else = crash, and the highest milestone present says exactly where it died. "Clean" requires positive proof; it is never inferred from the absence of a negative.

**Topology:** boot-init writer (`RUNNING`, via the arm unit) · orchestrator writer (ladder + pre-poweroff rungs, in-process) · systemd finalizer writer (`CLEAN_COMPLETE`) · next-boot reader (verdict → `startup_log`; opportunistic NAS archive when home).

### 4.2 Milestone ladder

Append-only, one line per milestone: `{boot_id, stage, ts, vcell}` + `fdatasync`. The file holds exactly one boot's trail (the arm step truncates each boot after reading the prior trail). Rungs, at the exact code seams (line numbers from the V0.27.11 tree):

| # | Milestone | Emitted at | A crash here means |
|---|---|---|---|
| 0 | `RUNNING` | arm unit, early boot, before orchestrator | died during normal op / drive — no power-loss ladder started |
| 1 | `WARNING` | top of `orchestrator._enterWarning` (before drain-DB open) | died mid-drain, pre-IMMINENT |
| 2 | `IMMINENT` | top of `orchestrator._enterImminent` | died between IMMINENT and TRIGGER |
| 3 | `TRIGGER` | top of `orchestrator._enterTrigger`, before `_closeDrainEvent` (orch:893) | reached trigger, wedged before closing drain event |
| 4 | `DRAIN_CLOSED` | after `_closeDrainEvent` returns | wedged on the `stage_trigger` SQLite write |
| 5 | `TRIGGER_ROW_WRITTEN` | after `_writePowerLogStage` (orch:899) | reached poweroff handoff, died before invoking it |
| 6 | `POWEROFF_INVOKED` | `shutdown_handler._executeShutdown`, before `subprocess.run` (sh:290) | **Drain-26 signature**: poweroff called, never returned/failed |
| 7 | `POWEROFF_RC0` | after `returncode == 0` (sh:314) | systemd accepted poweroff but shutdown did not finish |
| 8 | `CLEAN_COMPLETE` | `boot-progress-finalize.service` `ExecStop` only | — graceful, the only "clean" |

`markMilestone` is **fail-safe**: if its own write/`fdatasync` fails (storm) it logs best-effort and returns — it must never raise into the orchestrator/shutdown path (that path must keep trying to power off). A lost mid-storm breadcrumb only degrades fidelity; the no-false-clean invariant always holds because only the finalizer writes `CLEAN_COMPLETE`. Milestones are monotonic; a lower rung after a higher one is ignored.

### 4.3 systemd units

The ladder rungs 1–7 are written **in-process** by the existing `eclipse-obd.service` (new `boot_progress.markMilestone()` calls — no new unit). Only the arm and finalize ends need units.

**`boot-progress-finalize.service`** — the crash-proof `CLEAN_COMPLETE` writer:

```ini
[Unit]
Description=Eclipse OBD shutdown breadcrumb finalizer
DefaultDependencies=no
After=eclipse-obd.service drain-forensics.service
Before=shutdown.target
[Service]
Type=oneshot
RemainAfterExit=yes
User=mcornelison
WorkingDirectory=/home/mcornelison/Projects/Eclipse-01
Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01
ExecStart=/bin/true
ExecStop=/home/mcornelison/obd2-venv/bin/python -m src.pi.diagnostics.boot_progress --finalize
[Install]
WantedBy=multi-user.target
```

`WorkingDirectory` + `Environment=PYTHONPATH` are **mandatory**, not optional, and the import path must match the existing working units (`drain-forensics.service` / `orphan-cleanup.service`, which run `src.pi.*` with `PYTHONPATH=<repo root>`). Per the US-277 lesson documented in `drain-forensics.service`: omitting `PYTHONPATH` makes the import fail *silently* and every invocation a no-op — for this finalizer that would mean `CLEAN_COMPLETE` is never written and every clean shutdown is misreported as a crash. Cross-module import identity is a known project hazard (the 9-drain saga); the implementation plan must pin the finalizer's import form to the same form the in-process writer uses, with a test that the `--finalize` entrypoint actually appends the rung when invoked exactly as the unit invokes it.

Shutdown reverses start ordering, so `After=eclipse-obd.service drain-forensics.service` makes this unit's `ExecStop` run *after* those stop → the I/O storm is quiesced and the SD is still read-write (the read-only remount happens later, in the final phase — which is why an `ExecStop` service beats a `/usr/lib/systemd/system-shutdown/` hook that runs post-ro-remount). A hard crash never runs the shutdown transaction → `ExecStop` never fires → no `CLEAN_COMPLETE`. That single unit is the entire guarantee.

**`boot-progress-arm.service`** — oneshot, `Before=eclipse-obd.service`, once per boot: read prior trail → derive verdict → write `startup_log` → archive to NAS if writable → truncate → write `RUNNING`. It must be **boot-scoped, not** `eclipse-obd` `ExecStartPre` — `eclipse-obd` is `Restart=always`, so a per-process hook would clobber the trail on every restart.

Both install via a new `step_install_boot_progress_units()` in `deploy/deploy-pi.sh`, following the existing idempotent sync-if-changed pattern (`step_install_drain_forensics_unit` / `step_install_polkit_poweroff`).

**Honest caveats:** (1) a manual `sudo poweroff` or a deploy reboot correctly yields `CLEAN_COMPLETE` with no ladder rungs — that is *truthful* (it really was a clean shutdown), not a false positive. (2) Minor *fidelity* (not correctness) gap: a last in-flight `drain-forensics` oneshot fired by `drain-forensics.timer` could overlap the finalizer; it cannot forge `CLEAN_COMPLETE`, so the no-false-clean invariant holds; tightenable later by also ordering against the timer.

### 4.4 Reader, verdict, schema, configuration

`boot-progress-arm.service` runs once per boot, `Before=eclipse-obd.service`:

1. Read prior trail (reuse `boot_reason.readCurrentBootId` — that helper is sound; only the journal-scan is discarded).
2. Take the highest milestone reached (monotonic; malformed lines ignored).
3. Derive the verdict — **positive proof only**:

| Highest rung present | `prior_boot_clean` | `prior_boot_reason` |
|---|:--:|---|
| `CLEAN_COMPLETE` | **1** | `graceful` |
| `POWEROFF_RC0` (no finalize) | **0** | `poweroff_accepted_unfinalized` |
| `POWEROFF_INVOKED` | **0** | `poweroff_invoked_never_returned` |
| `TRIGGER` / `DRAIN_CLOSED` / `TRIGGER_ROW_WRITTEN` | **0** | `wedged_before_poweroff` |
| `WARNING` / `IMMINENT` | **0** | `died_mid_drain` |
| `RUNNING` only | **0** | `crashed_during_operation` |
| file missing / empty / corrupt | **NULL** | `indeterminate_no_record` |

Only `CLEAN_COMPLETE` ⟹ 1. Everything else is 0; never NULL-as-clean; never inferred.

4. Write `startup_log` idempotently (`INSERT OR IGNORE` on `boot_id`, same as today). Backward-compatible schema add (`ADD COLUMN`): `prior_boot_last_stage TEXT`, `prior_boot_reason TEXT`. `prior_boot_clean` (1/0/NULL) stays for existing consumers.
5. Archive prior trail to the NAS dir if it is writable (home) — best-effort, non-fatal, for Spool.
6. Truncate + write `RUNNING` for the new boot (write-temp+rename, fdatasync). Idempotent.

**Configuration.** Operational knobs live in `config.json` under the tier-aware `pi:` section, with validator dot-notation defaults (`python validate_config.py` is the config-story gate):

| Key | Default | Why config |
|---|---|---|
| `pi.bootProgress.filePath` | `data/boot_progress` | deploy-path portability |
| `pi.bootProgress.nasArchiveDir` | `/mnt/projects/O/OBD2v2/boot-progress` | home-only archive location |
| `pi.bootProgress.nasArchiveEnabled` | `true` | toggle archival |
| `pi.bootProgress.maxTrailBytes` | `65536` | bound the file against a restart loop |
| `pi.shutdown.poweroffTimeoutSeconds` | `30` | replaces the current hardcoded literal at `shutdown_handler.py:294` (`subprocess.run(timeout=30)`) |

**Config boundary (load-bearing).** The stage vocabulary (`RUNNING`…`CLEAN_COMPLETE`) and the `CLEAN_COMPLETE` sentinel are **NOT config** — they are a single shared code constant (`boot_progress.Stage` enum) imported by the writer, the reader, *and* the US-343 audit script, pinned by a contract test. Making the writer↔reader contract a mutable config value would re-create the exact US-308/US-342 silent-drift bug this effort exists to kill. Config = deployment/operational params; the detector contract = code + test.

### 4.5 Error handling & `boot_reason.py` replacement

The deletion of the journal scan is a deliverable, not a side effect. Keeping it "as a fallback" re-creates the ambiguity (which signal wins when they disagree — the lying one?).

| Keep | Delete | Replace |
|---|---|---|
| `readCurrentBootId`, `_normalizeBootId`, `BOOT_ID_PATH` | `runJournalctl`, `parseListBoots`, `_hasShutdownMarker`, `_probeLadderGraceful`, `_readBootList`, `BootListEntry`, all journal / `SHUTDOWN_MARKERS` / `LADDER_*` / `LIST_BOOTS_*` / `JOURNALCTL_*` / `PRIOR_BOOT_TAIL_LINES` constants | `detectBootReason` → trail reader (in `boot_progress.py`); `writeStartupLog` / `recordBootReason` → arm/reader with new columns |

`shutdown_handler.SHUTDOWN_SUCCESS_MARKER` and its journal `WARNING` emit **stay** as non-authoritative corroboration. Rationale: the US-343 historical audit legitimately greps old boots' journals (drains 10–26 have no breadcrumb trail; on a box you can still SSH to, the journal is valid *post-hoc* forensic). The crash truncates *the journal of the boot that crashed* — that is why it fails as a *live next-boot canary*; it is fine as *after-the-fact evidence on a reachable box*. Different use, different reliability.

**Consumer migration:** `prior_boot_clean` (1/0/NULL) stays — the US-343 audit script, Spool SQL, and F-008/F-012 regression_manifest references keep working unchanged; they receive truthful values plus two new optional columns. Zero breaking consumers. Old `test_boot_reason*.py` (journal-scan tests) are replaced by `test_boot_progress*.py`.

**Error matrix — every failure fails toward "crash/investigate", never toward "clean":**

| Failure | Behavior |
|---|---|
| `markMilestone` write/`fdatasync` fails (storm) | best-effort log, **return — never raise** into the shutdown path; fidelity drops, invariant holds |
| Finalizer `ExecStop` cannot write | no `CLEAN_COMPLETE` → next boot says "not clean" — safe direction, and *loud* (every deploy reboot would show it → self-announcing) |
| arm reader: prior file corrupt/missing | `prior_boot_clean=NULL, reason=indeterminate_no_record`; still write the row; still arm `RUNNING`; never crash boot |
| arm reader: `startup_log` write fails (DB locked) | log ERROR; **still truncate + arm `RUNNING`** (verdict already derived in memory; arming the new boot is the most critical step) |
| `boot_id` unreadable | mirror today: skip keyed row, log loudly; still arm `RUNNING` with timestamp |
| trail exceeds `maxTrailBytes` (restart loop) | stop appending, log once; invariant safe |

The new design's worst case is **noisy-but-safe and self-announcing**; the old design's worst case was **silent and dangerous** (11-day cover-up). That inversion is the point.

### 4.6 Verification — proving the instrument is honest

The instrument is **not trusted until it has demonstrably caught a real hard crash**, cheaply and repeatably. Four layers, weakest→strongest:

1. **Failure-shape unit tests.** Reproduce the real shapes, not author intent: trail truncated at `POWEROFF_INVOKED` / no `CLEAN_COMPLETE` ⟹ MUST return `0, poweroff_invoked_never_returned` (the Drain-26 shape; the old canary returned **1** here — this test must fail against any clean-on-absence logic). Plus `RUNNING`-only⟹0, `CLEAN_COMPLETE`⟹1, missing/corrupt⟹NULL, lossy-gapped trail⟹0-from-highest, malformed-line defense.
2. **Contract test.** Writer, reader, and the US-343 audit script import the one `boot_progress.Stage` enum / `CLEAN_COMPLETE` constant; a runtime test drives mocked-success `_executeShutdown` and the finalizer entrypoint and asserts the exact rungs verbatim. Drift breaks at PR time, not at the next drain.
3. **Real-chain integration test.** Drive the real `PowerDownOrchestrator` with a declining VCELL through the real ladder, faking only the OS edges (poweroff subprocess, file path); assert the on-disk trail; then run the real arm/reader against it and assert the verdict. Had this existed, US-308/330/342 fail at PR. Building it is the highest-value artifact of the effort.
4. **Bench hard-crash drill (IRL gate).** On a bench PSU (not the slow battery): arm → induce an abrupt hard-stop at a chosen rung (`echo b > /proc/sysrq-trigger`, or PSU yank, or `kill -9` orchestrator + SD I/O saturation to mimic the storm) → reboot → confirm the reader reports the precise expected `0, <reason>`. A ~2-minute repeatable loop.

**Acceptance gate before the instrument is trusted:**
- Layers 1–3 green in CI, **and**
- Layer 4 run by the CIO on the bench: the Drain-26-shape crash reads back `0 / poweroff_invoked_never_returned`; a real `systemctl poweroff` reads back `1 / graceful`; a drive-time PSU-yank reads back `0`. Synthetic cannot prove fdatasync-survives-yank or the systemd-ExecStop ordering — only the real Pi can (the IRL gate the chain kept skipping). The drill ships as an in-repo runbook + script; *running* it is a human action item (dev-only sprint scope rule).

Then — and only then — it becomes the measuring stick: Bug-1 work reads `prior_boot_reason` off `startup_log` each attempt and watches it march `wedged_before_poweroff` → `poweroff_invoked_never_returned` → … → `graceful`.

## 5. Module / file plan (seed for the implementation plan)

- **New:** `src/pi/diagnostics/boot_progress.py` (Stage enum + `markMilestone` + `readPriorThenArm` + `--finalize` CLI); `deploy/boot-progress-finalize.service`; `deploy/boot-progress-arm.service`; `tests/pi/diagnostics/test_boot_progress*.py`; an in-repo bench-drill runbook + helper script.
- **Modified:** `src/pi/power/orchestrator.py` (rung calls in `_enterWarning`/`_enterImminent`/`_enterTrigger`); `src/pi/hardware/shutdown_handler.py` (`POWEROFF_INVOKED`/`POWEROFF_RC0` rungs; `poweroffTimeoutSeconds` from config); `src/pi/diagnostics/boot_reason.py` (strip journal scan, keep boot-id helpers, repoint to trail reader); `deploy/deploy-pi.sh` (`step_install_boot_progress_units`); `config.json` + validator defaults; `startup_log` schema (`ADD COLUMN`); `offices/pm/scripts/audit_historical_drain_canary.py` (import the shared Stage constant); regression manifest refs as needed.
- **Deleted/replaced:** journal-scan internals of `boot_reason.py`; `tests/pi/diagnostics/test_boot_reason*.py` (journal-scan tests) → replaced by `test_boot_progress*.py`.

## 6. Open items (to confirm when the Pi is reachable — non-blocking for this design)

- The exact mechanism by which the *old* canary wrote `1` on Drain 26 (hypothesis: over-broad `SHUTDOWN_MARKERS` substring matched an app log line; this contradicts both Spool's "default-clean-on-empty" hint and a research-agent claim — unresolved, but moot for the new design since the journal path is deleted). Still worth confirming for the US-343 historical re-audit.
- Confirm no consumer other than the canary + US-343 audit reads the journal path.
- **Sequencing decision for PM:** whether this ships as V0.27.12 (extending the chain), a new line, or a standalone instrument deliverable, and how it orders against the still-open Drive-12 analytics gate. Deferred to the planning phase / PM.

## 7. Out of scope — the named follow-on (Bug 1)

The actual shutdown failure under I/O contention (drain-forensics 5s cadence + sync + DB + journald saturating the SD card at TRIGGER so `systemctl poweroff` cannot execute) is **not addressed here**. It is the next effort, and this instrument is what will measure it. Candidate directions to brainstorm separately when we get there: throttle/suspend `drain-forensics.timer` at IMMINENT; pre-poweroff I/O quiescing; a hardware/systemd watchdog as a backstop; `poweroff --force`/`systemctl --no-block` semantics. None are decided here.
