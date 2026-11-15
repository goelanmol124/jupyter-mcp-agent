#!/usr/bin/env python3
"""
Same-process MCP session: server_info -> run -> variable_preview.

Promotes the per-exp ``pilot_mcp_session.py`` pattern into ``scripts/`` so agents
do not need a fresh kernel between ``run`` and ``variable_preview``.

Anti-stamp: this script does **not** patch ``agent_report.json``. Cite the printed
``run_id`` and preview names; write reports yourself from kernel truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _env_roots() -> list[Path]:
    raw = os.environ.get("LLM_JUPYTER_ROOTS", "")
    return [Path(x.strip()).expanduser() for x in raw.split(os.pathsep) if x.strip()]


def _warn_roots(nb: Path, roots: list[Path]) -> None:
    """Loud footgun when trial notebooks sit outside notebook-parent-only allowlist."""
    nb_parent = nb.parent.resolve()
    extras = [p.expanduser().resolve() for p in roots]
    if extras:
        return
    # Default allowlist is notebook parent only - matrix trials under benchmarks/ need --roots .
    markers = ("benchmarks", "_matrix_trials", "demos")
    parts = {p.lower() for p in nb_parent.parts}
    if any(m in parts for m in markers) or "v04_agent_matrix" in str(nb_parent).lower():
        print(
            "WARNING: no --roots / LLM_JUPYTER_ROOTS; allowlist is notebook parent only. "
            "For matrix / cross-tree notebooks prefer: --roots . "
            f"(notebook={nb})",
            file=sys.stderr,
        )


def _preview_keys(prev: object) -> list[str]:
    if not isinstance(prev, dict):
        return []
    previews = prev.get("previews") or prev.get("variables") or {}
    return list(previews.keys()) if isinstance(previews, dict) else []


async def run_session(
    nb: Path,
    roots: list[Path],
    run_all: bool,
    cell_id: str | None,
    preview_batches: list[list[str]],
) -> dict:
    from llm_jupyter.server import build_mcp

    _warn_roots(nb, roots)
    mcp = build_mcp(nb, roots, "explore")
    tm = mcp._tool_manager
    out: dict = {
        "notebook": str(nb),
        "transport_label_hint": "tools_selftest",
        "process_cwd_note": (
            "Kernel cwd is usually MCP process cwd (often repo root), "
            "not the notebook directory - prefer absolute or notebook-parent paths."
        ),
    }
    try:
        info = await tm.call_tool("server_info", {}, context=None, convert_result=False)
        if isinstance(info, dict):
            out["server_info"] = {
                "status": info.get("status"),
                "process_cwd": info.get("process_cwd"),
                "extra_roots_resolved": info.get("extra_roots_resolved"),
                "effective_allowed_roots": info.get("effective_allowed_roots"),
                "tools_n": info.get("tools_n"),
            }
        else:
            out["server_info"] = info

        run_args: dict[str, object] = {}
        if cell_id:
            run_args["cell_id"] = cell_id
        else:
            run_args["run_all"] = run_all
        run = await tm.call_tool("run", run_args, context=None, convert_result=False)
        out["run"] = run if isinstance(run, dict) else {"raw": run}
        run_id = out["run"].get("run_id") if isinstance(out["run"], dict) else None
        out["run_id"] = run_id

        preview_results = []
        all_names: list[str] = []
        for names in preview_batches:
            if not names:
                continue
            prev = await tm.call_tool(
                "variable_preview",
                {"names": names},
                context=None,
                convert_result=False,
            )
            keys = _preview_keys(prev)
            all_names.extend(keys)
            preview_results.append(
                {
                    "requested": names,
                    "resolved_keys": keys,
                    "result": prev,
                }
            )
        out["previews"] = preview_results
        out["preview_names"] = all_names
        out["variable_preview_count"] = len(preview_results)
        return out
    finally:
        ks = getattr(mcp, "_llm_kernel_session", None)
        if ks is not None:
            ks.close()


def _parse_names(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Same-process MCP: server_info -> run -> variable_preview. "
            "Does not patch agent_report (anti-stamp)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/mcp_session_run_preview.py --roots . -n path/to/work.ipynb \\\n"
            "      --names resid_proxy,geo_te,final\n"
            "  python scripts/mcp_session_run_preview.py --roots . -n work.ipynb \\\n"
            "      --names-batch a,b --names-batch c,d,e\n"
        ),
    )
    p.add_argument("--notebook", "-n", required=True, help="Notebook path (repo-relative or absolute)")
    p.add_argument(
        "--roots",
        nargs="*",
        default=None,
        help="Extra allowed roots (same as agent_mcp_selftest / serve). Default: LLM_JUPYTER_ROOTS or none.",
    )
    p.add_argument("--run-all", action="store_true", default=True, help="run_all=true (default)")
    p.add_argument("--no-run-all", action="store_true", help="Disable run_all (requires --cell-id)")
    p.add_argument("--cell-id", default=None, help="Run a single cell_id instead of run_all")
    p.add_argument(
        "--names",
        default=None,
        help="Comma-separated variable_preview names (one batch)",
    )
    p.add_argument(
        "--names-batch",
        action="append",
        default=[],
        help="Additional preview batch (repeatable). Prefer post-win / middle-state names.",
    )
    args = p.parse_args()

    root = repo_root()
    nb_p = Path(args.notebook)
    nb = (nb_p if nb_p.is_absolute() else root / nb_p).resolve()
    if not nb.exists():
        raise SystemExit(f"Missing notebook {nb}")

    if args.roots is None:
        roots = _env_roots()
    else:
        roots = [Path(r).expanduser() for r in args.roots]

    batches: list[list[str]] = []
    first = _parse_names(args.names)
    if first:
        batches.append(first)
    for raw in args.names_batch:
        batch = _parse_names(raw)
        if batch:
            batches.append(batch)
    if not batches:
        raise SystemExit("Provide --names and/or --names-batch (comma-separated)")

    run_all = False if args.no_run_all or args.cell_id else True
    if not run_all and not args.cell_id:
        raise SystemExit("Need --cell-id when using --no-run-all")

    result = asyncio.run(
        run_session(nb, roots, run_all=run_all, cell_id=args.cell_id, preview_batches=batches)
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
