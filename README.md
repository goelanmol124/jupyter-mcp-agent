# LLM Jupyter

Open-source **Python MCP** server for **`ipykernel` notebooks**: checked cell edits (avoid hand-patching JSON), **`run_all`** / **`run_until`**, **`explore`** vs **`record`** modes, consistent JSON after runs (notebook file stamp, Python env hint, previews), **stderr** handled like stdout, append-only **`manifest.jsonl`** instead of hiding history in git.

**Docs:** [PRD](docs/PRD.md) · [Implementation](docs/IMPLEMENTATION.md) · **License:** [MIT](LICENSE)

Code not in this repo yet — register the finished CLI as a normal MCP server over **stdio** with Cursor or compatible editors.
