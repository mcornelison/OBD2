# Storage, Retention and Custody — design

**Status:** approved in design, not yet built · **Owner:** Atlas (Architect) ·
**Ratified by:** the CIO, 2026-09-20 · **Ticket:** ARCH-037
**Companions:** `specs/data-acquisition-architecture.md` (ARCH-036) — what we collect and how
fast. This file is what happens to it afterwards. `specs/shutdown-orchestration-design.md`
(ARCH-035) — Tier 2 sync is the custody handover this file defines.

**Relationship to `specs/architecture.md`:** that file is the system **as built**. This is the
target design. They disagree on purpose until the build lands, then `architecture.md` is
updated in the same sprint (Rule 10 DoD).

---

## 1. Why this exists — we already lost the data once

🔴 **Measured 2026-09-16. EDR recorded for six to ten weeks and deleted itself, because the
destination did not exist.**

    SHOW TABLES LIKE 'edr%' on obd2db        ->  0 rows
    Pi journal, hourly:  "EDR retention purge: deleted imu=73798 light=3575
                          (older than 7 days)"        ~1.77M rows/day

Persistence shipped 2026-07-01 (US-410). The server tables were never created. **All EDR
older than 2026-09-07 is gone and none of it ever synced.**

⚠️ **Every component was working correctly.** The reader read. The subscriber persisted. The
purge honoured its configured window. **The defect was the seam nobody owned:**

> 🔴 **A purge authorised by AGE alone, over data whose only copy was local.**

⏰ **Deletion resumes ~2026-10-22.** What survives — 14.4M IMU + 701K light rows — is
**single-copy on one SD card**, in a car whose WiFi is unreliable (A-24).

**This spec exists so that cannot happen a second time.**

## 2. What "stored" means — three distinct states, never conflated

| State | Means | Who can assert it |
|---|---|---|
| **CAPTURED** | written to Pi SQLite, fsync-safe | the Pi |
| **DELIVERED** | the server has acknowledged the rows | the Pi, from the server's ack |
| **DURABLE** | it exists somewhere the Pi's SD card failing would not destroy | the server |

🔴 **A clean shutdown guarantees CAPTURED. It guarantees nothing about DELIVERED.** That
distinction already exists in code (`sync_custody.py`, US-621) after a real incident: the CIO
drove off-WiFi, returned, and the Pi ran a full graceful shutdown. Every signal said success.
**~35 minutes of capture, on the order of 15,000 rows, had never left the Pi.**

> *"The sequencer was not wrong about what it was built for. The defect is that 'shutdown
> complete' was read as 'data delivered' and NOTHING distinguished them."*

**Rule: no surface, log line, or verdict may use a word that implies delivery for a fact that
is only captured.**

## 3. The retention rule

🔴 **NOTHING IS PURGED ON AGE ALONE. EVER.**

    purge(row) permitted  IFF   row is DELIVERED-verified
                          AND   row is older than the retention window
                          AND   the row is not drive-coupled evidence still under analysis

Age is a **necessary** condition, never a sufficient one. The first clause is the one that was
missing on 2026-07-01, and it cost six to ten weeks of data.

**Implementation constraint, inherited from US-768 (Gap 2):** 🔴 **modify `purgeExpired()` IN
PLACE. Do not add a second purge beside the live age-only one.** Two purges means one of them
is the unguarded one, and it will be the one that runs.

### Purge by AGE alone is backwards for this data

⚠️ The A-37 purge resumes ~2026-10-22 on an age-only rule. Against the drive-coupling ruling
(ARCH-036 §6) that rule would **delete old COUPLED drive data while keeping recent ORPHANED
wall-power data — exactly inverted.** Coupling, not age, is what makes a row worth keeping.

### Retention settings are currently ambiguous

    config.json:562                      pi.sensors.retentionDays  = 45
    validator default                    pi.sensors.retentionDays  = 7
    validator default                    database.retentionDays    = 365

⚠️ **Two differently-named retention keys with three different values.** `b25acc7d` (09-14)
raised the Pi window 7→45, which is why the Pi floor is 2026-09-07. 🔴 **The build must
establish one authoritative retention key per store and state what each governs** — an
ambiguous retention setting is how a purge ends up running on a window nobody intended.

## 4. Custody — the handover contract

Sync is a **custody transfer**, not a copy. It completes only when the receiving tier has
acknowledged. Every shutdown states the outcome, on a greppable prefix:

    DELIVERED    everything captured has been acknowledged
    OUTSTANDING  N rows remain on the Pi
    UNKNOWN      we could not determine it — a TYPED ABSENCE, never a substituted 0

🔴 **`UNKNOWN` must never be rendered or counted as zero.** A count that cannot be completed
is a **lower bound**: `total` must never travel without `residualIsComplete`, and a
`total` with unreadable tables is not a total.

⚠️ **The backlog reader currently EXCLUDES the EDR tables** (US-766), so "the backlog is
empty" can be true while millions of EDR rows sit undelivered. **The count that decides
custody must cover everything custody is claimed over, or the claim is false by construction.**

## 5. Currency — what the server may and may not say

🔴 **The server cannot answer "is the car synced?" from its own telemetry, and no schema fixes
it** (A-40, 2026-09-19). `sync_history` records what a session **pushed**; nothing records
what the Pi still **holds**. "All sessions completed" and "the vehicle is fully synced" have
the **same server signature**.

