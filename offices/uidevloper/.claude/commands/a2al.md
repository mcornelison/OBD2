---
description: Read, write, or compress a peer agent message in A2AL/0.4.1 (plain-text shorthand + mandatory routing header)
---

Use the `a2al` skill to handle this request.

If the user provided a path or text:
- If it's a path to a file ending in `.txt` or `.md` containing a routing header → read mode (parse header + body, summarize in plain English)
- If it's a verbose Markdown / English message → check audience first (audience rule §2.1); if agent-only → write mode (compose routing header + compress body to shorthand); if human in audience → keep as Markdown
- If it's already shorthand text with a routing header → read mode
- Otherwise → write mode (produce a header + shorthand body from the user's description)

Before writing:
- Confirm audience is agent-only (else Markdown is the right format per §2.1)
- Compose the mandatory routing header (§3): `from=<Name>(<Role>); to=<Name>(<Role>); date=<ISO>; topic=<label>` + any helpful optional fields (`audience=agent`, `urgency`, `refs`, `in-reply-to`)
- Ensure the appropriate vocabulary library files are loaded (`offices/library/core.yaml` always; add domain extensions per the skill's loading table)

If unclear, ask the user: "Reading an existing message, writing a new one, or compressing prose? And is the audience agent-only or will a human read it?"
