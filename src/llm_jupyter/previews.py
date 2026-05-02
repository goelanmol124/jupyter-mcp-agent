from __future__ import annotations

import base64
import io
import re
from typing import Any

from nbformat.notebooknode import NotebookNode


def previews_from_cells(
    cells_with_outputs: list[tuple[NotebookNode, int]],
    preview_rows: int,
    max_image_side: int,
) -> dict[str, list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    max_rows = max(0, preview_rows)
    img_side = max(32, min(max_image_side, 2048))

    for cell, index in cells_with_outputs:
        cell_id = cell.get("metadata", {}).get("cell_id")
        lines: list[str] = []
        for out in getattr(cell, "outputs", []) or []:
            if out.get("output_type") != "execute_result":
                continue
            data = out.get("data", {})
            txt = data.get("text/plain")
            if isinstance(txt, list):
                txt = "".join(txt)
            if isinstance(txt, str) and txt.strip():
                chunk = txt.strip().splitlines()
                lines.extend(chunk[: max_rows + 50])
            for mime in ("image/png", "image/jpeg"):
                raw = data.get(mime)
                if not raw:
                    continue
                b = _decode_maybe_base64(raw)
                if not b:
                    continue
                img_entry: dict[str, Any] = {
                    "cell_index": index,
                    "cell_id": cell_id,
                    "mime": mime,
                }
                try:
                    from PIL import Image

                    im = Image.open(io.BytesIO(b))
                    im.thumbnail((img_side, img_side))
                    if mime == "image/jpeg":
                        im = im.convert("RGB")
                    buf = io.BytesIO()
                    im.save(buf, format="PNG" if mime == "image/png" else "JPEG")
                    b2 = buf.getvalue()
                    img_entry["preview_base64"] = base64.standard_b64encode(b2).decode("ascii")
                except Exception:
                    img_entry["preview_note"] = "Pillow_resize_failed_using_raw_truncation"
                    img_entry["preview_base64"] = base64.standard_b64encode(
                        b[:50_000]
                    ).decode("ascii")
                images.append(img_entry)
        if lines and max_rows:
            trimmed = lines[:max_rows]
            tables.append(
                {
                    "cell_index": index,
                    "cell_id": cell_id,
                    "mime": "text/plain",
                    "rows": trimmed,
                    "truncated": len(lines) > max_rows,
                }
            )

    return {"tables": tables, "images": images}


def _decode_maybe_base64(raw: str | bytes) -> bytes | None:
    if isinstance(raw, bytes):
        return raw
    s = raw.strip()
    try:
        return base64.standard_b64decode(s, validate=False)
    except Exception:
        m = re.search(r"[A-Za-z0-9+/=]+", s)
        if m:
            try:
                return base64.standard_b64decode(m.group(0))
            except Exception:
                pass
        return None
