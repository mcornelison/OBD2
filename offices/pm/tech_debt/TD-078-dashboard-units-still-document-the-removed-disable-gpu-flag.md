# TD-078 — dashboard kiosk units still document the removed `--disable-gpu` flag

| | |
|---|---|
| **Found by** | Ralph (Rex), during US-548 (Sprint 71 / V0.29.26) |
| **Date** | 2026-08-10 |
| **Severity** | Low — comments only, no runtime effect |
| **Owner** | US-536's lane (PM-landed) |

## What

US-536 (`3e67e5d`) removed `--disable-gpu` from the `ExecStart` of both kiosk
units, but left the multi-paragraph rationale block that argues **for** the flag:

- `specs/UI/dist/dashboard-pi/dashboard.service.x11` — lines 19–45
  ("US-522 (F-124) -- `--disable-gpu`: … WHY `--disable-gpu` AND NOT
  `--disable-gpu-rasterization`…")
- `specs/UI/dist/dashboard-pi/dashboard.service.wayland` — lines 24–39
  ("see the full rationale in the .x11 sibling")

Both now describe a flag their own `ExecStart` no longer carries, and neither
mentions disposition B or US-536.

## Why it is worth fixing rather than shrugging at

A reader who greps these units for the GPU story finds a confident, live-grounded
argument to add `--disable-gpu` and nothing recording that the CIO **rejected**
it. The next freeze investigation is exactly when someone will read this file,
and the comment as written is an invitation to reopen a settled decision.

The x11 header also states `--disable-gpu` was verified live on the composed
cmdline — true when written, false of what now deploys.

## Not a test problem

US-548's guards are unaffected: `_execStartFlags` strips comments before matching
(and its self-test pins that a comment can neither satisfy nor trip the guard).
So this is documentation drift only — which is *why* it needs a human edit rather
than a failing test to force it.

## Suggested fix

Replace both rationale blocks with a short disposition-B note: the freeze RCA
still stands, the chosen remedy is now auto-rotate-off (US-536 AC-2) plus US-537's
animation gating, and `--disable-gpu` was deliberately **not** adopted. Keep the
`/etc/chromium.d` precedence paragraph — it is still true and still load-bearing
(the OS injects `--enable-gpu-rasterization` and the repo cannot manage it).

## Scope note

Not fixed inline. US-548's fence is the three RED guard tests, and these unit
files are US-536's lane (already `passes: true`). Filed per the drift-observation
rule rather than edited quietly.
