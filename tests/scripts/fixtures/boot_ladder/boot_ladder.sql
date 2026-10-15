-- US-861 boot_ladder fixture: rows only.  The test creates startup_log and boot_milestone
-- from src/pi/obdii/database_schema.py (and the Sprint 98 shape) and then runs this file.
-- Run with: --deploy-at 2026-10-08T08:04:00Z --deploy-at 2026-10-14T15:55:30Z (see README.md).

-- b01counted: One cold, car-powered, single-start boot: the only COUNTED one.
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b01counted', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-01T07:00:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b01counted', 'kernel_start', '2026-10-01T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b01counted', 'first_sample_imu', '2026-10-01T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b01counted', 'first_sample_light', '2026-10-01T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b01counted', 'first_sample_ups', '2026-10-01T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b01counted', 'obd_connected', '2026-10-01T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b01counted', 'first_sample_obd', '2026-10-01T08:00:32Z', 32.0);

-- b02nostartuplog: no startup_log row
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b02nostartuplog', 'kernel_start', '2026-10-02T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b02nostartuplog', 'first_sample_imu', '2026-10-02T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b02nostartuplog', 'first_sample_light', '2026-10-02T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b02nostartuplog', 'first_sample_ups', '2026-10-02T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b02nostartuplog', 'obd_connected', '2026-10-02T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b02nostartuplog', 'first_sample_obd', '2026-10-02T08:00:32Z', 32.0);

-- b03warmreboot: prior_boot_loss_at NULL: a software reboot
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b03warmreboot', 1, 'CLEAN_COMPLETE', 'clock_unsynced', NULL);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b03warmreboot', 'kernel_start', '2026-10-03T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b03warmreboot', 'first_sample_imu', '2026-10-03T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b03warmreboot', 'first_sample_light', '2026-10-03T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b03warmreboot', 'first_sample_ups', '2026-10-03T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b03warmreboot', 'obd_connected', '2026-10-03T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b03warmreboot', 'first_sample_obd', '2026-10-03T08:00:32Z', 32.0);

-- b04shortoff: off 30 s < --min-off-s 60
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b04shortoff', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-04T07:59:30Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b04shortoff', 'kernel_start', '2026-10-04T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b04shortoff', 'first_sample_imu', '2026-10-04T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b04shortoff', 'first_sample_light', '2026-10-04T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b04shortoff', 'first_sample_ups', '2026-10-04T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b04shortoff', 'obd_connected', '2026-10-04T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b04shortoff', 'first_sample_obd', '2026-10-04T08:00:32Z', 32.0);

-- b05noobd: no obd_connected / first_sample_obd: not car power
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b05noobd', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-05T07:00:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b05noobd', 'kernel_start', '2026-10-05T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b05noobd', 'first_sample_imu', '2026-10-05T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b05noobd', 'first_sample_light', '2026-10-05T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b05noobd', 'first_sample_ups', '2026-10-05T08:00:22Z', 22.0);

-- b06missinglight: no first_sample_light
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b06missinglight', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-06T07:00:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b06missinglight', 'kernel_start', '2026-10-06T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b06missinglight', 'first_sample_imu', '2026-10-06T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b06missinglight', 'first_sample_ups', '2026-10-06T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b06missinglight', 'obd_connected', '2026-10-06T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b06missinglight', 'first_sample_obd', '2026-10-06T08:00:32Z', 32.0);

-- b07obdrestarted: journal: eclipse-obd started twice
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b07obdrestarted', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-07T07:00:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b07obdrestarted', 'kernel_start', '2026-10-07T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b07obdrestarted', 'first_sample_imu', '2026-10-07T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b07obdrestarted', 'first_sample_light', '2026-10-07T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b07obdrestarted', 'first_sample_ups', '2026-10-07T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b07obdrestarted', 'obd_connected', '2026-10-07T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b07obdrestarted', 'first_sample_obd', '2026-10-07T08:00:32Z', 32.0);

-- b08deploymidboot: --deploy-at 2026-10-08T08:04:00Z inside [kernel_start, kernel_start + 300 s]
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b08deploymidboot', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-08T07:00:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b08deploymidboot', 'kernel_start', '2026-10-08T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b08deploymidboot', 'first_sample_imu', '2026-10-08T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b08deploymidboot', 'first_sample_light', '2026-10-08T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b08deploymidboot', 'first_sample_ups', '2026-10-08T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b08deploymidboot', 'obd_connected', '2026-10-08T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b08deploymidboot', 'first_sample_obd', '2026-10-08T08:00:32Z', 32.0);

-- b09firstafterdeploy: first kernel_start after --deploy-at 2026-10-08T08:04:00Z
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('b09firstafterdeploy', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-09T07:00:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b09firstafterdeploy', 'kernel_start', '2026-10-09T08:00:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b09firstafterdeploy', 'first_sample_imu', '2026-10-09T08:00:20Z', 20.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b09firstafterdeploy', 'first_sample_light', '2026-10-09T08:00:21Z', 21.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b09firstafterdeploy', 'first_sample_ups', '2026-10-09T08:00:22Z', 22.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b09firstafterdeploy', 'obd_connected', '2026-10-09T08:00:30Z', 30.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('b09firstafterdeploy', 'first_sample_obd', '2026-10-09T08:00:32Z', 32.0);

-- 7c6aafaa: Atlas boot 7c6aafaa: V0.30.0 deployed mid-boot (--deploy-at 2026-10-14T15:55:30Z), first_sample_* at uptime 769 s from the deploy restart, no OBD rows
INSERT INTO startup_log (boot_id, prior_boot_clean, prior_boot_last_stage, data_quality, prior_boot_loss_at) VALUES ('7c6aafaa', 1, 'CLEAN_COMPLETE', 'clock_unsynced', '2026-10-14T14:43:00Z');
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('7c6aafaa', 'kernel_start', '2026-10-14T15:43:00Z', 0.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('7c6aafaa', 'first_sample_imu', '2026-10-14T15:55:49Z', 769.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('7c6aafaa', 'first_sample_light', '2026-10-14T15:55:49Z', 769.0);
INSERT INTO boot_milestone (boot_id, milestone, ts_utc, uptime_s) VALUES ('7c6aafaa', 'first_sample_ups', '2026-10-14T15:55:49Z', 769.0);
