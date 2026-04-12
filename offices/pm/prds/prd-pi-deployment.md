# PRD: CI/CD Pipeline -- Windows to Raspberry Pi Deployment

**Parent Backlog Item**: B-013
**Status**: Active

## Introduction

Create a deploy script that transfers the Eclipse OBD-II application from the Windows development machine to the Raspberry Pi 5 over SSH. The project already has Pi setup scripts (`scripts/pi_setup.sh`), systemd service files (`deploy/`), and Pi-specific requirements (`requirements-pi.txt`). This PRD covers the missing piece: the actual code transfer and deployment automation.

The developer works on Windows (MINGW64/Git Bash) which has `rsync` and `ssh` available natively.

## Goals

- Single-command deployment from Windows to Pi
- Idempotent (safe to run multiple times)
- Handles code sync, dependency install, and service restart
- Provides clear pass/fail feedback
- Supports first-time setup and subsequent updates

## Existing Infrastructure

The developer does NOT need to create these -- they already exist:

| Component | File | Status |
|-----------|------|--------|
| Pi OS setup | `scripts/pi_setup.sh` | Done |
| Platform checker | `scripts/check_platform.py` | Done |
| Hardware verifier | `scripts/verify_hardware.py` | Done |
| systemd service | `deploy/eclipse-obd.service` | Done |
| Service installer | `deploy/install-service.sh` | Done |
| Service uninstaller | `deploy/uninstall-service.sh` | Done |
| Pi requirements | `requirements-pi.txt` | Done |
| Makefile targets | `make run`, `make test`, etc. | Done |

## User Stories

### US-DEP-001: Create Deploy Configuration File

**Description:** As a developer, I need a configuration file that stores Pi connection details so the deploy script doesn't hardcode them.

**Acceptance Criteria:**
- [ ] Create `deploy/deploy.conf` with variables: `PI_HOST`, `PI_USER`, `PI_PATH`, `PI_PORT` (SSH port)
- [ ] Default values: `PI_HOST=raspberrypi.local`, `PI_USER=pi`, `PI_PATH=/home/pi/obd2`, `PI_PORT=22`
- [ ] Create `deploy/deploy.conf.example` as a committed template (actual `deploy.conf` is gitignored)
- [ ] Add `deploy/deploy.conf` to `.gitignore`
- [ ] Typecheck passes

### US-DEP-002: Create Core Deploy Script

**Description:** As a developer, I want a single script that syncs code from my Windows machine to the Pi so I can deploy with one command.

**Acceptance Criteria:**
- [ ] Create `scripts/deploy.sh` that reads config from `deploy/deploy.conf`
- [ ] Uses `rsync` over SSH to sync project files to Pi (excluding `.venv/`, `__pycache__/`, `.git/`, `*.pyc`, `data/`, `logs/`, `.env`)
- [ ] Script checks SSH connectivity before attempting sync
- [ ] Prints clear summary of what was synced (file count, transfer size)
- [ ] Exits with code 0 on success, non-zero on failure
- [ ] Works from MINGW64/Git Bash on Windows
- [ ] Script is idempotent (safe to run multiple times)
- [ ] Typecheck passes

### US-DEP-003: Add Dependency Installation Step

**Description:** As a developer, I want the deploy script to install/update Python dependencies on the Pi after syncing code.

