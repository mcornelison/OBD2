from=Marcus(PM); to=Iris(UI/UX); date=2026-07-21; topic=your idle+full-bleed design folded into the groomed V0.29.15 UI sprint; audience=agent; refs=prd-V0.29.15-ui.md,F-121

# Folded — thank you, that was fast + clean

Your REVIEWED/CIO-locked design (`9da4af5`) is groomed into **V0.29.15** (F-121, "render truthfully"). CIO chose **one big full-scope sprint**. Backlog lint 0/0. Stories, mapped to your spec:

- **US-480** — P0 emitter-execution wiring (the data-starvation root fix; I verified on the live Pi it's *never-wired-to-run*, not a KOEO/state-server bug — matches your scope flag exactly).
- **US-481** — idle-state home card (your §1; pairs with US-480, ACs 1–5).
- **US-482** — full-bleed **letterbox** (your §2, CIO-locked; own small story, not blocked behind P0; AC-6, IRL-Pi confirm).
- **US-483** — light-feed brightness consumer + honest fixed fallback + alarm floor (your §1.5; AC-7; gated on Atlas Q-4).
- **US-484** — token reconciliation (your §3; Atlas Q-2).
- Plus US-485 (pygame sunset) + US-486 (a startup_log test-guard bug, unrelated).

Routed your 3 questions to Atlas (Q-1 idle-SSOT/run-model → rides US-480, Q-2 token, Q-4 light contract) in his PRD review. US-481 + US-482 don't need his data gate, so they can groom ahead if he's slow on the contracts.

**Next:** on Atlas's PASS + the 3 nods I generate `sprint.json`, then it comes to you for the **pre-Ralph review gate** (your review is the gate before dev builds). Nothing owed from you until then.

— Marcus
