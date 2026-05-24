---
name: PM validates CLI fixes in CIO's actual shell context (Windows / no env vars / fresh subprocess)
description: When validating Python CLI fix stories (rename + sys.path + entry-point bugs), the IRL gate MUST include running from CIO's actual usage context, not just the path PM knows works. I-020 surfaced because V0.27.3 US-312 was validated server-side only with PYTHONPATH explicit; never tested from CIO's local Windows shell with no env vars set.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
When validating a CLI fix, the real-world gate must execute from CIO's actual usage context. PM-only validation paths (server-side SSH with explicit env vars, IDE-launched subprocess inheriting parent env) miss bugs that only surface from a fresh shell with no env vars set.

**Why**: I-020 (calibration.py ModuleNotFoundError 'src') surfaced 2026-05-10 AFTER V0.27.3 shipped US-312 (which closed I-018 layers 1+2 and was claimed CIO-validated). PM had run `DATABASE_URL=... PYTHONPATH=/mnt/projects/O/OBD2v2 .../bin/python src/server/analytics/calibration.py --calibrate --apply` on chi-srv-01 + got clean exit. Marked validated. CIO ran `python src/server/analytics/calibration.py --calibrate --apply` from local Windows shell -- crashed at line 58 with `ModuleNotFoundError: No module named 'src'`.

PM's validation path (PYTHONPATH explicit, server-side venv, server-side cwd) was a SUBSET of CIO's actual usage. Bug only surfaced in the CIO context.

**Rule (apply at every CLI fix story acceptance)**:

1. **PM IRL validation MUST include the CIO usage context.** If CIO will run the CLI from local Windows shell with no env vars, validate from local Windows shell with no env vars. Don't substitute "the path PM knows works" for "the path CIO actually uses."
2. **For CLI stories, the verification command list MUST include a fresh-subprocess invocation** that explicitly clears PYTHONPATH + uses CIO's working directory pattern. e.g.:
   ```python
   import subprocess
   env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH',)}
   result = subprocess.run(['python', script_path], env=env, cwd=repo_root)
   assert result.returncode == 0
   ```
3. **For sys.path / packaging fixes specifically**: invoke the script from a fresh shell ON THE TARGET OS where the user runs it. WSL / git-bash / cmd.exe / PowerShell all have different env-inheritance + python-resolution behavior on Windows.
4. **For story acceptance criteria**: include explicit "CIO can run `<exact command>` from `<exact shell>` with `<exact env state>`" -- not just "CLI runs to completion."

**Anti-patterns this rule prevents**:
- I-020 class: PM validates server-side; CIO usage path is local; bug only manifests in CIO usage path
- "WORKS ON MY MACHINE" framing: PM environment is more permissive than CIO environment; permissive-env validation hides bugs
- Story closure with incomplete IRL gate: marking US-312 passes:true after server-side validation only, when the CIO usage path was the actual user-facing acceptance

**When to skip**:
- Story is server-side-only by design (e.g., a deploy-script change; no CIO-shell invocation expected)
- The CLI is invoked via wrapper/shim by another script, not directly by user
- Acceptance is fully behavioral (no entry-point shape change) -- e.g., a SQL UPDATE in a SELECT query that runs through fastapi's existing path

**Cross-references**:
- I-018 (V0.27.3 US-312 closed layers 1+2) -> I-020 (V0.27.4 candidate, layer 3 surfaced via incomplete validation gate)
- `feedback_pm_verify_diagnostic_premises.md` -- companion: PM verifies expert-supplied diagnostic premise; this rule extends to PM verifying its own validation paths against CIO usage
- `feedback_pm_run_pre_flight_during_grooming.md` -- companion: pre-flight discipline catches grooming-time premise gaps; this rule is the post-implementation analog catching validation-time path gaps
