from=Iris(UI/UX); to=Marcus(PM); date=2026-08-07; topic=W-16 sensor prototypes -- CIO-approved, Spool-gate CLEARED, hand-off for backlog; audience=agent; urgency=medium; refs=W-16,proposals/2026-08-03-full-advantage-sensor-prototypes,inbox/2026-08-07-from-spool-pid-return-rulings

CIO approved the "full advantage of existing sensors" prototypes (2026-08-03) and asked me to route them to you for the backlog. Spec + interactive mockup: `offices/uidevloper/proposals/2026-08-03-full-advantage-sensor-prototypes.{md,html}` (**rev 2026-08-07**). Everything uses only sensors we already have -- GPS + baro remain on the CIO's hold.

**Supersedes an unsent 2026-08-03 draft of this note** (written, never committed -- you never received it). Read this version only; the 08-03 one is deleted. The delta is not cosmetic: **Spool's data gate closed on P2, and it killed the boost gauge.**

## The headline before you scope anything: BOOST IS NOT BUILDABLE

`INTAKE_PRESSURE` 0x0B is **probe-confirmed unsupported** on MD326328 -- and **double-dead**: on the 2G 4G63 that PID is wired to the **MDP (EGR-monitor) sensor**, so it is not boost even where it answers. **No software fix reaches it** -- boost needs a GM 3-bar sensor + ECMLink, both behind the CIO's sensor freeze. If a boost/MAP gauge appears in any story, it is wrong and it came from the pre-08-07 draft.

Two more corrections that came with it: `CONTROL_MODULE_VOLTAGE` 0x42 is also dead (**keep the voltage readout** -- source it from the adapter's `ATRV`, off the K-line), and the O2 + timing gauges are out on semantics (narrowband O2 is not AFR; base timing reads as a knock gauge and isn't one).

I also want the root cause on the record because it generalises: I sourced my first "confirmed" list from the **`config.json` poll list**. **Config membership is not evidence of PID support** -- Tier 4 polls two dead PIDs and burns NO_DATA every 30th cycle (Spool's filed defect, `edr-pid-priority-allocation.md` §2b). The list is now re-derived from his capability probe.

## Two rulings that constrain EVERY engine tile, not just P2

1. **~2.5 s per PID.** The whole K-line budget is ~6.3 samples/sec across ALL PIDs (~0.39 Hz each at 16 PIDs), with no "turn up the Hz" knob -- more PIDs is strictly slower per PID. **So no smoothly-animated needles**: interpolating across the gap fabricates values the ECU never reported. Tiles step, or show last-value + age. Anything that must feel live comes off the IMU (100 Hz) or `ATRV`.
2. **LTFT must not be coloured at idle.** This engine sits at a characteristic **LTFT approximately -6.25% lock at warm idle** -- that is its normal, not a fault. Banded naively, **every stoplight paints amber**, and a gauge that cries wolf at every light gets ignored the one time it matters.

Worth writing into the stories' acceptance criteria rather than leaving to build-time discovery -- both are easy to get wrong and invisible on a desk.

## Per-prototype: priority · readiness · gate

**P2 · Dedicated "Engine" card -- PRIORITY, and NOW UNBLOCKED.**
MAF arc gauge + RPM + coolant + intake-air + throttle/load + STFT/LTFT + Closed/Open-loop + voltage. **MAF replaces boost as the centrepiece** -- and it's the right replacement, not a consolation: the 2G 4G63 is **MAF-based** (Karman-vortex), which is *precisely why* MAF lives and MAP is dead. It's the primary fuel-metering input, so it rises with exactly the effort the driver feels. Display-only consumer of existing OBD state. **Spool's gate is cleared -- this can be groomed and built.** P1 (airflow + vitals on the driving view) is folded in here.

**P3 · Post-drive review -- PRIORITY, still gated on Atlas.**
Server-analytics drive summary (airflow/effort trace, g-trace, corner-lean, grade profile) from already-logged data. Biggest build (server tier); needs an **Atlas contract for the analytics surface** before it's build-ready. Note the slow K-line stops mattering here -- a 22-minute trace reads fine at 0.4 Hz, and the IMU channels are 100 Hz regardless. This surface gets more out of the existing sensors than any live gauge can.

**P4 · Eclipse attitude indicator -- READY, fun/low priority.**
Aircraft gyro-horizon mapped to the car: pitch -> road grade, bank -> body lean; round bezel face, pitch ladder, bank scale, 2G GST rear-view silhouette as the fixed reference, slip/skid ball repurposed as a lateral-g meter. Design-done + CIO-iterated; all render logic is in the mockup. **Gate: expose `roll` + `yawRate` in `states/imu`** (Atlas/Ralph -- small; `gradePct`/pitch is already in Atlas's confirmed contract).

## Suggested stories (yours to shape)

- **P2 Engine card** -- groom + build; no remaining gate. Bake the 2.5 s step + LTFT-idle rules into acceptance.
- **P3 post-drive review** -- groom; **build after Atlas** contract.
- **P4 attitude card** + the small `states/imu` roll/yaw field add -- can move whenever you have room.

None of these touch the in-flight V0.29.26 / F-126 settings work. Ping me to split any of them and I'll take that one to a build-ready spec. -- Iris
