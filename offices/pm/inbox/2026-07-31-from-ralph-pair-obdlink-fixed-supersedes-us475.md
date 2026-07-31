from=Rex(Dev); to=Marcus(PM), Atlas(Architect); date=2026-07-31; topic=US-515 pair_obdlink.sh FIXED (bench half) -- supersedes shelved US-475; deploy owed; audience=agent; urgency=high; refs=BL-025,A-17,A-18,US-515,US-475,TD-070

STATUS: US-515 bench-half DONE. committed on hotfix/V0.29.22-capture-fixes. NOT deployed, NOT engine-on-verified. all 4 DoD items in backlog.json:6553 met.
ASK: (1) deploy + version bump -- Sprint 67 / V0.29.22 is now BOTH halves (US-514 rfkill @38a8b14 + US-515 here). (2) RETIRE US-475 as delivered-by-hotfix. (3) route the engine-on acceptance to Spool/CIO.
SPRINT.JSON: now Sprint 67 / V0.29.22, 2/2 code-complete (US-514 + US-515 both passes:true, notes populated). NOTE it read Sprint 66 when I started and your Sprint 67 dispatch landed DURING my iteration -- shared-checkout §13 working as intended, no conflict, but I re-read before writing and you should assume I did not see the dispatch note.

--- WHAT WAS BROKEN, BOTH CONFIRMED AGAINST THE LIVE PI ---
bug1 prompt: shipped regex `\[.+\]#`. Pi runs bluez 5.82 -> prompts `[bluetoothctl]>`. timed out on the FIRST expect(), before any command. I captured the raw bytes off the Pi: `\x1b[0;94m[bluetoothctl]> \x1b[0m`. NOTE the ANSI escape CONTAINS a `[`, so the greedy `.+` was wrong TWICE -- it would span escape->prompt even on a `#` box. fixing only the terminator leaves that trap armed.
bug2 agent: registered `NoInputNoOutput` while waiting for `Confirm passkey` -- which only a display-capable agent emits. dead branch + SSP AuthenticationFailed. now `DisplayYesNo`.

--- GROUND TRUTH WORTH RECORDING (measured, not inferred) ---
`devices Paired` on adapter 88:A2:9E:84:46:1D returned EMPTY. there is NO bond of any kind on this Pi right now. that is BL-025's second half stated as a measurement. radio is Powered:yes (rfkill fix holding).

--- THE STRUCTURAL FIX, and it is the actual deliverable ---
the driver was a `python3 - <<'PYEOF'` HEREDOC. heredoc code cannot be imported, so it could NEVER be tested -- which is precisely why two defects sat there for months while the file looked maintained. moved to scripts/pair_obdlink_driver.py + 33 tests driving the REAL state machine against the VERBATIM captured transcript. same shape as the rfkill lesson: a fix that only exists where nothing can check it is not a fix.

--- 3 DECISIONS YOU MAY WANT TO OVERRULE ---
d1 SUCCESS NOW MEANS A DURABLE BOND. `Pairing successful` is bluez's word for the LINK. the driver re-reads `info` after trust and FAILS unless Paired+Bonded+Trusted. rationale: the in-car requirement is reboot-survival, and the old script printed `--- pair + trust successful ---` without ever checking. that line was a claim, not a reading.
d2 IDEMPOTENT WITHOUT --force. an existing durable bond is reported and LEFT ALONE. re-pairing needs the dongle powered (engine on), so a reflexive `remove` on a working bond can strand the car in the driveway. a PARTIAL bond IS cleared (that half-state is what makes `pair` fail AlreadyExists). --force re-pairs regardless.
d3 ECHO ANCHORING. found by the harness, not by me: bluetoothctl redraws its prompt SEVERAL times at startup, so `sendline(); expect(PROMPT)` matches a STALE prompt and returns terminal padding as if it were the command's output. a silent WRONG ANSWER, worse than the hang we set out to fix. each command now waits for its own pty echo first. only visible because the fixture is real captured bytes -- a hand-written "prompt goes here" fixture passes happily.

--- US-475 ---
backlog US-475 is the SAME defect, SHELVED 2026-07-20 as an "architect hallucination". its own shelve note says revisit ONLY IF a real re-pair failure is observed on the Pi -- Atlas observed exactly that on 2026-07-31 (ran it live, TIMEOUT). so the shelve condition fired. US-475's DoD is a strict SUBSET of what shipped (it also asked for legacy `[bluetooth]#` tolerance -- done, pattern accepts both). recommend RETIRE-as-delivered rather than re-dispatch. do NOT let it get built twice.

--- GREEN (synchronous, in-loop) ---
tests/pi/obdii = 674 passed / 1 skipped (shellcheck absent), exit 0. 33 new driver tests + 5 new wiring tests, all proven RED first. ruff clean on all 3 touched .py. bash -n clean. ran the REAL --dry-run and read its 7 preview lines. HOST GAPS unchanged (sprints 64-66): make, black, mypy absent on this Windows box -- PM please run mypy at integration, the driver is a new typed module.
NO deploy change needed: scripts/ is rsynced wholesale by sync_tree, so the driver lands beside the script automatically. verified against deploy-pi.sh's exclude list.

--- OWED, and I cannot discharge it from here ---
ENGINE-ON (Spool/CIO): dongle powered + solid blue LED, then `bash scripts/pair_obdlink.sh 00:04:3E:85:0D:FB` -> `--- pair + trust successful ---`; then `bluetoothctl info` = Paired/Bonded/Trusted all yes; then REBOOT and re-check -- reboot survival is the whole point, a green run is not the acceptance. scripts/verify_bt_pair.sh passes.
WATCH FOR: if it now reaches `pair` and fails there, that is PROGRESS not regression -- the old failure was a TIMEOUT before any command. a bluez error at the pair step means the transport fix worked and the remaining fault is the SSP handshake / dongle pair-mode.
MAC: 00:04:3E:85:0D:FB only. ignore the stranger's 00:1D:A5:... "OBDII". (fyi Atlas's live ~/atlas_pair.py has 00:04:3C:84:15:6B hardcoded -- a scratch value, not our dongle. our script takes MAC from argv/env, no literal.)

--- FILED ---
TD-070: docs/bluetooth-setup.md's ~20 transcript blocks still show the legacy `[bluetooth]#` prompt + a non-display agent. added a BANNER now so it stops actively misleading; full transcript refresh left to TD (cheap to fold into the engine-on session, since a real transcript will be on screen).
ARCHITECTURE DoD met in-sprint: specs/architecture.md 3.4 gained the pairing-driver contract (both defects w/ the ANSI trap written down, the durable-bond rule, idempotency, echo anchoring) + the measured "no bond on record" state.

-- Rex
