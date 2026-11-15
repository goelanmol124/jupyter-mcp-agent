"""Second tiny research demo: quadratic truth + Gaussian noise → numpy.polyfit sanity check."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import nbformat
import nbformat.v4 as nbf

from jupyter_mcp_agent.session import KernelSession


def main() -> None:
    d = Path(tempfile.mkdtemp(prefix="demo_poly_"))
    p = d / "polyfit_demo.ipynb"
    nb = nbf.new_notebook()
    nb.cells = [
        nbf.new_code_cell(
            "import numpy as np\n"
            "rng = np.random.default_rng(7)\n"
            "true = np.array([0.7, -0.03, 0.001])\n"
        ),
        nbf.new_code_cell(
            "xs = rng.uniform(-15, 15, size=(80,))\n"
            "ys = true[0] + true[1] * xs + true[2] * xs**2\n"
            "ys_noisy = ys + rng.normal(0, 0.15, xs.shape)\n"
        ),
        nbf.new_code_cell(
            "coef = np.polyfit(xs, ys_noisy, deg=2)\n"
            "print(\"polyfit quadratic\", coef)\n"
            "rel_err = np.linalg.norm(coef[::-1] - true) / np.linalg.norm(true)\n"
            "print(\"relative_coeff_error\", float(rel_err))\n"
        ),
    ]
    with open(p, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    from jupyter_mcp_agent.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(p), persist_path=p)
    nb_meta = nbformat.read(open(p, encoding="utf-8"), as_version=4)
    cid_last = nb_meta.cells[2]["metadata"]["cell_id"]

    sess = KernelSession(p, [], "explore")
    try:
        r_until = sess.run(run_until_cell_id=str(cid_last))
        print(
            "run_until last cell:",
            r_until["status"],
            "run_id",
            r_until["run_id"],
            "cells_run",
            r_until["cells_executed"],
        )
        mf = [ln for ln in (d / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if ln]
        ids = []
        for ln in mf:
            o = json.loads(ln)
            if "run_id" in o:
                ids.append(o["run_id"])
        print("manifest run_ids:", ids)
    finally:
        sess.close()

    print("temp dir=", d)


if __name__ == "__main__":
    main()
