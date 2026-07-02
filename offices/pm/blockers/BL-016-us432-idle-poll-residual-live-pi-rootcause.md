# BL-016: US-432 idle-poll residual gap — root-cause pinned to a runtime (python-obd) mechanism that needs live-Pi disambiguation before a fix is safe

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Active                    |
| Blocking     | US-432 (Sprint 53 / V0.29.7) only — does NOT block US-433..440 |
| Waiting On   | CIO live-Pi bench repro (cold-boot key-off → engine-on) + Atlas fix-direction ruling |
| Created      | 2026-07-02                |

## Description

US-432 is VERIFY-FIRST: root-cause the RESIDUAL engine-on-in-idle miss that the
shipped US-242/B-049 escalation still leaves, WITHOUT re-solving the escalation,
and fix it. I completed the code-level root-cause (below). The verdict: the
residual miss lives in a **runtime (python-obd) masking mechanism**, and the
*correct un-mask fix* depends on python-obd internals + K-line behavior that
**cannot be verified from the Windows dev box**. Shipping a fix on the wrong
assumption would produce another "passes the mocked test but still misses IRL"
regression — which is exactly the failure mode this verify-first story exists to
prevent (the existing escalation tests mock `queryAndLogParameter` and never
exercise the real masking, so they are green while the live path misses).

Per the systematic-debugging Iron Law (no fix without a confirmed root cause) and
Refusal Rule 1, I am blocking US-432 for a live-Pi disambiguation rather than
guessing the fix. The other Sprint 53 stories are unaffected.

## Root cause (code-verified — the shipped escalation is fine; the miss is downstream)

The US-242 escalation itself works: sustained BATTERY_V > 13.8V (alternator
signature) fires and injects one RPM probe (`core.py:1150`
`_maybeEscalateOnAlternatorActiveSignature` → `_injectRpmProbeForEscalation`).
The RESIDUAL miss is what happens to that probe (and to every regular RPM poll):

1. **`supported_commands` is probed ONCE at connect and never refreshed.**
   `ObdConnection.connect()` calls `_runSupportedPidProbe()` exactly once
   (`obd_connection.py:408`); nothing re-probes for the life of the connection.
