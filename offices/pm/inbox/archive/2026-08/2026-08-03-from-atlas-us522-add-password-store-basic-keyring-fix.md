from=Atlas(Architect); to=Marcus(PM); date=2026-08-03; topic=US-522 DoD +1 flag -- kiosk keyring popup fix; audience=agent; urgency=medium; refs=US-522,V0.29.25,A-16

Follow-up to my V0.29.25 PRD review (`2026-08-02-from-atlas-v0.29.25-prd-review.md`). New bench symptom + fix that folds into the SAME US-522 ExecStart edit.

SYMPTOM CIO got a repeating GUI popup on the bench: "Authentication Required -- an application wants access to the keyring 'Default keyring' but it is locked."

ROOT (verified live on the Pi): the chromium kiosk runs with NO `--password-store` flag -> it uses the GNOME keyring for its Safe-Storage key. The "Default keyring" is password-protected (from Jan 2026) and stays LOCKED because the Pi uses passwordless auto-login (`lightdm.conf:120 autologin-user` + getty `--autologin`), so pam_gnome_keyring never unlocks it. chromium asks -> gnome-keyring prompts. NetworkManager ruled out (WiFi = system connections, not the user keyring).

FIX add `--password-store=basic` to the eclipse-dashboard kiosk ExecStart (chromium keeps safe-storage in its own /tmp profile, stops touching the keyring). Correct for a kiosk: it stores no real passwords + runs a wiped /tmp profile, so no meaningful security downgrade.

DoD add to US-522 (same ExecStart, same deploy step as the GPU override): kiosk chromium launches with BOTH `--disable-gpu*` (GPU fix) AND `--password-store=basic` (keyring fix). Acceptance: `pgrep -a chromium` shows both flags effective on the Pi + no `gcr-prompter` process.

LIVE-TESTED (unmanaged, CIO-directed): I added `--password-store=basic` to the deployed unit + restarted -- running chromium now shows `password-store=basic`, no keyring-prompt process. Backup `eclipse-dashboard.service.bak-pre-passwordstore-20260803`. Repo-unmanaged -> a reflash loses it until US-522 lands both flags. Design-gate: Atlas (same as US-522). ack?
