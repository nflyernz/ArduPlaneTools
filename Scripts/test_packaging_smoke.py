"""End-to-end contracts for disposable packaged-runtime smoke fixtures."""

import json

from Packaging.generate_smoke_fixtures import CSV_ROW_COUNT, generate_fixtures
from core.config import Config
from core.log_reader import FlightReader
from core.radio_link import RadioLinkDetector
from gui.packaging_smoke import run_packaging_smoke
from gui.range_walk_adapter import RangeWalkPreviewRequest, analyse_range_walk_preview


def test_synthetic_bin_decodes_independently_through_flight_reader(tmp_path):
    bin_path, _ = generate_fixtures(tmp_path)

    flight_log = FlightReader(
        bin_path,
        config=Config("Config/radio_link.yaml"),
    ).read()
    result = RadioLinkDetector().detect(flight_log)

    assert flight_log.firmware_version() == {
        "major": 4,
        "minor": 7,
        "patch": 1,
        "version": "ArduPlane V4.7.1 (synthetic packaging smoke)",
    }
    assert len(result.episodes) == 1
    episode = result.episodes[0]
    assert episode.start.time_us == 10_000_000
    assert episode.revalid.time_us == 20_100_000
    assert episode.short_mode[1] == "CIRCLE"
    assert episode.long_mode[1] == "RTL"
    assert episode.armed == "armed throughout"


def test_synthetic_csv_has_five_complete_marker_holds(tmp_path):
    _, csv_path = generate_fixtures(tmp_path)

    preview = analyse_range_walk_preview(
        RangeWalkPreviewRequest(csv_path, inverse=False, request_id=1)
    )

    assert preview.row_count == CSV_ROW_COUNT
    assert preview.direction_used == "higher"
    assert preview.direction_reliable
    assert len(preview.markers) == 5
    assert [marker.hold_s for marker in preview.markers] == [2.0] * 5


def test_packaging_smoke_runs_real_adapters_and_writes_json(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    bin_path, csv_path = generate_fixtures(fixtures)
    result_path = tmp_path / "result.json"
    application_data = tmp_path / "application-data"
    monkeypatch.setenv("LOCALAPPDATA", str(application_data))

    assert run_packaging_smoke(bin_path, csv_path, result_path) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result == {
        "status": "ok",
        "radio_link": {
            "episode_count": 1,
            "short_action_count": 1,
            "long_action_count": 1,
            "recovery_count": 1,
        },
        "range_walk": {
            "row_count": CSV_ROW_COUNT,
            "marker_candidates": 5,
            "direction": "higher",
        },
    }
    assert not (application_data / "ArduPlaneTools").exists()


def test_packaging_smoke_failure_is_machine_readable(tmp_path):
    result_path = tmp_path / "failure.json"

    assert run_packaging_smoke(
        tmp_path / "missing.bin",
        tmp_path / "missing.csv",
        result_path,
    ) == 1

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "error"
    assert result["error_type"]
    assert result["message"]
