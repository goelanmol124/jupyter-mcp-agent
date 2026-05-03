"""Lightweight fingerprints of the Python interpreter for manifests / MCP payloads."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import subprocess
import sys
import time

# Bump when whitelist or hashing rules change (invalidates TTL cache fingerprint).
ENV_SNAPSHOT_POLICY_VERSION = "2"
_SNAPSHOT_POLICY_VERSION = ENV_SNAPSHOT_POLICY_VERSION  # compat alias within module private FP

_RECORD_WHITELIST = frozenset(
    {
        "numpy",
        "torch",
        "tensorflow",
        "jax",
        "pandas",
        "matplotlib",
        "scikit-learn",
        "ipykernel",
        "jupyter-client",
        "nbformat",
        "nbclient",
    }
)


def _norm_pkg_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _collect_whitelisted_packages_for_record() -> list[str]:
    """Single pass over installed distributions (no sort of the full environment)."""

    matched: dict[str, str] = {}
    try:
        for dist in importlib.metadata.distributions():
            raw_name = (dist.metadata.get("Name") or "").strip()
            if not raw_name:
                continue
            key = _norm_pkg_name(raw_name)
            if key not in _RECORD_WHITELIST:
                continue
            ver = dist.version or ""
            matched[key] = f"{raw_name}=={ver}"
    except Exception:
        return []

    return sorted(matched.values())


def _snapshot_fingerprint() -> str:
    return "|".join(
        (
            sys.prefix or "",
            sys.executable or "",
            _SNAPSHOT_POLICY_VERSION,
        )
    )


def _record_ttl_seconds() -> float:
    key = "LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC"
    if key not in os.environ:
        return 120.0
    raw = os.environ.get(key, "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def _git_commit_record() -> str | None:
    """``git rev-parse HEAD`` resolves from subprocess cwd—which may omit or mis-resolve HEAD if MCP cwd ≠ repo."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()[:40]
    except Exception:
        pass
    return None


_ttl_cache_mono_at: float = 0.0
_ttl_fp: str | None = None
_ttl_payload_core: dict[str, object] | None = None


def reset_python_env_snapshot_cache_for_tests() -> None:
    """Clear process-local TTL state (pytest)."""

    global _ttl_fp  # noqa: PLW0603
    global _ttl_payload_core  # noqa: PLW0603
    global _ttl_cache_mono_at  # noqa: PLW0603

    _ttl_fp = None
    _ttl_payload_core = None
    _ttl_cache_mono_at = 0.0


def env_snapshot_ttl_meta_from_snapshot(snap: dict[str, object]) -> dict[str, object]:
    """Subset persisted on manifest rows; mirrors TTL-related keys from ``python_env_snapshot``."""

    meta_keys = (
        "env_snapshot_policy_version",
        "env_snapshot_ttl_sec_configured",
        "env_snapshot_cache_hit",
        "env_snapshot_cache_age_mono_sec",
    )
    return {k: snap[k] for k in meta_keys if k in snap}


def python_env_snapshot(mode: str) -> dict[str, object]:
    """Return interpreter metadata; ``record`` includes whitelisted-dist hash (+ git HEAD)."""

    mode_l = (mode or "explore").lower()
    lite_txt = ";".join([sys.version.split()[0]])
    lite_hash = hashlib.sha256(lite_txt.encode()).hexdigest()[:8]

    if mode_l != "record":
        return {
            "python_version": sys.version.split()[0],
            "packages_summary_or_hash": lite_hash,
            "git_commit": None,
            "env_snapshot_policy_version": ENV_SNAPSHOT_POLICY_VERSION,
        }

    global _ttl_cache_mono_at  # noqa: PLW0603
    global _ttl_fp  # noqa: PLW0603
    global _ttl_payload_core  # noqa: PLW0603

    fp = _snapshot_fingerprint()
    ttl_sec = _record_ttl_seconds()
    now = time.monotonic()

    cache_hit = False
    cache_age_mono: float | None = None
    if (
        ttl_sec > 0
        and _ttl_payload_core is not None
        and _ttl_fp == fp
        and (now - _ttl_cache_mono_at) < ttl_sec
    ):
        core = dict(_ttl_payload_core)
        cache_hit = True
        cache_age_mono = round(now - _ttl_cache_mono_at, 6)
    else:
        pkgs = _collect_whitelisted_packages_for_record()
        blob = ";".join(pkgs).encode()
        packages_summary_or_hash: str | None
        if blob:
            packages_summary_or_hash = hashlib.sha256(blob).hexdigest()[:12]
        else:
            packages_summary_or_hash = lite_hash

        git_commit = _git_commit_record()
        core = {
            "python_version": sys.version.split()[0],
            "packages_summary_or_hash": packages_summary_or_hash,
            "git_commit": git_commit,
        }
        if ttl_sec > 0:
            _ttl_fp = fp
            _ttl_payload_core = dict(core)
            _ttl_cache_mono_at = now

    meta: dict[str, object] = {
        "env_snapshot_policy_version": ENV_SNAPSHOT_POLICY_VERSION,
        "env_snapshot_ttl_sec_configured": ttl_sec,
        "env_snapshot_cache_hit": cache_hit,
        "env_snapshot_cache_age_mono_sec": cache_age_mono,
    }
    return {**core, **meta}
