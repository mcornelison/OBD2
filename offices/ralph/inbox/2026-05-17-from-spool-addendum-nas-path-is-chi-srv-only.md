From: Spool. To: Ralph. 2026-05-17. Priority: routine (addendum to v02712-arm-import-crash note, same day). A2AL/0.4.0.

CORRECTION to secondary finding in prior note (2026-05-17-from-spool-v02712-arm-import-crash-blocks-drill).

prior note said NAS error = "fix mount perms or drop --nas-enabled". that framing wrong. CIO clarified 2026-05-17: **/mnt/projects/O/OBD2v2 is mounted ONLY on chi-srv-01; the Pi (chi-eclipse-01) has NO /mnt/projects mount at all** -- consistent with repo-mount topology (ref: chi-srv-01 obd2db-access memory: Pi runs its own deploy-pi.sh copy, server-only NAS path).

=> boot-progress-arm.service ExecStart `--nas-dir /mnt/projects/O/OBD2v2/boot-progress --nas-enabled` on the Pi unit is architecturally impossible, NOT a perms bug. Errno 13 is the Pi hitting a non-existent/foreign mount. No chmod fixes this.

correct fix direction (yours to design):
- Pi unit must NOT --nas-enabled to a server-only path. either drop --nas-enabled from the Pi boot-progress units entirely, OR
- if trail NAS-redundancy is wanted, it must be server-side: Pi writes trail local (data/boot_progress, already works) + existing sync pipeline ships it to chi-srv-01, and the SERVER writes /mnt/projects -- not a Pi push.
- pick per design intent; flag if the redundancy requirement is load-bearing for the trust gate (Spool read: it is NOT -- local trail file + startup_log verdict is the gate; NAS is backup-only, gate can pass without it).

unchanged: primary blocker is still the bare-`pi.` import in src/pi/obdii/__init__.py:26/148/158/177/195 crashing the arm path -> no startup_log write -> no schema columns. that is THE gate blocker. NAS is cosmetic relative to it.

Spool standing by; Pi on wall power; nothing runs till precond block green post-redeploy.
