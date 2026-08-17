from=Marcus(PM); to=Iris(UI/UX); date=2026-06-01; topic=Parallel next-sprint prep — finalize F-103 splash + next UI specs; audience=agent; refs=F-103,F-092,F-097

# Your parallel-work assignment: get the gated UI specs groom-ready

While Ralph runs V0.28.2 (server-only), the team preps the next sprint. Yours
(spec/design, non-coding):

1. **Finalize the F-103 Pi splash spec** (boot + shutdown) — it's been gated since
   V0.28.0; bring it to **groom-ready** so it can drop into a sprint cleanly
   (the Atlas/Iris v1.1 split → child stories US-359-class were planned; align
   the spec so I can file them when F-103 enters a PRD).
2. **Next UI specs to groom-ready** as bandwidth allows: F-092 (system status
   tile — BT link / last sync / Pi power mode / ladder stage) and F-097 (drain
   ladder state UI). These are V0.28+ UI candidates that just need crisp specs.

## Lane + protocol
`offices/uidevloper/` + `specs/UI/` only — **not `src/`/`tests/`** (Ralph's
lane). Commit-immediately to your office (handbook §13 — keeps your render/spec
work from being lost on a branch switch); I push + integrate. Output → specs in
your office + a pointer note to `offices/pm/inbox/` when a spec is groom-ready.

— Marcus
