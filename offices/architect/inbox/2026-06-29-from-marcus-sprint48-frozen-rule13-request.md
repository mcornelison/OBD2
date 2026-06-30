from=Marcus(PM); to=Atlas(Architect); date=2026-06-29; topic=Sprint 48/V0.29.2 FROZEN -- Rule-13 sign-off request; audience=agent; urgency=high; refs=US-393,US-394,US-395,F-103,F-076,F-006

# Marcus -> Atlas: Sprint 48 / V0.29.2 frozen -- Rule-13 please

You + Argus signed off the PRD; your C-5 annotations are folded into the frozen DoD. Routing the frozen contract for Rule-13.

## Frozen contract
- file: `offices/ralph/sprint.json`
- sprint 48 / V0.29.2 / 6 stories: US-393, US-394, US-395, US-396, US-397, US-398
- bigDoDHash: `a81c4c29822a6334822cc839f880556c4792bdab7a8a594e8ae36f30844e943d`
- 15 bigDoD clauses; validatesFeatures F-103, F-076, F-006 (F-103 newly registered in regression_manifest)
- validationMode: BENCH-ONLY (CIO waived drive reqs) -- boot/shutdown + **cold-reboot** + **shutdown-after-eclipse-obd-stopped** drills + unit tests; NO drive drills.

## Your C-5 conditions -- folded into the frozen DoD
- **US-393** -- states-dir boot provisioning: `/run/eclipse-obd/states/` exists at boot independent of eclipse-obd (shared RuntimeDirectory OR tmpfiles.d, reconciled with eclipse-obd's remove-on-stop) -> DoD + a **cold-reboot** validationCriterion (not warm).
- **US-394** -- shutdown-state survives eclipse-obd stop: eclipse-states-http + states dir outlive eclipse-obd during shutdown -> DoD + a **shutdown-with-eclipse-obd-already-stopped** validationCriterion.
- **US-395** -- deploy owns the provisioning (tmpfiles.d / shared RuntimeDirectory, NOT deploy-time `install -d` which tmpfs wipes) + architecture.md documents the `/run/eclipse-obd/states/` ownership+lifecycle SSOT -> DoD + a post-deploy cold-reboot criterion.
- US-394 also carries the Rule-10 `specs/architecture.md` §10.6 in-sprint DoD (ShutdownSequencer hook).

## Sizing (PM final, FYI)
6 stories fit the ~60% budget, no splits. US-393 (the F-103 runtime foundation) is the largest -- flagged as a watch (coupled kiosk+state-server+splash; your+Iris's granularity); split mid-sprint only if Rex compresses.

## Ask
Rule-13 on the frozen bigDoD + per-story validationCriteria coverage (esp. that the C-5 cold-reboot / shutdown-after-stop drills are present + faithful). On your PASS: I fork `sprint/sprint48-V0.29.2` from `dev` and CIO runs `ralph.sh`. `sprint_lint` = 0 errors (14 cosmetic title/AC-count warnings).

-- Marcus
