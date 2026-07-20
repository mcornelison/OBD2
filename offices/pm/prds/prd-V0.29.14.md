---
sprint: 60
version: V0.29.14
status: draft
createdAt: 2026-07-15
createdBy: Marcus (PM)
selectedStories: [US-474]
shippedNotInSprint: [US-386, US-387, US-388, US-389, US-390]  # F-107 SHIPPED Sprint 47/V0.29.1 -- removed per Atlas PRD review 2026-07-20 (were stale-sprint-ready; A-9 closure = IRL re-gate, not a rebuild)
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-117 (OBD-capture reliability -- A-17 hardening)
theme: A-17 capture-fix hardening -- close the DTC-read raw-fallback hole + add the connect-edge concurrency regression F-117 missed
atlasReview: "PASS w/ corrections 2026-07-20 (inbox 2026-07-20-from-atlas-prd-review-v0.29.13-14-15-corrections.md). BLOCK: F-107 US-386->390 already SHIPPED (Sprint 47/V0.29.1) -- REMOVED. US-474 KEPT, re-scoped (Protocol exists; gap = drop getattr fallback + concurrency test). Corrections applied 2026-07-20."
---

# PRD: V0.29.14 -- A-17 capture-fix hardening (F-117)

| Field | Value |
|---|---|
| Version | V0.29.14 (patch on `dev`, forks from V0.29.13) |
| Theme | Harden the **live** A-17 DTC-read serialization fix (`4a17bc1`) so the connect-edge race F-117 missed cannot silently regress |
| Status | DRAFT — Atlas PASS-with-corrections 2026-07-20 (corrections applied). |
| Lane | Pi OBD-capture path; **load-bearing-adjacent** (connection-lock). |
| Stories | **US-474** (1) under **F-117** |
| Deploy + validate | Deploys from `dev`; US-474's own regression is bench-green; the end-to-end capture proof is the combined IRL car re-gate (drive 35). |

## ⚠️ Scope correction (Atlas PRD review 2026-07-20)

This PRD originally scoped the **F-107 DriveDetector chain (US-386→390)** as unbuilt. **Atlas's review + my verification confirmed all five already SHIPPED in Sprint 47 / V0.29.1** and are merged into `dev`:
- commits `4bd8444`/`f36b44d`/`75384e6`/`d4d7d22`/`25fcc0d` (US-386/387/388/389/390) are all ancestors of `dev`, `passes:true`;
- `detector.py:710 _maybeCloseOnDeadline` / `:739 evaluateTimeouts` implement the fix; `architecture.md §10.7.1.2` documents it.
- `backlog.json` statuses were stale (`sprint-ready`) — **corrected to `complete` 2026-07-20**. `prd-V0.29.1.md` is the shipped record (status corrected `superseded → shipped`).

**F-107 removed from this sprint** (it's done). The remaining **A-9 closure is the IRL car re-gate** — a single clean drive (one `drive_id`, correct close, no absorption) validated by the CIO + Atlas/QA — **not a Ralph rebuild sprint.** See "IRL re-gate" below.

## The one real story

| Story | Type | Size | Summary |
|---|---|---|---|
| **US-474** | issue | S | **A-17 capture-fix hardening (Atlas R1, F-117).** The A-17 fix (`4a17bc1`) is **live** (routes DTC reads through the `_ioLock`-serialized `query()` wrapper) but keeps a runtime `getattr(connection,'query',None)` **fallback to the raw unlocked `obd.query()`** at `dtc_client.py:353-354`, and lacks a non-mocked concurrency regression. Scope (Atlas-verified — the `ObdConnectionLike` Protocol + wrapper already exist, so this is a close, not greenfield): **(1) remove the raw fallback** so DTC reads always serialize; **(2) add `query()` as a typed Protocol member** (`:137`) + update DTC fakes; **(3) add a non-mocked connect-edge concurrency regression** (logger read + KOEO DTC read on one connection, no interleave — the exact GAP-1 F-117 missed); full pi suite + mypy green. |

## IRL re-gate (not a sprint — CIO + car)

The standing A-9 closure, unchanged: **one clean engine-on drive (drive 35)** producing exactly one `drive_id`, correct close on key-off, no absorption of a later key-on, tripwire clean. Atlas notes **one drive re-gates A-9 (attribution), A-16 Bug-3 (live carousel), A-17/F-117 (OBD capture), and BL-016 (cold-boot key-OFF→engine-on)** together. US-474's hardening deploys to the Pi and rides that same drive for its end-to-end capture proof. Atlas verifies end-to-end when the CIO drives.

## Notes
- Rule-13 retired → Atlas's PRD review IS the gate (PASS-with-corrections, applied).
- **Nuance flagged to Atlas:** removing the `getattr` fallback means calling `connection.query()` directly, which needs `query()` on the Protocol for mypy — so US-474 *does* add one typed member to the existing Protocol (not "building the contract"). Called out in the ack in case Atlas meant strictly no-Protocol-change.
- With F-107 gone, V0.29.14 is a small single-story capture-hardening sprint; could even fold into another Pi-touching sprint if the CIO prefers fewer deploys.
