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
