from __future__ import annotations

from pathlib import Path

import nbformat.v4 as nbf
import pytest

from llm_jupyter.notebook import ensure_cell_ids, load_notebook
from llm_jupyter.session import KernelSession


@pytest.mark.kernel
def test_run_all_writes_output_and_manifest(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell('import sys\nprint("out", file=sys.stdout)\nprint("err", file=sys.stderr)')])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True, mode="explore")
        assert out["status"] == "ok"
        assert list(out.keys())[:3] == ["status", "run_id", "mode"]
        assert out["kernel_generation"] >= 1
        assert not out["outputs_might_be_stale"]
        assert "out" in "".join(out["stdout_chunks"].values())
        assert "err" in "".join(out["stderr_chunks"].values())
        mf = tmp_path / "manifest.jsonl"
        assert mf.exists()
        line0 = mf.read_text(encoding="utf-8").strip().splitlines()[0]
        import json

        row0 = json.loads(line0)
        assert row0["run_id"] == out["run_id"]
        assert "sources_concat_sha256_prefix" in row0 and len(str(row0["sources_concat_sha256_prefix"])) == 16
    finally:
        sess.close()


@pytest.mark.kernel
def test_partial_run_reports_stale(tmp_path: Path):
    nb_path = tmp_path / "p.ipynb"
    nb = nbf.new_notebook(
        cells=[
            nbf.new_code_cell("x=1"),
            nbf.new_code_cell("x+=1"),
        ]
    )
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))

    sess = KernelSession(nb_path, [], "explore")
    try:
        sess.run(run_all=True, mode="explore")
        nb2 = nbfmt.read(open(nb_path, encoding="utf-8"), as_version=4)
        cid0 = nb2.cells[0]["metadata"]["cell_id"]
        out = sess.run(cell_id=str(cid0), mode="explore")
        assert out["status"] == "ok"
        assert out["outputs_might_be_stale"]
        assert any("partial" in n.lower() or "partial" in n for n in out["stale_notes"])
    finally:
        sess.close()


@pytest.mark.kernel
def test_kernel_restart_increments_generation(tmp_path: Path):
    nb_path = tmp_path / "r.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        sess.run(run_all=True)
        g = sess.kernel_generation
        sess.kernel_restart()
        assert sess.kernel_generation == g + 1
        out = sess.run(run_all=True)
        assert out["restart_since_previous_tool_call"] is True
    finally:
        sess.close()


@pytest.mark.kernel
def test_halt_on_false_still_reports_structured_execution_error(tmp_path: Path):
    """When allow_errors, nbclient attaches error outputs rather than raising; server must expose them."""
    nb_path = tmp_path / "halt.ipynb"
    nb = nbf.new_notebook(
        cells=[
            nbf.new_code_cell("works = True"),
            nbf.new_code_cell("raise ValueError('deliberate')"),
            nbf.new_code_cell("follow_up = True"),
        ],
    )
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))

    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True, halt_on_error=False)
        assert out["status"] == "error"
        assert out["halt_on_error"] is False
        assert out["execution_error"]["ename"] == "ValueError"
        assert "deliberate" in out["execution_error"]["evalue"]
        err_text = "".join(out["stderr_chunks"].values())
        assert "deliberate" in err_text or "ValueError" in err_text

        streamed = out.get("streams_by_cell_executed") or []
        assert len(streamed) == 3

        timings = out.get("phase_timings_ms") or {}
        assert timings.get("kernel_shell_setup_ms", 0) >= 0
        assert timings.get("payload_assembly_ms", 0) >= 0
        assert "manifest_append_wall_ms" in timings
    finally:
        sess.close()


