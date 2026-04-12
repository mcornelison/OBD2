# I-005: Config Path Breaks When Not Run From Project Root

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High                   |
| Status       | Open                   |
| Category     | bug                    |
| Found By     | CIO (Pi 5 deployment)  |
| Found Date   | 2026-01-31             |

## Description

`src/main.py` uses a relative default config path (`src/obd_config.json`). This only works if the current working directory is the project root. On the Pi, if the user runs the app from any other directory (home dir, `/`, via systemd, etc.), it fails with "configuration error file not found."

A production app running as a systemd service or from a cron job won't have a predictable CWD.

## Steps to Reproduce

```bash
cd /tmp
python3 ~/Projects/EclipseTuner/src/main.py --dry-run
# FAIL: configuration error file not found
```

## Expected Behavior

The app should find its config file regardless of CWD by resolving the path relative to the project root (i.e., relative to `main.py`'s location).

## Suggested Fix

In `src/main.py`, resolve the default config path relative to the script's own location:

```python
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, 'obd_config.json')
```

Then use `DEFAULT_CONFIG` as the argparse default instead of the relative string.

Also check `.env` default path -- same issue.

## Affected Files

- `src/main.py` (line 80: `default='src/obd_config.json'`)
- `src/main.py` (line 87: `default='.env'`)
- `deploy/eclipse-obd.service` (may need `WorkingDirectory=` as a workaround)
