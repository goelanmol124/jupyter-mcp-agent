from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from llm_jupyter.server import build_mcp


def apply_process_cwd(
    process_cwd: str | None = None,
    *,
    env_var: str = "LLM_JUPYTER_PROCESS_CWD",
) -> Path | None:
    """``os.chdir`` when ``--process-cwd`` / ``LLM_JUPYTER_PROCESS_CWD`` is set.

    Cursor (and some other MCP hosts) often **ignore** mcp.json ``cwd`` and spawn
    stdio servers from the user profile. Env vars are still applied — set this so
    ``server_info.process_cwd`` and relative path resolution match the project.
    """
    raw = (process_cwd if process_cwd is not None else os.environ.get(env_var, "")).strip()
    if not raw:
        return None
    target = Path(raw).expanduser().resolve()
    if not target.is_dir():
        print(f"{env_var} is not a directory: {target}", file=sys.stderr)
        raise SystemExit(1)
    os.chdir(target)
    return target


def _serve_child_argv(args: argparse.Namespace) -> list[str]:
    """Rebuild `serve` argv for the child process (never includes --watch)."""
    nb = Path(args.notebook).expanduser() if args.notebook else None
    roots = [Path(r).expanduser() for r in (args.roots or [])]

    child: list[str] = [
        sys.executable,
        "-m",
        "llm_jupyter",
        "serve",
    ]
    if nb is not None:
        child.extend(["-n", str(nb)])
    if roots:
        child.append("--roots")
        child.extend(str(r) for r in roots)
    child.extend(["--default-mode", args.default_mode])
    if getattr(args, "process_cwd", None):
        child.extend(["--process-cwd", str(args.process_cwd)])
    if getattr(args, "kernel_cwd", None):
        child.extend(["--kernel-cwd", str(args.kernel_cwd)])
    return child


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
    serve.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Restart automatically when llm_jupyter package sources change (dev; "
            "requires optional dependency watchfiles, e.g. pip install -e \".[dev]\")"
        ),
    )
    serve.add_argument(
        "--process-cwd",
        default=os.environ.get("LLM_JUPYTER_PROCESS_CWD"),
        metavar="DIR",
        help=(
            "chdir before serving (also LLM_JUPYTER_PROCESS_CWD). "
            "Use when the MCP host ignores mcp.json cwd (common on Cursor Windows)."
        ),
    )
    serve.add_argument(
        "--kernel-cwd",
        choices=["notebook_parent", "process"],
        default=None,
        help=(
            "Where new ipykernels start (default notebook_parent; also LLM_JUPYTER_KERNEL_CWD). "
            "notebook_parent makes relative data.npz / plot paths resolve next to the .ipynb."
        ),
    )

    exp = sub.add_parser(
        "export-apynb",
        help="Write a JSON (.apynb) or YAML (.companion.yaml) sidecar mirroring code cells (persists metadata.cell_id).",
    )
    exp.add_argument("notebook", help="Path to .ipynb")
    exp.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="PATH",
        help="Output companion path (defaults: *.apynb for json, *.companion.yaml for yaml)",
    )
    exp.add_argument(
        "--format",
        choices=["json", "yaml"],
        default="json",
        help="Companion encoding (YAML requires PyYAML, declared as a dependency).",
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

        outp = write_companion_from_notebook(args.notebook, args.out, fmt=args.format)
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

    apply_process_cwd(args.process_cwd)
    if args.kernel_cwd:
        os.environ["LLM_JUPYTER_KERNEL_CWD"] = args.kernel_cwd

    nb = Path(args.notebook).expanduser() if args.notebook else None
    roots = [Path(r).expanduser() for r in (args.roots or [])]

    if args.watch:
        try:
            from watchfiles import run_process  # type: ignore[import-not-found]
        except ImportError as e:
            print(
                "Serve --watch requires `watchfiles` (pip install watchfiles "
                'or pip install -e ".[dev]").',
                file=sys.stderr,
            )
            raise SystemExit(1) from e

        pkg_dir = Path(__file__).resolve().parent
        code = run_process(
            pkg_dir,
            target=subprocess.list2cmdline(_serve_child_argv(args)),
            debounce=int(os.environ.get("LLM_JUPYTER_WATCH_DEBOUNCE_MS", "800")),
            target_type="command",
        )
        raise SystemExit(code)

    mcp = build_mcp(nb, roots, args.default_mode)
    mcp.run(transport="stdio")
