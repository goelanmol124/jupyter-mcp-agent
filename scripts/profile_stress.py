#!/usr/bin/env python3
"""
Deep wall-clock stress / edge cases for KernelSession (no pytest).

Usage (repo root):

  set PYTHONPATH=src
  python scripts/profile_stress.py
  python scripts/profile_stress.py --cprofile mega_stdout

Uses ASCII-only log lines so Windows cp1252 consoles do not choke.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import nbformat as nbfmt
import nbformat.v4 as nbf


def _repo_src() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


def _ensure_path() -> None:
    src = _repo_src()
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _write_nb(path: Path, cells: list) -> None:
    nb = nbf.new_notebook(cells=cells)
    nbfmt.write(nb, open(path, "w", encoding="utf-8"))


def _phases(out: dict[str, Any]) -> str:
    pt = out.get("phase_timings_ms") or {}
    return json.dumps(pt, separators=(",", ":"))


def _summarize_stream(out: dict[str, Any]) -> str:
    sm = out.get("stream_summary") or {}
    chunks = out.get("stdout_chunks") or {}
    return (
        f"stdout_chars={sm.get('stdout_chars')} "
        f"stdout_chunks={len(chunks)} stderr_chars={sm.get('stderr_chars')}"
    )


def _run(tag: str, fn: Callable[[], dict[str, Any]], extra: str | None = None) -> None:
    t0 = time.perf_counter()
    out = fn()
    wall = int((time.perf_counter() - t0) * 1000)
    krm = out.get("kernel_runtime_ms")
    krm_str = f"{krm:5}" if krm is not None else "  n/a"
    line = f"{tag:42} wall_ms={wall:6d} kernel_runtime_ms={krm_str}  {_phases(out)}"
    print(line)
    if extra:
        print(f"{'':42} {extra}")
    if out.get("stdout_chunks"):
        print(f"{'':42} {_summarize_stream(out)}")


def scenario_baseline(sess: Any, nb: Path) -> None:
    _run("01_baseline_cold", lambda: sess.run(run_all=True, mode="explore"))
    _run("02_baseline_warm", lambda: sess.run(run_all=True, mode="explore"))


def scenario_record_repeat(sess: Any, _: Path) -> None:
    """record mode fingerprints a whitelist over distributions() each run unless LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC > 0 (see env_snapshot.py)."""

    outs: list[dict[str, Any]] = []

    def rec() -> dict[str, Any]:
        out = sess.run(run_all=True, mode="record")
        outs.append(out)
        return out

    _run("03_record_warm_1", rec)
    _run("04_record_warm_2", rec)
    _run("05_record_warm_3", rec)
    if len(outs) >= 2:
        pa1 = (outs[-2].get("phase_timings_ms") or {}).get("payload_assembly_ms")
        pa2 = (outs[-1].get("phase_timings_ms") or {}).get("payload_assembly_ms")
        if isinstance(pa1, int) and isinstance(pa2, int):
            print(
                f"{'record payload_assembly compare':42} delta_ms={pa2 - pa1:+5d}  "
                f"prev={pa1} curr={pa2}"
            )


def scenario_many_cells(nb: Path, sess_for: Callable[[Path], Any]) -> None:
    n = 120
    cells = [nbf.new_code_cell(f"_c{i} = {i}\n") for i in range(n)]
    _write_nb(nb, cells)
    sess = sess_for(nb)
    try:
        _run(
            f"06_many_cells_{n}",
            lambda: sess.run(notebook_path=str(nb), run_all=True, mode="explore"),
            extra="Includes NEW kernel startup for this NotebookSession (see kernel_shell_setup_ms)."
            " Large notebook_execute_loop_ms = many sequential execute_cell/ZMQ hops.",
        )
    finally:
        sess.close()


def scenario_mega_stdout(nb: Path, sess_for: Callable[[Path], Any], n_chars: int) -> None:
    mega_body = (
        "import sys\n"
        f"s = ('y' * {n_chars})\n"
        "print(s, file=sys.stdout)\n"
        "print('err_tail', file=sys.stderr)\n"
    )
    _write_nb(nb, [nbf.new_code_cell("_warm = 42\n"), nbf.new_code_cell(mega_body)])
    from llm_jupyter.notebook import load_notebook_ensuring_cell_ids

    nb2, _ = load_notebook_ensuring_cell_ids(nb)
    warm_id = str(nb2.cells[0]["metadata"]["cell_id"])
    mega_id = str(nb2.cells[1]["metadata"]["cell_id"])

    sess = sess_for(nb)
    try:
        sess.run(notebook_path=str(nb), cell_id=warm_id, mode="explore")
        _run(
            f"07_mega_stdout_{n_chars}_warm_k",
            lambda: sess.run(notebook_path=str(nb), cell_id=mega_id, mode="explore"),
            extra=(
                "Kernel already warm for this notebook path. "
                "Huge notebook_execute_loop_ms = streaming giant stdout via ZMQ, not Python chunk_json."
            ),
        )
    finally:
        sess.close()


def scenario_matplotlib(nb: Path, sess_for: Callable[[Path], Any], cell_cwd: Path) -> None:
    mpl_code = rf"""
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import os
    os.chdir(r"{cell_cwd.as_posix()}")
    fig, axes = plt.subplots(2, 2, figsize=(10, 10))
    for ax in axes.ravel():
        ax.imshow(np.random.default_rng(0).random((256, 256)))
    fig.savefig("stress_mpl_dummy.png")
    plt.close(fig)
    from IPython.display import Image, display
    display(Image(filename="stress_mpl_dummy.png"))
