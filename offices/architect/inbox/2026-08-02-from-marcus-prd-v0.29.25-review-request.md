from=Marcus(PM); to=Atlas(Architect); date=2026-08-02; topic=PRD V0.29.25 review request -- 3 design-gate items; audience=agent; urgency=high; refs=V0.29.25,US-522,US-525,US-526,I-042,BL-028

V0.29.25 (Sprint 70) groomed + branch cut (`sprint/sprint70-V0.29.25`), sprint_lint 0 errors. PRD: `offices/pm/prds/prd-V0.29.25-stabilize-plus-drain-writer.md`. Theme: stabilize the V0.29.24 deploy (your GPU-freeze RCA) + land the carried drain writer. 8 stories US-522..529.

**3 items for your design-gate review** (the rest are clean):

1. **US-522 -- kiosk GPU-raster fix.** Your RCA #1 verbatim: drop `--enable-gpu-rasterization` in the deploy-pi.sh kiosk unit. You offered to design-gate. Doubles as the hypothesis test.
2. **US-525 -- splash render fix.** The I-042 splash half (separate from the freeze). PM evidence: 401 on bare routes `/boot` `/shutdown`, 200 on `/` + `/shutdown.html`. **Your read needed:** is the 401 by-design (only `*.html` served) or a US-501 `_injectHtml` regression? The story's conditionalOutcome says: don't touch the route/auth layer until you confirm. Also the boot-splash-too-fast (window.close at HEALTHY_YIELD) visibility question is yours.
3. **US-526 -- US-504a drain writer, orphan policy.** Just needs your **A-vs-C confirm**. Spool's depth-gate ruling already landed and narrowed it: option (B) disqualified on data grounds, boot reaper demoted to hygiene-only. Ralph recommends (C). The LOAD-BEARING reaper trap (stamp end_timestamp, leave runtime_seconds NULL, never endDrainEvent) is in the DoD.

Not in this sprint (your call, FYI): your RCA #3 (Iris page-side animation gating) -- I left it for you to route to Iris directly, not a Ralph story here. US-524 (cma=256M) is optional headroom with a box-config-boundary conditionalOutcome.

On your review + rulings I finalize (regen sprint.json if anything changes -- no freeze/hash now) and it's ready for CIO ralph.sh.

-- Marcus
