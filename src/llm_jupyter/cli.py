from __future__ import annotations

import argparse
import os
from pathlib import Path

from llm_jupyter.server import build_mcp


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="llm-jupyter")
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Serve MCP tools over stdio (Cursor-friendly)")
    serve.add_argument(
        "--notebook",
        "-n",
        default=os.environ.get("LLM_JUPYTER_NOTEBOOK"),
        help="Default notebook path (optional if every tool passes notebook_path)",
    )
    serve.add_argument(
        "--roots",
        nargs="*",
        default=[
            x.strip()
            for x in os.environ.get("LLM_JUPYTER_ROOTS", "").split(os.pathsep)
            if x.strip()
        ],
        help="Additional allowed directory roots besides the notebook parent",
    )
    serve.add_argument(
        "--default-mode",
        choices=["explore", "record"],
        default=os.environ.get("LLM_JUPYTER_MODE", "explore"),
    )

    args = p.parse_args(argv)
    if args.cmd != "serve":
        raise SystemExit(2)

    nb = Path(args.notebook).expanduser() if args.notebook else None
    roots = [Path(r).expanduser() for r in (args.roots or [])]

    mcp = build_mcp(nb, roots, args.default_mode)
    mcp.run(transport="stdio")
