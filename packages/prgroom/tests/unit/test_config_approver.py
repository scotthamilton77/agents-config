"""The approver block's parse: what it accepts, and every way it refuses.

The block names the identity that signs off on merges, so a wrong or drifted
value must stop the verb rather than resolve to something plausible.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from prgroom.config import ApproverConfig

VALID = """
[merge-policy]
merge-authorization = "explicit"

[merge-policy.approver]
type         = "github-app"
app-id       = 4275336
key-path-env = "APPROVER_KEY_PATH"
"""


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "project-config.toml"
    path.write_text(body)
    return path


def test_a_valid_block_yields_the_app_id_and_env_var_name(tmp_path: Path) -> None:
    approver = ApproverConfig.load(write_config(tmp_path, VALID))
    assert approver.app_id == 4275336
    assert approver.key_path_env == "APPROVER_KEY_PATH"


def test_key_path_env_is_required_with_no_code_side_default(tmp_path: Path) -> None:
    # A default here would put the key's env-var name in two places and let a
    # block that never names one still resolve to something.
    body = '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\n'
    with pytest.raises(ValueError, match="key-path-env"):
        ApproverConfig.load(write_config(tmp_path, body))


def test_other_merge_policy_keys_are_ignored_not_rejected(tmp_path: Path) -> None:
    # The approver reader owns its own sub-table only; the rest of the merge
    # policy is somebody else's vocabulary and must not trip this parse.
    approver = ApproverConfig.load(write_config(tmp_path, VALID))
    assert approver.app_id == 4275336


@pytest.mark.parametrize(
    ("case", "body"),
    [
        ("no file at all", None),
        ("no merge-policy table", "other = 1\n"),
        ("merge-policy without an approver", '[merge-policy]\nmerge-authorization = "explicit"\n'),
        (
            "a wrong approver type",
            '[merge-policy.approver]\ntype = "oauth-app"\napp-id = 7\n',
        ),
        ("a missing type", "[merge-policy.approver]\napp-id = 7\n"),
        ("a missing app-id", '[merge-policy.approver]\ntype = "github-app"\n'),
        (
            "a zero app-id",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 0\n',
        ),
        (
            "a negative app-id",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = -3\n',
        ),
        (
            "a non-integer app-id",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = "7"\n',
        ),
        (
            "a boolean app-id",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = true\n',
        ),
        (
            "an env var name starting with a digit",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = "9-BAD"\n',
        ),
        (
            "an env var name with a hyphen after a legal first character",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\n'
            'key-path-env = "GOOD-NAME"\n',
        ),
        (
            "an env var name with a dot",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = "APP.KEY"\n',
        ),
        (
            "an env var name with a space",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = "APP KEY"\n',
        ),
        (
            "an empty env var name",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = ""\n',
        ),
        (
            "a non-string env var name",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = 5\n',
        ),
        (
            "an unknown key",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nprivate-key = "x"\n',
        ),
        (
            "an approver that is not a table",
            '[merge-policy]\napprover = "github-app"\n',
        ),
        ("a merge-policy that is not a table", 'merge-policy = "explicit"\n'),
    ],
)
def test_a_malformed_block_is_refused(case: str, body: str | None, tmp_path: Path) -> None:
    assert case  # names the case in the failure output
    path = tmp_path / "project-config.toml" if body is None else write_config(tmp_path, body)
    with pytest.raises(ValueError):  # the loader's uniform type; the message varies by case
        ApproverConfig.load(path)


def test_the_refusal_message_names_the_unknown_key(tmp_path: Path) -> None:
    body = '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nprivate-key = "x"\n'
    with pytest.raises(ValueError, match="private-key"):
        ApproverConfig.load(write_config(tmp_path, body))


REPO_CONFIG = Path(__file__).parents[4] / "project-config.toml"


@pytest.mark.skipif(
    not REPO_CONFIG.is_file(), reason="installed away from the repository this config belongs to"
)
class TestTheRepositorysOwnConfig:
    """The live block is what `prgroom approve` reads here; a temporary copy is not."""

    def test_it_resolves_to_the_configured_app_and_key_variable(self) -> None:
        approver = ApproverConfig.load(REPO_CONFIG)
        assert approver.app_id == 4275336
        assert approver.key_path_env == "MERGE_GUARD_APPROVER_KEY_PATH"

    def test_the_approver_table_carries_exactly_the_three_keys_the_reader_knows(self) -> None:
        with REPO_CONFIG.open("rb") as fh:
            approver = tomllib.load(fh)["merge-policy"]["approver"]
        assert set(approver) == {"type", "app-id", "key-path-env"}

    def test_merge_authorization_is_still_explicit(self) -> None:
        # The App can satisfy the ruleset's approving review; it does not decide
        # that a merge should happen.
        with REPO_CONFIG.open("rb") as fh:
            assert tomllib.load(fh)["merge-policy"]["merge-authorization"] == "explicit"
