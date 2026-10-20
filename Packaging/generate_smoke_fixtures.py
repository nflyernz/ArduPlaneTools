"""Generate deterministic packaging-only BIN and EdgeTX CSV smoke fixtures."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import struct


BIN_FILENAME = "synthetic-radio-link.bin"
CSV_FILENAME = "synthetic-range-walk.csv"
CSV_ROW_COUNT = 132
_HEADER = b"\xA3\x95"
_FMT_TYPE = 0x80
_FORMATS = {
    "VER": (0x81, "QBBBZ", "TimeUS,Maj,Min,Pat,FWS"),
    "ARM": (0x82, "QB", "TimeUS,ArmState"),
    "MODE": (0x83, "QBBB", "TimeUS,Mode,ModeNum,Rsn"),
    "RCI2": (0x84, "QHH", "TimeUS,Flags,OMask"),
    "MSG": (0x85, "QZ", "TimeUS,Message"),
}
_STRUCT_FIELDS = {
    "B": "B",
    "H": "H",
    "Q": "Q",
    "Z": "64s",
}


def _ascii(value: str, length: int) -> bytes:
    return value.encode("ascii")[:length]


def _format_record(message_type: int, name: str, fmt: str, columns: str) -> bytes:
    payload_format = "<" + "".join(_STRUCT_FIELDS[field] for field in fmt)
    message_length = 3 + struct.calcsize(payload_format)
    return _HEADER + bytes([_FMT_TYPE]) + struct.pack(
        "<BB4s16s64s",
        message_type,
        message_length,
        _ascii(name, 4),
        _ascii(fmt, 16),
        _ascii(columns, 64),
    )


def _message_record(name: str, *values: object) -> bytes:
    message_type, fmt, _ = _FORMATS[name]
    packed_values = [
        _ascii(str(value), 64) if field == "Z" else value
        for field, value in zip(fmt, values, strict=True)
    ]
    return _HEADER + bytes([message_type]) + struct.pack(
        "<" + "".join(_STRUCT_FIELDS[field] for field in fmt),
        *packed_values,
    )


def write_synthetic_bin(path: Path) -> Path:
    """Write one valid ArduPlane 4.7.1 RC short/long/recovery episode."""
    data = bytearray()
    for name, (message_type, fmt, columns) in _FORMATS.items():
        data.extend(_format_record(message_type, name, fmt, columns))
    records = (
        ("VER", 0, 4, 7, 1, "ArduPlane V4.7.1 (synthetic packaging smoke)"),
        ("ARM", 1_000_000, 1),
        ("MODE", 1_100_000, 0, 0, 1),
        ("RCI2", 2_000_000, 1, 0),
        ("RCI2", 10_000_000, 2, 0),
        ("MODE", 10_200_000, 1, 1, 3),
        ("MSG", 10_200_100, "RC Short Failsafe: switched to Circle"),
        ("MODE", 15_000_000, 11, 11, 3),
        ("MSG", 15_000_100, "RC Long Failsafe On: switched to RTL"),
        ("MSG", 20_050_000, "Throttle failsafe off"),
        ("RCI2", 20_100_000, 1, 0),
        ("MSG", 20_200_000, "RC Long Failsafe Cleared"),
        ("ARM", 30_000_000, 0),
    )
    for name, *values in records:
        data.extend(_message_record(name, *values))
    path.write_bytes(data)
    return path


def write_synthetic_csv(path: Path) -> Path:
    """Write five complete positive-Ele holds with neutral returns."""
    header = (
        "Date", "Time", "Ele", "RQly(%)", "1RSS(dB)", "2RSS(dB)",
        "RSNR(dB)", "RFMD", "TPWR(mW)", "TQly(%)", "FM",
    )
    start = datetime(2026, 1, 1, 12, 0, 0)
    holds = (2, 8, 14, 20, 26)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        for index in range(CSV_ROW_COUNT):
            elapsed = index * 0.25
            clock = start + timedelta(seconds=elapsed)
            ele = 1024 if any(onset <= elapsed < onset + 2 for onset in holds) else 0
            writer.writerow(
                (
                    clock.strftime("%Y-%m-%d"),
                    clock.strftime("%H:%M:%S.%f")[:-3],
                    ele,
                    95,
                    -90,
                    -92,
                    -2,
                    2,
                    50,
                    70,
                    "",
                )
            )
    return path


def generate_fixtures(output_directory: Path) -> tuple[Path, Path]:
    """Create both disposable fixtures outside the application bundle."""
    output_directory.mkdir(parents=True, exist_ok=True)
    return (
        write_synthetic_bin(output_directory / BIN_FILENAME),
        write_synthetic_csv(output_directory / CSV_FILENAME),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args(argv)
    bin_path, csv_path = generate_fixtures(args.output_directory)
    print(
        json.dumps(
            {
                "bin": str(bin_path.resolve()),
                "bin_bytes": bin_path.stat().st_size,
                "csv": str(csv_path.resolve()),
                "csv_bytes": csv_path.stat().st_size,
                "csv_rows": CSV_ROW_COUNT,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
