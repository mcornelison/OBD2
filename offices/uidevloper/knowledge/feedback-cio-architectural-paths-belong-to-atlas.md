---
name: feedback-cio-architectural-paths-belong-to-atlas
description: When UI design consumes architectural artifacts (paths, schemas, IPC contracts), propose shapes but DEFER concrete naming + ownership to Atlas. CIO 2026-05-26.
metadata:
  type: feedback
---

When my UI design needs architectural artifacts to consume — filesystem paths, JSON schemas, IPC mechanisms, systemd unit naming, file ownership semantics — propose the SHAPE but DEFER concrete naming + ownership decisions to Atlas under Rule-10 design-gate.

**Why:** CIO directive 2026-05-26 during B-103 Section 1 review: "looks right but keep the arch and path specs to Atlas." Architecture is Atlas's lane (PM Rule 10 + role boundary 2026-05-18). Iris is consumer, not author of architectural contracts. Prescribing concrete `/run/eclipse/boot-state` path naming in my spec section would have stepped into Atlas's lane — CIO pulled me back before I committed to it.

**How to apply:**
- In design specs / proposals: describe what I need to consume (data shape, semantic meaning, polling cadence)
- DO NOT prescribe: exact filesystem paths, file ownership, schema field naming, systemd unit Type= choices, IPC mechanism (HTTP vs socket vs file)
- Flag those decisions in a clearly-marked "Atlas to ratify" routing surface (spec §10 routing-surface pattern from B-103)
- If I have a strong preference, state it as "Iris prefers X" — not "X" — so Atlas knows I have a view but ratifies the call
- The line is: I own pixels + interaction + visual SSOT (tokens); Atlas owns what's on disk / on the wire / in systemd

**Edge cases:**
- If something is BOTH visual and architectural (e.g., where the splash service lives in the systemd target graph), it's architectural. Defer.
- If the architectural decision affects user experience (e.g., grace-period floor implied by my animation length), STATE the constraint in my spec and flag Atlas to confirm the contract can support it. That's not prescribing — that's surfacing a UX requirement.

**Confirmed:** B-103 splash design spec 2026-05-26 — pulled back path/schema specifics from §1 + §3 + §6 to "Atlas to ratify" items (A-1..A-10 in §10 routing surface). Spec stayed in Iris's lane; Atlas owns architectural ratification.

Related: [[pattern-ui-as-ssot-consumer]]; [[pattern-defects-first-existing-artifact-review]].
