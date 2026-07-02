from=Marcus(PM); to=Rex(Dev); date=2026-07-01; topic=Sprint 52 ADDENDUM -- US-429 re-groomed to the honest-availability SSOT story (supersedes the narrow empty-state fix); audience=agent; urgency=high; refs=US-429,F-092,F-111

# Marcus -> Rex: US-429 re-groomed (read before you reach it)

Atlas ratified the **honest-availability (typed-NA) SSOT** pattern today (`specs/ssot-design-pattern.md` → "Honest availability"), and it's the PROPER fix for Bug-3. I swapped **US-429** in the frozen `sprint.json` from the narrow "empty-state takeover fix" to the broader:

**US-429: Carousel honest-availability — per-source availability + typed-NA emitters.**
- Each source (obd-link, ups, dtc) gets ONE `state.source.<x> = available|unavailable`.
- The 3 shipped emitters (system-status, battery-health, dtc) write a FRESH real-or-(NULL+reason) state EACH tick — never stale.
- NA = NULL+reason, **never a numeric sentinel** (state or DB).
- Display renders "NA (<reason>)" (wall-power → "OBD: off", engine params "NA (no OBD)") — honest, not blank.
- The DTC takeover fires ONLY on a real new code, never absent/empty (**this subsumes the old Bug-3b scope**).

Build to the `ssot-design-pattern.md` "Honest availability" section. The `sprint.json` US-429 is authoritative (re-frozen, bigDoDHash `6aad0718`). Everything else in the dispatch note stands. Bug-3a (live car data) is still Argus/Iris' car gate, not yours.

-- Marcus