2. **Cold-boot while the ECU is dark poisons the support set.** On a Pi cold-boot
   with the car key OFF, the ELM327 adapter link is up (pin-16 battery power) but
   the ECU does not answer the Mode 01 support bitmap. python-obd's
   `supported_commands` therefore omits RPM (0x0c). (Our `SupportedPidSet` mirror
   omits it too, but see #4 — that mirror is NOT the RPM gate.)
3. **RPM is queried with `force=False`.** `queryParameter('RPM')` takes the legacy
   branch (RPM is in `LEGACY_ECU_PARAMETERS`, NOT `PARAMETER_DECODERS`) and calls
   `self.connection.obd.query(cmd)` with no force flag (`logger.py:220`). python-obd
   returns a **null response without touching the wire** for a command not in its
   cached `supported_commands`. → `ParameterReadError("null response")`.
4. **`_assertPidSupported` is a red herring for RPM.** It only guards the Spool-v2
   decoder PIDs in `PARAMETER_DECODERS` (`logger.py:212`); RPM never reaches it.
   So the fix is NOT "clear our `SupportedPidSet`" — that would be a no-op for RPM.
5. **The escalation swallows the null and latches.** The injected probe's
   `ParameterReadError` is caught at `core.py:1245` (WARN), and `_engineOnEscalated`
   stays `True` (single-shot invariant), so no retry happens. US-221 "ECU-silent
   recovery" cannot help: it only clears ECU-silent mode *on a successful read*
   (`realtime.py:590/711`), and no RPM read can succeed while python-obd's stale
   cache masks it. Result: RPM stays masked for the whole connection → DriveDetector
   never sees RPM rise → **drive_start never fires** for the engine-on-in-idle trip.

There is also a **structural weakness independent of the mask**: even a single
successful RPM probe only moves the detector STOPPED→STARTING; `drive_start`
needs RPM sustained ≥ `driveStartDurationSeconds`, which requires the *regular*
poll loop to keep reading RPM. So any fix must un-mask ongoing RPM polling, not
just the one probe.

## Why this needs the live Pi (the undetermined part)

The fix hinges on questions only answerable at runtime on the car:

- Does the live query backend go through real python-obd (`obd.query`, `force`
  semantics, one-shot `supported_commands`) or through a project facade that
  behaves differently?
- Will forcing a re-probe of `supported_commands` at engine-on actually
  re-interrogate the now-powered ECU over the 2G K-line, or return the same cached
  set? (python-obd does not re-interrogate on a plain re-read.)
- Is `obd.query(cmd, force=True)` viable/reliable on this ELM327 + 2G K-line, or
  does it produce garbage for genuinely-unsupported PIDs?

A fix built on the wrong answer is a silent no-op (worst case for a verify-first
story). Hence: confirm on the Pi first.

## Live-Pi repro + evidence the CIO's bench run should capture

1. Power the Pi with the car key OFF (ECU dark); let the collector connect.
   `journalctl -u <collector>` should show `Supported-PID probe | discovered=<small N>`.
2. Start the engine. Watch for:
   - `Engine-on detected via BATTERY_V > 13.80V sustained 3 samples` (escalation fired — good).
   - `Engine-on escalation: RPM probe failed:` **or** a null/`not supported` line for RPM (the residual miss — this confirms mechanism).
   - Absence of `DRIVE STARTED` and of `FORENSIC drive_state_transition | to=running`.
3. Grep tokens: `journalctl -u <collector> | grep -E "Supported-PID probe|Engine-on|RPM probe failed|DRIVE STARTED|FORENSIC drive_state_transition"`.
4. Confirm no `connection_log` `drive_start` row for that key-on, and `realtime_data`
   RPM rows NULL/absent while BATTERY_V keeps ticking.

If the trace shows RPM null-masked after engine-on despite the escalation firing,
the python-obd `supported_commands` root cause is confirmed and the fix direction
below (B or C) is safe to build.

## Proposed resolution (fix options — Atlas to rule after the bench confirm)

- **(A) Refresh `supported_commands` on escalation.** Force python-obd to
  re-interrogate the (now-powered) ECU support bitmap when the alternator signature
  fires, so RPM un-masks for the probe AND ongoing polls. Correct-by-intent;
  depends on a python-obd API that truly re-probes (needs live confirm).
- **(B) Force the escalation probe + un-mask ongoing RPM polls** (`force=True` /
  bypass the support cache for RPM once engine-on is confirmed). Needs live confirm
  that forced 2G K-line reads are clean.
- **(C) Alternator-active as a first-class drive_start signal** (mint drive_id +
  drive_start on the confirmed engine-on signature, independent of whether RPM ever
  un-masks). Most robust, but this is arguably a *re-design* the AC's "do NOT
  re-solve" clause discourages, and it interacts with drive_summary defer-INSERT
  (no-RPM start) + the foreign-guard — Atlas call required.

All three preserve US-388's close-guarantee and the drive_id NULL-latch (guardrail
a): none touch `evaluateTimeouts` / `_maybeCloseOnDeadline` / `_openDriveId` gate.
This finding should fold into the A-9 IRL re-gate (guardrail b) as another
drive-lifecycle failure to exercise.

## Impact

US-432 only. Sprint 53 stories US-433..440 are independent and remain auto-doable;
Ralph proceeds to the next available story. US-432 resumes as a follow-up once the
CIO's bench run disambiguates the mechanism and Atlas rules the fix direction.

## Attempted Solutions

Full static trace of the escalation → probe → query → support-cache path (see Root
cause). Ruled OUT the `_assertPidSupported` / `SupportedPidSet` clear as a fix (RPM
bypasses that gate). No speculative code shipped — deliberately, per verify-first.

## Resolution

[Fill in when resolved] Bench trace confirms the masking mechanism; Atlas rules
fix direction (A/B/C); follow-up story implements + unit-tests + IRL re-gates.
