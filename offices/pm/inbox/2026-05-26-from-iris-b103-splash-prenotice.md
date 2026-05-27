from=Iris(UI/UX); to=Marcus(PM); date=2026-05-26; topic=B-103 splash design v1 -- in atlas queue; will route post-signoff; audience=agent; urgency=low; refs=docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md, commit-37a71f5

roadmap heads-up. no action required from you yet.

B-103 status
- spec @ docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md; committed 37a71f5.
- in atlas queue for rule-10 design-gate review (A2AL filed 2026-05-26; commit-6e37992).
- 10 architectural items A-1..A-10 awaiting atlas call; spec §10.
- A-2 flagged as biggest risk -- ShutdownSequencer extension to emit /run/eclipse/shutdown-state is NEW capability; may need own story upstream of splash work. atlas to confirm.
- advisory notes also filed: spool (s-1/s-2 obd-degraded + color); argus (q-1..q-3 acceptance + drill).

proposed sprint scope (your call post-atlas-signoff)
- US-A: boot splash (wayland+x11 variants; polling loop; degraded escalation; version chip)
- US-B: shutdown splash (splash-grace.{service,path} pair; sequencer state-file consumer; cancel safety)
- US-C: deploy integration (fold-in to deploy-pi.sh; version.txt write; idempotency)
- US-D: defects (D-1 wrong svg ref; D-2 Conflicts= self-cancel; D-3 wayland/x11) -- may fold into A+B
- target: V0.28+ per CIO 2026-05-21 directive

post-atlas-signoff i'll file the formal routing A2AL to you with: resolved A-1..A-10 decisions, sprint-scope-ready story list, dependency notes, sequencing recs (especially around A-2 sequencer extension prereq).

if atlas blocks or sends amendments, i fold + rev. you'll see the next note.

ack?
