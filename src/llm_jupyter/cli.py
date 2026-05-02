from __future__ import annotations

import argparse
import json
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

    exp = sub.add_parser(
        "export-apynb",
        help="Write a `.apynb` sidecar from code cells (persists missing metadata.cell_id).",
    )
    exp.add_argument("notebook", help="Path to .ipynb")
    exp.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="PATH",
        help="Output `.apynb` (default: same stem as notebook)",
    )

    mt = sub.add_parser(
        "manifest-tail",
        help="Print recent manifest.jsonl records for one notebook (notebook_path-matched).",
    )
    mt.add_argument("notebook", help="Path to .ipynb")
    mt.add_argument(
        "-m",
        "--manifest",
        default=None,
        metavar="PATH",
        help="manifest.jsonl path (default: beside the notebook)",
    )
    mt.add_argument(
        "--last",
        type=int,
        default=8,
        metavar="N",
        help="Keep only the last N matching records (default: 8; use 0 for all)",
    )
    mt.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        metavar="ID",
        help=(
            "If set, print only manifest rows with this run_id "
            "(ignores --last; same notebook filter still applies)"
        ),
    )

    args = p.parse_args(argv)
    if args.cmd == "export-apynb":
        from llm_jupyter.companion import write_companion_from_notebook

        outp = write_companion_from_notebook(args.notebook, args.out)
        print(outp)
        return

    if args.cmd == "manifest-tail":
        from llm_jupyter.manifest import manifest_records_for_run, tail_manifest_records

        mf_arg = Path(args.manifest).expanduser() if args.manifest else None
        if args.run_id is not None and str(args.run_id).strip():
            rows = manifest_records_for_run(
                args.notebook,
                str(args.run_id).strip(),
                manifest_file=mf_arg,
            )
        else:
            rows = tail_manifest_records(
                args.notebook,
                last_n=args.last,
                manifest_file=mf_arg,
            )
        print(json.dumps(rows, indent=2, default=str))
        return

    if args.cmd != "serve":
        raise SystemExit(2)

    nb = Path(args.notebook).expanduser() if args.notebook else None
    roots = [Path(r).expanduser() for r in (args.roots or [])]

    mcp = build_mcp(nb, roots, args.default_mode)
    mcp.run(transport="stdio")
