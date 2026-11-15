#!/usr/bin/env python3
"""Validate and migrate legacy repository-local APT persistent data."""

import argparse
from pathlib import Path

from core.data_migration import DataMigrationError, migrate_persistent_data


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate an explicit legacy APT Data directory.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Existing repository-local Data directory",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        help=(
            "Destination application-data directory "
            "(defaults to this platform's APT directory)"
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report the migration without writing",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Validate, stage, revalidate, and publish the migration",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the explicit migration command."""
    arguments = _parser().parse_args(argv)
    try:
        result = migrate_persistent_data(
            arguments.source,
            arguments.destination,
            apply=arguments.apply,
        )
    except DataMigrationError as exc:
        print(f"Migration refused: {exc}")
        return 1

    action = "Migrated" if result.applied else "Validated dry run for"
    print(f"{action} {result.source} -> {result.destination}")
    for relative_path in result.relative_paths:
        print(f"  {relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
