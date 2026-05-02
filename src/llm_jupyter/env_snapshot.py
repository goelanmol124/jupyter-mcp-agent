from __future__ import annotations

import hashlib
import importlib.metadata
import subprocess
import sys


def python_env_snapshot(mode: str) -> dict[str, object]:
    packages_summary_or_hash = None
    if mode == "record":
        pkgs = []
        try:
            dists = sorted(importlib.metadata.distributions(), key=lambda d: d.metadata.get("Name", ""))
            for d in dists[:200]:
                name = d.metadata.get("Name") or ""
                ver = d.version or ""
                if name.lower() in (
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
                ):
                    pkgs.append(f"{name}=={ver}")
        except Exception:
            pkgs = []
        blob = ";".join(pkgs).encode()
        packages_summary_or_hash = hashlib.sha256(blob).hexdigest()[:12] if blob else None

    git_commit = None
    if mode == "record":
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if proc.returncode == 0:
                git_commit = proc.stdout.strip()[:40]
        except Exception:
            pass

    lite = ";".join(
        [
            sys.version.split()[0],
        ]
    )
    if mode == "explore" and not git_commit:
        return {
            "python_version": sys.version.split()[0],
            "packages_summary_or_hash": hashlib.sha256(lite.encode()).hexdigest()[:8],
            "git_commit": None,
        }
    return {
        "python_version": sys.version.split()[0],
        "packages_summary_or_hash": packages_summary_or_hash or hashlib.sha256(lite.encode()).hexdigest()[:8],
        "git_commit": git_commit,
    }
