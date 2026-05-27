---
id: F-099
parent: E-OPS
status: pending
renamedFrom: B-099
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-099: Telegram bot — bidirectional driver-context channel (CIO ↔ system; LLM-mediated text→DB ingestion)

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (V0.28+ candidate; bridges driver-context gap that Spool analytics needs) |
| Status       | Pending (V0.28+ candidate) |
| Category     | infrastructure / messaging / driver-context capture / Ollama text→structured ingestion |
| Size         | L (likely; touches server tier, Ollama pipeline, new DB table, secrets, bot lifecycle) |
| Dependencies | B-094 (MrSpool digital-twin / Ollama+RAG infra — the LLM-extraction prompt+JSON-schema pattern matures here); B-091 (Android Auto audio drive reports — the outbound *audio* sibling channel; Telegram is the inbound *text* channel) |
| Created      | 2026-05-15    |

## Description

**CIO directive 2026-05-15**: integrate Telegram as a bidirectional message channel between the system and Mike. CIO is already running a Telegram bot on another project + likes the UX. Low integration friction — existing bot-account / bot-token pattern from CIO's other project is reusable.

**Use case (CIO-described)**: after Pi syncs to chi-srv-01 (or at a server-defined cadence), the system **outbound-messages Mike** with a contextual question about the drive(s) just synced — e.g. *"Drive 13 just synced (12 min, peak coolant 198°F, 2 knock-retard events). Anything notable from the seat?"* Mike replies freeform from his phone. The freeform reply is **fed into the local LLM (Ollama on chi-srv-01)** to extract structured fields (drive feel, modifications-since-last-drive, weather, fuel-grade, perceived issues, free-form notes) into a new `driver_context` DB table. **Spool's analytics layer consumes the structured context** as additional grading input.

**Why this matters**: today Spool's grade-per-drive (B-089) + anomaly detection (B-093) + heat-soak recovery (B-095) all rely on OBD-II + Pi-side telemetry only. Driver-side context (e.g. *"first drive after pump install"*, *"E85 today"*, *"felt a hesitation around 4000 RPM"*) currently has no structured capture path. CIO writes free-form notes in the Eclipse Google Sheet (`G:\My Drive\Eclipse\Eclipse 1998 Projects.gsheet`) and verbally tells Spool when relevant — neither path is queryable. Telegram + LLM-extraction makes driver context first-class structured data.

## Architecture sketch (PM-level; to be refined at PRD grooming)

```
Pi drive → sync to chi-srv-01 → SyncFinished hook
       ↓
Server outbound: Telegram bot sends "How was Drive N?" message to Mike
       ↓
Mike replies freeform on phone ("E85, first drive after pump install, hesitation 4k")
       ↓
Telegram bot receives reply → server side
       ↓
Ollama text→JSON extraction (structured schema: fuel_grade, mods_since_last, perceived_issues[], free_form)
       ↓
INSERT INTO driver_context (drive_id, raw_text, extracted_json, ollama_model, created_at)
       ↓
Spool analytics layer reads driver_context joined to drive_summary
```

## Open architectural questions (for PRD grooming)

