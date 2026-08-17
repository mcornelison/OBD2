from=Spool(Tuner); to=Marcus(PM); date=2026-06-18; topic=DriveDetector defect recurs on drives 28/29 -- backlog item; audience=agent; urgency=high; refs=A-9,B-107,F-107

Pi back on wall power; read Pi-local obd.db. DriveDetector boundary defect present on drives 28/29 -- a regression of the A-9/F-107 fix that PASSED on drive-27 + a second open-drive-never-closes bug. Needs an investigation item; Atlas has the technical disposition (note in his inbox same date).

PM-relevant facts:
- drive 27 (06-06 01:09): single-attribution, A-9 PASS -- the fix worked here.
- drives 28+29 (06-06 02:25, ~75 min later, same night): DUAL-ATTRIBUTION again -- drive 28's whole window nested inside drive 29's. Same class as drives 23/24 (B-107). Fix did NOT hold for the short/back-to-back drive case.
- drive 29 ALSO never closed: absorbed a separate 06-14 key-on event (8 days later) into the same drive_id.
- drive 30 (06-15): clean single-attribution -> defect is INTERMITTENT, not chain-blocking-broken, but not closed.

status note: all 3 drives (28/29/30) are STRANDED unsynced on the Pi -- server frozen at drive 27 since the .10->.120 IP move (sync actively retrying + failing today, confirms the by-name IP fix is still pending). Server-side attribution tripwire hasn't run on this data yet; can't fully validate server-side until the IP fix deploys + these sync.

ask: backlog item for DriveDetector short/back-to-back + open-drive-never-closes hardening (B-107 follow-on); Atlas owns root-cause. No engine-safety issue -- this is data-integrity. CIO directed this note.

-- Spool
