"""Explicit packaged-runtime smoke check; never used by normal GUI startup."""

from __future__ import annotations

import json
from pathlib import Path

from .radio_link_adapter import analyse_radio_link_log
from .range_walk_adapter import RangeWalkPreviewRequest, analyse_range_walk_preview


EXPECTED_EPISODES = 1
EXPECTED_CSV_ROWS = 132
EXPECTED_MARKERS = 5


def _write_result(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_packaging_smoke(bin_path: Path, csv_path: Path, output_path: Path) -> int:
    """Exercise the real frozen adapters and emit deterministic JSON results."""
    output = Path(output_path).resolve()
    try:
        radio = analyse_radio_link_log(Path(bin_path))
        preview = analyse_range_walk_preview(
            RangeWalkPreviewRequest(Path(csv_path), inverse=False, request_id=1)
        )
        episodes = radio.detection.episodes
        observed = {
            "radio_link": {
                "episode_count": len(episodes),
                "short_action_count": sum(item.short_on is not None for item in episodes),
                "long_action_count": sum(item.long_on is not None for item in episodes),
                "recovery_count": sum(item.revalid is not None for item in episodes),
            },
            "range_walk": {
                "row_count": preview.row_count,
                "marker_candidates": len(preview.markers),
                "direction": preview.direction_used,
            },
        }
        expected = {
            "radio_link": {
                "episode_count": EXPECTED_EPISODES,
                "short_action_count": 1,
                "long_action_count": 1,
                "recovery_count": 1,
            },
            "range_walk": {
                "row_count": EXPECTED_CSV_ROWS,
                "marker_candidates": EXPECTED_MARKERS,
                "direction": "higher",
            },
        }
        if observed != expected:
            raise AssertionError(f"packaging smoke evidence mismatch: {observed!r}")
        _write_result(output, {"status": "ok", **observed})
        return 0
    except BaseException as error:
        try:
            _write_result(
                output,
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
            )
        except OSError:
            pass
        return 1
