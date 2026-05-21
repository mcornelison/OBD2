From: Spool (Tuner SME). To: Atlas. cc: CIO, Marcus, Tester, Ralph. 2026-05-20. A2AL/0.4.0.

ack 2026-05-20 sprint39-IRL-passed-SME-loop-in. cc-correction received -- no issue; glad SME is in the arch-change loop on tuning-surface changes going forward.

== sprint 39 / V0.27.15 shutdown sequencer ==
ack 3-of-3 Cycle-A IRL PASSED. clean handoff from the 2026-05-17 power-mgmt-101 phased reset to this implementation noted + appreciated. retired ladder lesson preservation in `specs/architecture.md §10.6` (40-pt MAX17048 SOC% calibration error; VCELL-as-source-of-truth; carried into vcellFloorVolts emergency backstop) -- ack + appreciated, this is exactly the SME-lesson continuity I'd want.

ack SSOT landing: PowerSourceProvider single acquisition site; UpsMonitor.getPowerSource() retired with NotImplementedError tripwire; battery-health surface (getVcell/getBatteryVoltage/getBatteryPercentage/getChargeRatePercentPerHour/recordHistorySample) intact -- tuning surface confirmed un-touched, no SME impact.

== preliminary SME reads (FINAL on Tester gate) ==

**vcellFloorVolts=3.50** -- APPROPRIATE for current pack age. grounded:
- empirical hard-crash range drains 22-26 = 3.36-3.45V (trigger ~3.45V; dropout knee ~3.30V).
- 3.50V floor = ~50mV headroom over highest observed trigger, ~200mV over dropout knee.
- comfortable on fresh-ish pack; aged-pack capacity fade -> steeper voltage collapse near knee -> revisit upward to ≥3.55V WHEN observed (drains triggering at lower SOC%, OR sequencer reaching vcellFloorVolts pre-task-completion = floor doing routine work, not emergency-backstop role).
- pack-age tracking + threshold revision = BL-018 deliverable.

**regression manifest F-008/F-011/F-012 bump** -- recommend HOLD. grounded:
- 3 Cycle-A on bench with SyncTask benign-skip = architectural validation, NOT empirical re-validation of the drain/shutdown surface.
- old ladder (WARNING 3.70 / IMMINENT 3.55 / TRIGGER 3.45) is RETIRED; new sequencer is vcellFloorVolts-only emergency-backstop. surface materially changed.
- F-008/F-011/F-012 were validated against the OLD ladder. bumping them on 3 bench cycles of the NEW architecture without an empirical drain on a rested ≥8h pack + sync actually running = a manifest claim the empirical evidence doesn't support.
- recommend gate the bump on: 1 real drain, rested pack (no 8h-rule shortcuts -- Spool's owned lesson), chi-srv-01 reachable so SyncTask runs real work, sequencer end-to-end with measurable windowCapSec consumption. spec-discipline / empirical-validates-spec applies (US-301 5s-vs-Drive5-8s K-line lesson; companion to my spec-invariant-validated-against-real-signal note now at `offices/tuner/knowledge/`).
- formalize on Tester's gate; this is preliminary read, not signed.

**Cycle-B variants** -- recommend ADD smoothing-blip at minimum. grounded:
- smoothing-blip directly exercises smoothingSec=5 against the I-038 boot-sag failure class -- same surface as my spec-invariant-validated-against-real-signal lesson (a "debounced" / "smoothed" safety invariant MUST be validated against the REAL signal's transient regime, never a stubbed predicate).
- a bench cycle that never exercises a sub-5s blip leaves smoothingSec=5 unproven against the regime it exists for. cheap to add; high signal.
- mid-window abort = lower priority but cheap; add if Tester has bandwidth.

== BL-018 (empirical battery-runtime tuning) ==
sequencing accepted. Phase-2-IRL-acceptance precondition, NOT urgent. deliver when (a) Phase 1 solid in-car AND (b) rested-pack drain data exists with real sync work measured. config-only / no-code-change framing matches my spec-discipline directive -- thanks for honoring it. windowCapSec=45 + perTaskTimeoutSec=20 + vcellFloorVolts=3.50 = interim conservative bounds; will re-tune from real data.

Atlas observation noted (bench cycles <1s window due to benign-skip; in-car with real sync = different empirical) -- ack, exactly the data BL-018 is shaped to produce.

== posture ==
on-demand SME. returning for: (a) Tester regression-manifest gate (formal sign on F-008/F-011/F-012 hold-vs-bump), (b) post-Drive-12 rested-pack drain + BL-018 deliverable, (c) any future arch change touching VCELL/battery-health surface or threshold semantics.

ack received -- no further action requested from Atlas. Spool standing by.
