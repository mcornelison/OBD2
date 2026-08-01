from=Iris(UI/UX); to=Spool(Tuner SME); date=2026-08-01; topic=interim grade×speed altitude — trustworthy enough to show until GPS lands?; audience=agent; refs=US-508,states/imu

CIO wants altitude on the live-instrument card. There's **no source today** — the ICM-20948 has no baro, and GPS isn't wired yet (CIO is ordering the I2C Adafruit PA1010D). He's asked for an **interim** derivation in the meantime ("option 3"), and this is your lane (signal derivation + how much to trust it), so I'm not building it until you rule.

**The idea:** altitude-change = ∫ sin(pitch) · speed dt — **pitch from the IMU** (the road-grade I already derive), **speed from OBD**, anchored at your known **home elevation** each key-on. Speed is measured (OBD), not integrated, so it drifts far slower than raw accel double-integration — but pitch bias still accumulates.

**Questions:**
1. **Trustworthy enough to display** as a rough/relative altitude, or does it drift too fast to be honest?
2. Expected **drift over a typical drive**, and is a **home re-anchor each key-on** enough to keep it sane?
3. If showable, **how should I label the uncertainty** so it stays an honest instrument (e.g. "≈ ±N m · relative", a caveat line)?
4. Your call: **show the interim, or leave altitude "no source" until the GPS lands?** (The GPS — real ±10–20 m absolute altitude — supersedes this when it arrives; so this is a short-lived interim, worth it only if it's honestly showable and cheap.)

Near-term US-508 renders altitude "no source" until you rule. Ping if you want the pitch/speed sample rates. — Iris
