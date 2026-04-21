# Pi Collector BT-Resilient Daemon — new story proposal + drill findings

**Date**: 2026-04-20
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (medium-high — blocks US-208 meaningful execution + autonomous capture)

## TL;DR

CIO ran a 22-minute thermostat + engine-restart drill today. Three outcomes:

1. **I-016 closed BENIGN** — thermostat is healthy (CIO gauge observation; annotated in the issue file directly).
2. **Engine mechanical health confirmed** — clean cold crank, stable 15-min idle, clean restart.
3. **Pi data-collection path exposed as non-resilient** — collector was not running as a persistent service. Zero rows captured during the drill. No wake-on-BT, no reconnect loop, no auto-restart. This is the finding CIO wants addressed.

No data was collected, but the drill was still valuable: it answered the I-016 hardware question and exposed a latent architectural gap in the operational-readiness path. CIO's word: *"No data is still a finding. This was a good test."*

This note proposes a new story (BT-Resilient Collector Daemon) to address the gap. Scoping is tight per CIO's refinement.

---

## Drill context

**Protocol**: `offices/tuner/drills/2026-04-20-thermostat-restart-drill.md` (saved before the drill for future reference).

**CIO's hypothesis going in** (confirmed by the drill): *"after BT disconnects, the Pi either goes to sleep or never wakes back up because the system requires a reboot or some other trigger."*

**What I found post-drill**:

| Finding | Details |
|---------|---------|
| `realtime_data` count = 0 | Not just in drill window — the entire table is empty. |
| No `obd-collector.service` in systemd | `systemctl list-units --state=running` shows only `bluetooth.service` matching. |
| Pi BT stack healthy | `hci0` UP RUNNING, `/dev/rfcomm0` exists, paired/bonded/trusted (Sprint 14 state preserved). |
| Schema intact | All expected tables exist (realtime_data, connection_log, statistics, drive_counter, etc.). |
| Pi display showed nothing during drill | This was the early warning signal at ~15 min mark; the renderer was correctly showing "no data" because no data was flowing. |

**What CIO observed directly (authoritative)**:

- Internal vehicle coolant gauge in **normal position throughout** the 15-min sustained idle. → I-016 closes benign.
- Engine cold-started and restarted cleanly. No rough idle, no warning lights, no anomalies.

---

## I-016 closeout — just a pointer

I annotated `offices/pm/issues/I-016-coolant-below-op-temp-session23.md` with the CLOSED BENIGN disposition + today's drill evidence. Status field updated in the file. Please archive per PM hygiene at your convenience — the tuning call is done.

One durable update: the Session 23 warm-idle fingerprint in `specs/grounded-knowledge.md` should now be treated as a **mid-warmup snapshot, not steady-state healthy idle**. Any future baseline comparisons against Session 23's 73-74°C coolant need that context. I won't edit the spec file mid-session without a fresh drill to replace the fingerprint with — just flagging the interpretive shift.

---

## The new story — Pi Collector BT-Resilient Daemon

### CIO's refined design target (use this as the spec)

> *"95% of the time the car is in sleep mode. If the Pi actually resets and goes completely to sleep, that's fine — then on power on it knows to look for Bluetooth. The edge case is the Pi never went to sleep and is still alert, but the car shut down and the Bluetooth disconnected. That is the scenario we need to solve."*