**Acceptance Criteria:**
- [ ] Deploy script creates venv on Pi if it doesn't exist (`python3 -m venv .venv`)
- [ ] Installs from `requirements.txt` and `requirements-pi.txt` via SSH
- [ ] Only runs pip install if requirements files changed since last deploy (compare checksums)
- [ ] Prints installed package count or "dependencies up to date"
- [ ] Handles pip install failures gracefully (reports error, doesn't exit silently)
- [ ] Typecheck passes

### US-DEP-004: Add Service Restart Step

**Description:** As a developer, I want the deploy script to restart the systemd service after deployment so the new code takes effect.

**Acceptance Criteria:**
- [ ] Deploy script checks if `eclipse-obd` service is installed on Pi
- [ ] If service exists: restarts it via `sudo systemctl restart eclipse-obd`
- [ ] If service not installed: skips restart, prints instruction to install it
- [ ] Waits 3 seconds after restart, checks service status
- [ ] Reports service state (active/failed) after restart
- [ ] Typecheck passes

### US-DEP-005: Add Post-Deploy Smoke Test

**Description:** As a developer, I want the deploy script to verify the deployment succeeded by running a smoke test on the Pi.

**Acceptance Criteria:**
- [ ] After sync + deps + restart, runs `python src/main.py --dry-run` on the Pi via SSH
- [ ] Checks exit code: 0 = success, non-zero = deployment problem
- [ ] Prints clear PASS/FAIL result with details on failure
- [ ] If smoke test fails, prints the service log tail (last 20 lines)
- [ ] Total deploy script outputs a final summary: files synced, deps status, service status, smoke test result
- [ ] Typecheck passes

### US-DEP-006: Add Makefile Deploy Targets

**Description:** As a developer, I want `make deploy` and related commands for convenience.

**Acceptance Criteria:**
- [ ] Add `deploy` target to `Makefile` that runs `scripts/deploy.sh`
- [ ] Add `deploy-first` target that runs `scripts/deploy.sh` with a `--first-run` flag (triggers `pi_setup.sh` on Pi before normal deploy)
- [ ] Add `deploy-status` target that SSHs to Pi and runs `systemctl status eclipse-obd`
- [ ] Add `deploy-env` target that copies `.env` to Pi via `scp` (see US-DEP-007)
- [ ] Typecheck passes

### US-DEP-007: One-Time .env File Push

**Description:** As a developer, I need a way to send the `.env` secrets file to the Pi once during initial setup, separate from the regular deploy flow.

**Acceptance Criteria:**
- [ ] `make deploy-env` copies local `.env` to `$PI_PATH/.env` on the Pi via `scp`
- [ ] Reads Pi connection details from `deploy/deploy.conf`
- [ ] Prompts with a confirmation before overwriting an existing `.env` on the Pi
- [ ] Sets file permissions to 600 (owner read/write only) on the Pi after copy
- [ ] Prints success/failure message
- [ ] `.env` remains excluded from rsync in the regular deploy script (FR-3 unchanged)
- [ ] Typecheck passes

## Functional Requirements

- FR-1: Deploy script must be a bash script runnable from MINGW64/Git Bash
- FR-2: All Pi communication via SSH (no additional tools required beyond ssh/rsync)
- FR-3: rsync exclusion list must prevent syncing: `.venv/`, `__pycache__/`, `.git/`, `*.pyc`, `data/`, `logs/`, `.env`, `node_modules/`
- FR-4: Deploy script must source config from `deploy/deploy.conf`
- FR-5: Deploy script must exit with meaningful codes: 0=success, 1=config error, 2=ssh error, 3=sync error, 4=deps error, 5=service error, 6=smoke test error
- FR-6: All output must use colored status messages (consistent with existing `pi_setup.sh` style)

## Non-Goals

- No Docker containerization
- No GitHub Actions or webhook-based automation
- No automatic deploy on git push (manual trigger only)
- No multi-Pi deployment (single target)
- No database migration automation (covered by B-015)
- No rollback automation (document git-based rollback in comments)

## Design Considerations

- Follow the output style of `scripts/pi_setup.sh` (colored log functions, section headers)
- Reuse the file header format from `specs/standards.md`
- The deploy script is bash, not Python -- it runs on the Windows side where the Python venv may not have Pi dependencies
- `rsync` with `--delete` flag to remove files on Pi that were deleted locally (keeps Pi in sync)
- Consider `--checksum` flag for rsync to handle clock differences between Windows and Pi

## Technical Considerations

- MINGW64 rsync path translation: use `//` prefix or `cygpath` if needed for Windows paths
- SSH key authentication should be set up (B-012 covers this) -- deploy script should fail clearly if password auth is required
- The Pi install path default (`/home/pi/obd2`) matches the systemd service file and `install-service.sh`
- `requirements-pi.txt` currently references Adafruit libraries that may conflict with the OSOYOO display -- this is a separate concern (not this PRD)

## Success Metrics

- Developer can deploy from Windows to Pi with a single `make deploy` command
- Full deploy cycle (sync + deps + restart + smoke test) completes reliably
- Deploy script provides clear feedback at each step

## Open Questions

- None (resolved: .env excluded from deploy, one-time push via `make deploy-env`)
