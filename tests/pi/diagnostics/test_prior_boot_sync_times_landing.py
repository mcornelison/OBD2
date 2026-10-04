import json

from src.pi.diagnostics.boot_progress import readPriorShutdownRecord


def test_timesAndCutVcell_land(tmp_path) -> None:
    p = tmp_path / "powerwatch_outcome.json"
    p.write_text(json.dumps({
        "boot_id": "b1", "sync_outcome": "DELIVERED",
        "sync_started_at": "2026-10-02T16:53:40Z", "sync_ended_at": "2026-10-02T16:58:12Z",
        "vcell_before_cut_v": 4.2188,
    }), encoding="utf-8")
    landed = readPriorShutdownRecord(str(p), {"b1"})
    assert landed["prior_boot_sync_started_at"] == "2026-10-02T16:53:40Z"
    assert landed["prior_boot_sync_ended_at"] == "2026-10-02T16:58:12Z"
    assert landed["prior_boot_vcell_before_cut_v"] == 4.2188


def test_garbageLandsNull_neverCoerced(tmp_path) -> None:
    p = tmp_path / "powerwatch_outcome.json"
    p.write_text(json.dumps({"boot_id": "b1", "sync_started_at": "yesterday",
                             "vcell_before_cut_v": 99}), encoding="utf-8")
    landed = readPriorShutdownRecord(str(p), {"b1"})
    assert landed["prior_boot_sync_started_at"] is None
    assert landed["prior_boot_vcell_before_cut_v"] is None
