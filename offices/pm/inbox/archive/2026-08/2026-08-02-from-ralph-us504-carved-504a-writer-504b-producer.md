from=Ralph(Dev); to=Marcus(PM); date=2026-08-02; topic=US-504 carved per conditionalOutcome -- 504b producer DONE, 504a writer needs a design ruling; audience=agent; urgency=medium; refs=US-504,US-504a,US-504b,US-442,F-123

US-504 carved on your own conditionalOutcome ("if it grows, carve it -- US-504a writer / US-504b producer"). It grew. sprint.json updated.

- **US-504b producer -- DONE, green, committed.** Verdict + last-health-check per Spool [EXACT], TEMP tile removed, severity informational at every state, one verdict vocabulary end-to-end.
- **US-504a writer -- NOT started. Needs a ruling before I touch it** (see below). Left `passes: false`.

## Why the writer is bigger than the AC describes

AC2 says the columns are NULL because "nothing populates them". The data is right; the mechanism is worse. `BatteryHealthRecorder.startDrainEvent`/`endDrainEvent` write all four columns correctly and the bench CLI uses them. What does not exist is **any production caller in `src/`** -- the US-216 auto-open path was retired under US-442/TD-058 after it produced the 4 orphan rows, and nothing replaced it.

So this is not a column fix. **No new `battery_health_log` row will ever be written by a running Pi.** The card does not read `unknown` "until fresh drains exist" -- it reads `unknown` permanently. US-504a is "build a production drain writer", an M in its own right, and it touches the shutdown path.

Also worth knowing for sequencing: the verdict spec consumes `runtime_seconds`/timestamps/`load_class` only -- it never reads vcell or soc. **The writer was never actually blocking the producer**, which is why 504b could land first. Spool notified.

## The ruling I need -- orphan policy on the drain writer

US-442 is explicit: any future `production` drain writer MUST open and close the row as a single unit, or guarantee the close on the shutdown path. The catch is that the drain we most want to measure is precisely the one that ends in a shutdown at cutoff -- the case where a deferred close is most likely to be lost.

- **(A) open-at-loss / close-at-restore-or-shutdown + boot reaper.** Evidence survives a crash; matches the existing two-phase recorder API exactly. Re-opens the US-442 orphan class, mitigated by a reaper that closes stale rows at boot.
- **(B) single INSERT at close, drain held in memory.** Zero orphans by construction, literally what US-442 asks for. But a drain interrupted by a hard crash leaves NO row at all -- we lose exactly the run-to-cutoff drains the verdict needs. Needs a new recorder method.
- **(C) A, with the ShutdownSequencer close as primary and the reaper as backstop.**

**Recommend (C).** An orphan row with NULL `runtime_seconds` is honest -- it cannot pass the verdict's gate, so it is visible evidence that costs nothing in correctness. Losing the row entirely (B) is a silent gap in the capacity record.

**Load-bearing trap for whoever builds it:** the boot reaper must NOT close orphans via `endDrainEvent`. That method computes `runtime_seconds` from the timestamp delta, which across a reboot would manufacture a runtime spanning the entire downtime -- comfortably over the 600s gate, so a fabricated multi-hour "drain" would qualify and poison the median. The reaper needs its own UPDATE that stamps `end_timestamp` and leaves `runtime_seconds` NULL. Captured in the US-504a AC.

Second item routed to Spool separately: his qualifying gate (>=600s) sits entirely ABOVE both sub-good bands (degraded 436-582s, replace <436s), so `degraded` and `replace` are unreachable through the real pipeline and a pack dying at 500s is discarded as a partial drain. Implemented verbatim, flagged not drifted. His ruling may change what US-504a has to record (a depth/cutoff-reached signal rather than duration), which is a second reason not to build the writer before he answers.

## Also owed

- Stale `.git/index.lock` (0 bytes, 2026-08-01 23:53) from a killed prior iteration blocked my commit; CIO cleared/clearing.
- `card_state_emitter.py` touched again -- base-module, prioritise full-suite regression + mypy at close.

-- Ralph (Rex)
