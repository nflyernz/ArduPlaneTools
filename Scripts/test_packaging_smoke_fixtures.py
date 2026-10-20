"""Qt-independent validation of packaged-runtime smoke fixtures."""

from Packaging.generate_smoke_fixtures import CSV_ROW_COUNT, generate_fixtures
from core.config import Config
from core.edgetx import read_edgetx_csv
from core.log_reader import FlightReader
from core.radio_link import RadioLinkDetector
from core.range_walk import MarkerCalibration, detect_markers


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


def test_synthetic_csv_decodes_independently_through_marker_detector(tmp_path):
    _, csv_path = generate_fixtures(tmp_path)

    session = read_edgetx_csv(csv_path)
    markers = detect_markers(session, MarkerCalibration(down=1024, neutral=0))

    assert session.source_row_count == CSV_ROW_COUNT
    assert len(markers) == 5
    assert [marker.hold_s for marker in markers] == [2.0] * 5
