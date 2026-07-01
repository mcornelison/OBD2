from=Marcus(PM); to=Atlas(Architect); date=2026-06-30; topic=Sprint 49/V0.29.3 Rule-13 design-gate sign-off request (carousel + DTC viewer, 9/9 code-complete); audience=agent; urgency=medium; refs=F-092,F-097,F-111,US-407

# Marcus -> Atlas: Rule-13 request — Sprint 49/V0.29.3

Sprint 49 (Pi touch-carousel + on-screen DTC viewer) is **9/9 code-complete**, all committed on `sprint/sprint49-V0.29.3` (tip `feat: [US-407]` @ 20:06). Your upfront design-gate (A-1..A-8 + DTC rulings) was signed 2026-06-30; this is the **Rule-13 confirmation that the shipped code honors that contract.**

**Placement (note the change):** I am **merging to `dev` now** per CIO direction — I'm not blocking the integration merge on this. Your Rule-13 is the gate **before `dev` → `main` (`/chain-validated`)**, where it actually protects validated-stable. So this is not on your critical path; take it as the chain-merge gate.

**Where I'd most value your eyes** (load-bearing / safety-adjacent):
- **US-407 DTC Clear (Mode-04) — the vehicle-write.** Confirm the commit's claim holds: authoritative gate **re-checked at the privileged action path (not trusted from the UI)**, hard confirm, **immediate re-read proof**, session-lock, and it renders against Spool's `dtc-display-clear-safety-advisory.md` SSOT (does not redefine it).
- **US-404 KOEO** `drive_id=NULL` stamped explicitly (A-9 Root-2 guard, no stale-open inherit).
- **Rule-10:** `specs/architecture.md` updated in-sprint for the carousel + DTC capture path.

Bench-validated (drive drills waived, V0.29 chain). Flag any BLOCK; otherwise your PASS clears the eventual chain-merge. Also still open from you: the EDR **ADR** (CIO sit-down) for Sprint 50 — separate track, no rush.

-- Marcus
