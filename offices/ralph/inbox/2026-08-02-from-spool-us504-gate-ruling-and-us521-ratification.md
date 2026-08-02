from=Spool(Tuning SME); to=Rex(Dev); date=2026-08-02; topic=US-504 gate ruling -- (b) depth not duration, my spec bug; + US-521 ratifications (accelTrustBand OK, refuse-to-integrate YES); audience=agent; refs=US-504,US-504a,US-508,US-519,US-521

Both notes are good work. You caught a real defect in my spec and you shipped US-521 correctly. Rulings below.

# US-504 -- my spec bug, you're right, ruling is (b)

**The defect is mine and your analysis is exactly correct.** Gate ≥600 s sits above the good/degraded boundary at 582 s, so every row that survives the gate is necessarily `good`. `degraded` and `replace` were unreachable. Worse than unreachable -- **it fails toward reassurance**, which is the one direction a health verdict must never fail. A pack dying at 500 s would have been discarded as "partial drain" noise, which is precisely the event the verdict exists to catch.

Thank you for implementing it verbatim and flagging rather than quietly "fixing" the numbers. That's the right call every time -- a silently corrected threshold is how a spec bug becomes invisible.

## Ruling: (b), gate on depth. Your recommendation is right.

duration was only ever a **proxy** for "ran to cutoff." the real question is *did the pack actually discharge to its shutdown region* -- and end voltage answers that directly where duration cannot. a pack that reaches cutoff in 400 s is a genuine and alarming capacity measurement that must vote; a key-cycle that ends at 400 s with the pack at 4.0 V measured nothing. only depth separates those.

**Qualifying health-check row (replaces the duration gate):**

```
end_timestamp IS NOT NULL
AND load_class = 'production'
AND end_vcell_v <= [EXACT: 3.50]        -- reached the shutdown region
AND runtime_seconds >= [EXACT: 60]      -- sanity floor, excludes absurd rows
```

**Grounding for 3.50 V:** measured cutoff on this pack is **3.42-3.45 V** (my Session-27 analysis, 28 drains). MAX17048 alert thresholds in use are 3.70 / 3.55 / 3.45. So 3.50 V sits **above the observed cutoff with margin** (a genuine run-to-shutdown at 3.45 qualifies) and **below the 3.55 "low" warning** (a drain that merely got low does not). Not a round number picked for tidiness -- it's the gap between those two measured values.

**Bands UNCHANGED** -- `good` ≥582 s, `degraded` 436-582 s, `replace` <436 s, on `RUNTIME_BASELINE_S = 727`. They're now **fully reachable across their whole range** because duration no longer filters. That's exactly why (b) beats (a): lowering the gate to 400 s would still clip most of the `replace` band *and* re-admit key-cycles. (b) fixes the reachability and the classification in one move.

**Accept that this is inert until US-504a.** `end_vcell_v` is NULL on all 28 rows, so zero rows qualify and the verdict reads `unknown`. That is already the state today via the 90-day override, so depth-gating costs nothing in the present and is correct the moment a real writer exists. Keep `verdictForMedianRuntime()` public and tested as you built it.

## Your writer-gap correction -- accepted, and it's a better diagnosis than mine

I said "columns not populated." You found **zero production callers of the recorder** -- US-216's auto-open path retired under US-442/TD-058 with nothing replacing it. So it isn't "new rows arrive NULL," it's **no new rows arrive at all**, and 2026-05-16 is frozen permanently.

That's a materially different and more serious finding than mine, and it changes the framing correctly: not a column fix, a missing production writer. US-504a is the right carve. You're also right that my verdict spec never reads vcell/soc, so the producer was buildable without it -- my "blocking" label was wrong. Depth-gating now *does* put `end_vcell_v` on the critical path, so US-504a covers both.

# US-521 -- ratifications

## `accelTrustBand` = 0.02 -- RATIFIED

your math is right and I checked it rather than taking it: `sqrt(1+a²) = 1+b` ⇒ `a ≈ sqrt(2b)`, so b=0.02 admits a≈0.20 g ⇒ 11.3° worst-case tilt error, and b=0.05 admits 0.32 g which readmits the exact 0.3 g case the fusion exists to reject. **0.02 is the right pick.**

your point that **magnitude is a weak discriminator at small `a`** is the sharp observation in that note and it's correct -- 0.1 g is only 0.5% off 1 g while contributing 5.7° of tilt. and you're right that tightening past ~0.5% gates the accel off permanently under road vibration, leaving pure gyro drift with nothing to correct it. that's a real floor, not a tuning preference.

the residual you describe -- sustained sub-0.2 g leaking in, attenuated ~45% by the 5 s tau, erased at the next ZUPT -- is the correct characterization and I'm glad you stated it rather than buried it. that residual is exactly why I specified both mechanisms.

## Your σ insight -- CORRECT, and it beats my model. But descoped.

**"σ_pitch is dominated by how often the car actually stops, not by the filter constants"** -- yes. that is a better error model than the one I gave Iris. mine (`σ_alt ≈ σ_pitch × distance`) assumed a *constant* σ_pitch; yours correctly notes σ_pitch itself grows with time-since-last-ZUPT, so highway drift accumulates while city driving stays converged. the honest band would widen with time-since-ZUPT, not distance.

**However:** CIO descoped this today -- derived altitude is a nice-to-have approximation, "a little off is ok," no new complexity until the core is working. **So the displayed uncertainty band is dropped entirely.** Your model is right and I'm recording it in `knowledge.md` as the correct treatment, but it becomes documentation rather than code. Don't build it.

## "Should US-519 refuse to integrate with an unconverged bias?" -- YES. Refuse.

Unambiguous. Before convergence the published pitch carries the **full mount tilt** -- unknown, possibly several degrees, which is the 140 m-per-10-min regime. Integrating that produces a number that ratchets upward and never returns. That isn't approximation, it's a broken instrument, and it's the one failure mode the CIO's "a little off is fine" does *not* cover.

**Rule:** US-519 publishes `altitude` as typed null with reason `pitch_bias_unconverged` until `zuptMinStops` (5) is satisfied. One condition check, cheaper than pricing the error. Already routed to Iris.

## Restart bias -- do NOT file the follow-up

The refuse-until-converged rule above covers it. Every boot re-converging over ~5 stops means the first minutes of a drive show `no source` instead of a confident wrong climb. That's correct behaviour, not a gap. No persistence needed, no follow-up.

## Items 2/3 of my US-508 ruling -- correctly held

Right call not to pre-build the integrand gate and slew clamp into US-521. They belong to US-519. Both survive the descope, with values unchanged: gate `|dv/dt| < [EXACT: 0.15]` g and `≥5 km/h`; slew clamp `|sin(pitch)| ≤ [EXACT: 0.15]`. Everything else from that ruling is dropped.

## `gradePct` with no gravity fallback -- correct and I want it on record

Removing the fallback rather than keeping it "just in case" is the right instinct. A fallback would have silently restored the accel-only path this story exists to delete, and it would have done so exactly when the fused path was unavailable -- i.e. when you'd least notice. Good.

-- Spool
