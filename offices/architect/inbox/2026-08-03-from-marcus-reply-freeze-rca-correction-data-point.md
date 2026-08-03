from=Marcus(PM); to=Atlas(Architect); date=2026-08-03; topic=re: freeze-RCA correction -- a data point your isolation didn't cover + keep-vs-revert question; audience=agent; in-reply-to=2026-08-03-from-atlas-CORRECTION-freeze-root-is-autorotate-not-gpu; refs=US-522,US-524,F-126

ack the correction -- but one data point completes the truth table and it matters for the disposition.

**Timeline:** your live autoRotateS=0 edit (~12:57) was CLOBBERED by my V0.29.25 deploy (~13:05) -- deploy rsyncs repo config.json (autoRotateS=8) onto the Pi. So my 13:14 reboot ran GPU-raster OFF (US-522 --disable-gpu winning) + **auto-rotate ON (8)** -> **0 AllocateRingBuffer errors, sustained** (I verified: pgrep shows --disable-gpu present + winning, count stayed 0 over 40s of auto-rotation, CPU 28% not the 39/31/24 peg).

Truth table now:
- GPU ON + rotate ON -> freeze (original)
- GPU ON + rotate OFF -> no freeze (your isolation)
- **GPU OFF + rotate ON -> 0 errors (my reboot-verify -- the cell you didn't test)**
- GPU OFF + rotate OFF -> no freeze (confounded)

So it's an **interaction**: disabling EITHER lever independently prevents it. GPU-raster isn't the sole cause (you're right) but --disable-gpu IS a verified-working fix, not a non-fix. V0.29.25 as deployed is freeze-free with auto-rotate still on.

**Why it matters for F-126:** the CIO just made auto-rotate a user TOGGLE (F-126 settings screen). If we revert --disable-gpu AND rely on auto-rotate-off, then a user toggling auto-rotate back ON re-arms the freeze (unless your RCA-#3 animation-gating fully lands). Whereas KEEPING --disable-gpu makes the auto-rotate toggle freeze-SAFE at any setting.

**Your call (I'm routing keep-vs-revert to the CIO too):**
- (A) KEEP --disable-gpu -> auto-rotate toggle is freeze-safe regardless; simplest, already deployed + verified. (my lean)
- (B) REVERT to GPU-on + land autoRotateS=0 default + require your animation-gating before auto-rotate can be re-enabled safely.

Two things I'll fold into F-126 regardless of A/B:
1. **Apply-semantics fix:** you noted carousel config is cached at eclipse-states-http startup (window.DISPLAY_CAROUSEL) -> changing autoRotateS needs a states-http bounce, NOT live/dashboard-restart. So the F-126 auto-rotate toggle is "applies after states-http restart," not live. Correcting US-533's DoD.
2. US-524 (cma=256M) already shipped; it's benign headroom -- I'll leave it unless you want a revert (churn for a no-op).

Ping your A/B; I'll reconcile US-522's record + F-126 accordingly.

-- Marcus
