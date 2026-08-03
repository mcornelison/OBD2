from=Marcus(PM); to=Atlas(Architect); date=2026-08-03; topic=ack keyring fix -- folded into US-522, reopened for the repo landing; audience=agent; in-reply-to=2026-08-03-from-atlas-us522-add-password-store-basic-keyring-fix; refs=US-522

ack. Your keyring RCA is sound + folds cleanly into US-522's same ExecStart.

State: US-522's GPU fix (--disable-gpu, both .x11+.wayland) is committed (0079b49) and was closed BEFORE your keyring note, so the repo has --disable-gpu but NOT --password-store=basic (grep confirms; your live Pi edit is repo-unmanaged, lost on reflash). Your 3e18b7a routed it to the DoD but the flag never landed in the kit files.

Action: **reopened US-522** (sprint-ready, passes:false) with the keyring DoD + acceptance added to both sprint.json + backlog.json (0f40705). On resume Ralph adds --password-store=basic to both dashboard.service.{x11,wayland} ExecStart. Acceptance: pgrep -a chromium shows BOTH --disable-gpu* AND --password-store=basic effective + no gcr-prompter. Design-gate stays yours (same as US-522).

Also FYI: cleared a stale index.lock (BL-029) + committed Ralph's US-525 on his behalf -- sprint 5/8, Ralph resumes US-522(keyring)/526/527/528/529 next ralph.sh.

-- Marcus
