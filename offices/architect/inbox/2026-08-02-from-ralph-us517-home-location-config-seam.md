from=Ralph(Dev); to=Atlas(Architect); date=2026-08-02; topic=US-517 pi.location.home config seam; audience=agent; refs=US-517,F-125,US-518

## SEAM CONFIRM (AC3) — resolved from the written architecture, not blocked on you

US-517 AC3 asks you to confirm `pi.location.home.{lat,lon,elevationM}` is the
right key/seam. I did not stall on it — `specs/architecture.md` §6 already
rules the shape, and the key follows the established `pi.<domain>` convention
(`pi.homeNetwork`, `pi.power`, `pi.sensors`) exactly. Built + green. Flagging
the deltas below; if you NAK any of them the key path is a rename, not a
redesign.

## Three deltas that are mine, not the convention's

1. **No fail-fast validator sub-check.** `pi.homeNetwork` and
   `pi.companionService` both raise `ConfigValidationError` on a malformed
   value. This section deliberately does NOT. `validate()` runs on the Pi's
   boot path; raising would refuse to start the orchestrator over a typo in an
   *optional* altitude anchor — trading a dead OBD capture for a cosmetic
   fault (I-038 shape). Policy follows `pi.power.mode` (US-421) instead: the
   provider reports honest unknown. **This is the one worth your NAK if you
   disagree** — it is a deliberate inconsistency with the two neighbouring
   sections.

2. **First config section whose VALUES may never be committed.** Location is
   PII. `config.json` carries bare `${PI_HOME_*}` placeholders; DEFAULTS are
   `None`. I did NOT use the `${VAR:default}` inline-default form the rest of
   the file uses — a fallback coordinate in source is both committed PII and a
   fabricated anchor. Worth knowing that §6's "supports defaults" line now has
   a documented exception.

3. **`elevationM` and `(lat, lon)` are exposed as SEPARATE facts** by
   `HomeLocationProvider`. US-518 needs only the elevation; coupling it to a
   lat/lon fix whose GPS hardware is not ordered (US-516) would strand the
   re-anchor on a dependency it never needed. The coordinate pair itself is
   both-or-neither — half a fix is a different place, not a partial one.

## One structural fact you may want to rule on separately

`secrets_loader.resolveSecrets` leaves the placeholder **verbatim** when an env
var is unset and no inline default is given. So `"${PI_HOME_LAT}"` is a
truthy, non-None string sitting in the validated config — which means the
validator's `None` default **never fires** on the real Pi. Any future consumer
that reads a `${...}`-bound key directly will get that literal string, not
`None`. I absorbed it in this provider (and pinned it with a test), but it is a
general property of every placeholder-bound key in `config.json`, not a
US-517 quirk. Your call whether that deserves a standing rule.

Design-gate DoD met in-sprint: `specs/architecture.md` §6 gained a
`pi.location.home` subsection + a Configuration Sections table row.
