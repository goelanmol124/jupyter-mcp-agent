"""Small end-to-end research-style demo against KernelSession (not Cursor MCP UI)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import nbformat
import nbformat.v4 as nbf

from llm_jupyter.session import KernelSession


def main() -> None:
    d = Path(tempfile.mkdtemp(prefix="demo_nb_"))
    p = d / "research_demo.ipynb"
    nb = nbf.new_notebook()
    nb.cells = [
        nbf.new_code_cell("import numpy as np\n"),
        nbf.new_code_cell(
            "x = np.linspace(-0.15, 0.15, 400)\n"
            "x = x[np.abs(x) > 1e-8]\n"
            "y = np.sin(1 / x)\n"
        ),
        nbf.new_code_cell('print("ymin", float(y.min()), "ymax", float(y.max()))\n'),
    ]
    with open(p, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    sess = KernelSession(p, [], "explore")
    try:
        r1 = sess.run(run_all=True)
        print("run_all:", r1["status"], "stale=", r1["outputs_might_be_stale"])

        nb2 = nbformat.read(open(p, encoding="utf-8"), as_version=4)
        cid0 = nb2.cells[0]["metadata"]["cell_id"]
        r2 = sess.run(cell_id=str(cid0))
        print("partial cell0:", "stale=", r2["outputs_might_be_stale"])
        print(" stale_notes[0]=", r2["stale_notes"][0][:80] if r2["stale_notes"] else None)

        try:
            sess.run(run_all=True, cell_id=str(cid0))
            print("BUG: contradictory run modes should raise")
        except ValueError as e:
            print("ambiguous rejected OK:", e)

        mf_lines = (d / "manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
        print("manifest lines=", len(mf_lines))
    finally:
        sess.close()

    print("temp dir=", d)


if __name__ == "__main__":
    main()
