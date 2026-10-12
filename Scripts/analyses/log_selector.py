"""Shared CLI selection of ArduPilot DataFlash log input."""

from pathlib import Path

_current_directory = Path("Logs")


def discover_logs(directory: Path) -> list[Path]:
    """Return immediate BIN files in deterministic case-insensitive order."""
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".bin"
        ),
        key=lambda path: (path.name.casefold(), path.name),
    )


def select_log_input(*, allow_directory: bool = False) -> list[Path] | None:
    """Select one log, or all logs when directory capability is enabled."""
    global _current_directory

    while True:
        discovery_error: str | None
        try:
            logs = discover_logs(_current_directory)
        except OSError as exc:
            logs = []
            discovery_error = str(exc)
        else:
            discovery_error = None

        _print_options(logs, allow_directory, discovery_error)
        all_option = "A=all, " if allow_directory else ""
        choice = input(
            f"\nEnter log number, {all_option}D=directory, P=path, Q=back: "
        ).strip()
        normalized_choice = choice.casefold()

        if normalized_choice == "q":
            return None
        if normalized_choice == "d":
            entry = input("\nDirectory: ").strip()
            if not entry:
                print("Invalid directory.")
                continue
            directory = Path(entry).expanduser()
            if not directory.is_dir():
                print("Invalid directory.")
                continue
            _current_directory = directory
            continue
        if normalized_choice == "p":
            selection = _manual_path(allow_directory)
            if selection is not None:
                return selection
            continue
        if normalized_choice == "a" and allow_directory:
            if logs:
                return logs
            print("No BIN logs found in this directory.")
            continue

        try:
            index = int(choice)
        except ValueError:
            index = 0
        if 1 <= index <= len(logs):
            return [logs[index - 1]]
        print("Invalid selection.")


def _print_options(
    logs: list[Path],
    allow_directory: bool,
    discovery_error: str | None,
) -> None:
    """Display the current directory and available selector actions."""
    print()
    print("Select log input")
    print("================")
    print()
    print(f"Directory: {_current_directory}")
    print()
    if discovery_error is not None:
        print(f"Unable to list directory: {discovery_error}")
    elif not logs:
        print("No BIN logs found in this directory.")
    else:
        for index, log_path in enumerate(logs, start=1):
            print(f"{index}. {log_path.name}")
    print()
    if allow_directory:
        print("A. Analyse all logs in this directory")
    print("D. Choose another directory")
    print("P. Enter a path manually")
    print("Q. Back")


def _manual_path(allow_directory: bool) -> list[Path] | None:
    """Validate a manually entered file or supported directory."""
    global _current_directory

    entry = input("\nLog file or directory: ").strip()
    if not entry:
        print("No path entered.")
        return None
    path = Path(entry).expanduser()
    if path.is_file():
        if path.suffix.lower() != ".bin":
            print("Log file must have a .bin extension.")
            return None
        return [path]
    if path.is_dir():
        if not allow_directory:
            print("A directory is not valid for this analysis.")
            return None
        _current_directory = path
        try:
            logs = discover_logs(path)
        except OSError as exc:
            print(f"Unable to list directory: {exc}")
            return None
        if not logs:
            print("No BIN logs found in this directory.")
            return None
        return logs
    print("Path not found.")
    return None
