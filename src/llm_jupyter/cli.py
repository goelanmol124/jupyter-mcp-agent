from __future__ import annotations

import argparse
import json
import os
import sys
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
        from llm_jupyter.manifest import (
            explain_manifest_miss_for_run_id,
            manifest_records_for_run,
            tail_manifest_records,
        )

        mf_arg = Path(args.manifest).expanduser() if args.manifest else None
        rid_arg = args.run_id
        rid_stripped = str(rid_arg).strip() if rid_arg is not None else ""

        if rid_arg is not None and rid_stripped != "":
            rows = manifest_records_for_run(
                args.notebook,
                rid_stripped,
                manifest_file=mf_arg,
            )
            # WHY stderr hints for empty `--run-id` matches:
            # Operators often cite a shortened/guessed ID; emitting `[]` alone is ambiguous
            # (manifest missing vs wrong notebook filter vs typo). Humans need guidance without
            # breaking JSON parsers that ingest stdout-only.
            if not rows:
                print(
                    explain_manifest_miss_for_run_id(
                        args.notebook,
                        rid_stripped,
                        manifest_file=mf_arg,
                    ),
                    file=sys.stderr,
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