**Proof, from a real drive:** at 19:35:30Z session 216962 completed clean and the Pi genuinely
was caught up. The drive data was created *after*, and the Pi never contacted the server
again. **A residual-at-close field would have read `CURRENT` and been correct — while the car
held a whole drive.** Rows created after last contact are invisible to the server *by
construction*.

Three questions, three different answers:

| | Question | Decidable? |
|---|---|---|
| **Q1** | was it current at last contact? | ✅ yes, cheaply (`SyncBacklog`) |
| **Q2** | is the Pi awake but failing? | ✅ only while it is awake |
| **Q3** | has the car been used since? | 🔴 **not from Pi telemetry** |

### The permitted vocabulary

    CURRENT AS OF <t>          HOLDING >= N AS OF <t>          UNKNOWN SINCE <t>

🔴 **The word "SYNCED" is forbidden on any surface.** *Synced* is a claim about **now**, and
the server cannot make it. A green "SYNCED" light is an inert instrument.

### The second witness — Q3's only closure

🟢 **The CIO corrected an earlier framing of mine that called Q3 undecidable.** It is
undecidable *from the Pi's own telemetry* — but the Pi is not the only thing that knows the
car moved. An **independent use-witness** (a Strava export, a GPS trip record) recorded by a
device that does not share the Pi's failure modes closes Q3 when present.

**It should be an admitted INPUT to vehicle currency, not a manual step the architect performs
by hand.**

⚠️ **Honest limit, so this does not over-swing:** such a witness is **opportunistic**. Its
ABSENCE proves nothing and must never be read as "no drive occurred." **It is decisive when
present and silent when absent** — it can strengthen a positive finding of a queue; it can
never license a claim of `CURRENT`.

⚠️ **Staleness must NEVER alarm.** A parked car is quiet by design. A nightly false alarm is
one nobody reads on the night it matters. **The one legitimate alarm is `HOLDING >= N` that
stops decreasing across contacts.**

## 6. Schema parity across tiers

The Pi (SQLite) and the server (MariaDB) hold the same facts under **different shapes**.
Measured 2026-09-20:

| Table | Pi | Server |
|---|---|---|
| `startup_log` | PK `boot_id`, **no `id`** | `id INT AUTO_INCREMENT` |
| `battery_health_log` | PK `drain_event_id` | `id INT AUTO_INCREMENT` |

Silent contract divergence is an architectural defect (A-4). **Rule: a fact's shape on each
tier is declared in one contract, and parity is checked by test — not discovered by a query
failing.**

⚠️ **The existing parity check is partly inert.** `checkTimestampParity` matches
`(^|_)(timestamp|ts|at|time)$` — suffix-anchored, so it matches `synced_at` but **never
`ts_utc`**, the ISO-8601 partition key of both EDR server tables. **Those tables pass the
check for the wrong reason.** Fixing it needs its own story with its own before/after.

## 7. The free detector nobody was running

🟢 **Compare row counts across tiers.** A destination sitting at **zero** for a producer at
**millions** is not a subtle signal, and it would have caught A-37 in the first week.

**Rule: every synced table is covered by a cross-tier count comparison**, reported on a
schedule, with a typed absence when a tier cannot be reached. This is cheap, needs no new
instrumentation, and is the single highest-value check in this document.

## 8. Blast radius — one line enrols a table into six consumers

🔴 **A single `PK_COLUMN` entry enrols a table into SIX consumers**, and a missing table
raised out of `pushAllDeltas` and **stopped ALL Pi→server sync** until it was guarded.

**Rule: adding a table to the sync contract is a reviewed change with a named blast radius**,
and every consumer degrades independently — one missing table must never stop the others.

## 9. Gates

1. **No purge on age alone.** Delivery-verified is a required condition.
2. **`purgeExpired()` is modified in place.** Never a second purge.
3. **One authoritative retention key per store**, each stating what it governs.
4. **The custody count covers everything custody is claimed over.**
5. **`UNKNOWN` is a typed absence.** Never rendered, summed or defaulted to 0.
6. **The word "SYNCED" appears on no surface.** Use the three permitted forms.
7. **Every synced table has a cross-tier row-count check.**
8. **Schema parity is declared in one contract and tested**, and the test must actually match
   the columns it claims to (see §6).
9. **Adding a table to the sync contract names its blast radius** and degrades independently.

## 10. Open items

| Item | Owner | Blocks |
|---|---|---|
| Reconcile the three retention keys into one per store | Atlas | the build |
| `checkTimestampParity` regex cannot see `ts_utc` — own story, own before/after | Marcus to schedule | parity claims only |
| Ingest a use-witness as a currency input (Q3) | Atlas + CIO | currency completeness, not the build |
| ⏰ **The age-only purge resumes ~2026-10-22** | **Marcus to schedule ahead of it** | 🔴 **data loss deadline** |

## 11. Out of scope

- Sync wire protocol, retry and backoff.
- Server-side storage engine, partitioning, indexes.
- The acquisition rates themselves (ARCH-036).
- The shutdown sequence (ARCH-035).
- Analysis and verdict logic consuming this data.
