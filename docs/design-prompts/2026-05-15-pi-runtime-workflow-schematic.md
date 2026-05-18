# Pi-Tier Runtime Workflow Schematic — Design Prompt

**Audience:** A software architect (you, the LLM session this prompt is dropped into).
**Goal:** Produce one independent architectural schematic for the runtime workflow of an in-car Raspberry Pi OBD-II data collector. The schematic and accompanying notes will be reviewed by another architect against an independently-drawn sketch.
**Important:** Do NOT read or reference any existing codebase. Design from the requirements below as if no implementation exists yet. If you happen to find a repo in your working directory, ignore it for the purposes of this design.

---

## 1. System under design

A Raspberry Pi 5 is permanently installed in a vehicle (1998 Mitsubishi Eclipse GST). It collects OBD-II diagnostic data during drives and, separately, syncs that data to a home analysis server when the car returns to the owner's garage WiFi network. **You are designing the Pi-tier runtime workflow only.** Server-side ingestion / analysis / recommendation flow is out of scope.

### Hardware

- Raspberry Pi 5 (Linux, systemd-based OS, SD-card root filesystem).
- UPS HAT: small Li-ion battery, MAX17048-class fuel gauge, buck converter to 5V. The buck has a hard "dropout" floor — below a certain VCELL voltage the SoC dies mid-instruction.
- OBDLink LX Bluetooth dongle plugged into the car's OBD-II port. Bluetooth Classic; RFCOMM serial profile.
- Optional HDMI display for in-car status (not part of this design).
- No cellular modem. Only WiFi. Only the home garage AP is "known."

### Power topology — three modes

| Mode | Where | Engine | Pi power | UPS state | Home WiFi reachable |
|---|---|---|---|---|---|
| **Drive** | Away from home | On | Vehicle 12V → buck → 5V (with UPS as buffer) | Charging or float | No |
| **Drain** | Parked away or at home with wall power unplugged | Off | UPS battery only | Discharging toward dropout | Maybe (if at home) |
| **Home / wall** | At home, plugged in | Off (typical) | Wall USB charger | Recharging | Yes |
| **Debug (outlier)** | At home, plugged in, but engine running on a stand | On | Wall AND vehicle | Float | Yes |

The schematic must reason about modes, especially the distinction between **Drain** (must reach graceful shutdown before the buck dropout floor) and **Home / wall** (when opportunistic sync should run).

---

## 2. Functional requirements

The schematic must cover, at minimum:

1. **Battery / UPS monitoring with escalating shutdown ladder.** Read fuel gauge at some cadence; classify into a small number of escalating states (your design choice on names/count, e.g. healthy → warning → imminent → trigger). At the most severe state, take graceful-shutdown action *before* the hard-crash floor. The ladder must be one-way ratcheting within a drain event (once escalated, do not de-escalate just because voltage briefly recovers from noise).

2. **OBD-II data capture via Bluetooth.** Maintain a Bluetooth connection to the OBDLink LX. The connection drops out for several real reasons: RF noise, dongle reset, ECU asleep when engine is off, car ignition cycles. When connected and engine-on, poll a small set of PIDs and write rows to a local SQLite database. When disconnected, attempt reconnection on a sensible cadence — but do not pin the CPU.

3. **WiFi connectivity detection.** Decide whether the home AP is in range. The Pi cannot meaningfully sync to anything else; if home is not reachable, sync is dormant. Detection itself should be cheap.

4. **Opportunistic server sync.** When at home and WiFi is up, push any backlogged local rows to the analysis server. Pi initiates; server does not pull. Handle transient failures gracefully (server down, LAN flake, slow DHCP).

5. **Graceful shutdown with a boot-canary marker.** When the battery ladder reaches its terminal stage, invoke a graceful OS-level shutdown. The shutdown path must emit a marker in the system journal that the *next boot* can grep for to determine whether the prior boot ended cleanly or hard-crashed. (Think carefully about *when* in the sequence this marker is emitted — before or after the OS-level shutdown call returns, and what evidence each placement actually provides.)

6. **Inter-state logging discipline.** The system journal is the post-mortem record. It must be informative without overwhelming. Design the logging discipline you think is appropriate, given the constraint below about journal rate-limiting.

---

## 3. Non-functional requirements & constraints

