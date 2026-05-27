---
id: F-055
parent: E-002
status: pending
renamedFrom: B-055
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-055: Weather API for drive context (auto-populate ambient + conditions)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium                 |
| Status       | Pending                |
| Category     | infrastructure / data  |
| Size         | S-M (depends on column-shape decision) |
| Related PRD  | None                   |
| Dependencies | B-057 drive_annotations table (depends on its weather_conditions / humidity columns being defined) |
| Created      | 2026-05-09             |

## Description

Mike 2026-05-09 directive (relayed via Spool): at drive-end (Pi-side) OR at sync-completion (server-side), call a free weather API to populate `ambient_temp_at_start_c` + weather/humidity/baro on the drive's record. Replaces the manual Spool-interview-based annotation Spool just did for drives 3-7.

**Why now**: Spool interviewed Mike on 5 drives this week. Drives 6+7 (yesterday) recall sharp; Drives 3-5 (10-16 days ago) had soft spots ("Drive 3's '52F overcast' was half-memory, half-best-guess"). API call deterministic, frees Spool from per-drive interviews going forward.

## Acceptance Criteria

- [ ] Drive_summary (or drive_annotations per B-057) row written at drive_end has non-NULL ambient_temp + weather_conditions + humidity (where API returns them)
- [ ] API failure path: write NULL on the columns; drive_summary still posts; Spool falls back to interview if needed
- [ ] Configurable home lat-long in config (~95% accurate since drives originate from home; future GPS module can override)
- [ ] Server-side trigger (recommended) -- Pi already busy at drive_end; server runs analytics rollup anyway
- [ ] Privacy: zero personal/vehicle info sent to API; only timestamp + coordinates

## Validation Script Requirements

- **Input**: completed drive with non-NULL drive_start_timestamp + home-lat-long config value
- **Expected Output**: drive_summary (or drive_annotations) row populated with ambient_temp + weather_conditions + humidity within 60s of sync completion
- **Database State**: SELECT ambient_temp_at_start_c, weather_conditions FROM drive_summary WHERE drive_id = N -- both non-NULL
- **Test Program**: integration test mocks API at the HTTP edge; asserts populated columns; failure-mode test asserts NULLs on API timeout

## Notes

**API options (Spool's recommendation order)**:
1. **Open-Meteo** -- no API key, generous free tier, JSON, historical lookups supported. Cleanest fit.
2. **NWS** (api.weather.gov) -- free, US-only, no key. Good fallback.
3. **OpenWeatherMap** -- free tier with key. More features than needed.

**Implementation sketch (NOT a contract)**:
- Server-side, fire on sync-completion when drive_summary row lacks weather populated
- Read drive_start_timestamp + home-lat-long from drive context
- HTTP GET to weather API, parse JSON, UPSERT the weather columns
- Handle API down with NULL writes + retry queue (server has cycles)

**Why Sprint 29+ not Sprint 28**: Sprint 28 is V0.27.2 bug-fix work. Adding a feature now dilutes focus. Belongs after analytics path is healthy enough that weather data has somewhere clean to land.

**Sequencing**: B-057 drive_annotations table must exist first (provides weather_conditions / humidity columns). Then this story plugs the API call into the right column shape.

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-feature-idea-weather-api-for-drive-context.md` (Spool relayed CIO 2026-05-09 directive)
