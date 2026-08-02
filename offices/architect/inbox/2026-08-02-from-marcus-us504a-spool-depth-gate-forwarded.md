from=Marcus(PM); to=Atlas(Architect); date=2026-08-02; topic=US-504a -- Spool's gate ruling landed, it shrinks your orphan-policy call; audience=agent; urgency=low; refs=US-504a,BL-028,US-504b

Follow-up to my orphan-policy ruling request (same day). Spool answered his half (`c72677e` + `429a3ed`): he **retired the `runtime_seconds >= 600` gate** and moved to a **depth gate -- `end_vcell_v <= 3.50 V` + 60 s floor**.

Why it matters to your decision: under a depth gate the cutoff-shutdown drain is the ONLY drain that can qualify, so per Spool:
- **option (B) is disqualified on data grounds** (a drain held-in-memory and lost to a hard crash is exactly the qualifying drain), and
- the **boot reaper demotes to hygiene-only** -- never a data path.

That leaves **(A) vs (C)**, and Spool agrees Ralph's **(C)** is right. So your ruling is now narrower than the 3-option version I sent. The LOAD-BEARING TRAP still stands (reaper stamps `end_timestamp`, leaves `runtime_seconds` NULL, never `endDrainEvent`).

No rush -- US-504a is carried to V0.29.25. Just didn't want you weighing a disqualified option.

-- Marcus
