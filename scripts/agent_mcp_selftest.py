#!/usr/bin/env python3
"""
Exercise the SAME tool callables as jupyter-mcp-agent stdio MCP (build_mcp + ToolManager).

This is how the agent validates the MCP layer without Cursor's MCP transport.
After adding .cursor/mcp.json, reload Cursor so tools appear under the jupyter-mcp-agent server.
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
    """Match ``llm_jupyter serve``: split ``LLM_JUPYTER_ROOTS`` on ``os.pathsep``."""
    raw = os.environ.get("LLM_JUPYTER_ROOTS", "")
    return [Path(x.strip()).expanduser() for x in raw.split(os.pathsep) if x.strip()]


def _warn_roots(nb: Path, roots: list[Path]) -> None:
    """Warn when matrix-style paths likely need ``--roots .`` but extras are empty."""
    if roots:
        return
    text = str(nb).lower().replace("\\", "/")
    if any(
        m in text
        for m in (
            "/benchmarks/",
            "/_matrix_trials/",
            "/v04_agent_matrix/",
            "/_orchestrator/",
        )
    ):
        print(
            "WARNING: extra_roots empty - allowlist is notebook parent only. "
            "Matrix / cross-tree notebooks usually need: --roots . "
            f"(or LLM_JUPYTER_ROOTS). notebook={nb}",
            file=sys.stderr,
        )


def list_code_cell_ids(notebook: Path) -> None:
    from jupyter_mcp_agent.notebook import ensure_cell_ids, indices_of_code_cells, load_notebook

    ensure_cell_ids(load_notebook(notebook), persist_path=notebook)
    nb = load_notebook(notebook)
    for i in indices_of_code_cells(nb):
        cell = nb.cells[i]
        cid = cell.metadata.get("cell_id", "?")
        first_line = "".join(cell.source).split("\n")[0][:72]
        print(f"{i}\t{cid}\t{first_line}")


def _parse_kv(args_raw: list[str]) -> dict[str, object]:
    args: dict[str, object] = {}
    for a in args_raw:
        k, _, v = a.partition("=")
        k = k.strip()
        v = v.strip()
        if v.lower() == "true":
            args[k] = True
        elif v.lower() == "false":
            args[k] = False
        elif v.lower() == "null" or v == "":
            args[k] = None
        elif v.startswith('"') or v.startswith("[") or v.startswith("{"):
            args[k] = json.loads(v)
        elif k == "names" or ("," in v and not v.replace(",", "").replace(".", "").replace("-", "").isdigit()):
            # Shell-friendly list: names=X,y  (avoid JSON quoting wars on Windows)
            args[k] = [x.strip() for x in v.split(",") if x.strip()]
        elif v.startswith("-"):
            try:
                args[k] = int(v)
            except ValueError:
                args[k] = float(v)
        else:
            try:
                args[k] = int(v)
            except ValueError:
                args[k] = v
    return args


def _parse_session_steps(raw_steps: list[str]) -> list[tuple[str, dict[str, object]]]:
    """Parse ``TOOL`` or ``TOOL:k=v`` steps (one k=v per step; repeat TOOL for multi-arg).

    Prefer ``variable_preview:names=a,b`` over JSON lists for shell portability.
    For multiple kwargs on one tool, pass consecutive steps with the same tool name
    — they are merged: ``run:run_all=true`` only needs one step.
    """
    steps: list[tuple[str, dict[str, object]]] = []
    for raw in raw_steps:
        tool, sep, rest = raw.partition(":")
        tool = tool.strip()
        if not tool:
            raise SystemExit(f"Bad --session step (empty tool): {raw!r}")
        if not sep:
            steps.append((tool, {}))
            continue
        # Single k=v after first colon (values may contain ':' e.g. Windows paths)
        kv = rest.strip()
        if not kv:
            steps.append((tool, {}))
            continue
        steps.append((tool, _parse_kv([kv])))
    # Merge consecutive same-tool steps so run:run_all=true works as one call
    merged: list[tuple[str, dict[str, object]]] = []
    for tool, kv in steps:
        if merged and merged[-1][0] == tool:
            merged[-1][1].update(kv)
        else:
            merged.append((tool, dict(kv)))
    return merged


async def invoke_tool(
    tool: str,
    args: dict[str, object],
    nb: Path,
    roots: list[Path],
):
    from jupyter_mcp_agent.server import build_mcp

    mcp = build_mcp(nb, roots, "explore")
    tm = mcp._tool_manager
    try:
        return await tm.call_tool(tool, args, context=None, convert_result=False)
    finally:
        ks = getattr(mcp, "_llm_kernel_session", None)
        if ks is not None:
            ks.close()


async def invoke_session(
    steps: list[tuple[str, dict[str, object]]],
    nb: Path,
    roots: list[Path],
    companion_path: str | None,
    companion_strict: bool,
):
    """Keep one build_mcp / kernel across multiple tool calls (run -> preview)."""
    from jupyter_mcp_agent.server import build_mcp

    mcp = build_mcp(nb, roots, "explore")
    tm = mcp._tool_manager
    results = []
    try:
        for tool, args in steps:
            call_args = dict(args)
            if companion_path is not None and "companion_path" not in call_args:
                call_args["companion_path"] = companion_path
            if companion_strict and "companion_strict" not in call_args:
                call_args["companion_strict"] = True
            out = await tm.call_tool(tool, call_args, context=None, convert_result=False)
            results.append({"tool": tool, "args": call_args, "result": out})
        return results
    finally:
        ks = getattr(mcp, "_llm_kernel_session", None)
        if ks is not None:
            ks.close()


async def async_main(
    tool: str,
    args_raw: list[str],
    notebook: str,
    companion_path: str | None,
    companion_strict: bool,
    roots: list[Path],
):
    root = repo_root()
    nb_path = Path(notebook)
    nb = nb_path if nb_path.is_absolute() else root / notebook
    nb = nb.resolve()
    if not nb.exists():
        raise SystemExit(f"Missing notebook {nb}")

    _warn_roots(nb, roots)
    args = _parse_kv(args_raw)

    if companion_path is not None:
        args["companion_path"] = companion_path
    if companion_strict:
        args["companion_strict"] = True

    out = await invoke_tool(tool, args, nb, roots)

    print(json.dumps(out, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(
        description="Call jupyter-mcp-agent MCP-style tools from the repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/agent_mcp_selftest.py -n examples/agent_demo_euler.ipynb --list-cell-ids\n"
            "  python scripts/agent_mcp_selftest.py -n examples/agent_demo_buffer.ipynb notebook_execution_plan\n"
            "  python scripts/agent_mcp_selftest.py -n examples/agent_demo_lognormal.ipynb run run_all=true\n"
            "  python scripts/agent_mcp_selftest.py --roots . -n benchmarks/case_studies/rnd_benchmark_2026/analysis_mcp.ipynb server_info\n"
            "  # Same-process run -> variable_preview (prefer this over two CLI invokes):\n"
            "  python scripts/agent_mcp_selftest.py --roots . -n path/to/work.ipynb --session \\\n"
            "      run:run_all=true variable_preview:names=x,y\n"
            "  # Or the dedicated helper (no agent_report stamp):\n"
            "  python scripts/mcp_session_run_preview.py --roots . -n path/to/work.ipynb --names x,y\n"
            "  python -m jupyter_mcp_agent manifest-tail examples/notebook.ipynb --run-id RUN_ID_HERE\n"
            "  python scripts/agent_mcp_selftest.py -n examples/agent_scratch.ipynb --companion-strict run run_all=true\n"
            "    ^ fails when same-stem .apynb is missing.\n"
        ),
    )
    p.add_argument(
        "--notebook",
        "-n",
        default="examples/agent_scratch.ipynb",
        help="Notebook path relative to repo root (or absolute). Default: Monte Carlo pi demo.",
    )
    p.add_argument(
        "--roots",
        nargs="*",
        default=None,
        help=(
            "Extra allowed roots passed to build_mcp (same role as serve --roots). "
            "Default: paths from LLM_JUPYTER_ROOTS (os.pathsep-separated), else none."
        ),
    )
    p.add_argument(
        "--list-cell-ids",
        action="store_true",
        help="Print code cell indexes, metadata.cell_id, first line; persist ids if missing.",
    )
    p.add_argument(
        "--companion-path",
        default=None,
        help="Optional explicit companion file (else same-stem .apynb auto if present)",
    )
    p.add_argument(
        "--companion-strict",
        action="store_true",
        help="Require a companion file (same-stem .apynb or --companion-path)",
    )
    p.add_argument(
        "--session",
        nargs="+",
        default=None,
        metavar="STEP",
        help=(
            "Multi-tool same-process session. Each STEP is TOOL or TOOL:k=v:k2=v2. "
            "JSON values ok (e.g. names=[\"a\",\"b\"]). Prefer over separate CLI invokes "
            "so variable_preview sees the kernel after run."
        ),
    )
    p.add_argument("tool", nargs="?", default="run")
    p.add_argument("kv", nargs="*", help="kwargs as key=value (e.g. run_all=true)")
    args = p.parse_args()
    root = repo_root()
    nb_p = Path(args.notebook)
    nb = nb_p if nb_p.is_absolute() else root / nb_p
    nb = nb.resolve()
    if args.list_cell_ids:
        if not nb.exists():
            raise SystemExit(f"Missing notebook {nb}")
        list_code_cell_ids(nb)
        return
    if args.roots is None:
        roots = _env_roots()
    else:
        roots = [Path(r).expanduser() for r in args.roots]
    if args.session:
        if not nb.exists():
            raise SystemExit(f"Missing notebook {nb}")
        _warn_roots(nb, roots)
        steps = _parse_session_steps(args.session)
        results = asyncio.run(
            invoke_session(
                steps,
                nb,
                roots,
                args.companion_path,
                args.companion_strict,
            )
        )
        print(json.dumps(results, indent=2, default=str))
        return
    asyncio.run(
        async_main(
            args.tool,
            args.kv,
            args.notebook,
            args.companion_path,
            args.companion_strict,
            roots,
        )
    )


if __name__ == "__main__":
    main()
