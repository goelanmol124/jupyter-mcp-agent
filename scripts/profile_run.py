#!/usr/bin/env python3
"""Profile KernelSession.run (cold vs warm kernel).

From repo root: ``PYTHONPATH=src python scripts/profile_run.py``

With ``--cprofile``, print top cumulative functions after the timing tables.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
from pathlib import Path


def run_harness() -> None:
    import nbformat as nbfmt
    import nbformat.v4 as nbf

    repo = Path(__file__).resolve().parents[1]
    src = repo / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook
    from llm_jupyter.session import KernelSession

    d = tempfile.mkdtemp(prefix="lj_prof_")
    nb_path = Path(d) / "prof.ipynb"
    nb = nbf.new_notebook(
        cells=[
            nbf.new_code_cell("import time\ntime.sleep(0.05)\nanswer = sum(range(5000))"),
            nbf.new_code_cell("print(answer)"),
        ],
    )
    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)

    sess = KernelSession(nb_path, [], "explore")
    try:

        def one_run(tag: str, mode: str) -> dict:
            t0 = time.perf_counter()
            out = sess.run(run_all=True, mode=mode)
            wall = int((time.perf_counter() - t0) * 1000)
            print(f"\n=== {tag} mode={mode} external_wall_ms={wall} ===")
            print("kernel_runtime_ms", out.get("kernel_runtime_ms"))
            print("phase_timings_ms", json.dumps(out.get("phase_timings_ms"), indent=2))
            return out

        one_run("first_run_cold_kernel", "explore")
        one_run("second_run_warm_kernel", "explore")
        one_run("third_run_record_snapshot", "record")
    finally:
        sess.close()


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cprofile", action="store_true", help="append top cumulative cProfile stats")
    p.add_argument("--top", type=int, default=40, metavar="N", help="cProfile rows to print")
    args = p.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    src = repo / "src"
    if src.is_dir():
        sys.path.insert(0, str(src))

    if args.cprofile:
        import cProfile
        import pstats

        prof = cProfile.Profile()
        prof.runcall(run_harness)
        buf = io.StringIO()
        pstats.Stats(prof, stream=buf).strip_dirs().sort_stats("cumtime").print_stats(args.top)
        print(buf.getvalue())
    else:
        run_harness()


if __name__ == "__main__":
    main(sys.argv[1:])
