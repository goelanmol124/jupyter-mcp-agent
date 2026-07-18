import nbformat as nbf
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell


def write(path: str, title: str) -> None:
    load_src = """# load data (do not change paths)
import numpy as np
data = np.load("data.npz")
X_train, X_test = data["X_train"], data["X_test"]
y_train, y_test = data["y_train"], data["y_test"]
print(X_train.shape, X_test.shape)
"""
    nb = new_notebook(
        cells=[
            new_markdown_cell(
                f"# {title}\n\nRead **TASK.md** in this folder. Work in this notebook only."
            ),
            new_code_cell(load_src),
        ]
    )
    nbf.write(nb, path)


if __name__ == "__main__":
    write("demos/rnd_benchmark_2026/analysis_mcp.ipynb", "MCP track")
    write("demos/rnd_benchmark_2026/analysis_terminal.ipynb", "Terminal track")
    print("ok")