Both "Pi-sleeps-and-wakes" (future car-accessory-wired path) and "Pi-stays-alive-BT-dropped" (today's wall-power reality AND future UPS-graceful-shutdown-window reality) converge on the same design: **a persistent collector daemon with an internal BT reconnect loop**.

### Suggested story skeleton

```
Title: Pi Collector BT-Resilient Daemon (systemd service + reconnect loop)
Size: M (possibly L if BT error classification turns out to be fussy)
Priority: medium-high
Backlog tier: new B-level item, OR single-story in a Sprint 16+ slot
Dependencies: none direct. Synergy with B-043 PowerLossOrchestrator (both
              need graceful-on-loss semantics). Must land before US-208 can
              meaningfully validate anything (currently US-208 would report
              "collector not running" as its primary finding).

Intent:
  Package the Pi collector as a persistent systemd service that starts at
  boot, auto-restarts on crash, and internally handles Bluetooth disconnects
  without exiting the process. When the OBDLink goes away (car off, BT flap,
  adapter power-cycle), the collector enters a reconnect-wait loop and
  resumes capture when BT returns — no reboot, no manual intervention, no
  external watchdog.

Scope:
  1. systemd unit file (deploy/obd-collector.service):
     - Restart=always with RestartSec starting at 5s
     - Backoff: StartLimitIntervalSec=300 + StartLimitBurst=10 (max 10 restarts
       in 5 min before systemd gives up — if we hit that, something's really
       broken)
     - After=bluetooth.service network.target
     - Requires=rfcomm-bind.service (shipped Sprint 14)
     - User=mcornelison (or dedicated obd user — Ralph decides)
     - Working dir + env file handling via standard systemd patterns
     - Enabled via systemctl enable so it auto-starts on Pi boot

  2. BT reconnect loop inside the main capture loop:
     - Classify errors into three categories:
       (a) ADAPTER_UNREACHABLE: /dev/rfcomm0 OSError, rfcomm timeout, BT disconnect
       (b) ECU_SILENT: rfcomm responds but ECU doesn't (engine off, key off)
       (c) FATAL: unexpected exception classes — log + re-raise (let systemd restart)
     - On (a): cleanly close python-obd connection, enter wait loop
     - On (b): stay connected, poll less aggressively, wait for ECU to come back
     - On (c): surface to systemd for fresh restart

  3. Reconnect-wait loop:
     - Poll /dev/rfcomm0 reachability every N seconds with backoff
     - Backoff schedule: 1s, 5s, 10s, 30s, 60s, 60s, 60s... (cap at 60s)
     - Probe = lightweight command (ATI or ATZ) over rfcomm — NOT a full python-obd
       OBD() constructor (that's expensive + stateful)
     - On successful probe, re-instantiate OBD connection, resume capture
     - Reset backoff on successful reconnect

  4. connection_log observability enhancements:
     - New event_types: bt_disconnect, adapter_wait, reconnect_attempt,
       reconnect_success, ecu_silent_wait
     - Every state transition logs a row
     - Post-hoc review ("what happened during that drive?") reads as a flap
       timeline, not a mystery gap

Acceptance:
  1. `sudo systemctl enable obd-collector && sudo systemctl start obd-collector`
     — service starts and stays running.
  2. `systemctl status obd-collector` shows active (running) with recent log lines.
  3. Pi reboot test: `sudo reboot` → after Pi comes back, collector auto-starts,
     begins capturing within 30s if OBDLink is available.
  4. BT drop test (the CIO drill scenario):
     - Pi running, OBDLink connected, capture active
     - Unplug OBDLink power / car off
     - Collector detects disconnect WITHIN 30 seconds, logs bt_disconnect +
       adapter_wait to connection_log
     - Collector process does NOT exit (ps auxf shows same PID)
     - Reconnect OBDLink / car on
     - Collector detects adapter within N seconds, logs reconnect_success,
       resumes capture
  5. Process-kill test: `sudo kill -9 <pid>` → systemd restarts collector within
     5-15s → captures resume on next BT availability.
  6. Capture continuity test: drop + restore BT twice in a 10-minute window.
     connection_log shows clean flap timeline with no overlapping drives.
  7. No regression in fast test suite; ruff clean; sprint_lint clean.
  8. deploy/obd-collector.service added to deploy tree and documented in
     docs/deployment.md or equivalent.

Invariants:
  - Collector process NEVER exits on BT disconnect. Only FATAL errors surface
    to systemd for restart.
  - Reconnect backoff caps at 60s. Never aggressive, never logarithmic beyond cap.
  - connection_log event_types are additive; existing types (connect_attempt,
    connect_success, disconnect, drive_start, drive_end) remain unchanged.
  - No wake-on-BT, no heartbeat rows, no observability endpoint — those are
    nice-to-haves deferred to a follow-up story. Keep this scope tight.
  - Service name obd-collector.service — do NOT use a different name and do NOT
    multiplex multiple services (one daemon, one service).

Stop conditions:
  - STOP if BT error classification requires intercepting bluetoothd internals
    or kernel-level events — file an inbox note to Spool describing the
    complexity cost. python-obd exception surface + /dev/rfcomm0 OSError handling
    should be sufficient; if it isn't, scope creep.
  - STOP if Restart=always triggers more than 10 restarts/hour during testing —
    masking a bug with aggressive restart is worse than the bug. Diagnose the
    underlying crash first.
  - STOP if the capture loop's current architecture requires significant refactor
    to host the reconnect loop (e.g., tight coupling of OBD connection to every
    PID poll function) — file inbox note with proposed refactor scope before
    implementing.

Nice-to-haves explicitly deferred:
  - Heartbeat rows in connection_log every N seconds while waiting
  - Observability endpoint (obd-status CLI / API)
  - Wake-on-BT from Pi low-power sleep
  - Prometheus-style metrics export
  All of the above are useful but orthogonal to "the daemon doesn't die on BT
  drop." Let's land the core behavior first.
```

### Why this matters for the broader sprint calendar

- **US-208** (Sprint 15, first-drive validation) cannot produce meaningful validation while the collector isn't a persistent service. Today's drill is exhibit A. Until this story lands, US-208 will always report "collector not running" as the primary finding. This is a soft blocker.
- **B-037 Pi Sprint phase** (live drive review ritual, touch carousel, backup push) all assume "Pi is continuously capturing." That assumption doesn't hold today.
- **B-043 PowerLossOrchestrator** (gated on CIO accessory-wiring) requires the collector to behave correctly during graceful-shutdown windows — which means surviving BT drop. B-043 and this story are natural neighbors.
- **Summer 2026 E85 conversion** doesn't directly need this, but the logging + interpretation work that justifies the E85 investment does. We need a reliable capture pipeline before we're tuning real drives.

---

## Separate item: US-205 triple-execution mystery

Not part of the collector-resilience story, but flagging since I surfaced it today:

Three backup files on the Pi (from Ralph's US-205 truncate script) have timestamps that fall DURING the drill window:

- `obd.db.bak-truncate-20260420-213248Z` (21:32:48 UTC)
- `obd.db.bak-truncate-20260420-213518Z` (21:35:18 UTC)
- `obd.db.bak-truncate-20260420-213809Z` (21:38:09 UTC)

Ralph's 2026-04-20 halt note said he did NOT execute, only dry-ran. But the backup filename pattern matches his script, and the three executions happened during my drill — which is evidence of an unexpected automation path. Possibilities:

- Ralph's scheduled-tasks framework auto-ran the truncate (if there's a "pick up next pending story" trigger)
- The script was executed manually by someone/something else
- A race condition with the dry-run logic that actually wrote despite claiming not to

This is Ralph's lane to investigate — not mine, not blocking this story, but worth a Ralph inbox note from your side asking him to root-cause the unexpected execution before any future scheduled-task-capable story lands. Scheduled tasks executing destructive operations without explicit trigger is a dangerous pattern regardless of the specific story involved.

Also: the three backups mean we have three intact snapshots of the pre-truncate 352K-row DB state. If anyone ever wants to post-mortem the pre-truncate content, those backups are there on the Pi.

---

## Sources

- Drill protocol: `offices/tuner/drills/2026-04-20-thermostat-restart-drill.md`
- I-016 issue (now annotated with closeout): `offices/pm/issues/I-016-coolant-below-op-temp-session23.md`
- CIO design scoping: 2026-04-20 PM session between Spool + CIO (this note's conversation)
- Ralph's US-205 halt note: `offices/tuner/inbox/2026-04-20-from-ralph-us205-halt.md`
- Spool knowledge on 4G63 warmup behavior: `offices/tuner/knowledge.md` cooling system section
- specs/architecture.md §5 Drive Lifecycle (context for why the reconnect loop matters)

---

## What I'm NOT asking for in this story

- Don't bundle in the benchtest data_source hygiene fix (`2026-04-20-from-spool-benchtest-data-source-hygiene.md`) — separate concern, separate story.
- Don't bundle in the US-205 execution mystery — separate investigation by Ralph.
- Don't bundle in US-208 itself — this story is the PREREQUISITE; US-208 is the consumer.
- Don't expand to wake-on-BT or heartbeat rows — nice-to-haves deferred.

Focus = one daemon that doesn't die. Everything else is scope creep.

— Spool
