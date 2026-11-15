import pytest

from Packaging.release_version import ReleaseVersion, release_is_enabled


def test_selected_preview_version_maps_to_numeric_macos_versions():
    version = ReleaseVersion.parse("1.1.0-beta.1")

    assert version.tag == "v1.1.0-beta.1"
    assert version.macos_short_version == "1.1.0"
    assert version.macos_bundle_version == "1.1.1"


def test_macos_build_number_distinguishes_patch_and_beta_iterations():
    assert (
        ReleaseVersion.parse("1.1.0-beta.2").macos_bundle_version
        == "1.1.2"
    )
    assert (
        ReleaseVersion.parse("1.1.1-beta.2").macos_bundle_version
        == "1.1.102"
    )


@pytest.mark.parametrize(
    "value",
    (
        "v1.1.0-beta.1",
        "1.1.0",
        "1.1.0-rc.1",
        "1.1.0-beta.0",
        "1.1.0-beta.100",
        "1.01.0-beta.1",
    ),
)
def test_invalid_preview_versions_are_rejected(value):
    with pytest.raises(ValueError, match="version must match"):
        ReleaseVersion.parse(value)


def test_pull_request_never_enables_release_creation():
    assert not release_is_enabled("pull_request", "refs/pull/44/merge", True)


def test_ordinary_manual_build_does_not_enable_release_creation():
    assert not release_is_enabled("workflow_dispatch", "refs/heads/main", False)


def test_explicit_main_manual_request_enables_release_creation():
    assert release_is_enabled("workflow_dispatch", "refs/heads/main", True)


def test_manual_build_from_non_main_branch_is_rejected():
    with pytest.raises(ValueError, match="dispatched from main"):
        release_is_enabled("workflow_dispatch", "refs/heads/release-drafts", False)