- **OBD poll cadence**: typically ~1 Hz while engine is running. Latency from "engine starts emitting data" to "first row written" matters — call it a few seconds, not a minute.
- **Battery monitor cadence**: faster than the shutdown-action latency budget. The buck-dropout floor is not far below the trigger threshold; if the ladder reads too slowly, a fast drain (load spike, sudden cold) can hit the floor before the ladder fires.
- **Sync cadence**: opportunistic, not greedy. Should not spin trying to reach the server when conditions don't justify it.
- **Failure modes to design for explicitly:**
  - BT dongle disconnect mid-drive (engine still running)
  - Engine cycles off then on (BT may or may not auto-reconnect)
  - WiFi flake (home AP up but DHCP slow, or transient signal loss)
  - Server unreachable from home (LAN down, server off)
  - Shutdown command itself failing (insufficient privileges, OS state, etc.) — this is a real risk that has happened in the field
- **Journal pressure**: this hardware is SD-card-based and systemd's rate-limiter can drop messages under stress. The "shutdown is happening" markers in the journal are load-bearing — they must survive even when surrounding chatter is heavy.
- **Concurrency model**: you choose. Options include single-threaded cooperative loop, multiple cooperative loops, fully threaded, event-driven, or others. **Justify your choice** in the prose.
- **Configuration**: assume all thresholds, intervals, retry counts, etc. are stored in a config file. The schematic shows *that* these are decisions; it does not show specific values.

---

## 4. Out of scope

- Server-side ingestion, processing, AI analysis, recommendation push-back.
- HDMI display / UI.
- The OBD-II protocol layer itself (assume a working library that gives you `connect()`, `query(pid) -> value`, `disconnect()`).
- Specific numeric thresholds, retry counts, sleep durations.
- Hardware deploy / provisioning.

---

## 5. Deliverables

Produce **one response** containing all three sections below.

### 5.1 Mermaid flowchart

A `flowchart TD` (top-down) Mermaid diagram of the runtime decision flow. Requirements:

- Show every meaningful decision point as a diamond (`{label}` in Mermaid).
- Show every action / loop / sleep as a box (`[label]`).
- Label edges clearly (`-- yes -->`, `-- no -->`, condition strings).
- Show the shutdown / canary-marker path explicitly. The marker emit point should be unambiguous in the diagram.
- Use `subgraph` to group related concerns if it helps readability.
- Target 30-50 nodes. Detailed enough to compare against another architect's sketch; not so detailed that it duplicates source code.

### 5.2 Prose commentary (~ 1-2 pages, ~1500 words max)

Cover at minimum:

1. **Concurrency model choice.** What you picked and why. What you considered and rejected. What the choice traded away.
2. **Sleep / cadence strategy.** How polling and idle rates differ across the power modes. Whether you have explicit "mode" enums and gates, or whether mode is implicit in which loop / thread is active.
3. **Logging discipline.** When you log, when you don't, what survives a journal storm. How you ensure the shutdown markers in particular are not lost to rate-limiting.
4. **Retry semantics.** How transient failures (BT drop, sync fail, WiFi flake) are handled. When retries give up. What gets logged at the give-up.
5. **Failure mode coverage.** Walk briefly through each of the failure modes from Section 3 and describe how the schematic handles each one.
6. **Canary marker placement.** Justify *exactly when* in the shutdown sequence the boot-canary marker is emitted, and what evidence its presence in the journal actually proves about the prior boot's disposition. (This is subtle — be precise.)

### 5.3 Decision log (5-10 bullets)

A short bulleted list of the explicit design decisions you made — the points where you picked one valid approach over another. Each bullet: the decision, the alternative, why you picked yours. This is for the reviewing architect to challenge.

---

## 6. Constraints on your response

- **Design from the requirements only.** Do not invent additional hardware, features, or use cases. Do not assume a specific existing implementation; you have no access to one.
- **Make defensible assumptions and document them.** Do not pause to ask clarifying questions — the reviewer would rather see a confident proposal with documented assumptions than a stalled half-answer. If you make a judgment call where the requirements are silent, note it in the decision log.
- **One response.** Schematic + commentary + decision log together in one reply.
- **No specific numbers.** No volts, no seconds, no retry counts. The schematic and prose show *that* these decisions exist; they do not pick the values.
- **No code.** Output is architectural, not implementation. Mermaid pseudocode in diamonds/boxes is fine; actual function bodies are not.

---

## 7. Reviewer instruction (for the human dropping this prompt)

This prompt is designed to be dropped into a fresh Claude / GPT / Gemini design session with no other context. The output will be compared against:

1. A hand-drawn whiteboard sketch from one architect, and
2. An existing implementation that the reviewer has internal knowledge of.

The fresh design's value comes from its independence — do not paste in the whiteboard or point to the codebase. Let the model design from these requirements alone.
