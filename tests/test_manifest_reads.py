from __future__ import annotations

import json
from pathlib import Path

from llm_jupyter.manifest import (
    explain_manifest_miss_for_run_id,
    manifest_records_for_notebook,
    manifest_records_for_run,
    tail_manifest_records,
)


def test_manifest_records_filters_by_resolved_notebook(tmp_path: Path):
    nb_a = tmp_path / "a.ipynb"
    nb_b = tmp_path / "b.ipynb"
    nb_a.write_text("{}", encoding="utf-8")
    nb_b.write_text("{}", encoding="utf-8")
    ra = nb_a.expanduser().resolve()
    rb = nb_b.expanduser().resolve()

    mf = tmp_path / "manifest.jsonl"
    lines = (
        {"notebook_path": str(ra), "run_id": "one"},
        {"notebook_path": str(rb), "run_id": "two"},
        {"notebook_path": str(ra), "run_id": "three"},
        {"oops": True},
        "not-json",
        {"notebook_path": str(rb), "run_id": "four"},
    )
    with mf.open("w", encoding="utf-8") as f:
        for obj in lines:
            if isinstance(obj, dict):
                f.write(json.dumps(obj) + "\n")
            else:
                f.write(str(obj) + "\n")

    a_rows = manifest_records_for_notebook(nb_a, manifest_file=mf)
    assert [r["run_id"] for r in a_rows] == ["one", "three"]
    b_rows = manifest_records_for_notebook(nb_b, manifest_file=mf)
    assert [r["run_id"] for r in b_rows] == ["two", "four"]


def test_tail_manifest_truncates_ordered(tmp_path: Path):
    nb = tmp_path / "only.ipynb"
    nb.write_text("{}", encoding="utf-8")
    mf = tmp_path / "manifest.jsonl"
    r = nb.expanduser().resolve()
    with mf.open("w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"notebook_path": str(r), "i": i}) + "\n")
    tail = tail_manifest_records(nb, manifest_file=mf, last_n=2)
    assert [x["i"] for x in tail] == [3, 4]

    assert [x["i"] for x in tail_manifest_records(nb, manifest_file=mf, last_n=0)] == [0, 1, 2, 3, 4]


def test_missing_manifest_returns_empty(tmp_path: Path):
    nb = tmp_path / "ghost.ipynb"
    nb.write_text("{}", encoding="utf-8")
    mf = tmp_path / "no_such_manifest.jsonl"
    assert manifest_records_for_notebook(nb, manifest_file=mf) == []


def test_manifest_records_for_run_specific_id(tmp_path: Path):
    nb = tmp_path / "r.ipynb"
    nb.write_text("{}", encoding="utf-8")
    rr = nb.expanduser().resolve()
    mf = tmp_path / "manifest.jsonl"
    rows_in = (
        {"notebook_path": str(rr), "run_id": "aaa", "i": 0},
        {"notebook_path": str(rr), "run_id": "bbb", "i": 1},
        {"notebook_path": str(rr), "run_id": " aaa ", "i": 2},  # edge: stored id differs
        {"notebook_path": str(rr), "run_id": "ccc", "i": 3},
        {"notebook_path": str(rr), "notebook_only": True},
        {"notebook_path": "/tmp/other.ipynb", "run_id": "aaa", "x": True},
    )
    with mf.open("w", encoding="utf-8") as f:
        for obj in rows_in:
            f.write(json.dumps(obj) + "\n")
    got = manifest_records_for_run(nb, "aaa", manifest_file=mf)
    assert sorted(x["i"] for x in got) == [0, 2]  # run_id whitespace normalized


def test_explain_manifest_miss_when_manifest_missing(tmp_path: Path):
    # WHY assert prose not structure: wording is UX; substring checks tolerate minor edits.
    nb = tmp_path / "solo.ipynb"
    nb.write_text("{}", encoding="utf-8")
    mf = tmp_path / "manifest.jsonl"
    msg = explain_manifest_miss_for_run_id(nb, "abc", manifest_file=mf)
    assert "missing" in msg.lower()


def test_explain_manifest_miss_when_no_rows_for_nb(tmp_path: Path):
    nb = tmp_path / "solo.ipynb"
    nb.write_text("{}", encoding="utf-8")
    other = tmp_path / "other.ipynb"
    other.write_text("{}", encoding="utf-8")
    mf = tmp_path / "manifest.jsonl"
    with mf.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"notebook_path": str(other.expanduser().resolve()), "run_id": "zzz"}) + "\n")
    msg = explain_manifest_miss_for_run_id(nb, "zzz", manifest_file=mf)
    assert "no notebook_path matching" in msg


def test_explain_manifest_miss_run_id_lists_recent_samples(tmp_path: Path):
    nb = tmp_path / "solo.ipynb"
    nb.write_text("{}", encoding="utf-8")
    mf = tmp_path / "manifest.jsonl"
    r = nb.expanduser().resolve()
    ids: list[str] = []
    with mf.open("w", encoding="utf-8") as f:
        for i in range(4):
            rid = f"run{i}"
            ids.append(rid)
            f.write(json.dumps({"notebook_path": str(r), "run_id": rid}) + "\n")
    msg = explain_manifest_miss_for_run_id(nb, "nope", manifest_file=mf)
    assert "not found" in msg
    tail = ids[-min(12, len(ids)) :]
    for rid in tail:
        assert rid in msg
