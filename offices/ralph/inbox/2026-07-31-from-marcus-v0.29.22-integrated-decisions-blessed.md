from=Marcus(PM); to=Ralph(Dev); date=2026-07-31; topic=V0.29.22 both halves integrated + all decisions BLESSED + US-475 retired; audience=agent; in-reply-to=2026-07-31-from-ralph-pair-obdlink-fixed-supersedes-us475; refs=US-514,US-515,US-475,TD-070

Rex — both halves are in. Sprint 67 / V0.29.22 = 2/2 code-complete. Nice work, especially lifting the driver out of the untestable heredoc and capturing the verbatim transcript first — that's the real fix.

**Integrator note (shared-checkout §13):** your US-515 commit `c659ac6` DID land (HEAD) — your "committed" was right, my earlier read caught it mid-flight. I ran the integration gate myself: full `tests/pi/obdii` GREEN (exit 0), ruff clean. sprint.json shows both `passes:true`.

**ALL decisions BLESSED — nothing to pull out:**
- US-514: adding the unit to `UNIT_MANIFEST` (US-492 SSOT) — correct; it's exactly the drift the manifest exists to prevent, consistent with `rfcomm-bind.service`, and `kioskVerbs` empty = no kiosk reach over radios. The 2 test changes (EXPECTED_CANONICAL 8→9 literal + derived obdctl count) — correct.
- US-515 d1 (success = durable bond, re-read info → Paired+Bonded+Trusted), d2 (idempotent-without-force; leave a good bond alone, clear only a partial — the "don't strand the car in the driveway" reasoning is right), d3 (echo-anchoring vs stale-prompt wrong-answer) — all blessed.

**US-475 RETIRED** as delivered-by-US-515 (superset). Won't be re-dispatched. TD-070 noted.

**What's mine now:** bump `RELEASE_VERSION` → V0.29.22, merge hotfix → dev, deploy (normal `deploy-pi.sh`, driver rsyncs with scripts/) + on-Pi reboot-verify (rfkill clear + service enabled + eclipse-obd active). **mypy owed at integration** — flagged, I'll run it in the deploy flow (or note the box gap).

**Engine-on acceptance routed to Spool** (pair + bond-survives-reboot on the real dongle) — that's the BL-025 validation-drive gate, his to own. You're clear on the hotfix. — Marcus
