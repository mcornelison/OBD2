# Spool — I-016 (Thermostat) Closed Benign

> Spool persona / diagnostic record. Migrated 2026-05-18 from `~/.claude/.../project_i016_thermostat_closed_benign.md` per CIO directive.

**Fact**: I-016 is CLOSED BENIGN as of 2026-04-20. The 1998 Eclipse GST 4G63 thermostat and cooling system are healthy. Session 23's coolant reading of 73-74°C (163-165°F) was a short-capture-window artifact — engine hadn't reached full op temp in the 23 seconds of OBD-connected time.

**Why**: On 2026-04-20 CIO ran a dedicated 15+ min sustained-idle warmup drill (`offices/tuner/drills/2026-04-20-thermostat-restart-drill.md`). Internal vehicle coolant gauge was observed in **normal operating position throughout**. Normal gauge position on a 4G63 ≈ 190-200°F (88-93°C), well above the 180°F thermostat-open disposition gate. No digital capture during the drill (collector not running), but the gauge observation is authoritative on the hardware question.

**How to apply**:
- The Session 23 warm-idle fingerprint in `specs/grounded-knowledge.md` (coolant 73-74°C) is now a **mid-warmup snapshot**, NOT steady-state healthy idle. Any future analysis comparing against Session 23 coolant needs this interpretive shift.
- Summer 2026 E85 conversion does NOT need a cooling-system audit beyond standard coolant service — thermostat is trusted.
- Any future drill that captures coolant trajectory digitally should overwrite the Session 23 baseline value with a real steady-state warm-idle reading.
- Annotation applied directly in `offices/pm/issues/I-016-coolant-below-op-temp-session23.md` — Marcus archives per PM hygiene.

**Spool's pending research item "2G thermostat diagnostic procedure"** (tracked in `pending-research.md`) is CLOSED. No diagnostic procedure needed — the gauge answered it.
