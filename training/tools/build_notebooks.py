"""Builds the Colab notebooks (.ipynb) from their readable sources (training/notebooks/*.py, "percent" format).

Edit the .py file, then run:  python training/tools/build_notebooks.py
Cells start with "# %%" (code) or "# %% [markdown]" (markdown; lines start with "# "). Each code cell is
compiled first, so a syntax error fails the build instead of a Colab session.
"""
import json
import sys
from pathlib import Path

NOTEBOOKS = Path(__file__).resolve().parent.parent / "notebooks"


def cells_of(source: str) -> list[dict]:
    cells, kind, lines = [], None, []

    def flush():
        if kind is None:
            return
        text = "\n".join(lines).strip("\n")
        if kind == "markdown":
            text = "\n".join(l[2:] if l.startswith("# ") else l.lstrip("#") for l in text.splitlines())
        if text.strip():
            cells.append({"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True),
                          **({"execution_count": None, "outputs": []} if kind == "code" else {})})

    for line in source.splitlines():
        if line.startswith("# %%"):
            flush()
            kind, lines = ("markdown" if "[markdown]" in line else "code"), []
        else:
            lines.append(line)
    flush()
    return cells


def build(src: Path) -> Path:
    cells = cells_of(src.read_text(encoding="utf-8"))
    for i, c in enumerate(cells):
        if c["cell_type"] == "code":
            compile("".join(c["source"]), f"{src.name} cell {i}", "exec")
    nb = {"nbformat": 4, "nbformat_minor": 5, "cells": cells,
          "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                       "kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"}}}
    for i, c in enumerate(cells):
        c["id"] = f"cell-{i:02d}"
    out = src.with_suffix(".ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    sources = [Path(a) for a in sys.argv[1:]] or sorted(NOTEBOOKS.glob("[0-9]*.py"))
    for s in sources:
        out = build(s)
        print(f"{out.relative_to(NOTEBOOKS.parent.parent)}: {len(json.loads(out.read_text(encoding='utf-8'))['cells'])} cells")
