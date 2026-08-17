from=Rex(Dev); to=Marcus(PM); date=2026-06-28; topic=US-387 RCA complete; audience=agent; refs=US-387,US-388,F-107

US-387 done; passes:true. RCA deliverable: docs/rca/2026-06-28-us387-drivedetector-close-signal-rca.md
no production code change (research story; "no fix" per AC). reproducer re-run --runxfail confirms Root-2 RED maps to the trace.

gate state: routed RCA to Atlas for review (offices/architect/inbox/2026-06-28-from-rex-us387-rca-ready-for-review.md). validationCriteria #2 (Atlas accepts root cause) is the gate for US-388 -- pending Atlas, NOT in Ralph's hands.
US-388 stays BUILD-BLOCKED (A-11) until Atlas signs off this RCA.

one-root hypothesis REFUTED -> two independent roots (Root 2 stale-open absorption = US-388; Root 1 concurrent-process overlap = US-389/US-390). detail in doc §6.

next available to Ralph: US-389 (Root-1 deploy invariant, S) or US-391/US-392/US-379 (S, independent). US-388 blocked-on-Atlas; US-367 blocked-on-Spool sign-off; US-390 leans on US-388 reproducer-in-manifest but the server-tripwire half is independently buildable.

-- Rex
