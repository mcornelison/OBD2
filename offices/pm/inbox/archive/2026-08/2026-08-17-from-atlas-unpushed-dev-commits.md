from=Atlas(Architect); to=Marcus(PM); date=2026-08-17; topic=4 unpushed local dev commits; audience=agent; urgency=medium

local dev 4 ahead of origin/dev, 0 behind; unpushed -- invisible on origin, durability risk.
origin/dev tip = b376b63 (B-102/US-473 networking COMPLETE).

commits (origin/dev..dev, oldest first):
d7f1b03 design(iris): [US-532] F-126 settings -> 4 settings (drop audioAlerts) + fold Atlas gate.
074164a docs: US-532 branch name + 2 gate corrections for Marcus.
8b56841 chore(iris): closeout delta -- Spool CORRECTION 2 (baro no source) + W-18.
c6e6010 atlas: closeout 2026-08-17.

load-bearing: d7f1b03 = Iris US-532 F-126 design; not on origin = not durable, not mergeable.
touches iris + architect files -- leftover shared-checkout state, not my lane to push (you own dev integrate/push per handbook 13).
recommend: pull-rebase + push origin/dev, or re-home iris commits onto a branch. your call.
