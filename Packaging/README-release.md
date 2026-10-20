# Desktop preview release automation

The release workflow accepts a desktop preview version in the strict form
`MAJOR.MINOR.PATCH-beta.N`. The GitHub tag and distribution filenames add a
leading `v`; application metadata retains the version without that prefix.

macOS requires numeric bundle versions, so the workflow maps the version as
follows:

| Release value | macOS metadata | `1.1.0-beta.1` |
| --- | --- | --- |
| Full preview version | `APTBuildVersion` | `1.1.0-beta.1` |
| Base application version | `CFBundleShortVersionString` | `1.1.0` |
| Deterministic build version | `CFBundleVersion` | `1.1.1` |

`CFBundleVersion` is `MAJOR.MINOR.(PATCH × 100 + beta iteration)`. The parser
limits the minor, patch and beta components to two digits, keeping the final
build component numeric and within four digits. Changing the beta iteration
therefore always changes the macOS build version.

Pull requests and ordinary manual builds create temporary workflow artifacts
only. A draft prerelease is eligible for creation only when a manual run is
started from `main` with `create_draft_release` selected. The release job checks
that neither the requested tag nor a release using it already exists.

## Published desktop preview

The first published prerelease is
[v1.1.0-beta.1](https://github.com/nflyernz/ArduPlaneTools/releases/tag/v1.1.0-beta.1).
It contains the native macOS ARM64 DMG, portable Windows x64 ZIP, SHA-256
checksum manifest and source-commit build metadata. The source commit is
`3090d5e70d236804545d563117e8909d39b3abe6`.

The application is ad-hoc signed, not Apple-notarized; macOS may require
first-launch approval in System Settings → Privacy & Security. The Windows
package is unsigned and lacks an installer. Native Windows automated analysis
and GUI smoke tests pass, but interactive Windows acceptance is outstanding.

## Preparing the next prerelease

1. Complete and merge reviewed code or documentation changes to `main`.
2. In GitHub **Actions → Release candidate builds**, choose **Run workflow**
   on `main`. Set a new unused `MAJOR.MINOR.PATCH-beta.N` version.
3. Leave **create_draft_release** unchecked for a build-only dry run, or select
   it to create an **unpublished draft prerelease** after both native builds,
   artifact metadata checks and SHA-256 verification pass.
4. Review the draft's source commit, platform assets, `SHA256SUMS.txt`,
   `BUILD-METADATA.txt`, installation notes and limitations. Perform
   appropriate acceptance testing against the exact draft assets.
5. When satisfied, publish the draft manually from GitHub Releases. The
   workflow does not automatically publish a public release.

The workflow will refuse to create a draft for a version whose release or
tag already exists. Do not reuse an existing tag or overwrite an earlier
published release to retry builds. Publishing a draft establishes its Git tag;
the prerelease is not marked as the latest stable version. The existing
`v1.0.0` tag must remain unchanged.

## Stored user data

Reinstalling the application is separate from persistent record management:
macOS uses `~/Library/Application Support/ArduPlaneTools`, Windows uses
`%LOCALAPPDATA%\\ArduPlaneTools`. Legacy repository-local `Data/` records
are not migrated automatically. The optional source utility
`Scripts/migrate_data.py` supports `--dry-run` and `--apply`, but refuses
an already-existing destination; do not merge or overwrite records to force a
migration. Retain backups before changing data.
