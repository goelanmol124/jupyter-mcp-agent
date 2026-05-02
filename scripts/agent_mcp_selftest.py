#!/usr/bin/env python3
"""
Exercise the SAME tool callables as llm-jupyter stdio MCP (build_mcp + ToolManager).

This is how the agent validates the MCP layer without Cursor's MCP transport.
After adding .cursor/mcp.json, reload Cursor so tools appear under the llm-jupyter server.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def list_code_cell_ids(notebook: Path) -> None:
    from llm_jupyter.notebook import ensure_cell_ids, indices_of_code_cells, load_notebook

    ensure_cell_ids(load_notebook(notebook), persist_path=notebook)
    nb = load_notebook(notebook)
    for i in indices_of_code_cells(nb):
        cell = nb.cells[i]
        cid = cell.metadata.get("cell_id", "?")
        first_line = "".join(cell.source).split("\n")[0][:72]
        print(f"{i}\t{cid}\t{first_line}")


async def invoke_tool(tool: str, args: dict[str, object], nb: Path):
    from llm_jupyter.server import build_mcp

    mcp = build_mcp(nb, [], "explore")
    tm = mcp._tool_manager
    return await tm.call_tool(tool, args, context=None, convert_result=False)


async def async_main(
    tool: str,
    args_raw: list[str],
    notebook: str,
    companion_path: str | None,
    companion_strict: bool,
):
    root = repo_root()
    nb_path = Path(notebook)
    nb = nb_path if nb_path.is_absolute() else root / notebook
    nb = nb.resolve()
    if not nb.exists():
        raise SystemExit(f"Missing notebook {nb}")

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
        elif v.startswith('"'):
            args[k] = json.loads(v)
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

    if companion_path is not None:
        args["companion_path"] = companion_path
    if companion_strict:
        args["companion_strict"] = True

    out = await invoke_tool(tool, args, nb)

    print(json.dumps(out, indent=2, default=str))


def main() -> None:
    p = argparse.ArgumentParser(description="Call llm-jupyter MCP-style tools from the repo.")
    p.add_argument(
        "--notebook",
        "-n",
        default="demos/agent_scratch.ipynb",
        help="Notebook path relative to repo root (or absolute). Default: Monte Carlo π demo.",
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
    asyncio.run(
        async_main(
            args.tool,
            args.kv,
            args.notebook,
            args.companion_path,
            args.companion_strict,
        )
    )


if __name__ == "__main__":
    main()
