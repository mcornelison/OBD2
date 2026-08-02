from=Ralph(Dev); to=Marcus(PM); date=2026-08-02; topic=US-517 done + one owed ops action + one pre-existing lint failure; audience=mixed; refs=US-517,US-518,F-125,TD-073

## US-517 DONE — but there is an owed OPS action before it does anything on the Pi

The config binding, validator default and consumer read path are built, green
and committed. The story's own validationCriteria (`validate_config` with
`PI_HOME_*` set in `.env`) passes on the dev box. **On the Pi it will correctly
report unknown, and that is not a bug — it is a missing ops step.**

**`deploy/deploy-pi.sh` excludes `.env` from the deploy payload** (lines 190,
217, 225 — the push tar excludes it and the remote cleanup preserves it). The
Pi keeps its own `.env`; the deploy only ever appends `COMPANION_API_KEY` to it
(step at line 430). So the `PI_HOME_LAT` / `PI_HOME_LON` /
`PI_HOME_ELEVATION_M` values Iris put in the dev checkout's `.env` **do not
propagate to the Pi**. Until someone writes them into the Pi's own `.env`, the
placeholders stay unresolved and `HomeLocationProvider` reports the honest
unknown.

Consequence for the NEXT story: **US-518's altitude re-anchor will be a no-op
on the Pi** until this is done. It is still correct to build (it resets to the
anchor when the anchor is known, and does nothing when it is not), but the live
validation of US-518 depends on this ops step, not on US-518's code.

**I deliberately did NOT add a deploy step for it.** Two reasons: it is outside
this story's ACs (scope fence), and writing location PII to the box via a
deploy script is a CIO decision about where his home coordinates are allowed to
land, not mine to make unilaterally. Options, cheapest first:

- **(A)** CIO appends the three lines to `/home/mcornelison/Projects/Eclipse-01/.env`
  by hand, once. Zero code. Survives every future deploy (`.env` is preserved).
- **(B)** A deploy step mirroring the existing `COMPANION_API_KEY` one —
  idempotent, `chmod 600`, values read from the local `.env` and never echoed.
  More machinery; puts PII in the deploy path.
- **(C)** Leave it unset deliberately and accept no altitude anchor on the Pi.

Ralph recommends **(A)** — the values change roughly never, and it keeps PII
out of the deploy path entirely.

## Pre-existing lint failure, NOT mine — TD-073 filed

`tests/lint/test_ralph_promise_tag_contract.py::test_promptMdAndRalphShDocumentSamePromiseTags`
fails on the current branch: `prompt.md` documents `COMPLETE` and
`PARTIAL_BLOCKED` but `ralph.sh` has no branches for them. Both files are
unmodified by me (`git status` clean on both), so this predates this story. I
did not fix it under the scope fence — filed as **TD-073**. Flagging it because
it is in the FAST lint suite and will fail your integration gate at sprint
close if it is not picked up.

It is worth a look rather than a rubber stamp: `COMPLETE` is the tag that ends
a sprint, and the contract test says `ralph.sh` does not branch on it.

## Sprint state after this story

8 done (US-501/502/503/504b/505/512/513/517). Remaining: **US-504a**
(needs-ruling — still BLOCKED on your/Atlas's orphan-policy ruling + Spool's
gate/band overlap; do not dispatch), **US-518** (next by priority, ready — see
the no-op caveat above), **US-521** (gyro-fused pitch).
