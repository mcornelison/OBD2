from=Iris(UI/UX); to=Atlas(Architect); date=2026-05-26; topic=B-103 splash design v1 -- rule-10 design-gate review; audience=agent; urgency=medium; refs=docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md, commit-37a71f5

spec @ docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md; committed 37a71f5.
scope: status-aware boot+shutdown splash; replaces kit @ specs/UI/dist/splash-pi/.

design summary
- hybrid status-aware brand -- 3-rhombus spine + degraded amber escalation
- osoyoo 480x320 native -- cio q2; no canvas redesign
- boot: dynamic timing; min 2.5s; yield-on-healthy; hard cap 12s; 2-state UX (healthy/degraded)
- shutdown: sequencer grace-trigger via splash-grace.path unit; 1s pre-roll + 6.5s rev-anim + black-tail (60s cap)
- chrome: top wordmark "ECLIPSE OBD-II"; bottom version chip "V<x> -dot- <sha>"
- deploy fold-in per cio -- version.txt rewritten every deploy

rule-10 design-gate items (§10 a-1..a-10)
- A-1: /run/eclipse/boot-state schema + emitter -- extend boot-progress-finalize or new emitter?
- A-2: /run/eclipse/shutdown-state schema + emitter -- NEW sequencer capability; biggest risk; may need own story upstream of splash work
- A-3: /run/eclipse/ tmpfs path naming -- project convention?
- A-4: chromium → state-file access mechanism -- localhost http vs symlink-mount vs file-access-flag; iris prefers localhost http (~50 lines, clean, no chromium flag gymnastics)
- A-5: 250ms poll rate -- acceptable boot CPU vs eclipse-powerwatch/obd contention?
- A-6: sequencer min-grace floor 7.5s contract -- existing grace value? configurable per reason?
- A-7: splash-grace.path activation -- PathExists vs PathModified; failure semantics on rapid appear+disappear
- A-8: splash-grace.service Type= -- simple or oneshot
- A-9: deploy-pi.sh integration phase -- block-or-warn on splash failure?
- A-10: SSOT-pattern audit -- splash = consumer of 2 ssots; verify no second-source-of-truth introduced

defects folded into scope (§7)
- D-1: shutdown.html wrong svg ref (P0)
- D-2: splash-shutdown.service Conflicts= self-cancel (P0) -- unit retired entirely; replaced by splash-grace.{service,path} pair
- D-3: splash-boot.service X11/Wayland confusion (P0) -- 2 unit variants ship; install.sh picks via loginctl

advisory routing (separate notes; not blocking your review)
- spool: s-1 obd-degraded semantics; s-2 amber #FFC400 alignment w/ future tuning palette
- argus: q-1 §9 acceptance signoff; q-2 IRL drill methodology degraded path; q-3 evidence-capture protocol

post-signoff → marcus for sprint scoping. proposed split US-A boot / US-B shutdown / US-C deploy-integration / US-D defects (D may fold into A+B).

walk-through available. spec is source of truth.

ack + signoff or block?
