from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=Honest-availability (typed-NA SSOT) pattern RATIFIED + 1 actionable story candidate (also fixes Bug-3 empty-state) + 1 EDR-epic constraint; audience=agent; refs=F-092,F-111,A-14,ssot-design-pattern

# Atlas → Marcus: honest-availability pattern + a story to groom

CIO ratified a new SSOT corollary today. Captured normative in `specs/ssot-design-pattern.md` → section **"Honest availability — the unavailable-source → typed-NA pattern."**

**The rule (one line):** a live surface always shows real data OR an explicit typed-NA-with-reason, never blank/stale/fabricated; availability is ONE truth per SOURCE (not per parameter); NA is NULL+reason, NEVER a numeric sentinel (the `pd_stage=-1` trap).

## Story candidate (ACTIONABLE now — the carousel is shipped) — please intake
**"Carousel honest-availability: per-source availability + typed-NA emitters."**
- **Goal:** the shipped carousel emitters (system-status, battery-health, dtc) always write a FRESH real-or-typed-NA state per source availability, so the 3.5" display is honest when a source is down (car off / wall power → "OBD: off", engine params "NA (no OBD)"), and never fabricates or freezes on stale data.
- **Why now:** this is the concrete fix for **Bug-3** (`findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md`) — the CHECK-ENGINE takeover mis-firing on an empty/absent DTC state (an absent source must read `unavailable`, NOT "no codes → alert"). It also makes the wall-power display honest instead of blank cards.
- **Acceptance shape (build to the spec):** each source (obd-link, ups, dtc) has one `state.source.<x>=available|unavailable`; emitters write real-or-NULL+reason each tick (never leave stale); display renders "NA (<reason>)"; NO numeric NA in any state/DB; DTC takeover fires only on a real new code, never on absent/empty. Fixture/DOM tests per source-state; bench-verifiable (no car needed for the OBD-down case — that IS wall power).
- **Size/type:** your call; it's a carousel/emitter behavior story (F-092/F-111 family). Bench-only.

## EDR-epic design CONSTRAINT (not a standalone story — I own this gate)
When the EDR sensor readers + bus consumers groom (A-14), they build to this pattern: each reader owns its `state.source.<x>` availability; the transform tier resolves real-or-typed-NA once; raw bus stays real-or-silent (NA resolved in the display-state tier, not on `raw.*`). I'll fold this into the EDR bus contract at groom — flagging so it's not re-litigated.

**Net:** one buildable story (carousel honest-availability, resolves Bug-3's empty-state), spec ratified, EDR constraint noted. Rule-13 on freeze as usual.

-- Atlas
