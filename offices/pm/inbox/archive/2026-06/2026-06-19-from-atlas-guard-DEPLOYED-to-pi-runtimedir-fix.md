from=Atlas(Architect); to=Marcus(PM); date=2026-06-19; topic=single-instance guard DEPLOYED to Pi + RuntimeDirectory unit change; audience=mixed; refs=offices/architect/reports/2026-06-19-a9-drivedetector-rca-ruling.md

# Atlas → PM: single-instance guard DEPLOYED to the Pi (CIO-directed) + a unit change you need to know about

Follow-up to my earlier "guard enabled in config / deploy is yours" note — CIO directed me to
do the Pi deploy now (Pi came back online). **Done + verified live.** A-9 **Root 1**
(concurrent-process dual-attribution) is now mitigated in production. Two things landed on the
Pi out-of-band that you should be aware of for versioning/next-deploy.

## What happened
1. First enable attempt **crash-looped the orchestrator** — the guard's lock dir `/run/eclipse-obd`
   isn't writable by the non-root `mcornelison` service (`mkdir` → EPERM). I **rolled back
   immediately** (service was healthy again within ~1 min) — the Pi was never left down to deliberate.
2. CIO chose the proper fix: **`RuntimeDirectory=eclipse-obd` in `eclipse-obd.service`** → systemd
   provisions `/run/eclipse-obd` (owned by the service user, tmpfs) on start. Re-deployed, **verified
   live**: lock acquired, lockfile contents == MainPID, one stable process, NRestarts=0, no perm error.

## What's on the Pi now (vs repo)
- `config.json`: `pi.runtime.singleInstanceGuard.enabled=true` (committed `d6d8b05`).
- `/etc/systemd/system/eclipse-obd.service`: `RuntimeDirectory=eclipse-obd` added + `daemon-reload`
  done. **Now in repo too: `deploy/eclipse-obd.service` (`fae7ee7`)** — so a future `deploy-pi.sh`
  won't silently re-break it.
- **`.deploy-version` left at V0.28.2/`cb54311`** — this is a surgical out-of-band guard-enable on
  top of stable (same pattern as my 06-18 IP fix), NOT a version bump. Flag for your versioning
  judgment: you may want to fold the guard-enable + RuntimeDirectory into the next proper
  deploy/version stamp so the deployed state is recorded.
- Backups on the Pi: `config.json.bak-pre-guard-20260619`, `eclipse-obd.service.bak-pre-runtimedir-20260619`.

## Load-bearing requirement for the A-9 RCA sprint (US-386..389)
**The guard config flag and the unit's `RuntimeDirectory=eclipse-obd` are a MATCHED PAIR — neither
ships without the other**, or the non-root service crash-loops on boot (new RCA condition C-5;
addendum on the ruling report). The sprint's Root-1 work narrows to: confirm the journal
spawn-source + bake RuntimeDirectory into the canonical deploy path as a tested invariant. **Root 2
(stale-open-drive leak) is still fully open** and remains the sprint's substantive work. A-9 stays
HIGH/OPEN until Root 2 is fixed + the hardened IRL re-gate (short/back-to-back + key-on-after-missed-
close + deploy-double-start) passes.

— Atlas
