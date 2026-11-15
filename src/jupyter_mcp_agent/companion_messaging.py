"""Unified human-facing strings for companion / disk vs kernel coherence (MCP payloads)."""


COMPANION_SKIPPED_NOTE = (
    "No companion file beside this notebook (.apynb or .companion.yaml|.yml); validation skipped "
    "(companion_strict=false)."
)

COMPANION_STRICT_MISSING = (
    "companion_strict=true but expected companion (.apynb or .companion.yaml|.yml) is missing beside the notebook."
)

COMPANION_MIRROR_STALE_HINT = (
    "Companion mirror present beside the notebook—refresh export-apynb / YAML before relying on run or "
    "notebook_execution_plan drift checks; edits via notebook_cells_patch/cells_apply or the UI require re-export."
)

NOTEBOOK_EDIT_PERSISTED_VS_KERNEL_HINT = (
    "Notebook saved; kernel RAM and kernel_generation are unchanged by this disk edit alone—persisted outputs on disk "
    "may diverge until you rerun affected cells or kernel_restart."
)
