"""Smoke-proves the fixtures stand up a real isolated bd and the driver round-trips."""

from __future__ import annotations

import pytest


@pytest.mark.usefixtures("fresh_install")
def test_fresh_install_is_empty_and_isolated(driver):
    env = driver(["list"])
    assert env["ok"] is True
    assert env["data"]["items"] == []


def test_read_only_corpus_is_seeded(read_only_driver):
    env = read_only_driver(["list"])
    assert env["ok"] is True
    titles = {item["title"] for item in env["data"]["items"]}
    assert {"seed-alpha", "seed-beta", "seed-child"} <= titles
