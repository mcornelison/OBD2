from=Atlas(Architect); to=Ralph(Dev); date=2026-07-31; topic=Fix scripts/pair_obdlink.sh -- it can't pair (CIO-directed, P0); audience=agent; refs=BL-025,A-17,A-18

# Task (CIO-directed): fix `scripts/pair_obdlink.sh` so it actually pairs the OBDLink LX + writes a durable bond

## Why
`pair_obdlink.sh` is the hands-free Pi↔dongle pairing tool. **It is broken and cannot pair** — confirmed live this session (I ran it on the Pi; it hung with "Agent registered" then died with a `pexpect.exceptions.TIMEOUT`, searcher `re.compile('\\[.+\\]#')`). A durable bond that survives reboot is the second half of getting OBD capture working on real drives (the radio-unblock we fixed tonight is the first half).

## Bug 1 (DEFINITE — this is why it hangs): wrong prompt regex
The embedded pexpect driver waits for a bluetoothctl prompt ending in **`#`**:
- `scripts/pair_obdlink.sh:215` — `child.expect(r"\[.+\]#", timeout=10)` (inside `send()`)
- `:219` — first-prompt wait
- `:263` — post-pair prompt wait

But the Pi's current bluetoothctl (Trixie/bluez) prompts with **`>`**, not `#`: `[bluetoothctl]>`, and `[OBDLink LX]>` after it selects the device. So every `expect(r"\[.+\]#")` **times out on the first command** and the script never reaches `pair`/`trust`.
**Fix:** make the prompt regex match the current prompt. Recommend a version-tolerant, ANSI-safe pattern (bluetoothctl wraps the prompt in color escapes, and `\[.+\]` can mis-match the `\x1b[0;94m` codes). Options: match `\[[\w -]+\][#>]` (accept `#` or `>`, restrict the bracket body so ANSI `[0;94m` doesn't get captured), or strip ANSI before matching, or drive bluetoothctl with `--` piped commands + explicit sleeps instead of prompt-matching (more robust than pexpect prompt-chasing — your call). Verify against the real `bluetoothctl` on the Pi.

## Bug 2 (agent ↔ confirm-logic mismatch): use a display-capable agent
- `:221` registers `agent NoInputNoOutput` (the "just-works" pairing mode).
- But `:232-250` waits for and answers a `"Confirm passkey NNNNNN (yes/no):"` prompt with `yes` — which **only appears with a display-capable agent** (`DisplayYesNo`/`KeyboardDisplay`). With `NoInputNoOutput` that prompt never fires, so the confirm branch is dead code, and the OBDLink LX's SSP can auth-fail (I hit `org.bluez.Error.AuthenticationFailed` with just-works). The **phone** pairs because it uses a display-capable agent.
**Fix:** register `agent DisplayYesNo` (or `KeyboardDisplay`) so the passkey-confirm dance the script already codes actually runs and a proper SSP bond completes. (NOTE: don't repeat the earlier "NoInputNoOutput writes no key" claim — it *does* write a key; the real issues are the prompt regex + the agent/confirm mismatch.)

## Acceptance
Split, because full pairing needs the dongle **powered (engine on) + in pair mode (solid blue LED)**:
- **Bench-testable now:** the pexpect/driver logic advances past the prompt (unit-test the driver against a recorded/mock bluetoothctl transcript that uses the real `[bluetoothctl]>` / `[OBDLink LX]>` prompts + a `Confirm passkey` line); `--dry-run` still works; ruff/shellcheck clean.
- **Engine-on (coordinate with CIO/Spool):** `bash scripts/pair_obdlink.sh 00:04:3E:85:0D:FB` runs to `--- pair + trust successful ---`; then `bluetoothctl info 00:04:3E:85:0D:FB` shows `Paired: yes / Bonded: yes / Trusted: yes`; and **crucially the bond SURVIVES a reboot** (still Bonded/Trusted after `sudo reboot`) — that's the durability requirement (Spool's fix path). `scripts/verify_bt_pair.sh` passes.

## Notes
- Pair against the correct MAC only: **`00:04:3E:85:0D:FB`** ("OBDLink LX"). Ignore the stranger's `00:1D:A5:…` "OBDII".
- This composes with the radio-unblock fix (BT must be unblocked first — done tonight, being baked into deploy separately).
- Hotfix-class, CIO-directed (like the rfkill-unblock + A-17 + US-500). Marcus owns the version bump.
- Spool owns the engine-on bond verification + the capture-drive acceptance.

— Atlas
