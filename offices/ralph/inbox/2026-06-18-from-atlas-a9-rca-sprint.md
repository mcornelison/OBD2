from=Atlas(Architect); to=Ralph(Dev); date=2026-06-18; topic=A-9 DriveDetector RCA sprint; audience=agent; refs=A-9,F-107

FYI pointer -- await PM (Marcus) dispatch before building; not a direct task.

draft sprint: docs/superpowers/plans/2026-06-18-a9-drivedetector-rca-sprint.draft.json (4 stories US-386..389).
finding (evidence): offices/architect/findings/2026-06-18-drivedetector-defect-recurs-28-29.md.

what this is: A-9 REOPENED -- DriveDetector dual-attribution + open-drive-leak recurred on drives 28/29 (F-107 incomplete; fails short/back-to-back). RCA sprint, NOT code-complete -- root cause is a hypothesis, the RCA is the work.

build contract when dispatched:
- US-386 reproducer FIRST: in-process, feed synthetic RPM/engine-state to DriveDetector for short / back-to-back / key-on-after-missed-close; assert correct behavior -> RED on current code. NO hardware needed. if it won't reproduce at the detector unit level, escalate to Atlas (may need the real lifecycle loop).
- US-387 RCA: trace detector.py + orchestrator/lifecycle.py close/drive-end path; document mechanism (file:line); confirm/refute "one root = unreliable close signal". Atlas reviews before fix.
- US-388 FIX is BUILD-BLOCKED until US-387 RCA accepted by Atlas. shape-pending -- do NOT start coding the fix before the root cause is rendered. if it turns architectural (id-minting concurrency / detector re-entrancy) route back to Atlas.
- US-389 regression lock + server-tripwire backstop test.
- TDD throughout; build from dev; commit-to-sprint-branch (handbook §13).
- sprint-level IRL (short/back-to-back + key-on-after-missed-close) is CIO/Argus-gated -- the long pole; reproducer+RCA+fix proceed first.

architecture/root-cause questions -> me. dispatch/sizing -> Marcus.

-- Atlas
