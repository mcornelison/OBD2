# TD-077: the open drain row is never checkpointed — a lost shutdown write loses the ONLY drain that can qualify

| Field      | Value                                                        |
|------------|--------------------------------------------------------------|
| Type       | tech-debt                                                    |
| Severity   | Medium (no wrong number is produced; a *correct* measurement is silently lost) |
| Status     | Open                                                         |
| Parent     | F-123                                                        |
| Filed      | 2026-08-03 (Ralph/Rex, during US-527)                        |
| Refs       | US-526, US-527, TD-074, Spool ruling `429a3ed` Consequence 2  |

## What

Spool's US-504a ruling (`offices/ralph/inbox/2026-08-02-from-spool-us504a-unblocked-depth-gate-consequences.md`,
commit `429a3ed`, "Consequence 2") specified that the **open** drain row be
UPDATEd every **`[EXACT: 30]` s** while draining, writing the current
`end_vcell_v` / `end_soc_pct` / `runtime_seconds` onto it. He was explicit that
this was the part he most wanted built, and framed it as a *simplification*:

> "That converts 'must not lose the shutdown write' from a hard requirement into
> a soft one."

**US-526 shipped without it.** `src/pi/power/drain_event_writer.py` implements
open-at-loss + close-at-restore/shutdown + the boot reaper, but there is no
periodic checkpoint (verified 2026-08-03: no `checkpoint`/interval mechanism in
`drain_event_writer.py` or `power_watch/controller.py`, and `[EXACT:30]` appears
nowhere in the power tree). No existing TD tracked it.

## Why it matters more now than when it was specified

US-527 has landed the **depth gate** (`end_vcell_v <= 3.50 V`). Under a depth
gate, **the cutoff-shutdown drain is the only drain that can ever qualify** — a
bench AC→BATTERY→AC tap restored at ~3.8 V correctly never qualifies. So the one
row the health verdict depends on is written best-effort at the *least reliable
moment in the system*, and per I-038 that write may never delay the
ShutdownSequencer.

Failure mode, and note it is the *quiet* kind rather than a wrong value: on a
hard crash at cutoff the shutdown close is lost, the boot reaper (correctly,
per US-526's honest-NA invariant) stamps `end_timestamp` only and leaves
`runtime_seconds` **and** `end_vcell_v` NULL — so the row is doubly excluded by
the gate. Nothing lies; the drain simply **does not count**. Repeat that a few
times and the verdict sits on `unknown` while the operator believes drains are
being measured.

With checkpointing the same crash leaves a real voltage and runtime from at most
30 s before cutoff — against the 727 s baseline a ≤4% error, which Spool stated
is well inside tolerance for a capacity measurement. Spool also pre-approved 60 s
(≈8% worst case) if 30 s is too much I/O on battery.

## Fix

Add a periodic UPDATE of the open row (30 s, Spool's `[EXACT]` value; 60 s
pre-approved) in the drain writer's battery-side path. Two constraints from the
existing rulings must be preserved:

1. The **reaper must still never compute** `runtime_seconds` — it stamps
   `end_timestamp` only and leaves whatever the checkpoint wrote, real or NULL.
   Spool's amended wording: *"It never computes, never guesses, never
   overwrites."*
2. `first-close-wins` (`battery_health.py:123-125`) must not be disturbed — a
   checkpoint writes to a row that is still **open** (`end_timestamp` NULL), so
   it must not be routed through `endDrainEvent`.

## Why it is not being fixed in US-527

US-527's scope is the verdict's qualifying gate (`verdictForMedianRuntime` +
`_parseRow` + the read SQL). Checkpointing is writer-side behaviour in
`drain_event_writer.py`, a different module and a different AC set — Rule 3
scope fence. Filed rather than silently worked around.