@pytest.mark.kernel
def test_record_snapshot_env_writes_notebook_copy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_JUPYTER_RECORD_NOTEBOOK_SNAPSHOT", "1")
    nb_path = tmp_path / "snap.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("y = 99\n")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True, mode="record")
        assert out["status"] == "ok"
        rid = out["run_id"]
        copied = nb_path.parent / ".llm_jupyter" / "notebook_snapshots" / rid / "notebook.ipynb"
        assert copied.is_file()
        assert "y = 99" in copied.read_text(encoding="utf-8")
    finally:
        sess.close()


    nb_path = tmp_path / "pv.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("demo_x = 714\n")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)
    sess = KernelSession(nb_path, [], "explore")
    try:
        nb2 = load_notebook(nb_path)
        cid = str(nb2.cells[0].metadata["cell_id"])
        sess.run(cell_id=cid)
        out = sess.variable_preview(names=["demo_x"])
        assert out["status"] == "ok"
        assert "714" in out["previews"]["demo_x"]
        assert "cold_kernel_hint" not in out
        assert "preview_diagnostic" not in out
        assert out.get("kernel_alive") is True
    finally:
        sess.close()


@pytest.mark.kernel
def test_variable_preview_cold_hint_when_all_undefined(tmp_path: Path):
    nb_path = tmp_path / "coldhint.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("# preamble\npass\n")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.variable_preview(names=["absent_z"])
        assert out["status"] == "ok"
        assert "preview_diagnostic" in out
        assert "cold_kernel_hint" not in out
        assert out["kernel_alive"] is True
    finally:
        sess.close()


@pytest.mark.kernel
def test_variable_preview_cold_kernel_marks_missing(tmp_path: Path):
    nb_path = tmp_path / "cold.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("# preamble\npass\n")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.variable_preview(names=["absent_name"])
        assert out["status"] == "ok"
        assert out["previews"]["absent_name"] == "<not defined>"
        assert "preview_diagnostic" in out
        assert "cold_kernel_hint" not in out
    finally:
        sess.close()


@pytest.mark.kernel
def test_two_notebooks_have_independent_kernels(tmp_path: Path):
    import nbformat as nbfmt

    a_path = tmp_path / "a.ipynb"
    b_path = tmp_path / "b.ipynb"

    nb_a = nbf.new_notebook(
        cells=[
            nbf.new_code_cell('who = "nb_a"\n'),
            nbf.new_code_cell("print(who)"),
        ],
    )
    nb_b = nbf.new_notebook(
        cells=[
            nbf.new_code_cell('who = "nb_b"\n'),
            nbf.new_code_cell("print(who)"),
        ],
    )
    for p, nb in ((a_path, nb_a), (b_path, nb_b)):
        nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    sess = KernelSession(None, [], "explore")
    try:
        sess.run(notebook_path=str(a_path), run_all=True)
        sess.run(notebook_path=str(b_path), run_all=True)

        nb = nbfmt.read(open(a_path, encoding="utf-8"), as_version=4)
        print_id = nb.cells[-1]["metadata"]["cell_id"]
        out = sess.run(notebook_path=str(a_path), cell_id=str(print_id))
        assert out["status"] == "ok"
        text = "".join(out["stdout_chunks"].values())
        assert "nb_a" in text
        assert "nb_b" not in text
        assert sess.kernel_status(notebook_path=str(a_path))["notebook_kernel_active"] is True
        assert sess.kernel_status(notebook_path=str(b_path))["notebook_kernel_active"] is True
    finally:
        sess.close()


@pytest.mark.kernel
def test_run_compact_assistant_quick_drops_pedagogy_keys(tmp_path: Path):
    nb_path = tmp_path / "compact.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("x = 1")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True, compact_assistant_quick=True)
        aq = out["assistant_quick"]
        assert "halt_on_false_means_continue_not_hide_errors" not in aq
        assert "kernel_wall_clock_hint" not in aq
    finally:
        sess.close()


@pytest.mark.kernel
def test_run_compact_via_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_JUPYTER_COMPACT_ASSISTANT_QUICK", "1")
    nb_path = tmp_path / "compact_env.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("y = 2")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True)
        aq = out["assistant_quick"]
        assert "halt_on_false_means_continue_not_hide_errors" not in aq
    finally:
        sess.close()
