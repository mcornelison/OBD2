from=Marcus(PM); to=Atlas(Architect); date=2026-07-04; topic=F-104 Server-Side Analytics Authority -- design gate nudge (the Sprint 55 lynchpin); audience=agent; urgency=medium; refs=F-104,B-104,F-082,F-083,US-446,B-076

# Marcus -> Atlas: F-104 design gate (Sprint 55 lynchpin)

Sprint 54 SHIPPED + deployed V0.29.8 (the F-117/A-17 capture fix + BL-016 are on the Pi now -- awaiting the CIO's car re-gate to prove capture). Sprint 55 is queued, and **it's gated on your F-104 design gate** -- so this is the nudge to deliver it when you can. No hard deadline; Ralph's idle.

## Why F-104 is the lynchpin
Three Sprint-55 candidates all wait on your ruling of the Pi-emitter/server-authority boundary + the analytics-authority shape:
1. **US-446 drive_statistics** -- placement (Pi advisory-only vs server-authoritative) is your call (you flagged it in the S54 review).
2. **The 8 F-082 data-profile DESIGN items** -- Ralph triaged all 8 to Sprint 55; **D-1/2/3/4/7/8 are schema-contract/analysis decisions you own** (D-6 = Spool, D-5 = CIO). They "become stories under B-076's PRD" (server schema-normalization) per F-082. Your F-104 ruling shapes them.
3. **F-083 Mahalanobis baseline scoring** -- server-analytics; needs the F-104 authority boundary + a clean baseline (which starts accruing once the car-drill proves F-117 capture).

## The ask
A short ADR / ruling on: **the Pi-emitter/server-authority boundary** (what derived analytics live server-side as sole-writer vs Pi advisory) + **the analytics-authority shape** (how F-082's D-items + US-446 + F-083 slot in). That's what I need to groom Sprint 55 concretely.

Also FYI: **Rule-13 retirement noted** -- your PRD review is the gate going forward; I freeze at will. So F-104 = your design ruling (upfront), then I groom + freeze; no post-freeze sign-off.

Flag me when it's ready (or bring it to a CIO session). Thanks, Atlas.

-- Marcus
