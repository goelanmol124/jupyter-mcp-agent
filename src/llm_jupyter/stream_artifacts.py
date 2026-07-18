"""Writers and readers for run stream evidence on disk (MCP reply stays index-sized)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

EVIDENCE_CONTRACT_VERSION = 1
DOT_DIR_NAME = ".llm_jupyter"


def evidence_root_for_notebook(notebook_path: Path) -> Path:
    """Directory under the notebook's parent: ``<parent>/.llm_jupyter``."""

    return notebook_path.expanduser().resolve().parent / DOT_DIR_NAME


def run_evidence_dir(notebook_path: Path, run_id: str) -> Path:
    return evidence_root_for_notebook(notebook_path) / "runs" / run_id


def mcp_stream_char_budget() -> int:
    raw = os.environ.get("LLM_JUPYTER_MCP_STREAM_CHAR_BUDGET", "").strip()
    if not raw:
        return 393_216
    try:
        return max(8_192, min(int(raw), 50_000_000))
    except ValueError:
        return 393_216


def run_stream_read_max_bytes() -> int:
    raw = os.environ.get("LLM_JUPYTER_RUN_STREAM_READ_MAX_BYTES", "").strip()
    if not raw:
        return 65_536
    try:
        return max(256, min(int(raw), 2_000_000))
    except ValueError:
        return 65_536


def write_run_stream_artifacts(
    notebook_path: Path,
    run_id: str,
    *,
    stdout_text: str,
    stderr_text: str,
    extra_meta: dict[str, Any],
) -> dict[str, Any]:
    """Write ``stdout.txt`` / ``stderr.txt`` / ``meta.json`` under ``.llm_jupyter/runs/{run_id}``.

    Returns a JSON-serializable ``stream_artifacts`` block suitable for manifests and MCP replies.
    """

    nb = notebook_path.expanduser().resolve()
    out_dir = run_evidence_dir(nb, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = out_dir / "stdout.txt"
    stderr_path = out_dir / "stderr.txt"

    stdout_path.write_text(stdout_text, encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr_text, encoding="utf-8", newline="\n")

    so_digest = hashlib.sha256(stdout_text.encode("utf-8")).hexdigest()
    se_digest = hashlib.sha256(stderr_text.encode("utf-8")).hexdigest()

    rel_root = nb.parent.resolve()
    try:
        rel_stdout = str(stdout_path.resolve().relative_to(rel_root)).replace("\\", "/")
        rel_stderr = str(stderr_path.resolve().relative_to(rel_root)).replace("\\", "/")
        rel_meta = str((out_dir / "meta.json").resolve().relative_to(rel_root)).replace("\\", "/")
    except ValueError:
        rel_stdout = str(stdout_path)
        rel_stderr = str(stderr_path)
        rel_meta = str(out_dir / "meta.json")

    meta: dict[str, Any] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "run_id": run_id,
        "notebook_path": str(nb),
        "stdout_chars": len(stdout_text),
        "stderr_chars": len(stderr_text),
        "stdout_sha256": so_digest,
        "stderr_sha256": se_digest,
        "artifacts_dir_relative_notebook_parent": DOT_DIR_NAME + f"/runs/{run_id}",
        "stdout_relative": rel_stdout,
        "stderr_relative": rel_stderr,
    }
    meta.update(extra_meta)
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "stdout_relative_notebook_parent": rel_stdout.replace("\\", "/"),
        "stderr_relative_notebook_parent": rel_stderr.replace("\\", "/"),
        "meta_relative_notebook_parent": rel_meta.replace("\\", "/"),
        "stdout_sha256": so_digest,
        "stderr_sha256": se_digest,
        "stdout_bytes": len(stdout_text.encode("utf-8")),
        "stderr_bytes": len(stderr_text.encode("utf-8")),
    }


def read_run_stream_slice(
    notebook_path: Path,
    run_id: str,
    stream_name: str,
    *,
    byte_offset: int = 0,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Read a capped byte slice from ``stdout.txt`` or ``stderr.txt`` under evidence runs."""

    nb = notebook_path.expanduser().resolve()
    rid = str(run_id).strip()
    if not rid:
        raise ValueError("run_id must be non-empty.")
    nm = stream_name.strip().lower()
    if nm not in ("stdout", "stderr"):
        raise ValueError("stream must be 'stdout' or 'stderr'.")
    cap = max_bytes if max_bytes is not None else run_stream_read_max_bytes()

    artifact_dir = run_evidence_dir(nb, rid)
    path = artifact_dir / f"{nm}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"No {nm} artifact for run_id={rid!r} under {artifact_dir}")

    data = path.read_bytes()
    off = max(0, int(byte_offset))
    if off >= len(data):
        return {
            "stream": nm,
            "byte_offset": off,
            "bytes_returned": 0,
            "total_bytes": len(data),
            "truncated_at_end": False,
            "data_base64": "",
        }

    chunk = data[off : off + cap]
    return {
        "stream": nm,
        "byte_offset": off,
        "bytes_returned": len(chunk),
        "total_bytes": len(data),
        "truncated_at_end": off + len(chunk) < len(data),
        "data_base64": __import__("base64").standard_b64encode(chunk).decode("ascii"),
    }
