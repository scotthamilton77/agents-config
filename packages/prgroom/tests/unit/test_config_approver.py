"""The approver block's parse: what it accepts, and every way it refuses.

The block names the identity that signs off on merges, so a wrong or drifted
value must stop the verb rather than resolve to something plausible.
"""

from __future__ import annotations

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
            "an env var name that is not one",
            '[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = "9-BAD"\n',
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
