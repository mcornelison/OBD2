# Task: Update Data Retention from 7 Days to 1 Year

## Summary
Increase realtime_data retention period from 7 days to 1 year (365 days) to preserve data during vehicle storage periods.

## Background
The current retention policy (per `specs/architecture.md` line 284) is:
- `realtime_data`: 7 days (configurable)
- `statistics`: Indefinite
- `ai_recommendations`: Indefinite

The 7-day retention is too short because:
- Vehicle may be in storage during winter months (3-4 months)
- User may want to analyze historical trips
- Pi 5 has 128GB storage - plenty of space for 1 year of data

## Files to Update

### Configuration
- [ ] `src/config.json` - Update default retention value
- [ ] Add retention setting if not present

### Documentation
- [ ] `specs/architecture.md` - Update line 284 from "7 days" to "365 days"
- [ ] `specs/samples/piSpecs.md` - Line 136 says "7 days or 100MB max" - update

### Code (if applicable)
- [ ] Verify data cleanup routine respects the new retention period
- [ ] Consider adding configurable retention in config.json

## Storage Estimation
Assuming:
- 1 reading per second during drives
- Average 1 hour of driving per day
- ~50 bytes per reading

Daily: 3,600 readings x 50 bytes = 180 KB
Yearly: 180 KB x 365 = ~65 MB

With 128GB storage, 1 year retention is easily achievable.

## Acceptance Criteria
- [ ] Default retention is 365 days
- [ ] Documentation updated
- [ ] Existing data cleanup respects new retention
- [ ] Retention is configurable via config.json

## Priority
Low - Configuration change

## Estimated Effort
Small - Config and documentation update

## Created
2026-01-25 - Tech debt review
