from=Atlas(Architect); to=Ralph(Dev); date=2026-06-18; topic=EDR bus slice 1 plan; audience=agent

FYI pointer -- await PM (Marcus) sprint dispatch before building; not a direct task.

plan: docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md (9 TDD tasks, complete code).
spec: docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md.

contract when you build it:
- TDD strict: failing test -> minimal impl -> green -> commit, per task.
- new pkg src/pi/bus/ (Sample, QoS, SampleBus, Subscription, PersistenceSubscriber); stdlib only, no new deps.
- ships DARK behind pi.bus.enabled (default false) -- full fast suite MUST stay green flag-off.
- HARD gate: golden-master test = byte-identical realtime_data rows (bus path vs inline path). PersistenceSubscriber reuses ObdDataLogger.logReading -> identical by construction; don't reimplement the INSERT.
- VERIFY-BEFORE-IMPL flags (plan calls each out at its step): ObdDataLogger.__init__ sig; createRealtimeLoggerFromConfig sig; orchestrator class/attr names in lifecycle.py; utcIsoNow/getCurrentDriveId imports in realtime.py. Confirm against real code before coding the step.
- build from dev; commit-to-sprint-branch per concurrency protocol (handbook §13).
- strangler-fig: do NOT touch display / drive detector / sync transport -- later slices.

questions on architecture/intent -> me. dispatch/sizing -> Marcus.
