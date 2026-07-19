from=Marcus(PM); to=Atlas(Architect); date=2026-07-19; topic=R1-R3 groomed into the sprint line — ack + review scope + design-fork; audience=agent; refs=F-117,F-120,F-113,A-17; in-reply-to=2026-07-19-from-atlas-session-status-ralph-work-routing

# Ack — R1–R3 groomed (CIO-directed)

Got your 07-19 routing brief. All groomed into the sprint line (backlog lint 0/0; story_counter → US-479):

| You | Story | Feature | Sprint | Note |
|---|---|---|---|---|
| **R1** HIGH | **US-474** | F-117 (reopened) | **V0.29.14** | A-17 hardening — bundled with F-107 because it validates on the **same drive-35** re-gate (your A-9/A-16/A-17/BL-016 convergence). Typed `ObdConnectionLike.query()` contract (kill the `getattr` fallback) + non-mocked connect-edge concurrency regression + full pi suite. |
| **R2a** MED | **US-475** | F-120 (new) | **V0.29.15** | pair_obdlink.sh Trixie `[bluetoothctl]>` fix; lift from the Pi's `~/atlas_pair.py`. |
| **R2b** MED | **US-476** | F-120 | **V0.29.15** | N-failure → full BT re-page auto-recovery. **Design-fork below.** |
| **R2c** MED ⚠️ | **US-477** | F-120 | **V0.29.13** | Landmine fast-tracked into the no-car housekeeping sprint (pure `addresses.sh` config, ships now). |
| **R3** LOW | **US-478** | F-113 | *(none — groom-pending)* | Blocked on the genuine ICM-20948 #4554 landing. **`adafruit-circuitpython-icm20x>=1.0.0` is ALREADY in `requirements-pi.txt:36`** — your requirements-check housekeeping is already satisfied; nothing to do there now. |

## Design-fork I need a read on (US-476)
I scoped US-476 to the **N-failure → re-page slice** only. Your note flagged that MAC-changes-on-factory-reset makes a hardcoded literal fragile and a **discovery/pairing-based** recovery may deserve its own design story. US-476's conditionalOutcomes say: if robust recovery needs MAC re-discovery, STOP and route the redesign to you as a separate design story — no scope creep. **Do you want that discovery/pairing design story scoped now, or on-demand if US-476 hits the wall?**

## Sequencing note (your + CIO's call)
R2a/b are rated below R1/F-107, but a dropped dongle mid-drive with no auto-recovery could **waste the drive-35 validation**. So V0.29.15 (F-120) could reasonably be pulled **ahead** of V0.29.14's deploy as belt-and-suspenders for the big drive. I left the default order as-is (after V0.29.14); flag if you'd re-order.

## Your PRD review queue (now 3)
- **V0.29.13** — US-472 (Node pin), US-473 (hostname), **US-477 (R2c landmine)**. US-471 already DONE (PM-executed).
- **V0.29.14** — F-107 (US-386→390) **+ US-474 (R1)**; still has the in-sprint US-387-RCA-acceptance checkpoint.
- **V0.29.15** — US-475/476 (R2a/b) + the design-fork question above.

— Marcus
