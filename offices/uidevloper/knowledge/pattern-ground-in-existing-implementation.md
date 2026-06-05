---
name: pattern-ground-in-existing-implementation
description: Before designing a UI from a backlog title, search for an EXISTING implementation — the real work is often "extend/unify," not greenfield, and may be smaller or differently-shaped than the title implies.
metadata:
  type: reference
---

# Ground in the existing implementation before designing from a backlog title

From F-092/F-097 (2026-06-05). The backlog read "system status tile" + "drain ladder state
UI" — sounded like two greenfield screens. Grounding the codebase FIRST revealed a whole
**pygame dashboard already existed** (`src/pi/hardware/status_display.py` +
`dashboard_layout.py`, US-257/B-052, wired via `hardware_manager.py`) already rendering most
of both — including a hard-won honest-instrument rule (VCELL authoritative, SOC tagged
`(uncalibrated)`, US-264, from the Drain Test 6 operator-misled incident). The real work
became "unify on the new HTML stack + fill the genuine gaps (last-sync, BT-reconnect detail,
runtime-remaining)," not "build from scratch." It also surfaced the F-097 pivot need (the
old drain-ladder framing was obsolete vs the new key-off sequencer).

**Why it matters:** a backlog title is a one-line intent, not a scope. Designing straight
from it risks (a) re-inventing existing infra, (b) missing honest-instrument decisions
already encoded in the old code, (c) mis-scoping (the gap is usually narrower than the
title). The CIO's "small UI work / data already in power_log, just surface it" was the
tell — it meant "extend," not "create."

**How to apply:** before any UI/design pass, grep for an existing implementation of the
data + surface (`status_display`, `dashboard`, the relevant table/emitter, the state enum).
Read what's already there — especially comments encoding past lessons (US-/TD- references).
Reframe the task as the *delta* from what exists. Bring that reframing to the CIO early — it
often shrinks the work and catches obsolete framing (like the drain-ladder → battery-health
pivot). Verify-before-asserting (charter §6) applies to existing code, not just memory.

See also: [[pattern-defects-first-existing-artifact-review]] (surface defects in the existing
artifact first), [[pattern-ui-as-ssot-consumer]] (consume existing state, never invent),
[[feedback-cio-prefers-visual-brainstorming]].
