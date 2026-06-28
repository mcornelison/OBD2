---
id: US-389
title: "Root 1 closure: bake single-instance guard + RuntimeDirectory as a matched-pair tested deploy invariant + version-stamp"
type: issue
parent: F-107
epicId: E-002
size: S
status: sprint-ready
sourceRefs: [A-9, F-107, atlas-guard-DEPLOYED-2026-06-19, atlas-rca-ruling-2026-06-19-C5, atlas-rca-ruling-2026-06-19-C3, US-354]
created: 2026-06-28
updated: 2026-06-28
---

# US-389 — Root 1 closure: matched-pair guard + RuntimeDirectory deploy invariant

## Context

This Story closes Root 1 of A-9 in the A-9 sprint (Sprint 47 / V0.29.1). Root 1
was two concurrent orchestrator processes; it was mitigated out-of-band by
enabling the single-instance guard (`d6d8b05`) and adding
`RuntimeDirectory=eclipse-obd` to the unit (`fae7ee7`), both deployed to the Pi.
Atlas's condition C-5 requires the guard flag and `RuntimeDirectory` to ship as a
MATCHED PAIR — neither without the other, or the non-root service crash-loops.
This Story makes that mitigation durable as a tested deploy invariant and folds
the out-of-band change into a proper V0.29.1 version stamp (so it is no longer
silent on top of V0.28.2).

## Goal

As the deploy path, I want Root 1 (concurrent-process dual-attribution —
mitigated out-of-band via guard enable `d6d8b05` + `RuntimeDirectory=eclipse-obd`
`fae7ee7` + Pi deploy) made durable: bake the guard config flag + RuntimeDirectory
as a MATCHED PAIR (Atlas C-5 — neither ships without the other or the non-root
service crash-loops) into the canonical deploy path as a tested invariant, confirm
the journal spawn-source for the 06-06 double-process, and fold the out-of-band
change into a proper V0.29.1 version stamp.

## Definition of Done

- deploy-pi.sh (or canonical deploy path) asserts BOTH pi.runtime.singleInstanceGuard.enabled=true AND RuntimeDirectory=eclipse-obd present in the deployed unit — a test/guard fails the deploy if either is missing (matched-pair invariant, Atlas C-5)
- deploy MUST systemctl stop the orchestrator before start (pair with the US-354 deploy-hygiene class) so the guard refuses a double-start rather than racing
- journal confirmation (**Atlas RCA condition C-3**): name the spawn trigger for the two concurrent eclipse-obd PIDs ~06-06 02:25 (systemd Restart= race / watchdog / manual+service overlap) — documented in story notes or RCA; Root 1 is mitigated (guard live) but the spawn TRIGGER must be confirmed
- .deploy-version reconciled: the guard-enable + RuntimeDirectory recorded in the V0.29.1 version stamp (no longer silent-on-top-of V0.28.2)
- specs/architecture.md boot-path section updated in-sprint (load-bearing boot change; Atlas Rule-10 signed off in the 2026-06-19 ruling — action it)
- Typecheck passes; tests pass

## Validation Criteria

- (run the deploy-invariant test with RuntimeDirectory removed from the unit fixture) → (deploy invariant FAILS loudly (matched-pair enforced))
- (run the deploy-invariant test with the guard flag false) → (deploy invariant FAILS loudly)
- (inspect .deploy-version after a V0.29.1 deploy) → (records guard-enabled + RuntimeDirectory state)
- (inspect the story notes / RCA for the 06-06 02:25 spawn-source finding — **Atlas RCA condition C-3**) → (names the spawn trigger — systemd Restart= race / watchdog / manual+service overlap — or best-available evidence + most-likely trigger if the journal aged out)

## Conditional Outcomes

- if the journal no longer holds the 06-06 boot window, document best-available evidence + the most likely spawn trigger rather than blocking

## Notes

Implements Atlas condition C-5 (matched-pair invariant). No dependency on the
US-386/387/388 reproducer chain — the Root-1 mitigation is already deployed; this
Story makes it a durable, tested, version-stamped invariant.

**2026-06-28 (Atlas freeze-gate ruling §4):** Atlas flagged that RCA condition
**C-3** (confirm the 06-06 02:25 spawn TRIGGER for the two concurrent
`eclipse-obd` PIDs) was not visible as an acceptance criterion. It lives in this
Story's DoD (journal-confirmation bullet) and is now also an explicit validation
criterion. Root 1 is mitigated (guard live) but the spawn trigger is unconfirmed.
