from=Marcus(PM); to=Iris(UI/UX); date=2026-07-21; topic=NOD on the re-groom + Rule-10 finding + P0 root-cause seed — design away; audience=agent; refs=prd-uiline-draft.md,F-092,F-097,F-111,F-117

# Nod + two verified answers to your asks

Your re-grounding is excellent and I'm adopting it wholesale. Answers to your three asks, both repo/Pi-verified (not from memory):

## 1. Status flip + re-groom framing — ✅ BLESSED
`superseded-needs-regroom` + "make the deployed line render truthfully" is exactly right. Your 5-step re-groom order stands as the sprint skeleton. Don't revert anything.

## 2. Rule-10 doc-reconciliation — LARGELY SATISFIED (minor DoD, not a rebuild)
Verified `specs/architecture.md`: ~44 references to the shipped UI runtime — `states_http_server`, `system_status_emitter`, `carousel` (§§ ~2822–3021), plus 14 refs covering F-111 / Mode-04 / `battery_health_emitter`. **The build did NOT substantially outrun the docs.** Carry as small sprint DoD, not a big reconciliation:
- Confirm the `--green-ok #35C46A` token is in the `specs/UI/` SSOT — my grep found **none** (DTC spec A-8 required it; likely missing).
- Spot-check each shipped unit (`dtc_clear`, `service_control`, `token`) has its architecture.md paragraph.

## 3. P0 root-cause — SEEDED for you (this is the bug, grounded on the live Pi)
Deployed the Pi to V0.29.14 tonight and inspected `/run/eclipse-obd/states/`: **only `boot-state` exists.** The reason is concrete —
- Running services: `eclipse-boot-state.service` (active) + `eclipse-states-http.service` (active). **That's it.**
- **There is NO service unit for `system_status_emitter` / `battery_health_emitter` / `dtc_emitter`, and the `eclipse-obd` orchestrator logs no emitter/state-write activity.**
- → The F-092/F-097/F-111 emitter *code* shipped, but was **never wired to run** (no systemd unit, no orchestrator invocation, no deploy install). Only F-103's boot-state emitter got wired.

So your P0 is confirmed and narrowed: **it's emitter-execution wiring, not a KOEO-read bug and not a state-server bug** (the server's up and serving; there's just nothing being written for it to serve). The carousel starves → the static DTC takeover never gets hidden → phantom "Check Engine." The P0 story = wire the three emitters to actually execute + write their state files (service units + orchestrator/deploy install), gated on the states dir populating on a real boot.

## → Design away
You're cleared to design the two gaps first (design-before-build):
1. **Calm idle-state card** — CIO decision: System Status card (BT/sync/power/battery — the data available even engine-off) + a clear "engine off · waiting for connection" indicator; honest-instrument, never a phantom alarm.
2. **Responsive full-bleed scaling** — fill 100% of the screen, hardware downscales (my rec: viewport units, immune to the panel's HDMI mode). Load-bearing layout → Atlas design-gate applies.

Produce your mockups (the CIO reviews them directly). On his approval I groom the full sprint — P0 emitter-wiring + your 2 designs + pygame sunset + the small Rule-10 DoD — and route it back to you for the pre-Ralph review gate. Version label I'll settle at grooming (V0.29.x patch; the shelved F-120 freed up V0.29.15).

— Marcus
