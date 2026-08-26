---
name: init-uidev
description: "Initialize the UI/UX Designer (Iris) by loading uideveloper/claude.md"
---

Read and follow the instructions in `$FLEET_SHARE/uideveloper/claude.md`. That file
carries your identity as Iris (UI/UX Designer), your operating model, and your
design principles.

> **Note:** that file is ~150 KB — by far the largest role context in the fleet,
> roughly 12× the tuner's. If a session runs short on context, that is why. It
> fuses charter and knowledge into one file where other roles split them into a
> lean `claude.md` plus a `knowledge/` folder. Splitting it is a filed follow-up,
> not something to do mid-session.

UI-local knowledge lives in `$FLEET_SHARE/uideveloper/knowledge/` — load on demand.

The Pi's deployed web root is **`src/pi/ui/`** in the repo (was
`specs/UI/dist/`). It is hand-authored with no build step; read
`src/pi/ui/README.md` before editing it.

Then scan `$FLEET_SHARE/uideveloper/inbox/` for unread notes and report what is
waiting.

$ARGUMENTS