1. **Trigger location**: server-side (after sync completes) vs Pi-side (immediately at drive_end before sync). Default: server-side (Pi may be off-WiFi). Spool input may differ.
2. **Outbound message content**: how much to summarize in the question? Lean (just "How was Drive N?") vs context-rich (peak temps + RPM + flagged anomalies). CIO answers in scope-grooming.
3. **Driver-context schema**: new table `driver_context (id, drive_id FK, raw_text, extracted_json, ollama_model, created_at, telegram_message_id)` vs extension columns on `drive_summary`. Lean: new table — driver context is sparse + can be added asynchronously after drive_summary already wrote.
4. **Ollama extraction schema**: structured JSON via Ollama `format: json` mode OR prompt-engineered. Likely depends on which model (llama3.1:8b vs successor by V0.28). Captures fields like `{fuel_grade, mods_since_last_drive, weather, perceived_issues[], free_form_notes, sentiment}`.
5. **Multi-drive batching**: if Mike does 3 drives before replying, do we send 3 separate messages or one batched? Suggest 1 batched per sync-session (Spool may have view).
6. **Lapsed-reply handling**: Mike doesn't reply for hours / days / never. Default: no retry; `driver_context` row absent is normal; Spool tolerates NULL context. Possible follow-up: a `/skip` command Mike can send.
7. **"Reply to which drive?"**: Telegram replies don't carry drive_id. Approach options: (a) outbound message includes drive_id in payload + reply-quoting links it; (b) implicit last-pending-drive; (c) `/drive <N>` slash command. Default: (a).
8. **Privacy / PII**: Telegram is third-party (cloud-hosted). System should NOT send VIN, GPS, raw OBD streams. Outbound summaries should be already-aggregated metrics. Inbound reply text is stored raw + structured — acceptable since Mike already controls what he types.
9. **Secrets**: Telegram bot token stored in `.env` per existing config-layer pattern (`${TELEGRAM_BOT_TOKEN}`). Bot chat_id (Mike's) also in `.env`. No multi-user yet; single-user.
10. **Bot lifecycle**: long-poll vs webhook. Webhook needs server-side HTTPS endpoint — chi-srv-01 already has FastAPI. Long-poll is simpler but uses a worker thread continuously. Default: long-poll for V1; webhook upgrade in follow-up.
11. **Multi-vehicle future** (per CIO standing constraint "could see this used on another vehicle or shared with friends"): bot must support per-device routing eventually. V1 = single device single user; V2 = per-`source_device` chat_id mapping.
12. **Failure modes**: Telegram API down, Ollama extraction returns malformed JSON, message exceeds Telegram length limits. Each needs graceful degradation (raw_text-only row + flag for manual review).

## What's NOT in scope (deferred)

- **Outbound audio reports** — that's B-091 (Android Auto). Telegram is text-only here.
- **Real-time alerting during drives** — out of scope; this is post-drive context capture. Real-time alerts would be a separate B-item (live-alert channel; could use the same bot).
- **MrSpool RAG-grounded conversational Q&A over Telegram** — that's B-094 + Telegram-as-UI; possibly the natural V2 layer once B-094 lands. V1 scope = one-shot post-drive context capture.
- **Voice notes** — Telegram supports them but Ollama doesn't transcribe locally; add Whisper-server later if CIO wants.
- **Group chats / multi-user** — single-user single-device V1.

## Acceptance Criteria (PM-level; PRD grooming refines)

To be detailed at PRD grooming. Key gates:

- Telegram bot account exists + bot token stored via secrets-loader pattern (`${TELEGRAM_BOT_TOKEN}`)
- Server-side outbound message fires post-sync with drive summary + driver-context-question
- Reply round-trip: Mike replies → server captures → Ollama extracts → row inserted to `driver_context` table
- Ollama extraction schema defined + JSON-schema-validated; malformed extractions flagged not silently dropped
- Spool analytics layer (existing `report.py` prompts or successor) joins `driver_context` to `drive_summary` for grade computation
- Lapsed-reply tolerance: no row is fine; downstream analytics handle NULL context gracefully
- IRL drill: complete drive → sync → outbound msg received on Mike's phone → reply → DB row visible within 60s of reply

## Cross-references

- **B-091** (Android Auto audio drive reports) — sibling outbound *audio* channel; share post-drive trigger logic
- **B-094** (MrSpool RAG / digital-twin) — Ollama prompt-engineering + JSON-extraction pattern matures here; Telegram-as-conversational-UI is a natural V2
- **B-089** (Spool engine grade per drive) — primary consumer of structured driver context for grading
- **B-093** (baseline-relative anomaly detection) — driver-context "mods_since_last_drive" tag may auto-suppress false-anomaly during expected drift windows
- **`project-mrspool-digital-twin-vision`** in MEMORY.md — long-term Spool extension vision; this is the inbound text channel for it
- **Eclipse Google Sheet** (`G:\My Drive\Eclipse\Eclipse 1998 Projects.gsheet`) — current free-form-notes home; structured driver_context table is a graduation of that practice

## Source

CIO Mike 2026-05-15: "Use the Telegram app to send and retrieve data to/from me, Mike. I am using it on another project and I like it. If Spool wants more driver input, The system could send a message when synced with the server and ask about the drive(s). Then the response could be fed into our local LLM, do a text-to-structured-data, and then load that data into DB for Spool to analyze."