except Exception as e:
    print("SKIP_MPL", repr(e))
"""
    _write_nb(nb, [nbf.new_code_cell("_warm = True\n"), nbf.new_code_cell(mpl_code)])
    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(nb), persist_path=nb)
    nb2 = load_notebook(nb)
    warm_id = str(nb2.cells[0]["metadata"]["cell_id"])
    mpl_id = str(nb2.cells[1]["metadata"]["cell_id"])

    sess = sess_for(nb)
    try:
        sess.run(notebook_path=str(nb), cell_id=warm_id, mode="explore")
        out_holder: dict[str, Any] = {}

        def call() -> dict[str, Any]:
            o = sess.run(notebook_path=str(nb), cell_id=mpl_id, mode="explore")
            out_holder.clear()
            out_holder.update(o)
            return o

        _run(
            "08_matplotlib_4panel_png(warm_k)",
            call,
            extra="Rich MIME outputs -> Pillow thumbnails + large base64 in previews.images (+ payload_assembly)",
        )
        imgs = (out_holder.get("previews") or {}).get("images") or []
        print(f"{'':42} preview_images_n={len(imgs)}")
    finally:
        sess.close()
        for p in cell_cwd.glob("stress_mpl_dummy.png"):
            p.unlink(missing_ok=True)


def scenario_lru_eviction(root: Path, KernelSession: type) -> None:
    prev = os.environ.get("LLM_JUPYTER_MAX_NOTEBOOK_KERNELS")
    os.environ["LLM_JUPYTER_MAX_NOTEBOOK_KERNELS"] = "2"
    try:
        nbs: list[Path] = []
        for i in range(4):
            p = root / f"lru_{i}.ipynb"
            _write_nb(p, [nbf.new_code_cell(f"_k = {i}\nprint(_k)")])
            nbs.append(p)

        sess = KernelSession(None, [root], "explore")
        try:
            for i, nb_path in enumerate(nbs):
                pp = nb_path
                tag = f"09_lru_cap2_run_notebook_{i}"
                _run(
                    tag,
                    lambda pi=pp: sess.run(notebook_path=str(pi), run_all=True, mode="explore"),
                    extra="when i>=2 oldest kernel popped -> stop_channels/thread join hides here + next cold-ish start",
                )
        finally:
            t_close = time.perf_counter()
            sess.close()
            close_ms = int((time.perf_counter() - t_close) * 1000)
            print(f"{'10_session_close_all_kernels':42} wall_ms={close_ms:6d}  (long ZMQ teardown on Windows)")
    finally:
        if prev is None:
            os.environ.pop("LLM_JUPYTER_MAX_NOTEBOOK_KERNELS", None)
        else:
            os.environ["LLM_JUPYTER_MAX_NOTEBOOK_KERNELS"] = prev


def scenario_variable_preview_batch(nb: Path, sess_for: Callable[[Path], Any]) -> None:
    setup = "import json\n" + "".join(f"v{i} = {i}\n" for i in range(40))
    _write_nb(nb, [nbf.new_code_cell(setup)])
    sess = sess_for(nb)
    try:
        sess.run(notebook_path=str(nb), run_all=True, mode="explore")
        names = [f"v{i}" for i in range(40)]
        t0 = time.perf_counter()
        out = sess.variable_preview(notebook_path=str(nb), names=names, max_chars_each=200)
        wall = int((time.perf_counter() - t0) * 1000)
        print(
            f"{'11_variable_preview_40_names':42} wall_ms={wall:6d}  "
            f"status={out.get('status')} preview_wall_clock_ms={out.get('preview_wall_clock_ms')}"
        )
    finally:
        sess.close()


def scenario_execution_plan_hot_path(nb: Path, sess_for: Callable[[Path], Any], n: int) -> None:
    _write_nb(nb, [nbf.new_code_cell("1+1")])
    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(nb), persist_path=nb)
    sess = sess_for(nb)
    try:
        t0 = time.perf_counter()
        for _ in range(n):
            sess.notebook_execution_plan(notebook_path=str(nb), run_all=True)
        wall = int((time.perf_counter() - t0) * 1000)
        per = wall / max(n, 1)
        print(
            f"{f'12_notebook_execution_plan_x{n}_total':42} wall_ms={wall:6d}  (~{per:.2f} ms/call)"
            " disk read + validate + companion gate (+ notebook lock overhead if contended)"
        )
    finally:
        sess.close()


def scenario_cells_apply(nb: Path, sess_for: Callable[[Path], Any]) -> None:
    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    _write_nb(nb, [nbf.new_code_cell("x = 0\n")])
    ensure_cell_ids(load_notebook(nb), persist_path=nb)
    nb2 = load_notebook(nb)
    cid = str(nb2.cells[0]["metadata"]["cell_id"])
    sess = sess_for(nb)
    try:
        src = "x = 1\n" + ("# pad\n" * 4000)

        def apply() -> dict[str, Any]:
            return sess.cells_apply(notebook_path=str(nb), edits=[{"cell_id": cid, "source": src}])

        _run(
            "13_cells_apply_large_source",
            apply,
            extra="Two validate_notebook_node passes + rewriting a large UTF-8 .ipynb JSON",
        )
    finally:
        sess.close()


def scenario_notebook_validate_persist_large(root: Path, default_nb: Path) -> None:
    from llm_jupyter.server import build_mcp

    big_nb = root / "validate_big.ipynb"
    big = "\n".join(f"# section {i}\nprint({i})" for i in range(200))
    _write_nb(big_nb, [nbf.new_code_cell(big)])
    mcp = build_mcp(default_nb, [root], "explore")
    try:
        tm = mcp._tool_manager

        async def call() -> dict[str, Any]:
            return await tm.call_tool(
                "notebook_validate",
                {"notebook_path": str(big_nb), "persist_cell_ids": True},
                context=None,
                convert_result=False,
            )

        t0 = time.perf_counter()
        out = asyncio.run(call())
        wall = int((time.perf_counter() - t0) * 1000)
        print(
            f"{'14_notebook_validate_persist_large':42} wall_ms={wall:6d}  "
            f"cell_ids_assigned_written={out.get('cell_ids_assigned_written')}"
        )
    finally:
        ks = getattr(mcp, "_llm_kernel_session", None)
        if ks is not None:
            ks.close()


def main() -> None:
    _ensure_path()
    from llm_jupyter.session import KernelSession

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cprofile",
        metavar="TAG",
        help="profile one heavy scenario (mega_stdout,many,validate_big)",
    )
    ap.add_argument("--mega-chars", type=int, default=120_000, help="warm-kernel mega stdout stress size")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    root = Path(tempfile.mkdtemp(prefix="lj_stress_"))
    base_nb = root / "base.ipynb"
    _write_nb(base_nb, [nbf.new_code_cell("1+1")])

    def sess_for(primary: Path) -> Any:
        return KernelSession(primary, [root.resolve()], "explore")

    print(f"temp_root={root}\n")
    print(f"{'scenario':42} metrics")
    print("-" * 120)

    if args.cprofile:
        import cProfile
        import io
        import pstats

        tag = (args.cprofile or "mega_stdout").lower()

        def run_wrapped() -> None:
            if "many" in tag:
                scenario_many_cells(root / "cprof_many.ipynb", sess_for)
            elif "validate_big" in tag or "validate" in tag:
                scenario_notebook_validate_persist_large(root, base_nb)
            else:
                scenario_mega_stdout(root / "cprof_mega.ipynb", sess_for, min(args.mega_chars, 250_000))

        pr = cProfile.Profile()
        pr.runcall(run_wrapped)
        buf = io.StringIO()
        pstats.Stats(pr, stream=buf).strip_dirs().sort_stats("cumtime").print_stats(args.top)
        print(buf.getvalue())
        return

    sess = KernelSession(base_nb, [root.resolve()], "explore")
    try:
        scenario_baseline(sess, base_nb)
        scenario_record_repeat(sess, base_nb)
    finally:
        sess.close()

    scenario_many_cells(root / "many_cells.ipynb", sess_for)
    mega_n = max(1_000, min(args.mega_chars, 600_000))
    scenario_mega_stdout(root / "mega_stdout.ipynb", sess_for, mega_n)
    scenario_matplotlib(root / "mpl.ipynb", sess_for, root)
    scenario_lru_eviction(root, KernelSession)
    scenario_variable_preview_batch(root / "vp.ipynb", sess_for)
    scenario_execution_plan_hot_path(root / "dry.ipynb", sess_for, 80)
    scenario_cells_apply(root / "apply.ipynb", sess_for)
    scenario_notebook_validate_persist_large(root, base_nb)


if __name__ == "__main__":
    main()