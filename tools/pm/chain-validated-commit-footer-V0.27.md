# /chain-validated commit footer -- V0.27 chain merge to main

**Use at**: PM `/chain-validated` ritual for V0.27.1..V0.27.19 (or current tip if higher patch by then) merge to main.

**Approved by**: CIO 2026-05-22 (Session 42 post-V0.27.18 deploy + Argus drill PASS + Atlas chain-clearance).

**Source of wording**: Atlas's 2026-05-22 disposition note (`offices/pm/inbox/2026-05-22-from-atlas-drive-23-24-dual-attribution-disposition.md`) + PM additions (Drive 25 evidence per CIO observation + regression manifest HOLD paragraph) + CIO ratification.

---

## Merge commit body (use verbatim; substitute actual version range + ride-alongs at fire time)

```
merge: chain V0.27.1..V0.27.19 -- B-104 Step 1 server analytics authority empirically validated; main = fully validated stable

<one-paragraph chain summary -- B-104 Step 1 architectural shift,
3-cycle false-pass class structurally closed by V0.27.18, US-350..US-358 shipped,
Sprint 40 + Sprint 41 + Sprint 42 validated, etc. Tailored at fire time.>

## Known scoped exception (V0.28.0 B-107 top priority)

Drive 23/24 dual-attribution surfaced V0.27.18 IRL drill 2026-05-22 -- Pi-side DriveDetector defect upstream of B-104 Step 1 compute path; architecturally orthogonal to chain-merge architectural scope. Bounded: drive 25 single-attribution clean (witnessed live 2026-05-22). See offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md.

## Regression manifest discipline

F-005 + F-007 + F-008 + F-011 + F-012 HELD pending V0.28.0 tripwire (server-side detect_overlapping_drives + data_quality='attribution_anomaly' flag). F-008/F-011/F-012 also held on rested-pack drain validation + new ECU baseline collection.

## Validated this chain (lastValidated 2026-05-22)

<list of features with refreshed lastValidated -- F-001/F-002/F-003/F-004/F-006/F-009/F-010 etc. -- pulled from regression_manifest at fire time after Argus's rollback lands>

V0.28.0 sprint 1 = B-107 fix + tripwire + B-076 schema-normalization first slice (see offices/pm/backlog/B-076 V0.28 expansion section).
```

## Git tag message (shorter; pointer to commit body)

```
chain-V0.27

Chain V0.27.1..V0.27.19 merged 2026-05-22; main = fully validated stable.

Known scoped exception: drive 23/24 dual-attribution -- V0.28.0 B-107 top
priority. See merge commit body + offices/architect/findings/
2026-05-22-drive-detector-dual-attribution.md.
```

## Pre-fire checklist

- [ ] Argus manifest-rollback ack landed (F-005/F-007 reverted to prior `lastValidated`)
- [ ] Ralph V0.27.19 TI-002 fix committed on `sprint/sprint42-v0.27.19-ti-002` branch
- [ ] PM sprint.json US-358 + story_counter advance to 359 + RELEASE_VERSION V0.27.19 bump committed
- [ ] `python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --strict` exits 0 (TI-002 fix proves out + chain READY)
- [ ] `pm_regression_status.py` shows F-005/F-007/F-008/F-011/F-012 as HELD/STALE/NEVER (NOT validated 2026-05-22)
- [ ] CIO greenlight to fire

## At fire time

1. Substitute actual `<one-paragraph chain summary>` with Sprint 40 + Sprint 41 + Sprint 42 narrative + the V0.27 chain achievements list
2. Pull current `regression_manifest.json` to populate `<list of features with refreshed lastValidated>` section
3. Confirm tag name (`chain-V0.27` per convention, or other if CIO directs)
4. Run `/chain-validated`; verify the merge commit body matches the template above before pushing

## Decisions NOT incorporated (per CIO 2026-05-22 ratification)

- **ECU swap context**: NOT in chain-merge commit. Atlas's call -- ECU swap is concurrent telemetry context, not architectural delta. Belongs in V0.28.0 sprint context + B-108 file + Spool's knowledge.md.
- **TI-002 explicit mention**: NOT in carve-out footer. V0.27.19 patch closes it within the chain range; not a defect riding into main.
