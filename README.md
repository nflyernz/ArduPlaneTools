# ArduPlaneTools (APT)

ArduPlaneTools (APT) is a Python application for evidence-based analysis of
ArduPlane flight logs. It reads ArduPlane DataFlash BIN logs and, where a
workflow supports it, EdgeTX transmitter CSV recordings. See the
[illustrated APT Wiki](https://github.com/nflyernz/ArduPlaneTools/wiki) for
step-by-step module guides, screenshots and reference material.

APT focuses on ArduPlane 4.7.x evidence. It provides a native PySide6 desktop
interface and a terminal interface. Reports preserve missing or ambiguous
evidence instead of filling gaps with assumptions.

## Features

### Battery & packs

- **Battery Analysis** — Examines flight-scoped battery consumption, voltage
  sag, current, power, capacity and configured voltage margins from a selected
  BIN log. The GUI analysis is read-only.
- **Battery Pack Management** — Assigns physical Pack IDs to BIN-log
  fingerprints, renames packs and records supported AUTO-takeoff observations
  into battery history after confirmation.
- **Pack Performance** — Compares saved observations for a selected physical
  pack across logs, including first takeoffs by session and all retained AUTO
  takeoffs. It does not require a selected BIN and does not calculate a battery
  health score.

### Flight analysis

- **TAKEOFF** — Reviews TAKEOFF-mode triggers, execution stages, completion or
  mode-exit censoring, and associated logged performance evidence.
- **Landing** — Separates approach, preflare, flare, optional rangefinder and
  landing or rollout-completion evidence for detected landing attempts.
- **AUTOTUNE** — Examines recorded tuning sessions, active axes, gain changes,
  limits, completion milestones and save or restore evidence.
- **Stall** — Reviews deliberate FBWA slow-flight attempts and probable
  demand-opposed attitude departures. A reported departure does not prove an
  aerodynamic stall or establish a stall speed.
- **Events** — Presents supported firmware messages, landing-stage changes and
  flight-mode records chronologically within each detected flight.

### Radio & diagnostics

- **Radio Link** — Identifies aircraft-side RC failsafe episodes and response
  from BIN evidence. Optional EdgeTX CSV evidence is kept separate and is added
  only with explicit pairing and alignment qualifications.
- **Range-Walk Comparison** — Detects deliberate transmitter marker holds,
  saves a five-landmark Walk 1 baseline and later walks, and compares four
  route sections using qualified RSSI, link-quality, SNR and coverage evidence.

## Requirements

- **Python 3.13** (the normal, GIL-enabled build)
- A source checkout or downloaded source archive
- Enough free disk space for Python packages, logs and any saved history

`requirements-gui.txt` installs the complete GUI environment. It includes
`requirements.txt` plus PySide6 6.12.0. The pinned runtime packages are:

```text
contourpy 1.3.3          MAVProxy 1.8.74       pyserial 3.5
cycler 0.12.1           numpy 2.5.0            python-dateutil 2.9.0.post0
fastcrc 0.3.6           packaging 26.2         PyYAML 6.0.3
fonttools 4.63.0        pandas 3.0.3           six 1.17.0
kiwisolver 1.5.0        pillow 12.3.0          PySide6 6.12.0
lxml 6.1.1              pymavlink 2.4.49
matplotlib 3.11.0       pynmeagps 1.1.5
                        pyparsing 3.3.2
```

The native GUI has been developed and validated on macOS. The automated base
test suite also runs on Ubuntu with Python 3.13. Windows has not yet received
equivalent project validation; its instructions below describe the intended
portable setup and should be treated as requiring confirmation on the target
computer.

APT is currently distributed as source code. There is no installer, DMG,
signed application or published binary release.

## Installation on macOS

These steps use a ZIP download. You do not need a GitHub account, Git or prior
command-line experience. Complete steps 1–10 once.

1. Open the [ArduPlaneTools repository](https://github.com/nflyernz/ArduPlaneTools)
   in a web browser.
2. Select the green **Code** button above the repository file list.
3. Select **Download ZIP**.
4. Open **Finder**, select **Downloads**, and double-click the downloaded ZIP
   if macOS has not already extracted it. The resulting folder is normally
   named `ArduPlaneTools-main`.
5. Download the **macOS installer** for
   [Python 3.13.16](https://www.python.org/downloads/release/python-31316/)
   from Python.org. Open the downloaded package and follow its installer. Use
   the standard Python build, not the experimental free-threaded build.
6. Open **Terminal**: press Command-Space, type `Terminal`, then press Return.
7. Change into the extracted folder. If it is in Downloads, copy and paste:

   ```bash
   cd ~/Downloads/ArduPlaneTools-main
   ```

   `cd` means “change directory.” If you moved or renamed the folder, type
   `cd ` with a trailing space, drag the folder from Finder into Terminal, and
   press Return.
8. Create APT's isolated Python environment:

   ```bash
   python3.13 -m venv venv
   ```

   A virtual environment is a private set of Python packages stored inside the
   APT folder. It avoids changing packages used by other applications.
9. Install the GUI and analysis dependencies:

   ```bash
   venv/bin/python -m pip install --upgrade pip
   venv/bin/python -m pip install -r requirements-gui.txt
   ```

10. Launch the desktop GUI:

    ```bash
    venv/bin/python Scripts/gui_app.py
    ```

### Starting APT again on macOS

On subsequent days, open Terminal and run only:

```bash
cd ~/Downloads/ArduPlaneTools-main
venv/bin/python Scripts/gui_app.py
```

If the folder is elsewhere, use its actual path in the `cd` command. Keep the
folder intact because it contains the virtual environment and APT's saved data.

To use the optional terminal interface instead of the GUI:

```bash
venv/bin/python Scripts/analyse.py
```

## Installation on Windows

Windows support has not yet been validated to the same level as macOS. These
steps use standard portable Python and Qt commands and are the intended setup
for testing. Complete steps 1–10 once.

1. Open the [ArduPlaneTools repository](https://github.com/nflyernz/ArduPlaneTools)
   in a web browser.
2. Select the green **Code** button, then select **Download ZIP**. No GitHub
   account is required.
3. Open **File Explorer** and select **Downloads**.
4. Right-click the downloaded ZIP, choose **Extract All…**, retain the proposed
   destination, and select **Extract**. The folder is normally named
   `ArduPlaneTools-main`.
5. Open the [Python 3.13.16 download page](https://www.python.org/downloads/release/python-31316/).
   Scroll down to **Files** and select **Windows installer (64-bit)**. Do not
   select the Python install manager button near the top of the page. Run the
   downloaded installer, keep the **Python launcher** enabled, and select
   **Add python.exe to PATH** if offered. Complete the standard installation;
   do not select the experimental free-threaded build.
6. Open **Command Prompt**: open the Start menu, type `Command Prompt`, and
   select it.
7. Change into the extracted folder. For the normal Downloads location, copy
   and paste:

   ```bat
   cd /d "%USERPROFILE%\Downloads\ArduPlaneTools-main"
   ```

   If you chose another destination, type `cd /d ` followed by the full folder
   path in quotation marks.
8. Create APT's isolated Python environment:

   ```bat
   py -3.13 -m venv venv
   ```

9. Install the GUI and analysis dependencies:

   ```bat
   venv\Scripts\python.exe -m pip install --upgrade pip
   venv\Scripts\python.exe -m pip install -r requirements-gui.txt
   ```

10. Launch the desktop GUI:

    ```bat
    venv\Scripts\python.exe Scripts\gui_app.py
    ```

### Starting APT again on Windows

On subsequent days, open Command Prompt and run only:

```bat
cd /d "%USERPROFILE%\Downloads\ArduPlaneTools-main"
venv\Scripts\python.exe Scripts\gui_app.py
```

To use the optional terminal interface instead of the GUI:

```bat
venv\Scripts\python.exe Scripts\analyse.py
```

## Installation from a Git checkout

People who already use Git may clone the repository instead of downloading a
ZIP, then run the same platform-specific virtual-environment and installation
commands from the cloned `ArduPlaneTools` directory:

```bash
git clone https://github.com/nflyernz/ArduPlaneTools.git
cd ArduPlaneTools
```

Git is optional and is not required for normal ZIP installation.

## Troubleshooting installation

### “Python was not found” or “command not found”

- On macOS, close and reopen Terminal after installing Python, then try
  `python3.13 --version`. If it still fails, reinstall Python 3.13 from the
  Python.org macOS package.
- On Windows, close and reopen Command Prompt, then try `py -3.13 --version`.
  If that fails, rerun the Python installer and enable its PATH or launcher
  option.

The version command should report `Python 3.13.x` before you create the virtual
environment.

### “No such file or directory” or “The system cannot find the path”

The `cd` command does not point to the extracted APT folder. Find
`ArduPlaneTools-main` in Finder or File Explorer and use its actual location.
Confirm that the folder contains `README.md`, `requirements-gui.txt` and the
`Scripts` directory.

### Dependency installation fails

Check that the command prompt is inside the APT folder and that the virtual
environment was created successfully. Then rerun the pip-upgrade command,
followed by the `requirements-gui.txt` installation command for your platform.
An internet connection is required while pip downloads packages. Read the last
error lines: security software, a proxy, insufficient disk space or an
unsupported Python version can prevent installation. Do not continue to the
launch command until installation finishes without an error.

## Running APT

The GUI entry point is `Scripts/gui_app.py`. Choose **Source BIN** for analyses
that use an ArduPlane DataFlash log. Range-Walk Comparison selects EdgeTX CSV
files within its own page, and Pack Performance reads previously saved history.

Quick Start:

1. Start the GUI with the command for your platform.
2. Select a BIN log when the module requires one.
3. Choose a module from **Overview** or the tabs.
4. Select **Analyse**, or use the action named on that module's page.
5. Read the report, evidence qualifications and any unavailable-data notices.

The optional terminal entry point is `Scripts/analyse.py`. It provides the
existing text menu and interactive selectors for supported workflows.

## Documentation

Every GUI module provides **Docs** with workflow and interpretation guidance.
Radio Link, Range-Walk Comparison and Stall also provide dedicated **Test
Procedure** guidance where deliberate testing needs additional preparation.

The project [GitHub Wiki](https://github.com/nflyernz/ArduPlaneTools/wiki) is
the intended home of the detailed illustrated manual. It is being prepared
separately; this README does not assume that particular Wiki chapters are
already published.

Repository documentation also includes the current
[validation record](Docs/Validation.md) and the
[Stall Analysis guide](Docs/Stall_Analysis_Guide.md).

## Data, privacy and limitations

APT reads source logs locally. Flight logs can contain sensitive information,
including GPS coordinates, routes, timestamps and aircraft configuration. Take
care before sharing a BIN, CSV, report or backup.

Persistent records are stored relative to the APT folder:

- `Data/battery_packs.json` — Pack IDs and BIN-log associations.
- `Data/battery_pack_history.json` — recorded supported battery observations.
- `Data/range_walk_history.json` — saved Range-Walk metadata and mappings.
- `Data/range_walk_csv/` — checksum-named managed copies of saved Range-Walk
  CSV evidence.

Back up the `Data` folder if these records matter to you. Restoring or replacing
the application folder without it can lose the saved associations and history.
The source BIN files are not embedded in battery history; Range-Walk explicitly
preserves managed CSV evidence for reconstruction.

APT reports what supported logged evidence establishes. Missing telemetry is
reported as unavailable and is not replaced with zero or inferred values.
Commands and logged states are not necessarily physical feedback. Results are
analysis evidence, not flight-safety certification, maintenance approval or a
substitute for pilot judgement and safe test planning.

## Project status

The planned APT v1.0 feature set is complete in the source repository. The
current focus is documentation, review and release preparation.

APT remains focused on the validated ArduPlane 4.7.x evidence model. Broader
firmware compatibility, complete Windows validation and packaged desktop
distribution have not yet been established.
