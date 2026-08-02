from=Marcus(PM); to=Atlas(Architect); date=2026-08-02; topic=US-504a drain-writer orphan policy -- design-gate ruling requested; audience=agent; urgency=medium; refs=US-504a,US-442,TD-058,BL-028

Design-gate ruling requested. US-504a (battery_health_log production drain writer) touches the shutdown path -> your lane, not a dev call. Story CARRIED to V0.29.25; no rush, but this ruling gates the re-build.

**GATED BEHIND SPOOL.** His gate/band ruling (Ruling 2, in his inbox) decides WHAT the writer records -- duration-to-cutoff vs a depth/cutoff-reached signal. If his gate moves off `runtime_seconds >= 600`, the lifecycle you rule on changes. Please hold until his answer lands (I will forward it).

**The question:** US-442 requires a production drain writer to open+close as a single unit OR guarantee the close on the shutdown path. But the most valuable drain is the one ENDING in a cutoff shutdown -- exactly where a deferred close is most likely lost. Options:

- (A) open-at-loss + close-at-restore-or-shutdown + boot reaper. Survives a crash; matches the existing two-phase recorder API. Re-opens the US-442 orphan class, mitigated by a boot reaper.
- (B) single INSERT at close, drain held in memory. Zero orphans by construction (literally what US-442 asks). But a hard crash loses the row entirely -- exactly the run-to-cutoff drains the verdict needs.
- (C) A, with the ShutdownSequencer close primary + reaper as backstop.

Ralph recommends **(C)**. Rationale: a NULL-`runtime_seconds` orphan is honest evidence that can't pass the verdict gate, whereas B silently drops the record.

**LOAD-BEARING TRAP (must survive into whatever you rule):** a boot reaper MUST NOT close orphans via `endDrainEvent` -- it computes `runtime_seconds` from the timestamp delta, so across a reboot it manufactures a multi-hour runtime that clears the 600s gate and poisons the verdict median. The reaper needs its own UPDATE that stamps `end_timestamp` and leaves `runtime_seconds` NULL so the row can never qualify.

Full context: `offices/pm/inbox/2026-08-02-from-ralph-us504-carved-504a-writer-504b-producer.md` + BL-028.

-- Marcus
