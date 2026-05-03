# TD-046: Stale Cross-Component State Shared By Reference -- Codebase Audit Needed

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | architecture              |
| Affected     | Codebase-wide; suspected hot spots in `src/pi/power/`, `src/pi/hardware/`, `src/pi/obdii/orchestrator/`, `src/pi/diagnostics/` |
| Introduced   | Pre-Sprint-21; bug class went undetected for 8 drain tests (Sprints 21-24) before Drain Test 8 isolated the canonical instance |
| Created      | 2026-05-03                |
| Filed by     | Rex (Ralph), Sprint 24, US-281 (companion anti-pattern doc) |

## Description

The 8-drain saga (Sprints 21-24) was caused by a single instance of a broader bug class: cross-component state shared by reference, with no freshness contract / pull-getter / push-callback. `PowerDownOrchestrator.tick()` read `power_source` from a stale view while `UpsMonitor._pollingLoop` correctly detected the BATTERY transition. Because the orchestrator's view was never refreshed, every tick bailed at the first guard, the staged shutdown ladder never fired, and the Pi hard-crashed at the LiPo dropout knee on every drain.

Sprint 24 US-279 fixed this specific instance via Escape Hatch #3 (push-with-acknowledgment callback). Sprint 24 US-281 documented the bug class as a project anti-pattern in `specs/anti-patterns.md` ("Stale Cross-Component State Shared By Reference").

**This TD records the hunting protocol for the next audit pass to find similar instances elsewhere in the codebase.** It is filed Severity Low, Status Open as a future maintenance item -- no production drift is currently confirmed, but the same shape is statistically likely elsewhere given how many components share sensor/state data on the Pi tier.

## Why It Was Accepted

Closing this TD requires reading every cross-component state-sharing site in the Pi-tier codebase and judging whether it has one of the three escape hatches (TTL / pull / push). That's a multi-hour audit and outside Sprint 24's scope. Sprint 24 took the higher-leverage win (fix the canonical instance + document the anti-pattern); a sweep can be scheduled when capacity allows.

## Risk If Not Addressed

| Likelihood | Impact | Combined |
|---|---|---|
| Medium | Variable -- depends on which state and how silently it fails | **Medium-Low** |

The 8-drain saga proves this bug class can hide for an extended period when the failure mode is "silent runtime divergence under conditions you don't synthetically test." Other candidate consumers in the codebase that read sensor or state data from a sibling component (and whose failure would be invisible to unit tests) carry the same risk shape until proven safe.

If undetected and the same pattern bites a second consumer, the cost is another multi-sprint investigation. Cheap to audit pre-emptively; expensive to debug live.

## Hunting Protocol

The audit pattern is: **find every place a component holds another component's state by reference and reads it without going through a getter, callback, or TTL-checked cache.** Concrete commands:

### Step 1 -- Find candidate consumers (components that hold a reference to another component)

```bash
# Constructors / __init__ that take another tier component as a dependency
rg --type py -n "def __init__\(self.*(UpsMonitor|PowerMonitor|PowerDownOrchestrator|TelemetryLogger|HardwareManager)" src/pi/

# Attribute assignments that capture the reference
rg --type py -n "self\._(upsMonitor|powerMonitor|orchestrator|telemetryLogger|hardwareManager) = " src/pi/
```

### Step 2 -- Find places that read state through that reference

For each consumer found in Step 1, grep the consumer's module for state reads that bypass a getter:

```bash
# Direct attribute access on the reference (likely cached state, no freshness check)
rg --type py -n "self\._upsMonitor\.(powerSource|vcell|soc|crate)" src/pi/
rg --type py -n "self\._powerMonitor\.(currentSource|status|state)" src/pi/
rg --type py -n "self\._hardwareManager\.(upsMonitor|powerMonitor|obd)" src/pi/

# Cached state on self that was read once at __init__ and never refreshed
rg --type py -n "self\._powerSource|self\._currentSource|self\._currentStage" src/pi/

# Snapshot-then-read patterns (snapshot may be stale by tick time)
rg --type py -B2 -A4 "snapshot\(\)" src/pi/
```

### Step 3 -- Classify each find

For each match, judge which category it falls into:

1. **Safe (Escape Hatch #1)**: read goes through a TTL-checked cache (look for `time.monotonic() - self._readAt` style checks)
2. **Safe (Escape Hatch #2)**: read goes through a getter on the producer (look for `self._upsMonitor.getPowerSource()` style calls)
3. **Safe (Escape Hatch #3)**: consumer maintains state via a callback registered on the producer (look for `registerXxxCallback` / `_onXxxChange` pairs)
4. **At risk**: direct attribute read of producer's state, no getter, no callback, no TTL -> document the seam, file follow-up
5. **Single-instance / read-once-at-init**: state is genuinely immutable for the consumer's lifetime (e.g., a chip ID read at construction) -> mark safe with rationale

### Step 4 -- Document findings + remediate

For each "at risk" find, choose:

- Patch in place to use the appropriate escape hatch (preferred when the seam is small)
- File an issue under `offices/pm/issues/I-XXX-<seam>.md` for the next sprint's grooming candidate (when the seam crosses multiple files)

Update this TD's Status field as audit progresses: `Open` -> `Auditing` -> `Resolved` (with closure notes naming each find and how it was resolved).

## Suspected Hot Spots

Pre-audit guesses (low confidence; concrete confirmation requires running the hunting protocol):

| Module | Why Suspect | Confidence |
|---|---|---|
| `src/pi/power/orchestrator.py` | Already fixed by US-279; any *other* state held cross-component? | Medium (already audited for `power_source`; other fields not reviewed) |
| `src/pi/hardware/telemetry_logger.py` | Reads UpsMonitor + PowerMonitor + multiple sensor sources; aggregator is a classic Escape-Hatch-#2 candidate but may carry direct attribute reads | Medium |
| `src/pi/diagnostics/` (boot_reason.py, drain_forensics.py) | Boot-state + drain-state aggregators that read across components | Low-Medium |
| `src/pi/obdii/orchestrator/` (core.py, event_router.py) | Drive-state machine reads OBD + power state from multiple sources | Low-Medium |
| `src/common/` (tier-shared models) | Less suspect -- shared models tend to be value objects, not stateful references | Low |

## Remediation Plan

**Phase 1 -- Hunting pass** (1 sprint slot, S size if findings are minimal):
Run Steps 1-3 of the hunting protocol on `src/pi/`. Produce a written audit report (an inbox note from the auditor to PM) listing every find by category. Phase 1 *only* produces the report; it does not patch anything.

**Phase 2 -- Remediation** (sized by Phase 1 findings, S to L depending on seam count):
For each "at risk" find, patch in place or file a follow-up issue. Each patch should add a synthetic test that fails pre-fix per `feedback_runtime_validation_required.md`. Update this TD's Closed field with closure notes per find.

**Phase 3 -- Close**:
Set Status = Resolved when Phase 2 ships. Update `specs/anti-patterns.md` modification history to point at this TD's closure date as evidence of a clean codebase.

## Reference

- `specs/anti-patterns.md` "Stale Cross-Component State Shared By Reference" (US-281, Sprint 24)
- US-279 (Sprint 24): the canonical Escape Hatch #3 fix
- Drain Test 8 forensic CSV (`/var/log/eclipse-obd/drain-forensics-20260503T135023Z.csv` on Pi): empirical signature of the bug class
- `offices/pm/inbox/2026-05-03-from-spool-sprint24-ladder-fix-bug-isolated.md`: the Spool note that diagnosed the bug class and recommended this TD
