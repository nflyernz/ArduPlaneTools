[CmdletBinding()]
param(
    [string]$PythonExecutable = "python",
    [string]$BuildRoot = $(
        if ($env:APT_BUILD_ROOT) {
            $env:APT_BUILD_ROOT
        }
        else {
            Join-Path ([System.IO.Path]::GetTempPath()) "ArduPlaneTools-windows-build"
        }
    ),
    [string]$PackagingEnvironment = $(
        if ($env:APT_PACKAGING_VENV) {
            $env:APT_PACKAGING_VENV
        }
        else {
            Join-Path ([System.IO.Path]::GetTempPath()) "ArduPlaneTools-pyinstaller-venv"
        }
    )
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw "The Windows preview build requires an x64 operating system and Python process."
}

$packagingDirectory = $PSScriptRoot
$workDirectory = Join-Path $BuildRoot "work"
$distributionDirectory = Join-Path $BuildRoot "dist"
$configurationDirectory = Join-Path $BuildRoot "pyinstaller-config"
$venvPython = Join-Path $PackagingEnvironment "Scripts\python.exe"
$pyinstaller = Join-Path $PackagingEnvironment "Scripts\pyinstaller.exe"
$requirements = Join-Path $packagingDirectory "requirements-windows-build.txt"
$specification = Join-Path $packagingDirectory "ArduPlaneTools-Windows.spec"
$application = Join-Path $distributionDirectory "ArduPlaneTools\ArduPlaneTools.exe"

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    & $PythonExecutable -m venv $PackagingEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the dedicated packaging environment."
    }
}

& $venvPython -m pip install --requirement $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Unable to install the pinned packaging dependencies."
}

& $venvPython -c "import platform, struct; assert struct.calcsize('P') == 8 and platform.machine().endswith('64')"
if ($LASTEXITCODE -ne 0) {
    throw "The packaging environment is not using x64 Python."
}

New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
$env:PYINSTALLER_CONFIG_DIR = $configurationDirectory

$buildInformation = @(
    "application=ArduPlaneTools"
    "architecture=$([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture)"
    "windows=$([Environment]::OSVersion.VersionString)"
    "python=$(& $venvPython --version 2>&1)"
    "pyinstaller=$(& $pyinstaller --version)"
)
Set-Content -LiteralPath (Join-Path $BuildRoot "build-info.txt") -Value $buildInformation

& $pyinstaller `
    --noconfirm `
    --clean `
    --workpath $workDirectory `
    --distpath $distributionDirectory `
    $specification
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}

if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "Windows application was not created at $application"
}

Write-Host "Built $application"
