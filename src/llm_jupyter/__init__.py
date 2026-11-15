"""Backwards-compatible alias for :mod:`jupyter_mcp_agent` (formerly ``llm-jupyter``).

``import llm_jupyter.session`` and ``python -m llm_jupyter serve ...`` keep working;
new code should import ``jupyter_mcp_agent`` instead. Each ``llm_jupyter.<name>``
submodule is the very same module object as ``jupyter_mcp_agent.<name>``.
"""

from __future__ import annotations

import importlib
import sys

import jupyter_mcp_agent as _pkg
from jupyter_mcp_agent import __version__

_SUBMODULES = (
    "cells_apply_helpers",
    "chunks",
    "cli",
    "companion",
    "companion_messaging",
    "env_snapshot",
    "envelopes",
    "manifest",
    "notebook",
    "notebook_cells_patch",
    "paths",
    "previews",
    "server",
    "session",
    "stamp",
    "stream_artifacts",
)

for _name in _SUBMODULES:
    _mod = importlib.import_module(f"{_pkg.__name__}.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _mod
    globals()[_name] = _mod

__all__ = ["__version__", *_SUBMODULES]
