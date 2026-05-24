# Feature idea — pull weather context per drive from a free weather API
**Date**: 2026-05-09
**From**: Spool (Tuning SME) — relayed from CIO directive
**To**: Marcus (PM)
**Priority**: Routine — backlog grooming candidate (not Sprint 28)

## TL;DR

Mike floated this idea in today's Spool session: **at drive-end, hit a free weather API to populate ambient_temp + conditions for the drive automatically**, replacing the manual interview-based annotation we just did for drives 3–7.

This is a clean Sprint 29+ candidate. Pairs naturally with the `drive_annotations` schema work that came out of yesterday's PM note Item 1+2 — those columns include `ambient_temp_f` and `weather`, which the API call would populate.

## Why this is a good idea

Today I interviewed Mike on 5 drives and captured ambient temp + weather. For drives 6 + 7 (yesterday) his recall was sharp. For drives 3–5 (10–16 days ago) his recall had soft spots — Drive 3's "52°F overcast" was half-memory, half-best-guess. A weather API call at drive-end would:

- Capture the data deterministically from the timestamp, no human in the loop.
- Free Spool from interviewing the CIO every drive going forward (5 fields × N future drives = real interview load).
- Populate the **already-existing `ambient_temp_at_start_c` column on `drive_summary`** (per `models.py`), which is currently unused.
- Let Spool's drive-grading rubric reference deterministic ambient context: "Drive 12 ran at 95°F on a 88% humidity day vs. Drive 7's 67°F cloudy" becomes a query, not a memory test.

## Implementation sketch (for Rex/Ralph context — not a contract)

**Trigger**: Pi-side at `drive_end` event, OR server-side at sync-completion for a drive_summary row that doesn't yet have weather populated.

**API options (free tier sufficient for this volume)**:
- **Open-Meteo** — no API key, generous free tier, JSON, historical lookups supported. Probably the cleanest fit.
- **NWS** (api.weather.gov) — free, US-only, no key required. Good fallback if Open-Meteo coverage thins.
- **OpenWeatherMap** — free tier with API key, well-documented. More features than we need.

**Inputs needed**:
- Drive timestamp (`drive_start_timestamp` already on schema).
- Location. Two options:
  - Hardcode CIO's home zip / lat-long (cheap, ~95% accurate since drives originate from home).
  - Read GPS from a future Pi GPS module (not currently in scope).
  - Vehicle's last-known coordinates if we ever add that (also future scope).
- For now: hardcode home lat-long. ~95% accuracy is sufficient for tuning context — when the Eclipse drives 2 hours away to Brookfield, ambient there might be different from home, but it's still a useful approximation.

**Output fields to populate**:
- `ambient_temp_at_start_c` (already on `drive_summary` per models.py)
- `weather_conditions_at_start` (NEW — would need to be added with the `drive_annotations` schema work)
- `humidity_pct_at_start` (NEW, optional but useful — air density variable)
- `barometric_pressure_kpa_external` (NEW, optional — distinct from the `barometric_kpa_at_start` column which is from the OBD/MAP sensor; useful as cross-check)

**Failure mode**: API down or unreachable — write NULL into the columns. Drive_summary still posts. Spool can fall back to interview if a specific drive's analysis demands it.

**Privacy footprint**: zero. The API call sends a timestamp + coordinates and gets back public weather data. No personal info, no vehicle identifiers. The car's location is implied as "near home" which the CIO has already signaled is fine.

## Why this is Sprint 29+, not Sprint 28

Sprint 28 is V0.27.2 bug-fix work (drive_summary writer regression, calibration.py fix, battery_health_log close-event flush, etc.). Adding a feature now would dilute the bug-fix focus. This belongs after the analytics path is healthy enough that the weather data has somewhere clean to land.

Tentatively a Sprint 29 or Sprint 30 candidate, sized around S–M depending on:
- Whether we add the new columns or piggy-back on the `drive_annotations` table you'll already be specifying.
- Whether we go API-call-from-Pi (offline-tolerant retry queue needed) or API-call-from-server-on-sync (simpler).

Recommend **server-side at sync-time** for simplicity — Pi already has 100 things to do at drive_end, and the server's already doing analytics rollup work; weather lookup fits there cleanly. Pi doesn't need internet at drive-end.

## Backlog action

File this as a backlog item (`B-???-weather-api-drive-context.md`) with the above as the seed description. Spool will revise once the `drive_annotations` schema lands and the actual column shape is known. No PRD needed yet — the idea is small enough that a backlog item with the implementation sketch is sufficient until grooming time.

— Spool (relaying CIO 2026-05-09 directive)
