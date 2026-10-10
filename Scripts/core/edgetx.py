"""Optional EdgeTX evidence beside, never inside, the BIN Radio Link detector."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
import math
from pathlib import Path
from statistics import median

from .modes import mode_name


GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
GPS_UTC_LEAP_SECONDS = 18  # ArduPlane 4.7.1's AP_GPS conversion.
RF_COLUMNS = ("RQly(%)", "1RSS(dB)", "2RSS(dB)", "RSNR(dB)", "RFMD", "TPWR(mW)")
REQUIRED_COLUMNS = ("Date", "Time", *RF_COLUMNS)


@dataclass(frozen=True)
class EdgeTxRow:
    clock: datetime  # Raw radio-local time; intentionally timezone-naive.
    values: dict[str, float | None]
    gps: tuple[float, float] | None
    fm: str
    availability: str  # active, partial, unavailable, ambiguous
    ele: float | None = None  # Radio-local elevator control, independent of RF telemetry.

    def observed(self, field: str) -> float | None:
        """Return a usable observation; placeholders and absent antennas stay absent."""
        value = self.values.get(field)
        if value is None:
            return None
        if field == "RQly(%)":
            return value if self.availability == "active" and 0 <= value <= 100 else None
        if field in ("1RSS(dB)", "2RSS(dB)"):
            return value if self.availability == "active" and value < 0 else None
        if field == "RSNR(dB)":
            return value if self.availability == "active" else None
        if field == "RFMD":
            if self.availability == "active":
                return value  # Index zero can be a real mode in another schema.
            return value if self.availability == "partial" and value > 0 else None
        if field == "TPWR(mW)":
            return value if self.availability in ("active", "partial") and value > 0 else None
        return None


@dataclass(frozen=True)
class EdgeTxRun:
    availability: str
    start: datetime
    end: datetime
    count: int


@dataclass
class EdgeTxSession:
    path: Path
    header: tuple[str, ...]
    rows: list[EdgeTxRow]
    runs: list[EdgeTxRun]
    source_row_count: int = 0

    def extrema(
        self, field: str, rows: list[EdgeTxRow] | None = None,
    ) -> tuple[float, float] | None:
        values = [value for row in (self.rows if rows is None else rows)
                  if (value := row.observed(field)) is not None]
        return (min(values), max(values)) if values else None


def _number(raw: str) -> float | None:
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _gps_coordinate(raw: str) -> tuple[float, float] | None:
    try:
        lat, lng = map(float, raw.split())
    except (ValueError, TypeError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 6), round(lng, 6)


def read_edgetx_csv(path: str | Path) -> EdgeTxSession:
    """Read the actual CSV schema by column position, preserving duplicate headers."""
    path = Path(path)
    if path.suffix.lower() != ".csv":
        raise ValueError("EdgeTX input must have a .csv extension")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        try:
            header = tuple(next(reader))
        except StopIteration as exc:
            raise ValueError("EdgeTX CSV is empty") from exc
        if any(header.count(name) != 1 for name in REQUIRED_COLUMNS):
            raise ValueError("EdgeTX CSV lacks a unique required Date/Time/RF column")
        index = {name: header.index(name) for name in REQUIRED_COLUMNS}
        for name in ("GPS", "FM", "TRSS(dB)", "TQly(%)", "TSNR(dB)"):
            if header.count(name) == 1:
                index[name] = header.index(name)
        if header.count("Ele") == 1:
            index["Ele"] = header.index("Ele")
        rows = []
        for line_number, cells in enumerate(reader, start=2):
            if len(cells) != len(header):
                raise ValueError(f"EdgeTX CSV row {line_number} has wrong column count")
            try:
                clock = datetime.strptime(
                    f"{cells[index['Date']]} {cells[index['Time']]}",
                    "%Y-%m-%d %H:%M:%S.%f",
                )
            except ValueError as exc:
                raise ValueError(f"EdgeTX CSV row {line_number} has invalid date/time") from exc
            if rows and clock <= rows[-1].clock:
                raise ValueError(f"EdgeTX CSV row {line_number} is not time-ordered")
            values = {name: _number(cells[position]) for name, position in index.items()
                      if name not in ("Date", "Time", "GPS", "FM", "Ele")}
            ele = _number(cells[index["Ele"]]) if "Ele" in index else None
            gps = _gps_coordinate(cells[index["GPS"]]) if "GPS" in index else None
            fm = cells[index["FM"]].strip() if "FM" in index else ""
            quality, rssi = values["RQly(%)"], values["1RSS(dB)"]
            if (quality is not None and 0 < quality <= 100) or \
                    (rssi is not None and rssi < 0):
                availability = "active"
            elif any(values.get(name) not in (None, 0) for name in
                     ("RFMD", "TPWR(mW)", "TRSS(dB)", "TQly(%)", "TSNR(dB)")):
                availability = "partial"
            elif (quality in (0, None) and rssi in (0, None) and not gps and not fm and
                  all(values.get(name) in (None, 0) for name in RF_COLUMNS)):
                availability = "unavailable"
            else:
                availability = "ambiguous"
            rows.append(EdgeTxRow(clock, values, gps, fm, availability, ele))
    if not rows:
        raise ValueError("EdgeTX CSV has no data rows")
    return EdgeTxSession(path, header, rows, _runs(rows), len(rows))


def _runs(rows: list[EdgeTxRow]) -> list[EdgeTxRun]:
    runs = []
    for row in rows:
        if runs and runs[-1].availability == row.availability:
            previous = runs[-1]
            runs[-1] = EdgeTxRun(previous.availability, previous.start, row.clock,
                                 previous.count + 1)
        else:
            runs.append(EdgeTxRun(row.availability, row.clock, row.clock, 1))
    return runs


@dataclass(frozen=True)
class GpsAnchor:
    boot_s: float
    utc_s: float
    coordinate: tuple[float, float] | None


@dataclass(frozen=True)
class GpsClock:
    intercept_utc_s: float
    slope: float
    first_boot_s: float
    last_boot_s: float
    rms_residual_s: float
    max_residual_s: float
    anchors: tuple[GpsAnchor, ...]

    def utc_at(self, boot_s: float) -> datetime:
        return datetime.fromtimestamp(self.intercept_utc_s + self.slope * boot_s,
                                      tz=timezone.utc)


def gps_clock_from_flight(flight_log) -> GpsClock | None:
    """Use only primary 3D fixes with nonzero GPS week, never startup placeholders."""
    anchors = []
    for record in flight_log.get("GPS").to_dict("records"):
        try:
            boot_s = float(record["TimeUS"]) / 1e6
            week = int(record["GWk"])
            week_ms = float(record["GMS"])
            valid = (int(record["I"]) == 0 and int(record["U"]) == 1
                     and int(record["Status"]) >= 3 and week > 0
                     and 0 <= week_ms < 604_800_000 and boot_s >= 0)
            if not valid or not all(math.isfinite(x) for x in (boot_s, week_ms)):
                continue
            utc_s = (GPS_EPOCH + timedelta(weeks=week,
                      milliseconds=week_ms, seconds=-GPS_UTC_LEAP_SECONDS)).timestamp()
            coordinate = _gps_coordinate(f"{record['Lat']} {record['Lng']}")
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        anchors.append(GpsAnchor(boot_s, utc_s, coordinate))
    anchors.sort(key=lambda item: item.boot_s)
    if len(anchors) < 3 or anchors[-1].boot_s - anchors[0].boot_s < 2:
        return None
    if any(b.utc_s <= a.utc_s for a, b in zip(anchors, anchors[1:])):
        return None
    t0, u0 = anchors[0].boot_s, anchors[0].utc_s
    xs = [anchor.boot_s - t0 for anchor in anchors]
    ys = [anchor.utc_s - u0 for anchor in anchors]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    if denominator <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator
    intercept = u0 + my - slope * (t0 + mx)
    residuals = [anchor.utc_s - (intercept + slope * anchor.boot_s)
                 for anchor in anchors]
    rms = math.sqrt(sum(value * value for value in residuals) / len(residuals))
    maximum = max(abs(value) for value in residuals)
    if not (0.98 <= slope <= 1.02) or rms > 0.25 or maximum > 1:
        return None
    return GpsClock(intercept, slope, t0, anchors[-1].boot_s,
                    rms, maximum, tuple(anchors))


@dataclass(frozen=True)
class AlignmentAnchor:
    """A verified same-semantic cross-stream landmark with a known lag bound."""
    bin_boot_s: float
    csv_clock: datetime
    lag_bound_s: float


@dataclass(frozen=True)
class EdgeTxAlignment:
    status: str  # unavailable, coarse, bounded
    offset_s: float | None = None  # Aircraft UTC minus timezone-interpreted CSV.
    sensitivity_s: float | None = None
    bound_s: float | None = None
    reason: str = ""
    anchors: int = 0
    anchor_offsets_s: tuple[float, ...] = ()
    anchor_intervals_s: tuple[tuple[float, float], ...] = ()


@dataclass
class EdgeTxOverlay:
    session: EdgeTxSession
    pairing: str  # accepted explicit, accepted automatic, paired but unaligned
    alignment: EdgeTxAlignment
    warnings: list[str] = field(default_factory=list)
    episode_context: dict[int, str] = field(default_factory=dict)
    episode_rf: dict[int, dict[str, tuple[float, float]]] = field(default_factory=dict)


def _local_epoch(clock: datetime, local_zone: tzinfo | None) -> float:
    # None uses the machine's local timezone for this CSV date, including DST.
    return clock.replace(tzinfo=local_zone).timestamp() if local_zone else clock.timestamp()


def _session_window(session: EdgeTxSession, flight_log, clock: GpsClock,
                    offset_s: float, local_zone: tzinfo | None) -> EdgeTxSession:
    """Exclude unrelated file runs far outside the mapped aircraft session."""
    end_us = flight_log.metadata.get("last_decoded_time_us")
    if not isinstance(end_us, (int, float)) or not math.isfinite(end_us):
        end_s = clock.last_boot_s
    else:
        end_s = max(float(end_us) / 1e6, clock.last_boot_s)
    start_utc = clock.utc_at(0).timestamp() - offset_s - 60
    end_utc = clock.utc_at(end_s).timestamp() - offset_s + 60
    selected = [row for row in session.rows if start_utc <= _local_epoch(
        row.clock, local_zone) <= end_utc]
    if not selected:
        return session
    return EdgeTxSession(session.path, session.header, selected, _runs(selected),
                         session.source_row_count or len(session.rows))


def _coordinate_offsets(clock: GpsClock, session: EdgeTxSession,
                        local_zone: tzinfo | None) -> list[tuple[datetime, float]]:
    """Use rare matching aircraft coordinates as a coarse, held-data diagnostic."""
    bins: dict[tuple[float, float], list[float]] = {}
    for anchor in clock.anchors:
        if anchor.coordinate is not None:
            bins.setdefault(anchor.coordinate, []).append(anchor.utc_s)
    first_csv: dict[tuple[float, float], datetime] = {}
    for row in session.rows:
        if row.gps is not None and row.availability == "active":
            first_csv.setdefault(row.gps, row.clock)
    offsets = []
    for coordinate, csv_time in first_csv.items():
        candidates = bins.get(coordinate, [])
        if len(candidates) == 1:
            offsets.append((csv_time, candidates[0] - _local_epoch(csv_time, local_zone)))
    return offsets


def _cluster_offset(
    offsets: list[tuple[datetime, float]],
) -> tuple[float, tuple[float, ...]] | None:
    if len(offsets) < 2:
        return None
    values = [value for _, value in offsets]
    # A dense five-second neighborhood beats isolated repeated-coordinate aliases.
    clusters = [(sum(abs(other - value) <= 3 for other in values), value)
                for value in values]
    count, center = max(clusters, key=lambda item: item[0])
    selected = [value for value in values if abs(value - center) <= 3]
    return (median(selected), tuple(selected)) if count >= 2 else None


def _event_pattern(result, flight_log, session: EdgeTxSession) -> bool:
    """Require more than a lone generic gap for automatic correlation."""
    episodes = [episode for episode in result.episodes
                if episode.start and episode.armed.startswith("armed")]
    gaps = [run for run in session.runs if run.availability == "unavailable"
            and (run.end - run.start).total_seconds() >= 1]
    active = [run for run in session.runs if run.availability == "active"]
    if episodes and len(gaps) >= 2 and len(active) >= 2:
        return True
    # A split recovery file may have one return and two matching MODE states.
    bin_modes = []
    for record in flight_log.get("MODE").to_dict("records"):
        try:
            name = mode_name(int(record["ModeNum"]))
        except (KeyError, ValueError, TypeError):
            continue
        if not bin_modes or bin_modes[-1] != name:
            bin_modes.append(name)
    csv_modes = []
    for row in session.rows:
        name = {"MANU": "MANUAL", "CIRC": "CIRCLE"}.get(row.fm, row.fm)
        if name and (not csv_modes or csv_modes[-1] != name):
            csv_modes.append(name)
    iterator = iter(bin_modes)
    return bool(episodes and len(csv_modes) >= 2 and
                all(any(candidate == name for candidate in iterator)
                    for name in csv_modes))


def _wall_overlap(clock: GpsClock | None, session: EdgeTxSession,
                  local_zone: tzinfo | None) -> bool:
    if clock is None:
        return False
    start = _local_epoch(session.rows[0].clock, local_zone)
    end = _local_epoch(session.rows[-1].clock, local_zone)
    first = clock.utc_at(clock.first_boot_s).timestamp()
    last = clock.utc_at(clock.last_boot_s).timestamp()
    # This proposes a candidate only; it does not prove radio synchronization.
    return start <= last + 60 and end >= first - 60 and end > first and start < last


def _pattern_overlap(result, session: EdgeTxSession, clock: GpsClock,
                     local_zone: tzinfo | None, offset_s: float) -> bool:
    """Validate an automatic candidate without equating gap edges to RC edges."""
    gaps = [(run.start, run.end) for run in session.runs
            if run.availability == "unavailable" and run.count >= 2]
    overlapping = set()
    for episode in result.episodes:
        if not episode.start or not episode.revalid or not episode.armed.startswith("armed"):
            continue
        projection = _csv_interval(
            episode, clock, EdgeTxAlignment("coarse", offset_s), local_zone)
        if projection is None:
            continue
        start, end = projection
        for index, (gap_start, gap_end) in enumerate(gaps):
            if max(start, gap_start) < min(end, gap_end):
                overlapping.add(index)
    return bool(overlapping)


def bounded_alignment(clock: GpsClock, anchors: list[AlignmentAnchor],
                      local_zone: tzinfo | None = None) -> EdgeTxAlignment:
    """Intersect two-plus independent, separated, explicitly lag-bounded anchors."""
    if len(anchors) < 2 or max(a.bin_boot_s for a in anchors) - min(
            a.bin_boot_s for a in anchors) < 10:
        return EdgeTxAlignment("unavailable", reason="fewer than two separated landmarks")
    intervals = []
    offsets = []
    for anchor in anchors:
        if not (math.isfinite(anchor.lag_bound_s) and anchor.lag_bound_s >= 0):
            return EdgeTxAlignment("unavailable", reason="landmark latency unbounded")
        center = clock.utc_at(anchor.bin_boot_s).timestamp() - _local_epoch(
            anchor.csv_clock, local_zone)
        offsets.append(center)
        intervals.append((center - anchor.lag_bound_s, center + anchor.lag_bound_s))
    low, high = max(x[0] for x in intervals), min(x[1] for x in intervals)
    if low > high:
        return EdgeTxAlignment("unavailable", reason="landmark offsets disagree")
    return EdgeTxAlignment("bounded", (low + high) / 2, bound_s=(high - low) / 2,
                           reason="independent lag-bounded landmarks", anchors=len(anchors),
                           anchor_offsets_s=tuple(offsets),
                           anchor_intervals_s=tuple(intervals))


def analyse_edgetx(result, flight_log, session: EdgeTxSession, *,
                   explicit: bool = True, local_zone: tzinfo | None = None,
                   anchors: list[AlignmentAnchor] | None = None,
                   sample_age_bound_s: float | None = None) -> EdgeTxOverlay:
    """Produce a read-only overlay; no BIN episode or detector field is changed."""
    clock = gps_clock_from_flight(flight_log)
    warnings = ["CSV timezone assumed to be this computer's local timezone"
                if local_zone is None else "CSV timezone supplied by caller"]
    if clock is None:
        warnings.append("aircraft GPS absolute time unavailable; episode alignment unavailable")
    offsets = _coordinate_offsets(clock, session, local_zone) if clock else []
    cluster = _cluster_offset(offsets)
    pattern = _event_pattern(result, flight_log, session)
    wall_overlap = _wall_overlap(clock, session, local_zone)
    if not explicit:
        if clock is None or not pattern or not (wall_overlap or cluster):
            return EdgeTxOverlay(
                session, "unpaired", EdgeTxAlignment("unavailable"),
                warnings + ["automatic pairing ambiguous: wall/coordinate "
                            "and event pattern insufficient"],
            )
        if cluster and abs(cluster[0]) > 120 and not wall_overlap:
            return EdgeTxOverlay(
                session, "unpaired", EdgeTxAlignment("unavailable"),
                warnings + ["automatic pairing rejected: radio wall clock disagrees"],
            )
        proposed_offset = cluster[0] if cluster else 0
        if not _pattern_overlap(result, session, clock, local_zone, proposed_offset):
            return EdgeTxOverlay(
                session, "unpaired", EdgeTxAlignment("unavailable"),
                warnings + ["automatic pairing ambiguous: no overlapping loss pattern"],
            )
        pairing = "accepted automatic"
    else:
        pairing = "accepted explicit" if pattern or cluster else "paired but unaligned"
        if not (pattern or cluster):
            warnings.append("explicit pair has insufficient independent session evidence")
    if cluster:
        offset, samples = cluster
        if abs(offset) > 120:
            warnings.append(
                f"radio clock discrepancy about {offset:.0f} s "
                "(aircraft UTC minus CSV clock)"
            )
        alignment = EdgeTxAlignment(
            "coarse", offset, sensitivity_s=3,
            reason="aircraft GPS coordinate echoes; telemetry age unbounded",
            anchors=len(samples), anchor_offsets_s=samples,
        )
    else:
        alignment = EdgeTxAlignment("unavailable", reason="no unique GPS/CSV clock landmarks")
    if clock and anchors:
        verified = bounded_alignment(clock, anchors, local_zone)
        if verified.status == "bounded":
            alignment = verified
        else:
            warnings.append(verified.reason)
    if alignment.status == "unavailable":
        warnings.append(f"episode alignment unavailable: {alignment.reason}")
    if clock and alignment.offset_s is not None and pairing != "unpaired":
        selected = _session_window(session, flight_log, clock,
                                   alignment.offset_s, local_zone)
        if len(selected.rows) < len(session.rows):
            warnings.append(
                f"{len(session.rows) - len(selected.rows)} CSV rows outside GPS-mapped "
                "aircraft session window excluded from RF summary; partial file coverage"
            )
        session = selected
    overlay = EdgeTxOverlay(session, pairing, alignment, warnings)
    if pairing == "paired but unaligned" or pairing == "unpaired" or clock is None:
        return overlay
    if any(
        (interval := _csv_interval(episode, clock, alignment, local_zone)) is not None
        and (session.rows[0].clock > interval[0] or session.rows[-1].clock < interval[1])
        for episode in result.episodes
    ):
        overlay.warnings.append(
            "CSV covers only part of a BIN episode; missing interval is not a measured RF outage"
        )
    _add_episode_context(overlay, result, clock, local_zone)
    if (alignment.status == "bounded" and sample_age_bound_s is not None
            and math.isfinite(sample_age_bound_s) and sample_age_bound_s >= 0):
        _add_episode_rf(overlay, result, clock, local_zone, sample_age_bound_s)
    elif alignment.status == "bounded":
        overlay.warnings.append("numeric RF aggregation withheld: sample age unbounded")
    return overlay


def _csv_interval(episode, clock: GpsClock, alignment: EdgeTxAlignment,
                  local_zone: tzinfo | None) -> tuple[datetime, datetime] | None:
    if not episode.start or not episode.revalid or alignment.offset_s is None:
        return None
    # UTC epoch arithmetic to avoid local DST ambiguities in the comparison.
    start = clock.utc_at(episode.start.time_us / 1e6).timestamp() - alignment.offset_s
    end = clock.utc_at(episode.revalid.time_us / 1e6).timestamp() - alignment.offset_s
    if local_zone is None:
        return datetime.fromtimestamp(start), datetime.fromtimestamp(end)
    return (datetime.fromtimestamp(start, tz=local_zone).replace(tzinfo=None),
            datetime.fromtimestamp(end, tz=local_zone).replace(tzinfo=None))


def _add_episode_context(overlay: EdgeTxOverlay, result, clock: GpsClock,
                         local_zone: tzinfo | None) -> None:
    uncertainty = (overlay.alignment.bound_s if overlay.alignment.status == "bounded"
                   else overlay.alignment.sensitivity_s)
    if uncertainty is None:
        return
    for index, episode in enumerate(result.episodes, start=1):
        interval = _csv_interval(episode, clock, overlay.alignment, local_zone)
        if interval is None:
            continue
        start, end = interval
        context = []
        for run in overlay.session.runs:
            if run.availability != "unavailable":
                continue
            if run.start + timedelta(seconds=uncertainty) <= start and \
                    end <= run.end - timedelta(seconds=uncertainty):
                qualifier = (f"±{uncertainty:g} s offset sensitivity (not a proven bound)"
                             if overlay.alignment.status == "coarse" else
                             f"±{uncertainty:g} s bounded offset")
                context.append(
                    f"EdgeTX CSV telemetry unavailable throughout projected BIN episode "
                    f"under {qualifier}; not a measured RF-loss interval"
                )
                break
        for run in overlay.session.runs:
            if run.availability != "active":
                continue
            if ((run.end - run.start).total_seconds() >= 10 and
                    timedelta(seconds=uncertainty) < start - run.end <=
                    timedelta(seconds=10)):
                lead_in = [row for row in overlay.session.rows
                           if run.end - timedelta(seconds=30) <= row.clock <= run.end]
                quality = overlay.session.extrema("RQly(%)", lead_in)
                rssi = overlay.session.extrema("1RSS(dB)", lead_in)
                if quality and rssi:
                    context.append(
                        "EdgeTX CSV pre-episode lead-in (final 30 s before telemetry "
                        f"disappearance): RQly {quality[0]:g}–{quality[1]:g}%, "
                        f"1RSS {rssi[0]:g}–{rssi[1]:g} dBm; values may be held"
                    )
                break
        if not context:
            for run in overlay.session.runs:
                if (run.availability == "active" and
                        abs((run.start - end).total_seconds()) <= uncertainty):
                    context.append(
                        "EdgeTX CSV telemetry return near projected BIN recovery; "
                        "numeric RF episode membership withheld"
                    )
                    break
        if context:
            overlay.episode_context[index] = "; ".join(context)


def _add_episode_rf(overlay: EdgeTxOverlay, result, clock: GpsClock,
                    local_zone: tzinfo | None, sample_age_bound_s: float) -> None:
    alignment = overlay.alignment
    assert alignment.offset_s is not None and alignment.bound_s is not None
    for index, episode in enumerate(result.episodes, start=1):
        if not episode.start or not episode.revalid:
            continue
        start = clock.utc_at(episode.start.time_us / 1e6).timestamp()
        end = clock.utc_at(episode.revalid.time_us / 1e6).timestamp()
        included = []
        for row in overlay.session.rows:
            if row.availability != "active":
                continue
            nominal = _local_epoch(row.clock, local_zone) + alignment.offset_s
            # The RF value may be older than the CSV row by the calibrated bound.
            if (nominal - alignment.bound_s - sample_age_bound_s > start and
                    nominal + alignment.bound_s < end):
                included.append(row)
        values = {field: observed for field in ("RQly(%)", "1RSS(dB)", "RSNR(dB)")
                  if (observed := overlay.session.extrema(field, included)) is not None}
        if values:
            overlay.episode_rf[index] = values
