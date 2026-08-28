#!/usr/bin/env python3
# ==============================================================================
# File:        tools/pm/us618_apply_command_doc_fix.py
# Purpose:     ONE-SHOT -- apply the US-618 chain-TIP gating correction to the
#              two slash-command docs under .claude/commands/.
# Author:      Claude (Ralph / Rex)
# Created:     2026-08-28
# Copyright:   (c) 2026 Eclipse OBD-II Project. All rights reserved.
# ==============================================================================
# Why this script exists instead of the edit itself
# -------------------------------------------------
# US-618 corrects a false claim -- that the chain merge is gated on EVERY sprint
# in a V0.X chain carrying a `validatedAt` stamp, when the gate is the chain TIP
# alone -- across four files. Two were writable and are already corrected in the
# same commit as this script (tools/pm/README.md and the module docstring of
# chain_validate_aggregate.py). The other two live under `.claude/`, and the
# agent harness blocks writes there: command and hook definitions change what
# executes, so they sit behind an explicit human approval that a headless Ralph
# session cannot obtain. Routing around that boundary with a shell write was not
# an acceptable option, so the edit is packaged here instead of being re-typed
# by whoever applies it.
#
# DELETE THIS FILE once it has been applied and the lint is green. It is a
# migration, not a tool.
#
#     python -m tools.pm.us618_apply_command_doc_fix --commands-dir .claude/commands --check
#     python -m tools.pm.us618_apply_command_doc_fix --commands-dir .claude/commands
#     python -m pytest tests/lint/test_chain_gate_docs_match_the_tool.py -q
#
# The replacements were verified before hand-off by applying them to COPIES of
# both documents and scanning the result with the shipped lint's own patterns
# (not a re-typed copy of them): 10/10 applied, 0 banned wordings remaining, all
# four US-618 acceptance checks green, and both controls -- the CIO "fully
# functional working" confirmation and the CIO-confirms clause -- still present.
#
# Every replacement asserts its target appears EXACTLY ONCE before substituting,
# so a drifted file fails loudly rather than being half-patched. Re-running after
# a successful run reports ALREADY APPLIED and writes nothing.
# ==============================================================================
"""One-shot: apply the US-618 chain-TIP gating correction to .claude/commands/."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CHAIN_DOC = "chain-validated.md"
SPRINT_DOC = "sprint-validated.md"

# (filename, old, new) -- `old` must occur exactly once, and must NOT survive
# inside `new` (see the idempotence assertion in main()).
REPLACEMENTS: list[tuple[str, str, str]] = [
    # -- chain-validated.md :15 -- the command table's "When" column ------------
    (
        CHAIN_DOC,
        "| After every sprint in the chain has `/sprint-validated` run + CIO "
        "confirms whole chain green |",
        "| After the CHAIN-TIP sprint has `/sprint-validated` run + CIO confirms "
        "the whole chain works IRL |",
    ),
    # -- chain-validated.md :17-22 -- WHEN to run / WHEN NOT to run -------------
    (
        CHAIN_DOC,
        "**WHEN to run**: every sprint in a V0.X chain has `validation.validatedAt`\n"
        "populated on `dev` (each had its own `/sprint-validated`) AND CIO explicitly\n"
        "confirms the chain is \"fully functional working\" + ready to merge to main.\n"
        "\n"
        "**WHEN NOT to run**:\n"
        "- Any sprint in the chain still has `validatedAt: null` (chain INCOMPLETE)\n",
        "**WHEN to run**: the CHAIN-TIP sprint -- the highest patch version in the\n"
        "V0.X chain -- has `validation.validatedAt` populated on `dev` (it had its\n"
        "own `/sprint-validated`) AND CIO explicitly confirms the chain is \"fully\n"
        "functional working\" + ready to merge to main.\n"
        "\n"
        "> ### The gate is the chain TIP alone\n"
        ">\n"
        "> **Earlier patches in the chain keep `validatedAt: null`, and that is the\n"
        "> EXPECTED state -- not a debt, not a backlog, not something to go and\n"
        "> clear.** Under the CIO 2026-05-23 chain-end-merge rule each patch is\n"
        "> superseded by the next and is never re-validated on its own; the chain\n"
        "> validates as a whole, at its tip.\n"
        ">\n"
        "> The gate is one line, and it -- not this document -- is the source of\n"
        "> truth. `tools/pm/chain_validate_aggregate.py:238`:\n"
        ">\n"
        "> ```python\n"
        "> chainStatus = \"READY\" if chainTip and chainTip[\"validatedAt\"] else \"INCOMPLETE\"\n"
        "> ```\n"
        ">\n"
        "> `unvalidatedSprints` still lists every null stamp it finds, but that list\n"
        "> is informational and does NOT gate -- same file, `:188`.\n"
        ">\n"
        "> **Why this section is worded so emphatically (US-618).** Until 2026-08-28\n"
        "> four lines of this document said the opposite: that a `validatedAt: null`\n"
        "> anywhere in the chain left it INCOMPLETE and blocked the merge. The tool\n"
        "> had been corrected to the chain-end-merge rule; this file never was. The\n"
        "> PM read it, reasonably believed it, and groomed the whole of Sprint 76\n"
        "> around clearing a 27-sprint validation-ledger \"debt\" that does not exist\n"
        "> and has never blocked a merge. If you are about to soften this wording,\n"
        "> that is the outcome it exists to prevent.\n"
        "\n"
        "**WHEN NOT to run**:\n"
        "- The CHAIN-TIP sprint still has `validatedAt: null` -> `chainStatus:\n"
        "  INCOMPLETE`. (Earlier patches sitting at null is normal and does NOT\n"
        "  block the merge -- see the box above.)\n",
    ),
    # -- chain-validated.md :77 -- Phase 1 stop conditions ----------------------
    (
        CHAIN_DOC,
        "- Sprints in chain = 0 -> wrong --chain prefix; abort\n"
        "- chainStatus = INCOMPLETE -> at least one sprint lacks `validatedAt`;\n"
        "  run `/sprint-validated` on that sprint first",
        "- Sprints in chain = 0 -> wrong `--chain` prefix; abort. Note this ALSO\n"
        "  reports `chainStatus: INCOMPLETE`, with `chainTipVersion: null` -- read\n"
        "  `chainTipVersion` to tell an empty chain from an unvalidated tip.\n"
        "- chainStatus = INCOMPLETE with a non-null `chainTipVersion` -> the\n"
        "  CHAIN-TIP sprint has no `validatedAt`; run `/sprint-validated` on the TIP\n"
        "  first. `unvalidatedSprints` may also name earlier patches: informational\n"
        "  only, never a gate (`chain_validate_aggregate.py:188`).",
    ),
    # -- chain-validated.md :91 -- the strict-gate comment ----------------------
    (
        CHAIN_DOC,
        "# Strict gate -- exit 1 if any sprint lacks validatedAt",
        "# Strict gate -- exit 1 if the CHAIN TIP lacks validatedAt (or the chain\n"
        "# is empty). Earlier patches at validatedAt: null do NOT fail this.",
    ),
    # -- chain-validated.md :260 -- stop-condition flowchart --------------------
    (
        CHAIN_DOC,
        "| 2 | `--strict` exits 1 (INCOMPLETE) | Run `/sprint-validated` on "
        "missing sprint(s); re-run |",
        "| 2 | `--strict` exits 1 (INCOMPLETE) | Chain TIP unvalidated -> run "
        "`/sprint-validated` on the TIP; re-run. If `chainTipVersion` is null "
        "instead, the chain is empty -> wrong `--chain` prefix |",
    ),
    # -- chain-validated.md :275-277 -- workflow rationale ----------------------
    (
        CHAIN_DOC,
        "workflow). `/sprint-validated` stamps each sprint's validation on dev + bumps\n"
        "the regression manifest. `/chain-validated` consummates the chain merge once\n"
        "every sprint in the chain has its stamp AND CIO confirms whole-chain green.",
        "workflow). `/sprint-validated` stamps a sprint's validation on dev + bumps\n"
        "the regression manifest. `/chain-validated` consummates the chain merge once\n"
        "the CHAIN-TIP sprint has its stamp AND CIO confirms whole-chain green.\n"
        "Earlier patches are superseded by later ones and are never individually\n"
        "re-validated -- their `validatedAt: null` is the expected steady state, not\n"
        "a debt (US-618).",
    ),
    # -- chain-validated.md -- Related: name the source of truth ----------------
    # NOTE the renamed leading token. The obvious phrasing would leave the
    # original bullet as a PREFIX of the replacement, so `old` would still be
    # present after substitution, the "already applied?" test could never be
    # satisfied, and the entry would re-apply on every run and nest itself.
    # Caught by an idempotence probe; guarded structurally in main().
    (
        CHAIN_DOC,
        "- `chain_validate_aggregate.py` -- Phases 1 + 2 (enumerate + status)",
        "- `chain_validate_aggregate.py:238` -- Phases 1 + 2 (enumerate + status).\n"
        "  That line IS the gate expression and this document's source of truth;\n"
        "  `:188` documents `unvalidatedSprints` as informational, not a gate.",
    ),
    # -- sprint-validated.md :8 ------------------------------------------------
    (
        SPRINT_DOC,
        "`/chain-validated` does that at chain end (after every sprint in the V0.X "
        "chain has its own `/sprint-validated` stamp AND CIO confirms whole-chain "
        "green).",
        "`/chain-validated` does that at chain end (after the CHAIN-TIP sprint has "
        "its `/sprint-validated` stamp AND CIO confirms whole-chain green -- "
        "earlier patches keep `validatedAt: null` and that is expected; "
        "`chain_validate_aggregate.py:238` gates on the tip alone).",
    ),
    # -- sprint-validated.md :163 ----------------------------------------------
    (
        SPRINT_DOC,
        "The chain merge runs once at chain end via `/chain-validated` after every "
        "sprint in the V0.X chain has its own `/sprint-validated` stamp AND CIO "
        "confirms whole-chain green.",
        "The chain merge runs once at chain end via `/chain-validated` after the "
        "CHAIN-TIP sprint has its `/sprint-validated` stamp AND CIO confirms "
        "whole-chain green. Earlier patches in the chain keep `validatedAt: null` "
        "and that is the expected state, not a debt "
        "(`chain_validate_aggregate.py:238` gates on the tip alone).",
    ),
    # -- sprint-validated.md :211 ----------------------------------------------
    (
        SPRINT_DOC,
        "The chain merge to main happens via `/chain-validated` once every sprint "
        "in the chain has its own stamp AND CIO confirms whole-chain green.",
        "The chain merge to main happens via `/chain-validated` once the CHAIN-TIP "
        "sprint has its stamp AND CIO confirms whole-chain green (earlier patches' "
        "`validatedAt: null` is expected -- see "
        "`chain_validate_aggregate.py:238`).",
    ),
]


def main(argv: list[str]) -> int:
    """Apply (or check) the US-618 command-doc replacements.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        0 on success or already-applied, 1 on drifted/ambiguous target text,
        2 on a bad path or a non-idempotent replacement table.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commands-dir", required=True, help="path to .claude/commands")
    parser.add_argument("--check", action="store_true", help="report only; write nothing")
    args = parser.parse_args(argv)

    commandsDir = Path(args.commands_dir)
    if not commandsDir.is_dir():
        print(f"ERROR: not a directory: {commandsDir}", file=sys.stderr)
        return 2

    # Idempotence is structural, not hoped for. If any `old` survives inside its
    # own `new`, the already-applied test below can never be satisfied and the
    # entry re-applies on every run, nesting the text. Assert it up front so the
    # failure lands here rather than in a mangled command doc.
    for name, old, new in REPLACEMENTS:
        if old in new:
            print(
                f"ERROR: replacement for {name} is not idempotent -- its target "
                f"text survives inside its own replacement:\n  {old[:110]!r}...",
                file=sys.stderr,
            )
            return 2

    texts: dict[str, str] = {}
    for name in (CHAIN_DOC, SPRINT_DOC):
        path = commandsDir / name
        if not path.is_file():
            print(f"ERROR: missing {path}", file=sys.stderr)
            return 2
        texts[name] = path.read_text(encoding="utf-8")

    applied, alreadyDone = 0, 0
    for name, old, new in REPLACEMENTS:
        text = texts[name]
        occurrences = text.count(old)
        if occurrences == 0:
            if new in text:
                alreadyDone += 1
                continue
            print(
                f"ERROR: {name}: target text not found and replacement not present.\n"
                f"  The file has drifted from what US-618 measured. Apply by hand.\n"
                f"  Wanted: {old[:110]!r}...",
                file=sys.stderr,
            )
            return 1
        if occurrences != 1:
            print(
                f"ERROR: {name}: target text occurs {occurrences}x, expected 1. "
                f"Refusing to guess which one.\n  {old[:110]!r}...",
                file=sys.stderr,
            )
            return 1
        texts[name] = text.replace(old, new)
        applied += 1

    if applied == 0:
        print(f"ALREADY APPLIED -- all {alreadyDone} replacements present; nothing written.")
        return 0

    if args.check:
        print(
            f"CHECK: {applied} replacement(s) would be applied "
            f"({alreadyDone} already present). Nothing written."
        )
        return 0

    for name, text in texts.items():
        # These two files ship with LF endings; newline="\n" preserves them on
        # Windows, where the default would rewrite every line to CRLF and make
        # the diff unreadable.
        (commandsDir / name).write_text(text, encoding="utf-8", newline="\n")

    print(f"Applied {applied} replacement(s) ({alreadyDone} already present).")
    print("Verify: python -m pytest tests/lint/test_chain_gate_docs_match_the_tool.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
