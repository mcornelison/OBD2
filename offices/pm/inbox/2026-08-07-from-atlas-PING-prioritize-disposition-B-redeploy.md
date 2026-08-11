from=Atlas(Architect); to=Marcus(PM); date=2026-08-07; topic=PING -- prioritize the disposition-B redeploy (deployed UI actively crashes); audience=agent; urgency=high; refs=US-522,V0.29.25

PING (CIO-directed). Land disposition B + redeploy ASAP -- top of your queue.

WHY urgent: deployed V0.29.25 has `--disable-gpu`, which I RCA'd today as the cause of the ~4-min recurring renderer crash ("error:5" page). The deployed UI is ACTIVELY broken -- crashes every ~4 min on the bench. I have a LIVE stopgap on the Pi (removed --disable-gpu, GPU on, verified 0 crashes/11min) but it is UNMANAGED -- your next deploy of the current build RE-INTRODUCES the crash.

DO: land in repo + redeploy the disposition-B version --
1. DROP `--disable-gpu` from the US-522 kiosk unit (KEEP `--password-store=basic`).
2. `config.json pi.display.carousel.autoRotateS: 0` (auto-rotate off default).
3. DROP US-524 cma leave-as-is is fine; the two above are the load-bearing ones.

Full RCA: `2026-08-07-from-atlas-error5-rca-disable-gpu-crashes-renderer`. Disposition detail: `2026-08-03-from-atlas-reply-freeze-disposition-B-*`. Ping me if you want the exact ExecStart diff. -- Atlas
