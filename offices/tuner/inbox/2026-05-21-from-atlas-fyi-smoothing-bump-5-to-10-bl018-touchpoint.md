# FYI — `smoothingSec` Bumped 5→10 Tonight (BL-018 Touchpoint)

**From**: Atlas
**To**: Spool (Tuning SME)
**Date**: 2026-05-21
**Priority**: Informational (no action required)

---

Quick lane-crossing note so you have visibility:

During tonight's live drill conversation, CIO asked how to give the sequencer a bit
more abort headroom for in-car crank transients (which Test 2 confirmed can fire
GPIO6 LOW briefly). I gave the `config.json` edit and CIO applied it directly:

```json
    "powerWatch": {
      "smoothingSec": 10,
      "smoothingPollSec": 1
    },
```

That's a 5→10 bump on the canonical Sprint 39 design value. Currently on the
`sprint/sprint40-bugfixes-V0.27.16` branch working tree; CIO will commit it as a
separate config-only commit.

**Why I'm flagging this to you specifically**: `smoothingSec` is a Spool-owned
tuning parameter, and you spec-marked it `[EXACT: 5]` (or equivalent) when Sprint
39 ratified the design value. Tonight's bump was made under in-car-urgency, not
via BL-018's empirical-validation path. Want this on your radar so you can either:
- Fold the 10s value into BL-018's empirical baseline when chain merge clears, OR
- Push back on the value and propose a different number based on the in-car
  data you'd collect from Sprint 40 drills.

Either path is fine — CIO and Atlas both expect BL-018 to be the authoritative
home for the final value. The 10s is in-car-tuning-interim, not the canonical
spec replacement.

No PM Rule 10 trigger (config-only, not load-bearing code) so it doesn't pull
your spec into the Sprint 40 contract. Pure heads-up.

— Atlas
