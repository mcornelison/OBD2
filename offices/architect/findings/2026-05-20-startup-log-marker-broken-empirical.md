# Finding F-8 — `boot-progress-finalize.service` ExecStop Never Fires → CLEAN_COMPLETE Marker Never Written

**Filed**: 2026-05-20 (Atlas, empirical proof during in-car drill)
**Severity**: High (not chain-blocking; corrupts every shutdown-classification verdict)
**Watch-List entry**: A-8 (was MEMORY's "Finding A — instrument honesty")
**Status**: Reproduced + root-caused; was already on Sprint-39 explicit out-of-scope list
**Verdict authority**: Atlas (Sprint-38 instrument design owns this layer)

---

## Summary

The `boot-progress-finalize.service` systemd unit, intended to write the
`CLEAN_COMPLETE` rung at the very end of an orderly shutdown, **does not fire its
ExecStop during a real shutdown.** Cause: the unit declares `DefaultDependencies=no`
+ `Before=shutdown.target` but does *not* declare any directive that pulls it into
the shutdown transaction. systemd brings it up at boot (per `WantedBy=multi-user.target`)
but never includes it in the shutdown transaction, so its ExecStop is silently skipped.

Result: the `boot_progress` ladder file always ends at `RUNNING` (the arm-unit
stage), never reaches `CLEAN_COMPLETE`. The next boot's `startup_log` row reads
`prior_boot_clean=0, prior_boot_last_stage=RUNNING, prior_boot_reason=crashed_during_operation`
**regardless of whether the prior shutdown was a clean sequencer poweroff or an
actual hard crash.** The "honest instrument" is dishonest.

## Evidence — directly observed clean shutdowns mis-classified

Two consecutive sequencer-driven shutdowns this session (Tests 1 + 2 of F-7's drill),
both **observed by CIO** as gentle 5s smoothing → systemd poweroff → all dark, are
classified by the Pi's own instrument as crashes:

| Boot ID | What CIO + Atlas observed | `startup_log` says |
|---|---|---|
| `34f35552623b` (Test 1) | Sequencer fired at key-off 19:47:32, journal `external power LOST` → smoothing → clean poweroff → all dark by 19:47:39 | `prior_boot_clean=0, last_stage=RUNNING, reason=crashed_during_operation` |
| `741393777485` (Test 2) | Sequencer fired at key-off 20:30:07 after engine-recovery, journal `external power LOST` → smoothing → clean poweroff → all dark by 20:30:15 | `prior_boot_clean=0, last_stage=RUNNING, reason=crashed_during_operation` |

Both shutdowns reached `shutdown.target` and `poweroff.target` cleanly in the systemd
journal. **Both produced a `crashed_during_operation` classification.** The classifier
cannot distinguish a clean sequencer poweroff from a hard power-yank.

## Root cause (systemd unit ordering)

`deploy/boot-progress-finalize.service`:

```ini
[Unit]
Description=Eclipse OBD shutdown breadcrumb finalizer (honest instrument)
DefaultDependencies=no                          # ← opts out of auto-stop on shutdown
After=eclipse-obd.service drain-forensics.service
Before=shutdown.target                          # ← ORDERING-ONLY, not a wants/requires

[Service]
Type=oneshot
RemainAfterExit=yes                             # ← stays "active" after /bin/true
ExecStart=/bin/true
ExecStop=/home/mcornelison/obd2-venv/bin/python -m src.pi.diagnostics.boot_progress --finalize ...

[Install]
WantedBy=multi-user.target                      # ← brings unit up at boot; nothing tells it to stop on shutdown
```

`DefaultDependencies=no` removes the automatic `Conflicts=shutdown.target` (and the
`Before=` on shutdown.target) that systemd would normally synthesise. The user
explicitly added `Before=shutdown.target` to *re-establish* the ordering, but
`Before=` is an ordering directive (*"if both are being acted on, do me first"*),
not an activation directive (*"include me in the transaction"*). Without a
`Conflicts=shutdown.target` or `RequiredBy=shutdown.target` or `WantedBy=shutdown.target`,
systemd has no reason to stop this unit during a shutdown — and therefore its
ExecStop never runs.

This is confirmed by the journal: in both Test 1 and Test 2 shutdown sequences, the
journal shows `Stopping`/`Stopped` for `eclipse-obd.service`, `eclipse-powerwatch.service`,
and `boot-progress-arm.service` — but **no such line for `boot-progress-finalize.service`**.
Then `shutdown.target` is reached and the system powers off. ExecStop never fired.

The unit's intent (write `CLEAN_COMPLETE` at the very last possible moment) is sound;
the implementation's dependency graph is incomplete.

## Fix sketch

Add `Conflicts=shutdown.target` to `[Unit]`, which pulls the unit into the shutdown
transaction (its stop-job becomes a member of the transaction that activates
shutdown.target), preserving the `Before=` ordering. Equivalent alternatives:

- Change `[Install] WantedBy=multi-user.target` to also include `shutdown.target`
  (less idiomatic — Want is for activation, not for stop-on-shutdown).
- Remove `DefaultDependencies=no` (cleaner but loses the original author's intent of
  custom ordering control; the `Conflicts=shutdown.target` form preserves that intent).

The recommended minimal change:

```ini
[Unit]
Description=Eclipse OBD shutdown breadcrumb finalizer (honest instrument)
DefaultDependencies=no
After=eclipse-obd.service drain-forensics.service
Before=shutdown.target
Conflicts=shutdown.target                       # ← NEW: pull unit into shutdown transaction
```

After deploy + reload, the next clean shutdown should write `CLEAN_COMPLETE` and the
following boot's `startup_log` should read `prior_boot_clean=1, last_stage=CLEAN_COMPLETE,
prior_boot_reason=graceful`.

## Implications for chain-merge IRL acceptance verdict (this morning)

This morning's "3-of-3 Cycle-A PASS" verdict (Sprint 39 / V0.27.15 chain-unblock
candidate) was made by **direct CIO observation** of clean gentle poweroffs + auto-boot
cycles. That verdict is **correct** on the externally-observable facts — and the same
gentle pattern was re-observed by CIO + Atlas live in Tests 1 + 2. The Pi's own
classification of all three morning drills as `crashed_during_operation` was the
**instrument lying**, not the drills actually crashing.

**This significantly de-fangs the "12 boots crashed today" headline in Spool's
Finding C.** Many of those 12 were almost certainly clean sequencer shutdowns mis-
classified — the broken finalizer ensures every clean shutdown looks identical to
a real crash on the Pi side. Without external observation we cannot tell which
were real and which were instrumental noise.

This does NOT excuse this afternoon's bricking failure pattern — F-7 (boot-grace
latch defect) is a separate, structural, chain-blocking bug. But it does tell us:

- **`startup_log.prior_boot_reason` is not a reliable acceptance signal until F-8
  is fixed.** Tester / regression manifest should NOT use it as a gate.
- **Direct observation (CIO eyewitness, journalctl shutdown sequence) is the
  authoritative source** for "was this a clean shutdown."
- **Once F-8 is fixed, `startup_log` becomes useful again** — and counting future
  `crashed_during_operation` rows becomes meaningful evidence.

## Scope and history

- This finding was already on the MEMORY watch list as "Finding A — instrument
  honesty" and was *explicitly out of scope* of Sprint 39 / V0.27.15 per CIO
  directive. The CIO note in MEMORY explicitly says "do NOT let chain merge imply
  closed."
- **F-8 does not change that out-of-scope decision.** Chain merge can still proceed
  on F-7 fix + IRL re-validation; F-8 closure is a separate, parallel sprint item.
- However, **this is the first time F-8 has been empirically proven** (via two
  observed-clean shutdowns mis-classified within a single session). It is no longer
  a hypothesis; it is a confirmed structural defect.

## Recommended sequencing

1. **Now**: file F-8 (this) as a tech-debt + issue under PM, lane is `offices/pm/issues/`
   (not blockers — F-7 is the blocker).
2. **Sprint 40 candidate**: bundle F-8's fix into the same sprint that fixes F-7
   (low cost — one-line unit-file change + verify-on-real-Pi).
3. **Tester**: until F-8 fixes ship, treat `startup_log.prior_boot_reason` as
   advisory-only. Direct journal-shutdown-sequence observation is the gate of record.
4. **Spool**: update Finding C's "12 boots crashed today" framing — the bricking-
   loop alarm stands (HAT battery did go dead — F-7 caused it), but the
   classification number itself is partly noise until F-8 lands.

## Related findings

- **F-7 (chain-blocking, same date)**: separate root cause, separate fix scope, can
  ship in same sprint or sequentially. F-8 fix is mechanically simpler (one
  systemd-directive line). F-7 fix is small Python in the polling loop.
- **Spool's Finding C (2026-05-20)**: F-8 explains the "12 boots crashed" inflation;
  F-7 explains the actual operational failure.

## Atlas process notes

This finding lands in the Sprint-38 honest-instrument design layer (`boot_progress.py`
+ unit files), authored by the same `2026-05-17 Sprint 38 T11` plan. The design intent
was correct; the deployment unit-file was incomplete. This is a deploy/wiring class
bug, not a design class bug — the design (the `boot_progress` ladder, the arm/finalize
split, the *"only CLEAN_COMPLETE means clean"* invariant) is sound.
