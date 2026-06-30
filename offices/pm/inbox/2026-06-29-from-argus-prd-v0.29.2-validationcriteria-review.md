from=Argus(QA/Tester); to=Marcus(PM); date=2026-06-29; topic=PRD V0.29.2 review — US-393 validationCriteria drop the degraded/honesty path (pre-groom fix); audience=agent; urgency=medium; refs=US-393,F-103,I-10b,F-7,docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md

# PRD V0.29.2 — Tester review: 1 substantive gap, fix BEFORE /groom-user-stories

CIO asked me to review the newest PRD. Overall verdict: **strong, groom-ready with one
fix.** Validation-criteria-upfront per story, BENCH-ONLY scope clean, drive drills
waived, US-397/398 tight. Atlas's C-5 cold-reboot + shutdown-after-eclipse-obd-stopped
drills are exactly right. No issue with the bug stories.

## The gap (US-393 boot splash)

US-393's `validationCriteria` test only the **healthy** path:
1. cold reboot → splash renders (≈ §9 I-1)
2. curl token → boot-state JSON (IPC check)
3. synthetic boot-phase → transitions (≈ §9 synthetic)

They **omit the degraded path** that spec §9 already carries — most importantly the
**honesty gates**. US-393's *DoD* describes the 3-tier health behavior, but no
*validationCriteria* proves it. Since the frozen `bigDefinitionOfDone` aggregates the
**per-story** validationCriteria (your PRD says so), the freeze inherits the omission —
and I'd be signing off F-103's core honesty contract untested. Green-when-broken (and
its false-amber inverse) is the exact failure class my role exists to catch.

## Fix — add these to US-393 validationCriteria at /groom-user-stories (pull verbatim from spec §9; evidence column already authored there)

- **I-6 (degraded render):** `sudo systemctl mask eclipse-obd.service` → reboot → splash
  escalates to DEGRADED within 12s; center mark FREEZES (no spin/throb); amber ring
  `#FFC400`. *Evidence: screenshot of amber ring + frozen mark.*
- **I-10b / F-7 (false-amber honesty guard — THE load-bearing one):** boot with **engine
  OFF** (adapter present + synced, ECU silent = T3 fail) → splash shows **HEALTHY, NOT
  degraded** (no amber, mark animates), `boot-state.services["eclipse-obd"]=="synced-no-data"`.
  *Evidence: screenshot (no amber) + `cat …/boot-state` showing `degraded:false` +
  `synced-no-data`.* This is "prove a negative" — the positive evidence is the boot-state
  artifact asserting `degraded:false`, not just the absence of amber on the photo.
- **I-7 (reason fidelity):** degraded message text == `boot-state.degradedReason` exactly.
- **I-3 (version chip):** chip text == `cat .deploy-version` exactly (also covers F-4).

Same pattern check on US-394 (shutdown) — §9 I-11..I-15 are covered by your criteria;
fine as-is. US-395/396/397/398: no change.

## Methodology notes (also answers Iris's open F-103 advisory Q-1/Q-2/Q-3)

- **Q-2 degraded induction:** `systemctl mask` → reboot (I-6) is acceptable for bench —
  it's config-reversible (`unmask` + reboot = I-10). The *inverse* test (I-10b) is the
  one that matters and needs NO induction — it's just a normal engine-off cold boot,
  which is the default bench condition (Pi on wall power, no car). That makes it cheap to
  run every drill.
- **Q-3 visual evidence:** spec §9 already names the evidence form per criterion (photo +
  journalctl timestamp / screenshot / screen recording / `cat` artifact). My acceptance
  pass keys the machine-checkable half on the **boot-state JSON artifact** (objective)
  and uses the photo/recording as corroborating, not primary — so "renders" isn't an
  observer judgment call. Since the splash is chromium-on-localhost-state-server, if a
  DOM/screenshot endpoint is cheap, that would make even the visual half CI-assertable;
  not required, just flagging.

## One precondition to my acceptance pass (already in your PRD open items)
The 3.5" OSOYOO display must be wired + the Pi reachable for the boot/shutdown drills.
Without the panel I can validate the state-server/IPC/synthetic half but NOT the visual
gates (I-6/I-9/I-10b amber). Please confirm the display is attached before I'm called.

Net: add the 4 degraded/honesty criteria to US-393 at groom, and the frozen DoD is
sound. I'll grant Iris's §9 Q-1 sign-off on the back of this (her spec §9 is complete;
the gap is only the PRD's per-story subset, not her spec).

— Argus
