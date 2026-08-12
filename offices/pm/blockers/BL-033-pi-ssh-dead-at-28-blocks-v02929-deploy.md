# BL-033 — Pi SSH dead (pings at .28, port 22 refused) blocks the V0.29.29 deploy

| | |
|---|---|
| **Raised by** | Marcus (PM), during `/sprint-deploy-pm` for Sprint 74 / V0.29.29 |
| **Date** | 2026-08-12 |
| **Blocks** | The Pi tier of the **V0.29.29** deploy (Phase 6–7). Also blocks the on-Pi legibility validation (`/sprint-validated`) and, downstream, `/chain-validated` (V0.29 → main). |
| **Severity** | **HIGH** — the sprint is merged + versioned on `dev` but cannot reach the hardware; the whole sprint is Pi-side. |
| **Owner** | **CIO** (physical diagnostics — moving the Pi to the inside office bench). |
| **Status** | Open — CIO diagnosing on the bench. |

## Symptom

- `10.27.27.28` **responds to ping** but **refuses TCP port 22** ("Connection refused" = a TCP reset, host up, nothing listening on 22). Verified: 4× TCP-22 probes + 2× `ssh` over ~45s after a CIO reboot — still refused.
- `10.27.27.100` and `10.27.27.9` (the other two flap addresses) **do not ping at all**. `chi-eclipse-01` hostname does not resolve.
- CIO reboot did not restore SSH. CIO assessment: "That is an issue. I will need to move it to the inside office bench for diagnostics."

## Reading

"Connection refused" (not "timed out") means a device is answering at `.28` but no sshd is listening. Two candidates: (a) `.28`'s DHCP lease now belongs to a *different* device and the Pi is elsewhere/off-network; or (b) the Pi is at `.28` but sshd did not start (kiosk boot, disabled unit, or a deeper fault). Bench diagnostics will disambiguate.

## What is NOT blocked

V0.29.29 is fully closed out on `dev`: PR #15 merged (`f268ac7`), RELEASE_VERSION bumped to V0.29.29 (`4922e02`), sprint archived, backlog + tracking updated. **Server deploy intentionally not run** — this sprint has zero server-runtime changes (all Pi dashboard assets + deploy scripts + PM tooling), so a server-only deploy would ship nothing functional and split versions. Deploy both together when the Pi is back.

## Resume path (one command each, once SSH answers)

1. Confirm the Pi's real IP on the bench: `hostname -I`; confirm sshd: `sudo systemctl status ssh` (→ `enable --now ssh` if down).
2. If the address changed, update `deploy/deploy.conf` `PI_HOST`.
3. `bash deploy/deploy-pi.sh` then `bash deploy/deploy-server.sh` from `dev` → Phase 7 verify → `/sprint-validated` after the in-car legibility read.

## Durable fix

This is the **third address-flap this session**. The standing durable fix is **B-102 / US-473** (static DHCP reservation + stable hostname for the Pi), which ends the probe-all-three-addresses guessing. Deferred; re-surface to CIO after the bench diagnostics resolve the SSH fault.
