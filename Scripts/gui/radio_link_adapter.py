"""Qt-independent adapter for aircraft-BIN Radio Link analysis."""

from dataclasses import dataclass, field
from pathlib import Path

from analyses.radio_link import (
    _candidate_preview,
    format_edgetx_overlay,
    format_radio_link_report,
    format_radio_link_summary,
)
from core.config import Config
from core.edgetx import EdgeTxOverlay, EdgeTxSession, analyse_edgetx, read_edgetx_csv
from core.log_reader import FlightReader
from core.radio_link import RadioLinkDetector


@dataclass(frozen=True)
class RadioLinkGuiResult:
    """Both existing BIN report views tied to one source file."""

    source_path: Path
    summary: str
    detail: str
    flight_log: object | None = field(default=None, compare=False, repr=False)
    detection: object | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class EdgeTxCandidatePreview:
    """One nearby CSV diagnostic, without accepting a pairing."""

    path: Path
    hint: str
    session: EdgeTxSession | None
    automatic_overlay: EdgeTxOverlay | None

    @property
    def usable(self) -> bool:
        return self.session is not None

    @property
    def automatic_eligible(self) -> bool:
        return (
            self.automatic_overlay is not None
            and self.automatic_overlay.pairing == "accepted automatic"
        )


@dataclass(frozen=True)
class EdgeTxCandidateSet:
    """Nearby diagnostics tied to one cached aircraft BIN result."""

    source_path: Path
    candidates: tuple[EdgeTxCandidatePreview, ...]


@dataclass(frozen=True)
class EdgeTxOverlayRequest:
    """Explicit CSV request tied to one BIN context and GUI generation."""

    context: RadioLinkGuiResult
    csv_path: Path
    request_id: int
    session: EdgeTxSession | None = None


@dataclass(frozen=True)
class EdgeTxGuiOverlay:
    """Formatted optional overlay tied to its BIN, CSV, and request."""

    source_path: Path
    csv_path: Path
    request_id: int
    text: str
    overlay: EdgeTxOverlay


class RadioLinkCsvService:
    """Run existing EdgeTX preview and explicit-overlay semantics."""

    @staticmethod
    def discover(context: RadioLinkGuiResult) -> EdgeTxCandidateSet:
        _require_context(context)
        candidates = []
        for path in sorted(context.source_path.parent.glob("*.csv")):
            session, automatic, hint = _candidate_preview(
                path,
                context.detection,
                context.flight_log,
            )
            candidates.append(
                EdgeTxCandidatePreview(path, hint, session, automatic)
            )
        return EdgeTxCandidateSet(context.source_path, tuple(candidates))

    @staticmethod
    def explicit(request: EdgeTxOverlayRequest) -> EdgeTxGuiOverlay:
        context = request.context
        _require_context(context)
        session = request.session or read_edgetx_csv(request.csv_path)
        overlay = analyse_edgetx(
            context.detection,
            context.flight_log,
            session,
            explicit=True,
        )
        return EdgeTxGuiOverlay(
            context.source_path,
            request.csv_path,
            request.request_id,
            format_edgetx_overlay(overlay),
            overlay,
        )


def analyse_radio_link_log(log_path: Path) -> RadioLinkGuiResult:
    """Read and detect once, then format both existing aircraft-BIN views."""
    path = Path(log_path).resolve()
    config = Config("Config/radio_link.yaml")
    flight_log = FlightReader(path, config=config).read()
    result = RadioLinkDetector().detect(flight_log)
    return RadioLinkGuiResult(
        path,
        format_radio_link_summary(result, path, flight_log),
        format_radio_link_report(result, path),
        flight_log,
        result,
    )


def automatic_overlay_result(
    context: RadioLinkGuiResult,
    candidates: EdgeTxCandidateSet,
    request_id: int,
) -> EdgeTxGuiOverlay | str:
    """Select only one unambiguous existing automatic-pairing result."""
    eligible = [
        candidate for candidate in candidates.candidates
        if candidate.automatic_eligible
    ]
    if len(eligible) != 1:
        if eligible:
            return (
                "Automatic pairing is ambiguous: "
                f"{len(eligible)} candidates qualify. Select one explicitly."
            )
        if not candidates.candidates:
            return "Automatic pairing unavailable: no nearby CSV candidates found."
        return (
            "Automatic pairing unavailable: no candidate has sufficient "
            "independent pairing evidence. Review the candidate diagnostics "
            "or select a CSV explicitly."
        )
    candidate = eligible[0]
    overlay = candidate.automatic_overlay
    assert overlay is not None
    return EdgeTxGuiOverlay(
        context.source_path,
        candidate.path,
        request_id,
        format_edgetx_overlay(overlay),
        overlay,
    )


def _require_context(context: RadioLinkGuiResult) -> None:
    if context.flight_log is None or context.detection is None:
        raise ValueError("Radio Link BIN context is unavailable; analyse the BIN again")
