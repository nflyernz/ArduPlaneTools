"""On-demand, CSV-only Radio Link range-walk comparison presentation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from textwrap import wrap

from core.edgetx import read_edgetx_csv
from core.range_walk import (
    MarkerCalibration,
    WalkEvidence,
    WalkSettings,
    build_walk,
    detect_markers,
    settings_comparable,
)


class _RangeWalkCancelled(Exception):
    """Signal deliberate cancellation separately from invalid walk input."""


def _prompt(prompt: str) -> str:
    """Read one setup value, treating Q as deliberate cancellation."""
    value = input(prompt).strip()
    if value.casefold() == "q":
        raise _RangeWalkCancelled
    return value


def _value(value: float | None, unit: str = "") -> str:
    return f"{value:.1f}{unit}" if value is not None else "Unavailable"


def _coverage(evidence) -> str:
    if evidence is None:
        return "Incomplete markers"
    return (f"{evidence.usable_counts['1RSS(dB)']}/{evidence.row_count} rows, "
            f"{100 * evidence.rssi_coverage:.0f}% observed time")


def format_range_walk_report(walks: list[WalkEvidence],
                             landmarks: tuple[str, ...], turnaround: str) -> str:
    """Present baseline-first section metrics with their evidence denominator."""
    if len(walks) < 2 or len(landmarks) != 5:
        raise ValueError("Comparison requires Walk 1, another walk, and five landmarks")
    baseline = walks[0]
    if any(marker is None for marker in baseline.landmarks):
        raise ValueError("Walk 1 must have five confirmed landmarks")
    lines = ["Radio Link Range-Walk Comparison — EdgeTX CSV", "",
             "Walk 1 is the original-antenna baseline for every comparison.",
             "Radio clock is transmitter-local; section positions are physical landmarks, "
             "not metre-by-metre alignment.", "",
             "Route: " + " → ".join(landmarks),
             f"Safe turnaround: {turnaround}", "", "Walk setup and validity"]
    for number, walk in enumerate(walks, 1):
        role = "baseline" if number == 1 else "comparison"
        selected = sum(marker is not None for marker in walk.landmarks)
        first = walk.session.rows[0].clock
        last = walk.session.rows[-1].clock
        lines.extend([
            f"  Walk {number} — {role}: {walk.label}; antenna: {walk.antenna}",
            f"    CSV: {walk.session.path} (radio-local {first} to {last})",
            f"    Markers: {selected}/5 confirmed from {len(walk.candidates)} candidates; "
            f"sections: {sum(section is not None for section in walk.sections)}/4",
            f"    Configured TX power: {walk.settings.tx_power or 'unknown'}; "
            f"packet rate: {walk.settings.packet_rate or 'unknown'}; "
            f"RF mode: {walk.settings.rf_mode or 'unknown'}; "
            f"dynamic power: {walk.settings.dynamic_power or 'unknown'}",
        ])
        powers = sorted({value for row in walk.session.rows
                         if (value := row.observed("TPWR(mW)")) is not None})
        modes = sorted({value for row in walk.session.rows
                        if (value := row.observed("RFMD")) is not None})
        lines.append("    EdgeTX reported TPWR: " + (
            ", ".join(f"{x:g}" for x in powers) + " mW" if powers else "unavailable") +
            "; RFMD index: " + (", ".join(f"{x:g}" for x in modes)
                                  if modes else "unavailable"))
        if number > 1 and not settings_comparable(baseline, walk):
            lines.append("    Not like-for-like: configured RF settings differ or are unknown.")
        if selected < 5:
            lines.append("    Incomplete walk: missing landmarks are not inferred.")
        selected_numbers = [
            str(walk.candidates.index(marker) + 1) if marker is not None else "missing"
            for marker in walk.landmarks
        ]
        lines.append("    Confirmed candidate mapping 1–5: " +
                     ", ".join(selected_numbers))
        existing = [section for section in walk.sections if section is not None]
        route_s = sum(section.duration_s for section in existing)
        usable_s = sum(section.usable_time_s["1RSS(dB)"] for section in existing)
        lines.append(
            f"    Moving sections: {usable_s:.1f}/{route_s:.1f} s with eligible "
            f"1RSS ({100 * usable_s / route_s:.0f}% observed time)"
            if route_s else "    Moving sections: no complete section coverage"
        )

    lines.extend(["", "Section comparison (eligible logged reported values; "
                  "not independent RF updates)",
                  "P10 is the lower-tail 10th percentile of usable logged values. "
                  "Coverage is observation time, not RF refresh freshness.",
                  "Section | Walk | 1RSS median | 1RSS P10 | RQly P10 | "
                  "RSNR median | 1RSS usable coverage | Longest unavailable"])
    for section_index in range(4):
        section_name = f"{section_index + 1}→{section_index + 2}"
        for walk_number, walk in enumerate(walks, 1):
            section = walk.sections[section_index]
            if section is None:
                lines.append(f"{section_name} | Walk {walk_number}"
                             + (" baseline" if walk_number == 1 else "")
                             + " | Incomplete marker boundary")
                continue
            rssi = section.median_values["1RSS(dB)"]
            status = ("Unavailable" if rssi is None else
                      "Not like-for-like" if walk_number > 1 and not
                      settings_comparable(baseline, walk) else "Observed")
            lines.append(
                f"{section_name} | Walk {walk_number}"
                f"{' baseline' if walk_number == 1 else ''} | "
                f"{_value(rssi, ' dBm')} | "
                f"{_value(section.p10_values['1RSS(dB)'], ' dBm')} | "
                f"{_value(section.p10_values['RQly(%)'], '%')} | "
                f"{_value(section.median_values['RSNR(dB)'], ' dB')} | "
                f"{_coverage(section)} | {section.longest_unavailable_s:.1f} s "
                f"[{status}]"
            )
    lines.extend(["", "Section and landmark evidence detail"])
    for number, walk in enumerate(walks, 1):
        lines.append(f"  Walk {number} — {walk.label}")
        for index, (name, marker, hold) in enumerate(zip(
                landmarks, walk.landmarks, walk.holds), 1):
            if marker is None or hold is None:
                lines.append(f"    Landmark {index} {name}: missing")
                continue
            lines.append(
                f"    Landmark {index} {name}: radio-local "
                f"{marker.onset.time()} to {marker.release.time()} "
                f"({marker.hold_s:.1f} s hold); stationary 1RSS median "
                f"{_value(hold.median_values['1RSS(dB)'], ' dBm')}, "
                f"RQly median {_value(hold.median_values['RQly(%)'], '%')}; "
                f"{_coverage(hold)}"
            )
        for index, section in enumerate(walk.sections, 1):
            if section is None:
                continue
            counts = section.availability_counts
            times = section.availability_time_s
            lines.append(
                f"    Section {index}→{index+1}: {section.duration_s:.1f} s; "
                f"{section.row_count} logged rows; 1RSS {_coverage(section)}; "
                f"active/partial/unavailable/ambiguous rows "
                f"{counts['active']}/{counts['partial']}/{counts['unavailable']}/"
                f"{counts['ambiguous']}; corresponding observed times "
                f"{times['active']:.1f}/{times['partial']:.1f}/"
                f"{times['unavailable']:.1f}/{times['ambiguous']:.1f} s; "
                f"unlogged {section.unlogged_time_s:.1f} s; "
                f"TQly median {_value(section.tqly_median, '%')} (downlink context)"
            )
    lines.extend([
        "", "Evidence limits: All RF values come from EdgeTX CSV; 1RSS/RQly/RSNR "
        "are receiver-reported uplink metrics returned by telemetry.",
        "Zero-filled unavailable telemetry is excluded; missing telemetry is not "
        "measured RF loss or a Plane failsafe. Repeated values may be held.",
        "TPWR is telemetry-reported, not measured radiated power; RFMD is an index, "
        "not a verified packet rate. No antenna winner or RF margin is inferred.",
    ])
    return "\n".join(lines)


def _trace_points(rows, field: str, cadence_s: float, t0):
    """Return a line with explicit NaN breaks for missing values and row gaps."""
    xs, ys = [], []
    previous = None
    for row in rows:
        x = (row.clock - t0).total_seconds()
        if previous is not None and x - previous > 1.5 * cadence_s:
            xs.append(x - 0.5 * cadence_s)
            ys.append(float("nan"))
        xs.append(x)
        value = row.observed(field)
        ys.append(value if value is not None else float("nan"))
        previous = x
    return xs, ys


def _landmark_key(landmarks: tuple[str, ...]) -> str:
    names = [f"{i}. {name}" for i, name in enumerate(landmarks, 1)]
    if "turnaround" not in landmarks[-1].casefold():
        names[-1] += " (turnaround)"
    return "\n".join(wrap("   |   ".join(names), width=95,
                          break_long_words=False, break_on_hyphens=False))


def write_range_walk_graphs(walks: list[WalkEvidence],
                            landmarks: tuple[str, ...], output: Path) -> list[Path]:
    """Save per-walk RF traces and baseline-referenced section P10 PNGs."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(f"PNG plotting requires matplotlib/numpy: {exc}") from exc

    output.mkdir(parents=True, exist_ok=True)
    paths = []
    plotted_rows = [
        [row for row in walk.session.rows
         if walk.landmarks[-1] is None or row.clock <= walk.landmarks[-1].release]
        for walk in walks
    ]
    rssi_values = [value for rows in plotted_rows for row in rows
                   if (value := row.observed("1RSS(dB)")) is not None]
    rssi_limits = None
    if rssi_values:
        low, high = min(rssi_values), max(rssi_values)
        padding = max(3.0, (high - low) * 0.08)
        rssi_limits = (low - padding, high + padding)
    landmark_key = _landmark_key(landmarks)
    key_lines = landmark_key.count("\n") + 1
    for number, (walk, rows) in enumerate(zip(walks, plotted_rows), 1):
        end = walk.landmarks[-1].release if walk.landmarks[-1] else None
        t0 = rows[0].clock
        cadence = sorted((b.clock - a.clock).total_seconds()
                         for a, b in zip(rows, rows[1:]))
        cadence_s = cadence[len(cadence) // 2] if cadence else 0.1
        fig, axes = plt.subplots(2, 1, figsize=(10, 5.5), sharex=True)
        fig.subplots_adjust(left=0.10, right=0.97, bottom=0.15,
                            top=max(0.72, 0.84 - 0.035 * (key_lines - 1)),
                            hspace=0.13)
        for axis, field, label in zip(
                axes, ("1RSS(dB)", "RQly(%)"),
                ("1RSS (reported dBm; CSV 1RSS(dB))", "RQly (%)")):
            xs, ys = _trace_points(rows, field, cadence_s, t0)
            axis.plot(xs, ys, linewidth=1, label=f"EdgeTX CSV {field}")
            for i, marker in enumerate(walk.landmarks, 1):
                if marker is None:
                    continue
                onset = (marker.onset - t0).total_seconds()
                axis.axvline(onset, color="tab:orange", linestyle="--", alpha=0.7)
                axis.text(onset, 0.97, str(i), transform=axis.get_xaxis_transform(),
                          ha="center", va="top", fontsize=8,
                          bbox={"facecolor": "white", "edgecolor": "none",
                                "alpha": 0.8, "pad": 1})
            for run in walk.session.runs:
                if run.availability == "unavailable":
                    left = (run.start - t0).total_seconds()
                    right = (run.end - t0).total_seconds() + cadence_s
                    if end is not None:
                        right = min(right, (end - t0).total_seconds())
                    if right <= left:
                        continue
                    axis.axvspan(left, right, color="gray", alpha=0.18)
            axis.set_ylabel(label)
            axis.grid(alpha=0.25)
        if rssi_limits is not None:
            axes[0].set_ylim(*rssi_limits)
        else:
            axes[0].text(0.5, 0.5, "No eligible 1RSS observations",
                         transform=axes[0].transAxes, ha="center")
        axes[1].set_ylim(-2, 102)
        axes[-1].set_xlim(-0.5, (rows[-1].clock - t0).total_seconds() + 0.5)
        axes[-1].set_xlabel("Elapsed transmitter-local CSV time (s)")
        fig.suptitle(f"Walk {number} — {walk.label}\n{walk.session.path.name}",
                     y=0.995, fontsize=11)
        fig.text(0.5, 0.91, landmark_key, ha="center", va="top", fontsize=8.5)
        fig.text(0.5, 0.025, "EdgeTX CSV  •  Gray = telemetry unavailable  •  "
                 "Line breaks = unusable RF", ha="center", fontsize=8)
        path = output / f"walk_{number}_rf.png"
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths.append(path)

    fig, axes = plt.subplots(2, 1, figsize=(10, 5.8), sharex=True)
    fig.subplots_adjust(left=0.10, right=0.97, bottom=0.15,
                        top=max(0.67, 0.82 - 0.035 * (key_lines - 1)),
                        hspace=0.18)
    xs = np.arange(4)
    colours = ("tab:blue", "tab:orange")
    for number, walk in enumerate(walks, 1):
        label = f"Walk {number} — {walk.label}"
        if number > 1 and not settings_comparable(walks[0], walk):
            fields = ("tx_power", "packet_rate", "rf_mode", "dynamic_power")
            known_difference = any(
                getattr(walks[0].settings, field)
                and getattr(walk.settings, field)
                and getattr(walks[0].settings, field) !=
                getattr(walk.settings, field)
                for field in fields
            )
            label += (" (RF settings differ)" if known_difference
                      else " (RF settings not independently verified)")
        for axis, field in zip(axes, ("1RSS(dB)", "RQly(%)")):
            values = [section.p10_values[field] if section else None
                      for section in walk.sections]
            ys = [value if value is not None else np.nan for value in values]
            axis.plot(xs, ys, marker="o", color=colours[(number - 1) % 2],
                      label=label)
            for x, y, section in zip(xs, ys, walk.sections):
                if section is None or np.isnan(y):
                    continue
                coverage = (section.usable_time_s[field]
                            / section.duration_s if section.duration_s else 0)
                axis.annotate(f"{100 * coverage:.0f}%", (x, y),
                              xytext=(-12 if number % 2 else 12,
                                      7 + 12 * ((number - 1) // 2)),
                              textcoords="offset points", ha="center", fontsize=8)
    for axis in axes:
        axis.set_xlim(-0.3, 3.3)
        axis.margins(y=0.2)
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
    axes[0].set_ylabel("1RSS P10 of usable logged values (dBm)")
    axes[1].set_ylabel("RQly P10 of usable logged values (%)")
    axes[1].set_ylim(-2, 102)
    axes[1].set_xticks(xs, [f"{i}→{i + 1}" for i in range(1, 5)])
    axes[1].set_xlabel(
        "Landmark-bounded outward section; not equal-distance positions"
    )
    fig.suptitle("Section comparison — Walk 1 fixed baseline | EdgeTX CSV",
                 y=0.99, fontsize=11)
    fig.text(0.5, 0.925, landmark_key, ha="center", va="top", fontsize=8.5)
    fig.text(0.5, 0.02, "Point labels = metric-specific observed-time coverage; "
             "missing points = unavailable", ha="center", fontsize=8)
    path = output / "section_1rss_p10.png"
    fig.savefig(path, dpi=120)
    plt.close(fig)
    paths.append(path)
    return paths


def _prompt_settings() -> WalkSettings:
    return WalkSettings(
        _prompt("Configured TX power (e.g. 50 mW; blank if unknown): "),
        _prompt("Configured packet rate (blank if unknown): "),
        _prompt("Configured RF mode/band (blank if unknown): "),
        _prompt("Dynamic TX power state (off/on; blank if unknown): "),
    )


def _csv_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_walk(number: int, landmarks: tuple[str, ...] | None) -> WalkEvidence:
    path = Path(_prompt(f"Walk {number} EdgeTX CSV path: ")).expanduser()
    session = read_edgetx_csv(path)
    label = _prompt(f"Walk {number} label: ") or path.stem
    antenna = _prompt("Receiver antenna configuration: ")
    if number == 1 and not antenna:
        raise ValueError("Walk 1 requires an original-antenna description")
    if number == 1 and _prompt(
            "Confirm Walk 1 used the original antenna installation [y/N]: "
            ).casefold() not in ("y", "yes"):
        raise ValueError("Walk 1 must be the confirmed original-antenna baseline")
    settings = _prompt_settings()
    down = float(_prompt("This model's calibrated full elevator-down Ele value: "))
    neutral = float(_prompt("This model's calibrated neutral Ele value: "))
    threshold = _prompt("Near-full-down Ele threshold from calibration "
                        "(blank = 87.5% of calibrated span): ")
    calibration = MarkerCalibration(down, neutral,
                                    near_down=float(threshold) if threshold else None)
    candidates = detect_markers(session, calibration)
    print(f"\nWalk {number}: {len(candidates)} down-hold candidates (radio-local clock)")
    for index, marker in enumerate(candidates, 1):
        print(f"  {index}. {marker.onset.time()} → {marker.release.time()} "
              f"({marker.hold_s:.1f} s)")
    if landmarks:
        print("Frozen Walk 1 landmark order: " + " → ".join(landmarks))
    print("Confirm five candidate numbers in landmark order; use 0 for a "
          "missing marker on Walk 2+. Extra candidates are excluded explicitly.")
    raw = _prompt("Landmarks 1–5 (e.g. 1,2,3,4,5): ")
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 5:
        raise ValueError("Enter exactly five landmark mappings")
    numbers = tuple(int(part) if part != "0" else None for part in parts)
    return build_walk(session, label, antenna, settings, calibration, numbers,
                      baseline=number == 1)


class RangeWalkComparisonPresentation:
    """Interactive route confirmation and on-demand PNG/text export."""

    def run(self):
        print("\nRadio Link Range-Walk Comparison (CSV-only; aircraft disarmed)")
        print("Enter Q at any setup prompt to cancel.")
        try:
            count = int(_prompt("Number of walks (2 or more): "))
            if count < 2:
                raise ValueError("At least two walks are required")
            walks = []
            seen_csvs = set()
            for number in range(1, count + 1):
                if number == 2:
                    print("\nWalk 1 route is frozen for later walks.")
                while True:
                    try:
                        walk = _prompt_walk(number,
                                            landmarks if number > 1 else None)
                        fingerprint = _csv_fingerprint(walk.session.path)
                        if fingerprint in seen_csvs:
                            raise ValueError("CSV content duplicates an earlier walk")
                        seen_csvs.add(fingerprint)
                        walks.append(walk)
                        break
                    except (OSError, ValueError) as exc:
                        print(f"Walk {number} input skipped with reason: {exc}")
                        print("Select a valid CSV and confirmed markers for this walk.")
                if number == 1:
                    landmarks = tuple(
                        _prompt(f"Physical landmark {i} name/description: ")
                        for i in range(1, 6))
                    if any(not name for name in landmarks):
                        raise ValueError("Five physical landmark descriptions are required")
                    turnaround = _prompt(
                        "Safe turnaround at landmark 5 (physical note): ")
                    if not turnaround:
                        raise ValueError(
                            "Walk 1 requires a safe turnaround description")
            destination = _prompt("PNG output directory [RangeWalkReports]: ")
            print("\n" + format_range_walk_report(walks, landmarks, turnaround))
            output = Path(destination or "RangeWalkReports").expanduser()
            paths = write_range_walk_graphs(walks, landmarks, output)
            print("\nPNG graphs:")
            for path in paths:
                print(f"  {path.resolve()}")
        except _RangeWalkCancelled:
            print("\nRange-Walk Comparison cancelled.")
        except (EOFError, OSError, ValueError, RuntimeError) as exc:
            print(f"Range-Walk Comparison unavailable: {exc}")
