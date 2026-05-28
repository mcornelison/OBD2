"""Shared freeze-recipe helper for the validation-criteria-upfront contract.

Single source of truth for canonicalizing `bigDefinitionOfDone` content prior
to SHA-256 hashing. Used by:

- `prd_to_sprint.py` — writes the initial freeze hash at PRD→sprint conversion.
- `sprint_lint.py` — recomputes hash to detect drift in `lintSprintValidation`.

Per spec 2026-05-28 (CIO directive #2). Centralizing the recipe prevents
silent freeze-drift caused by the two call sites diverging.
"""


def canonicalizeBigDoD(lines: list[str]) -> str:
    """Return the canonical form of a bigDefinitionOfDone list for hashing.

    Recipe: strip each line, sort, join with '\\n'. Deterministic; whitespace
    and order do not affect the result.

    Args:
        lines: The bigDefinitionOfDone list (list of strings).

    Returns:
        Canonical multi-line string suitable for SHA-256 hashing.
    """
    return "\n".join(sorted(line.strip() for line in lines))
