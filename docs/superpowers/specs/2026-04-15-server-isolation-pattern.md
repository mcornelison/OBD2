# Server Isolation Pattern: Protecting Linux Production from Windows Development on Shared NAS

| Field | Value |
|---|---|
| **Spec ID** | server-isolation-pattern |
| **Status** | Approved |
| **Created** | 2026-04-15 |
| **Author** | External architect, captured by CIO |
| **Applies To** | Chi-Srv-01 deployment, chi-eclipse-01 deployment |

---

## The Problem

When a Linux server runs code directly from an SMB/NAS mount that Windows developers also use as their working copy, three things can go wrong:

1. **CRLF corruption** — Windows writes `\r\n` line endings. Linux bash scripts fail with `\r: command not found`. Python is tolerant but YAML/config parsers may not be.

2. **Mid-write file reads** — A git checkout or merge on Windows temporarily writes incomplete files. If the server reads a file mid-write (cron job, long-running daemon), it gets garbage.

3. **NAS outage = production outage** — If the network share drops, the server has no local copy to fall back on.

---

## The Fix (Two Layers)

### Layer 1: Kill CRLF at the Source

Add a `.gitattributes` file at the repo root:

```gitattributes
# Force LF line endings for all text files
* text=auto eol=lf

# Explicit overrides for critical file types
*.sh text eol=lf
*.py text eol=lf
*.yaml text eol=lf
*.json text eol=lf
*.service text eol=lf
*.toml text eol=lf
*.cfg text eol=lf
*.md text eol=lf
*.txt text eol=lf
*.csv text eol=lf
*.html text eol=lf
*.css text eol=lf
*.js text eol=lf

# Binary files — never touch
*.png binary
*.jpg binary
*.zip binary
*.gz binary
*.pdf binary
```

Then on every developer's Windows machine:

```bash
# Change autocrlf from 'true' to 'input'
# true  = adds CRLF on checkout (BAD — pollutes working copy)
# input = strips CRLF on commit, no conversion on checkout (GOOD)
git config core.autocrlf input

# Renormalize all existing files to LF
git add --renormalize .
git commit -m "fix: normalize all line endings to LF via .gitattributes"
```

**Why this works**: `.gitattributes` with `eol=lf` forces LF in both the repo AND the working copy, regardless of the OS. `autocrlf=input` is the safety net — even if `.gitattributes` misses a file, CRLF gets stripped on commit.

### Layer 2: Deploy Boundary (rsync snapshot)

Stop running code directly from the NAS mount. Instead, rsync to a local directory on the server.

#### Deploy Script

```bash
#!/usr/bin/env bash
set -euo pipefail

# === CONFIGURE THESE ===
SOURCE_DIR="/mnt/nas/YourProject"           # NAS mount (shared with Windows)
DEPLOY_DIR="/opt/your-project"              # Local server copy (production reads from here)
EXCLUDE_DIRS=(.git data offices .claude)    # Dirs to skip (large data, agent workspaces, etc.)
# =======================

# Build exclude args
EXCLUDES=()
for d in "${EXCLUDE_DIRS[@]}"; do
    EXCLUDES+=(--exclude="$d")
done

# Keep previous snapshot for instant rollback
if [[ -d "$DEPLOY_DIR" ]]; then
    rsync -a "$DEPLOY_DIR/" "${DEPLOY_DIR}.prev/"
fi

# Sync current code
rsync -a --delete "${EXCLUDES[@]}" "$SOURCE_DIR/" "$DEPLOY_DIR/"

COMMIT=$(git -C "$SOURCE_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "Deployed $(date '+%Y-%m-%d %H:%M:%S') — commit $COMMIT"
```

#### One-time server setup

```bash
sudo mkdir -p /opt/your-project
sudo chown $USER:$USER /opt/your-project
```

#### Update all server references

| File | Change |
|---|---|
| Cron scripts | `PROJECT_DIR="/opt/your-project"` |
| systemd service files | `WorkingDirectory=/opt/your-project` |
| venv shebangs (if applicable) | Verify they use absolute paths to the venv, not the project dir |

---

## Application to This Project

### Chi-Srv-01 (Server)

| Setting | Value |
|---|---|
| NAS source | `/mnt/projects/OBD2v2` (Chi-NAS-01 at 10.27.27.121) |
| Deploy target | `/opt/obd2-server` |
| Exclude dirs | `.git`, `data`, `offices`, `.claude`, `src/pi` (Pi-only code) |
| systemd service | `WorkingDirectory=/opt/obd2-server` |
| Deploy trigger | Manual `deploy.sh` run by CIO after git push |

### chi-eclipse-01 (Pi)

The Pi clones directly from git (not NAS-mounted), so Layer 2 is less critical. However, Layer 1 (`.gitattributes` + `autocrlf=input`) still applies because the Pi pulls code that was committed from Windows.

### Current State (as of 2026-04-15)

- **`.gitattributes`**: EXISTS — covers most critical types. Missing: `.service`, `.csv`, `.html`, `.css`, `.js`. Should add `eol=lf` to the `* text=auto` line.
- **`core.autocrlf`**: Set to `true` (BAD) — should be `input`. Needs fix on CIO's Windows workstation.
- **Layer 2 (rsync)**: NOT IMPLEMENTED — server deployment stories should include this.

---

## Impact on Existing Specs

The server crawl/walk/run spec (`2026-04-15-server-crawl-walk-run-design.md`) story US-CMP-009 (systemd service and deployment) should incorporate Layer 2. The deploy script in `deploy/` should use rsync to `/opt/obd2-server`, and the systemd service should point at the local copy, not the NAS mount.

The `.gitattributes` fix (Layer 1) should be a pre-requisite task before any deployment work begins.
