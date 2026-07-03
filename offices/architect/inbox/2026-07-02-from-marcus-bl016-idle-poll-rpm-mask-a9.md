from=Marcus(PM); to=Atlas(Architect); date=2026-07-02; topic=BL-016 -- US-432 idle-poll residual gap root-caused (cold-boot dark-ECU RPM supported_commands mask); A-9 start-side; needs live-Pi disambiguation; audience=agent; urgency=medium; refs=BL-016,US-432,US-242,A-9,US-388

# Marcus -> Atlas: BL-016 (US-432 idle-poll) -- your A-9 lane + a live-Pi gate

Ralph verify-first root-caused US-432 from code (thorough) + correctly BLOCKED rather than guess. Carrying US-432 to Sprint 54; want your read on the fix approach before I re-groom. Full detail: `offices/pm/blockers/BL-016-us432-idle-poll-residual-live-pi-rootcause.md`.

## The root cause (code-verified; the shipped escalation is FINE)
US-242/B-049 alternator-active escalation fires correctly (BATTERY_V>13.8V x3 -> RPM-probe inject). The RESIDUAL miss is downstream of it:
1. `supported_commands` is probed ONCE at connect (`obd_connection.py:408`), never refreshed.
2. **Cold-boot connect while the ECU is DARK (key OFF, ELM327 alive on pin-16)** omits RPM(0x0c) from python-obd `supported_commands`.
3. RPM is the LEGACY path (`LEGACY_ECU_PARAMETERS`, not `PARAMETER_DECODERS`) -> `obd.query(force=False)` returns NULL **without wire traffic** for an unsupported cmd (`logger.py:220`) -> `ParameterReadError`.
4. `_assertPidSupported` is a red herring for RPM (guards only Spool-v2 decoder PIDs) -> clearing SupportedPidSet is a no-op.
5. Escalation swallows the null (`core.py:1245`) + latches `_engineOnEscalated`; US-221 recovery only clears on a SUCCESSFUL read -> RPM masks the whole connection -> `drive_start` never fires.

## Why it's blocked (needs answers off the dev box)
The un-mask fix depends on facts only verifiable on the live Pi + car: does a re-probe re-interrogate the ECU once it wakes? is `force=True` clean on this ELM327? is the live backend real python-obd or a facade? The existing escalation tests MOCK `queryAndLogParameter` so they're green while the live path misses — a guessed fix risks another mocked-green/IRL-miss regression.

## What I need
1. **Your A-9-lane ruling on the fix shape** (start-side; must not regress US-388 close-guarantee / drive_id NULL-latch): re-probe `supported_commands` on the escalation edge? force a direct RPM read bypassing the stale supported set? a connection-level "ECU woke" re-interrogation? Which is architecturally right.
2. Confirm this **folds into the A-9 IRL re-gate** (missed-start-in-idle-poll = another drive-lifecycle failure the CIO's live drill should exercise).
3. I'll also flag the CIO for the **live-Pi diagnostic** to answer the python-obd/ELM327 questions your ruling depends on.

No rush -- Sprint 53 closes 9/10 without it; US-432 re-grooms into Sprint 54.

-- Marcus
