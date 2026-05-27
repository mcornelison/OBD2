---
name: pattern-defects-first-existing-artifact-review
description: When polishing an existing CIO/peer-authored artifact, surface concrete defects FIRST in shared grounding BEFORE proposing redesign. Discussion incoherent otherwise.
metadata:
  type: pattern
---

When CIO directs me to polish an existing artifact (kit, spec, code, design) authored by him or a peer:

1. Read the full artifact first.
2. Identify concrete defects (bugs, contradictions, broken assumptions).
3. Surface them in a focused message BEFORE any redesign discussion or clarifying questions.
4. Separate defects ("things broken") from polish opportunities ("things to improve") — they have different review velocities.
5. THEN proceed to brainstorming / clarifying questions / design proposal.

**Why:** When the existing artifact is the shared grounding for the conversation, undiscovered defects make redesign discussion incoherent. If I propose new behavior on top of broken assumptions about what currently works, my proposal lands sideways. CIO can't evaluate a redesign without first knowing what's actually true about the starting point.

**How to apply:**
- High value when the existing artifact has been around for a while (drift accumulated) or was rushed
- High value when the artifact crosses tier/lane boundaries (multiple authors, multiple assumption surfaces)
- Skip when the artifact is trivial or was just written by the same author still in the room

**Confirmed:** B-103 splash design session 2026-05-26 — I dumped 3 concrete defects in the existing kit (`shutdown.html` wrong SVG ref; `Conflicts=` self-cancel; X11/Wayland confusion) before any redesign discussion. CIO response: "the picture is clear now" — proceeded to brainstorming on solid ground.

Related: [[pattern-ui-as-ssot-consumer]] (the redesign that followed); [[feedback-cio-architectural-paths-belong-to-atlas]] (lane discipline that applied during it).
