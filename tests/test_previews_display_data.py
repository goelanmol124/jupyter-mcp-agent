from __future__ import annotations

import nbformat.v4 as nbf

from llm_jupyter.previews import previews_from_cells


def test_previews_pick_text_plain_from_display_data() -> None:
    cell = nbf.new_code_cell("pass")
    cell.outputs = [
        {"output_type": "display_data", "data": {"text/plain": "shown via display"}},
    ]
    out = previews_from_cells([(cell, 0)], preview_rows=4, max_image_side=64)
    assert out["tables"] and out["tables"][0]["rows"] == ["shown via display"]
