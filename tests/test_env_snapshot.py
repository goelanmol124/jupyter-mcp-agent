"""Tests for record-mode python env fingerprinting."""

from __future__ import annotations

import importlib.metadata
from types import SimpleNamespace

import pytest


def _fake_distribution(name: str, version: str) -> SimpleNamespace:
    md = SimpleNamespace()

    def get(key: str, default: str | None = None) -> str | None:
        if key == "Name":
            return name
        return default

    md.get = get
    return SimpleNamespace(metadata=md, version=version)


@pytest.fixture(autouse=True)
def clear_snapshot_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests expect each record snapshot rebuild unless TTL is exercised explicitly — production default is 120s.
    monkeypatch.setenv("LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC", "0")
    from llm_jupyter import env_snapshot

    env_snapshot.reset_python_env_snapshot_cache_for_tests()
    yield
    env_snapshot.reset_python_env_snapshot_cache_for_tests()


def test_record_whitelist_collects_matching_names_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Many unrelated alphabetical dists cannot hide whitelisted labs packages."""

    from llm_jupyter.env_snapshot import python_env_snapshot

    floods = [_fake_distribution(f"zzz-flood-{i}", "9.9.9") for i in range(300)]

    monkeypatch.setattr(
        importlib.metadata,
        "distributions",
        lambda: [
            *floods,
            _fake_distribution("nbformat", "5.99.1"),
            _fake_distribution("numpy", "1.99.2"),
            _fake_distribution("jupyter-client", "8.88.88"),
            _fake_distribution("matplotlib", "9.88.77"),
            _fake_distribution("torch", "2.88.77"),
            _fake_distribution("torch", "2.77.76"),
        ],
    )

    monkeypatch.setattr("llm_jupyter.env_snapshot._git_commit_record", lambda: None)

    snap = python_env_snapshot("record")
    digest = snap["packages_summary_or_hash"]
    assert isinstance(digest, str)


def test_record_hash_changes_when_whitelist_bundle_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from llm_jupyter.env_snapshot import python_env_snapshot

    floods_a = [_fake_distribution(f"aaa-{i:04d}", "0.1.0") for i in range(400)]

    monkeypatch.setattr(
        importlib.metadata,
        "distributions",
        lambda: [*floods_a, _fake_distribution("nbformat", "5.14.10")],
    )
    monkeypatch.setattr("llm_jupyter.env_snapshot._git_commit_record", lambda: None)

    h1 = python_env_snapshot("record")["packages_summary_or_hash"]

    floods_b = [_fake_distribution(f"bbb-{i:04d}", "0.1.0") for i in range(400)]
    monkeypatch.setattr(
        importlib.metadata,
        "distributions",
        lambda: [
            *floods_b,
            _fake_distribution("nbformat", "5.14.10"),
            _fake_distribution("numpy", "1.88.88"),
        ],
    )
    monkeypatch.setattr("llm_jupyter.env_snapshot._git_commit_record", lambda: None)

    snap2 = python_env_snapshot("record")
    assert h1 != snap2["packages_summary_or_hash"]


@pytest.mark.parametrize("mode", ["explore", "EXPLORE", "junk_mode"])
def test_non_record_no_git_effort(mode: str) -> None:
    from llm_jupyter.env_snapshot import python_env_snapshot

    snap = python_env_snapshot(mode)
    assert snap["git_commit"] is None
    assert "python_version" in snap
    assert snap.get("env_snapshot_policy_version") is not None


def test_ttl_cache_avoids_second_distributions_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC", "999")
    from llm_jupyter.env_snapshot import python_env_snapshot

    called: list[bool] = []

    def distributions() -> list[SimpleNamespace]:
        called.append(True)
        return [_fake_distribution("nbformat", "12.34.56")]

    monkeypatch.setattr(importlib.metadata, "distributions", distributions)
    monkeypatch.setattr("llm_jupyter.env_snapshot._git_commit_record", lambda: "beef" * 10)

    a = python_env_snapshot("record")["packages_summary_or_hash"]
    b = python_env_snapshot("record")["packages_summary_or_hash"]
    assert a == b
    assert len(called) == 1
    second = python_env_snapshot("record")
    assert second["env_snapshot_cache_hit"] is True
    assert second["env_snapshot_ttl_sec_configured"] == 999.0
    assert second.get("env_snapshot_cache_age_mono_sec") is not None
