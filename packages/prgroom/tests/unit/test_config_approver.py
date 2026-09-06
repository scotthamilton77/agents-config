"""The approver block's parse: what it accepts, and every way it refuses.

The block names the identity that signs off on merges, so a wrong or drifted
value must stop the verb rather than resolve to something plausible.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

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
    with pytest.raises(ValueError, match="key-path-env"):
        ApproverConfig.load(write_config(tmp_path, approver_block(**{"key-path-env": DROP})))


def test_other_merge_policy_keys_are_ignored_not_rejected(tmp_path: Path) -> None:
    # The approver reader owns its own sub-table only; the rest of the merge
    # policy is somebody else's vocabulary and must not trip this parse.
    approver = ApproverConfig.load(write_config(tmp_path, VALID))
    assert approver.app_id == 4275336


# Every approver row below is a complete, valid block apart from the one field
# it names, so a row cannot pass on a defect other than its own.
DROP = object()
VALID_APPROVER: dict[str, Any] = {
    "type": "github-app",
    "app-id": 7,
    "key-path-env": "APP_KEY",
}


def approver_block(**overrides: Any) -> str:
    fields = {**VALID_APPROVER, **overrides}
    body = "\n".join(
        f"{key} = {json.dumps(value)}" for key, value in fields.items() if value is not DROP
    )
    return f"[merge-policy.approver]\n{body}\n"


@pytest.mark.parametrize(
    ("case", "body"),
    [
        ("no file at all", None),
        ("no merge-policy table", "other = 1\n"),
        ("merge-policy without an approver", '[merge-policy]\nmerge-authorization = "explicit"\n'),
        ("a merge-policy that is not a table", 'merge-policy = "explicit"\n'),
        ("an approver that is not a table", '[merge-policy]\napprover = "github-app"\n'),
        ("a wrong approver type", approver_block(**{"type": "oauth-app"})),
        ("a missing type", approver_block(**{"type": DROP})),
        ("a missing app-id", approver_block(**{"app-id": DROP})),
        ("a zero app-id", approver_block(**{"app-id": 0})),
        ("a negative app-id", approver_block(**{"app-id": -3})),
        ("a string app-id", approver_block(**{"app-id": "7"})),
        ("a boolean app-id", approver_block(**{"app-id": True})),
        ("a float app-id", approver_block(**{"app-id": 7.0})),
        ("an array app-id", approver_block(**{"app-id": [7]})),
        ("a table app-id", approver_block(**{"app-id": {"n": 7}})),
        ("a non-string env var name", approver_block(**{"key-path-env": 5})),
        ("a missing env var name", approver_block(**{"key-path-env": DROP})),
        ("an unknown key", approver_block(**{"private-key": "/k.pem"})),
    ],
)
def test_a_malformed_block_is_refused(case: str, body: str | None, tmp_path: Path) -> None:
    assert case  # names the case in the failure output
    path = tmp_path / "project-config.toml" if body is None else write_config(tmp_path, body)
    with pytest.raises(ValueError):  # the loader's uniform type; the message varies by case
        ApproverConfig.load(path)


def test_an_otherwise_valid_block_built_the_same_way_is_accepted(tmp_path: Path) -> None:
    # Guards the builder: if it emitted something the reader refuses, every row
    # above would pass without testing the defect it names.
    approver = ApproverConfig.load(write_config(tmp_path, approver_block()))
    assert (approver.app_id, approver.key_path_env) == (7, "APP_KEY")


def test_the_refusal_message_names_the_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="private-key"):
        ApproverConfig.load(write_config(tmp_path, approver_block(**{"private-key": "/k.pem"})))


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


# The grammar the reader enforces is `[A-Za-z_][A-Za-z0-9_]*`. Pinning only the
# refusals would leave a reader narrowed to uppercase looking correct while it
# rejected every legal lowercase name.
ACCEPTED_ENV_NAMES = ["lower_case", "MiXeDcAsE", "_leading_underscore", "A1", "x9_8y", "A", "_"]
REJECTED_ENV_NAMES = ["9BAD", "9-BAD", "GOOD-NAME", "APP.KEY", "APP KEY", "", "1234", "a-b"]


def approver_with_env_name(tmp_path: Path, name: str) -> Path:
    body = f'[merge-policy.approver]\ntype = "github-app"\napp-id = 7\nkey-path-env = "{name}"\n'
    return write_config(tmp_path, body)


@pytest.mark.parametrize("name", ACCEPTED_ENV_NAMES)
def test_a_legal_env_var_name_is_accepted_unchanged(name: str, tmp_path: Path) -> None:
    assert ApproverConfig.load(approver_with_env_name(tmp_path, name)).key_path_env == name


@pytest.mark.parametrize("name", REJECTED_ENV_NAMES)
def test_an_illegal_env_var_name_is_refused(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="key-path-env"):
        ApproverConfig.load(approver_with_env_name(tmp_path, name))
