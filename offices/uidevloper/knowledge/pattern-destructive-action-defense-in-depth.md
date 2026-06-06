---
name: pattern-destructive-action-defense-in-depth
description: Guard consequential UI actions (exit, stop services, poweroff) with THREE layers — deliberate gesture + confirm + structural impossibility — not one.
metadata:
  type: reference
---

# Destructive UI actions get defense-in-depth, not one guardrail

From the F-092/F-097 System Setup menu (CIO 2026-06-05). The CIO's own instincts — a
5–6s long-press to open the menu, and confirms before actions fire — are the textbook
**defense-in-depth** pattern for consequential controls. The strongest version stacks
THREE independent layers so no single accidental input can do harm:

1. **Deliberate gesture** — make the entry hard to trigger by accident. A 5–6s long-press
   (with a filling-ring feedback so it doesn't feel broken; release early = cancel) can't
   be hit by a stray pocket-touch. Distinguished from swipe by movement threshold.
2. **Confirm step** — make completion hard by accident. Stop-service and Exit-UI each ask
   first, and the confirm states the consequence + how to recover (e.g. "returns on reboot,
   or `systemctl restart eclipse-dashboard`") so the user is never stranded.
3. **Structural impossibility** — make the *most* dangerous thing simply unavailable. The
   safe-shutdown guard (`eclipse-powerwatch`) has **no Stop control at all** (restart-only),
   and the privilege path enforces an install-fixed allow-list — off-list units are rejected.
   Removing the capability beats discouraging its use.

**Why it matters:** any one layer alone is weak (a deliberate gesture still lets you confirm
a catastrophic action; a confirm still fires on a double-tap). Together, an errant touch
cannot stop the Pi's safe-shutdown guard. Layer 3 is the strongest — prefer making the
dangerous thing *impossible* over making it *confirmable*.

**How to apply:** for any UI action that's hard to reverse or safety-relevant (exit,
stop/restart services, poweroff, delete), ask "which layers apply?" Gate entry behind a
deliberate gesture, confirm with consequence+recovery text, and for the truly dangerous
subset remove the control entirely (or allow-list it server-side). Also: status must reflect
*real* state after the action (a failed Stop shows the service still running — no optimistic
UI). Privilege: never run the UI as root to get these powers — use a scoped polkit rule /
privileged helper (I-036 poweroff precedent).

See also: [[pattern-ui-as-ssot-consumer]] (honest status, no optimistic UI),
[[pattern-argus-ui-acceptance-criteria]] (failure-mode enumeration — "X must NOT happen").
