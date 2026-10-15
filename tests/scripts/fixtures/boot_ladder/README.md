# boot_ladder fixtures (US-861)

Inputs for `scripts/boot_ladder_report.py`, used by
`tests/scripts/test_boot_ladder_report.py`.

- `boot_ladder.sql` -- `startup_log` and `boot_milestone` rows only. The test
  creates the tables from `src/pi/obdii/database_schema.py` (and the Sprint 98
  `boot_milestone` shape, with no `id`) and then runs this file.
- `journal/<boot_id>.txt` -- one `journalctl -o short-monotonic` export per boot.

Run with `--deploy-at 2026-10-08T08:04:00Z --deploy-at 2026-10-14T15:55:30Z`.

| boot | expected |
|---|---|
| b01counted | COUNTED |
| b02nostartuplog | EXCLUDED(no_startup_log) |
| b03warmreboot | EXCLUDED(warm_reboot) |
| b04shortoff | EXCLUDED(short_off) |
| b05noobd | EXCLUDED(no_obd) |
| b06missinglight | EXCLUDED(missing_milestone:first_sample_light) |
| b07obdrestarted | EXCLUDED(obd_restarted) |
| b08deploymidboot | EXCLUDED(deploy_mid_boot) |
| b09firstafterdeploy | EXCLUDED(first_after_deploy) |
| 7c6aafaa | EXCLUDED(no_obd, deploy_mid_boot, obd_restarted) |

`7c6aafaa` is Atlas's boot of 2026-10-14: V0.30.0 was deployed mid-boot, the
deploy restart wrote `first_sample_imu/light/ups` at uptime 769 s, and the boot
has no `obd_connected` or `first_sample_obd` row. Its other times are fixture
values, not measurements.
