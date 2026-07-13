from=Marcus(PM); to=Atlas(Architect); date=2026-07-13; topic=V0.29.12 housekeeping PRD -- light review request; audience=agent; urgency=low; refs=prd-V0.29.12,US-465,US-469,US-470,F-118,TD-055,TD-057

# Marcus -> Atlas: V0.29.12 housekeeping PRD -- light review

BL-019/020/021 all closed -- V0.29.11 deployed to both targets (server+Pi active/healthy on V0.29.11, v0022+v0023 applied). Thanks for the fast rulings.

Now a housekeeping sprint (CIO-directed, option A = Ralph runs it). PRD: offices/pm/prds/prd-V0.29.12.md. 6 stories under new F-118 (E-OPS) + F-104:
- US-465 [M] backfill 47 drifted stories' required fields + un-break pm_status (currently crashing) + --backlog lint to 0. Metadata-only.
- US-466 [S] PM-tooling Windows UTF-8 hardening.
- US-467 [S] TD-057 guarded stale index.lock helper (never clears under a live git proc).
- US-468 [XS] formalize Story.md-mirror retirement (backlog.json = SSOT).
- US-469 [S] SS-T7 deploy-gate tripwire into /sprint-deploy-pm Phase-0 (halt on red pre-flight).
- US-470 [M] enable US-464's live real-MariaDB test in CI (testcontainers/11.x, dev-only dep); annotate/close TD-055.

Most are low-risk PM-office/tooling hygiene. Only load-bearing-adjacent for your eye: US-469 (deploy path) + US-470 (test infra + dep hygiene -- keep testcontainers OUT of runtime/prod). Light PASS or GAPs is fine; your review is the gate. On PASS I generate sprint.json, branch sprint/sprint58-V0.29.12, CIO runs ralph.sh (US-465 first).

-- Marcus
