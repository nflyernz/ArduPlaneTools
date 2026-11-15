#!/usr/bin/env python3
"""Validate desktop preview versions and derive release build metadata."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re


_PREVIEW_VERSION = re.compile(
    r"^(?P<major>0|[1-9][0-9]{0,3})\."
    r"(?P<minor>0|[1-9][0-9]?)\."
    r"(?P<patch>0|[1-9][0-9]?)-beta\."
    r"(?P<beta>[1-9][0-9]?)$"
)


@dataclass(frozen=True)
class ReleaseVersion:
    """Validated desktop beta version and its platform representations."""

    version: str
    major: int
    minor: int
    patch: int
    beta: int

    @classmethod
    def parse(cls, value: str) -> ReleaseVersion:
        match = _PREVIEW_VERSION.fullmatch(value)
        if match is None:
            raise ValueError(
                "version must match MAJOR.MINOR.PATCH-beta.N without a leading v; "
                "MAJOR supports four digits and the other components support two"
            )
        numbers = {name: int(text) for name, text in match.groupdict().items()}
        return cls(value, **numbers)

    @property
    def tag(self) -> str:
        return f"v{self.version}"

    @property
    def macos_short_version(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def macos_bundle_version(self) -> str:
        build_component = self.patch * 100 + self.beta
        return f"{self.major}.{self.minor}.{build_component}"


def release_is_enabled(
    event_name: str,
    git_ref: str,
    release_requested: bool,
) -> bool:
    """Return whether this run may create a draft release."""

    if event_name == "pull_request":
        return False
    if event_name != "workflow_dispatch":
        raise ValueError(f"unsupported release workflow event: {event_name}")
    if git_ref != "refs/heads/main":
        raise ValueError("manual release-candidate builds must be dispatched from main")
    return release_requested


def _boolean(value: str) -> bool:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _write_github_outputs(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--git-ref", required=True)
    parser.add_argument("--release-requested", required=True, type=_boolean)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()

    version = ReleaseVersion.parse(args.version)
    release_enabled = release_is_enabled(
        args.event_name,
        args.git_ref,
        args.release_requested,
    )
    values = {
        "version": version.version,
        "tag": version.tag,
        "macos_short_version": version.macos_short_version,
        "macos_bundle_version": version.macos_bundle_version,
        "create_draft_release": str(release_enabled).lower(),
    }
    _write_github_outputs(args.github_output, values)
    for name, value in values.items():
        print(f"{name}={value}")


if __name__ == "__main__":
    main()
