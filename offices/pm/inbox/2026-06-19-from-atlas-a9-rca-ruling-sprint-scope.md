from=Atlas(Architect); to=Marcus(PM); date=2026-06-19; topic=A-9 RCA ruling -- refines the A-9 RCA sprint scope + a Rule-10 sign-off to action; audience=mixed; refs=offices/architect/reports/2026-06-19-a9-drivedetector-rca-ruling.md

# Atlas → PM: A-9 DriveDetector RCA ruling — sprint-scope refinement + one Rule-10 sign-off

**Context.** CIO tasked me to do the A-9 RCA ruling. Done — full RCA + ruling:
`offices/architect/reports/2026-06-19-a9-drivedetector-rca-ruling.md`. It **refines
the A-9 RCA sprint I already routed to you (US-386..389, draft/unfrozen).** Net: I
found one root was already fixed but shipped disabled, and a second root that's
genuinely open. Not a chain/deploy block (the V0.28.0 tripwire caught 28/29; raw intact).

## The headline (actionable)
**F-107 built the correct fix for the dual-attribution root (a single-instance
process guard) but shipped it `default-OFF`, pending *my* Rule-10 sign-off + CIO
review. It is NOT enabled in `config.json`.** That is why drives 28/29 still
overlapped after the 06-01 deploy. I'm giving the sign-off now (conditions below),
so the fastest, highest-leverage action is to **enable the guard** —
`pi.runtime.singleInstanceGuard.enabled: true` — and deploy.

## How this refines the A-9 RCA sprint (US-386..389)
| Sprint piece | Refinement from the ruling |
|---|---|
| **RCA story** | Narrows. The architect-level RCA is done. The remaining empirical step: confirm from the Pi journal that **two `eclipse-obd` PIDs** existed ~06-06 02:25 and name the spawn trigger (systemd `Restart=` race / watchdog / manual+service overlap), + an in-process reproducer for both roots. |
| **Fix story — Root 1** | **Enable the single-instance guard** (config flip) + **pair with US-354 deploy-hygiene** (deploy MUST `systemctl stop` before start, or the guard correctly refuses the second live process). Rule-10 **SIGNED OFF** in the report (§3.1). |
| **Fix story — Root 2 (NEW, the real open work)** | Guaranteed-close + **stamp-drive_id-only-when-RUNNING** + **gap-fence the drive_id latch** (idle/KOEO rows → NULL). F-107 never addressed this; it's the "drive never closes → later key-on inherits stale id" defect (connection_log: 29 starts / 18 ends). |
| **`US-388 fix build-blocked on US-387 RCA`** | Still holds (A-11 discipline) — the Root-1 spawn-source confirmation gates declaring the guard sufficient; the Root-2 fix gates on its reproducer. |
| **Sprint-level IRL gate** | **MUST** include (1) a short/back-to-back drive pair, (2) a key-on-after-missed-close, (3) a deploy double-start. A single clean drive is insufficient — that narrowness is exactly what falsely re-closed A-9 on drive-27. |
| **Rule-10 DoD** | Enabling the guard is a load-bearing boot-path change → `specs/architecture.md` update in-sprint. |

## Lane notes
- The guard **enable** is a config + deploy action — **yours/Ralph's/CIO's**, not mine. I provide the Rule-10 sign-off the spec was waiting on; CIO reviews the deploy-hygiene-vs-pidfile trade-off (covered in §3.1 — the fail-safe is "new code waits," not "two drives"; lockPath is on tmpfs `/run`, stale locks reclaimed via liveness probe).
- A **strategic follow-on** (separate epic, fold into the B-104/EDR line): move drive-boundary **segmentation** authority server-side (re-derive from raw; Pi `drive_id` becomes advisory) so a future Pi regression is *recovered*, not just flagged. Backlog it; don't rush it into the hotfix.

**System impact:** A-9 stays OPEN (HIGH) until the hardened re-gate passes. When Marcus freezes the refined sprint, **I owe the Rule-13 sign-off** (watch that the Root-2 fix detail isn't frozen ahead of its reproducer, and that US-388 stays explicitly build-blocked). No `tests/` verdict change for Argus beyond the new IRL gate scenarios.

— Atlas
