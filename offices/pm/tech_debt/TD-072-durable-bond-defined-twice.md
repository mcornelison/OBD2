# TD-072: "Durable bond" is defined in two modules

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | code                      |
| Affected     | `src/pi/obdii/bluetooth_helper.py` (`parseBondState` / `isDurableBond` / `BondState`), `scripts/pair_obdlink_driver.py` (`parseBondState` / `isDurableBond`) |
| Introduced   | 2026-08-02, US-512 — the runtime half of the durable-bond check needed the same rule the pairing driver already held, and consolidating meant editing a live P0 hotfix script |
| Created      | 2026-08-02                |

## Description

The rule "a bond is durable iff Paired AND Bonded AND Trusted" — plus the
`bluetoothctl info` parser that feeds it — now exists in two places:

- `scripts/pair_obdlink_driver.py` decides it at **pair time** (returns a `dict`).
- `src/pi/obdii/bluetooth_helper.py` decides it at **connect time** (returns a
  frozen `BondState` dataclass), added by US-512.

Two independent definitions of one fact is the cross-module enum-identity
drift class that cost the 9-drain saga (V0.24.1).

## Why It Was Accepted

Consolidating requires the pairing driver to import from `src/`, and the driver
is deliberately standalone: `pair_obdlink.sh` invokes it as
`python3 scripts/pair_obdlink_driver.py`, so `sys.path[0]` is `scripts/` and a
`from src.pi...` import fails unless the caller happens to be in the repo root.
Making it work needs a `__file__`-relative `sys.path` bootstrap in a script
whose failure mode is *stranding the car* (no re-pair without the dongle
powered, i.e. engine running). That is not a change to make as a side-effect of
a capture-hardening story.

Mitigation shipped instead: the two definitions are pinned against each other
across the whole 8-row truth table by
`tests/pi/obdii/test_bluetooth_bond_and_reset.py::TestBondVocabularyMatchesThePairingDriver`.
Drift now fails loudly at test time rather than silently in the field.

## Risk If Not Addressed

**Low likelihood, low impact given the mitigation.** The cross-check test makes
a silent divergence impossible; the residual cost is that a future change to
the rule must be made twice, and the parsers (ANSI stripping, flag regexes)
could still diverge on a bluez output-format change without the truth-table
test noticing — it compares verdicts, not parsing.

## Remediation Plan

Add a `__file__`-relative `sys.path` bootstrap to `pair_obdlink_driver.py`,
re-export `parseBondState` / `isDurableBond` from `bluetooth_helper`, and keep
the cross-check test (it becomes trivially true, which is the point). Verify
with the existing `tests/pi/obdii/test_pair_obdlink_driver.py` transcript
replay, and re-run the driver on the Pi before closing — the script's failure
mode is operational, not just a red test.
