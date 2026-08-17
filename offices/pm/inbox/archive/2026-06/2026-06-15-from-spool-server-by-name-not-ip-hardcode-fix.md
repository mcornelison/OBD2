# Server address hardcoded as IP — sync is broken; fix to resolve by NAME + standing no-hardcode rule

**Date**: 2026-06-15
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (data pipeline down — CIO directive)

## Context

CIO moved chi-srv-01's IP from **10.27.27.10 → 10.27.27.120** today. That single change broke the data pipeline because the server address is **hardcoded as a literal IP** in config instead of being reached by name.

**Operational impact right now:** the Pi pushes drives to `config.json → pi.companionService.baseUrl`, which is pinned to the dead `http://10.27.27.10:8000`. So **the Pi can't sync.** The server's last data is **Drive 27 (2026-06-06)** — `MAX(drive_id)=27`, zero realtime rows after, last sync `2026-06-06 01:10`. CIO has taken **several drives since** and reported a **check-engine light** on the latest one; all of that telemetry (and the stored DTC) is **stranded on the Pi's local DB**, invisible to the server, until the sync target is fixed and the Pi is back online. My own DB tooling only worked tonight by overriding `PROD_DB_HOST=...@10.27.27.120` by hand.

## CIO Directive (relay)

1. **Fix this so the server is reached by NAME, not IP.** Pick a durable resolution path so the next IP change doesn't break anything (mDNS `chi-srv-01.local`, a DHCP reservation, or LAN DNS — route the *how* through Atlas; that's an architecture call). Then **update the Pi's config and redeploy** so sync resumes.
2. **Standing rule — never hardcode numbers or values that can change.** Server addresses, ports, IPs, thresholds — anything mutable lives in a **config file**, not baked into code/scripts. CIO wants this reinforced as a discipline, not just patched this once.

## Exact blast radius (grep from repo root)

| File / line | Current | Should be |
|---|---|---|
| `config.json:453` `pi.companionService.baseUrl` | `http://10.27.27.10:8000` | by name (this is the one breaking **sync**) |
| `config.json:534` `server.network.serverHost` | `10.27.27.10` | by name |
| `config.json:539` `server.network.serverBaseUrl` | `http://10.27.27.10:8000` | by name |
| `config.json:537` `server.network.serverHostname` | `chi-srv-01` | **already correct — but nothing consumes it** |
| `deploy/addresses.sh:40` | `SERVER_HOST="${SERVER_HOST:-10.27.27.10}"` | default to name |
| `.env.production.example:144` | `OLLAMA_BASE_URL=http://10.27.27.10:11434` | by name |
| `tests/server/*` (4 fixtures) | `serverHost='10.27.27.10'` | stale literals — update with the rename |

Note the smell: `config.json` already carries `serverHostname: chi-srv-01` (537) sitting right beside three hardcoded IPs that are what's *actually consumed*. The name field is decorative today. The fix is to make the consumed URLs resolve `chi-srv-01` (or `.local`) and retire the literal IPs.

## This is already on your backlog

Maps directly to the existing Feature **`backlog.json:1014` — "Pi + server hostname resolution cleanup (`chi-eclipse-01` / `chi-srv-01` LAN-wide)"**, and overlaps the **B-044 hardcoded-`chi-srv-01` lint debt**. This isn't net-new scope — it's a "pull it forward, the IP move just made it urgent" call. The Pi-config edit + redeploy is the Pi-dev/deploy lane; the resolution design is Atlas's.

## Why I'm flagging instead of fixing

Config + deploy is outside my tuning lane (per my charter I don't touch configs or deploy to Pi/server), and this touches shared `config.json` + a Pi redeploy — your integration lane, not mine to hack mid-session. I mapped the blast radius so you've got a head start. Ping me if you want the engine/data-side acceptance check once sync is restored — I'll confirm the stranded drives + the CEL code land clean.

— Spool
