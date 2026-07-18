from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from jupyter_client import KernelManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

from llm_jupyter.companion_messaging import (
    COMPANION_MIRROR_STALE_HINT,
    COMPANION_SKIPPED_NOTE,
    COMPANION_STRICT_MISSING,
    NOTEBOOK_EDIT_PERSISTED_VS_KERNEL_HINT,
)
from llm_jupyter.env_snapshot import env_snapshot_ttl_meta_from_snapshot, python_env_snapshot
from llm_jupyter.chunks import (
    MAX_KERNEL_ERROR_LOG_ENTRIES,
    STREAM_SUFFIX_DESCRIPTOR,
    append_kernel_traceback_stderr,
    cell_stream_row,
    chunk_text,
    collect_streams,
    kernel_error_digest_from_outputs,
    stream_summary_for_tool,
    strip_ansi_text,
    trim_streams_by_cell,
)
from llm_jupyter.companion import (
    companion_path_for_notebook,
    companion_yaml_paths_for_notebook,
    default_companion_path_for_notebook,
    validate_companion_file,
)
from llm_jupyter.manifest import append_manifest
from llm_jupyter.notebook_cells_patch import (
    apply_notebook_cells_patch,
    normalize_patch_operations,
    notebook_cells_summary,
)
from llm_jupyter.notebook import (
    bulk_eligible_code_indices,
    cell_index_for_id,
    cell_index_for_stable_id,
    ensure_cell_ids,
    indices_of_code_cells,
    load_notebook,
    load_notebook_ensuring_cell_ids,
    save_notebook,
    sources_concat_sha256_prefix,
    strip_cell_outputs_matching_type,
    validate_notebook_node,
)

from llm_jupyter.paths import allowed_roots_for_notebook, is_under_roots, normalize_allowed_path
from llm_jupyter.previews import previews_from_cells
from llm_jupyter.stamp import notebook_file_stamp
from llm_jupyter.stream_artifacts import (
    evidence_root_for_notebook,
    mcp_stream_char_budget,
    write_run_stream_artifacts,
)

_NOTEBOOK_EXCLUSIVE_LOCK_ENV = "LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC"
_COMPACT_ASSISTANT_QUICK_ENV = "LLM_JUPYTER_COMPACT_ASSISTANT_QUICK"
_STRIP_ANSI_STREAMS_ENV = "LLM_JUPYTER_STRIP_ANSI_STREAMS"
_VERBOSITY_COMPACT_ENV = "LLM_JUPYTER_VERBOSITY_COMPACT"


def _verbosity_compact() -> bool:
    """Omit lengthy ``assistant_quick`` prose and MCP ``field_hints`` on kernel tools."""

    raw = os.environ.get(_VERBOSITY_COMPACT_ENV, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    cq = os.environ.get(_COMPACT_ASSISTANT_QUICK_ENV, "").strip().lower()
    return cq in ("1", "true", "yes", "on")


def _omit_stream_chunks_requested(omit_stream_chunks: bool | None) -> bool:
    if omit_stream_chunks is not None:
        return bool(omit_stream_chunks)
    raw = os.environ.get("LLM_JUPYTER_OMIT_STREAM_CHUNK_MAP", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _env_truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


_PREVIEW_JSON_START = "__LLM_JUPYTER_PREVIEW_JSON_START__"
_PREVIEW_JSON_END = "__LLM_JUPYTER_PREVIEW_JSON_END__"


def _manifest_sources_and_optional_snapshot(nb: Any, path: Path, run_id: str, mode_eff: str) -> tuple[str, str | None]:
    h = sources_concat_sha256_prefix(nb)
    snap_rel: str | None = None
    if mode_eff == "record" and _env_truthy(os.environ.get("LLM_JUPYTER_RECORD_NOTEBOOK_SNAPSHOT")):
        ev = evidence_root_for_notebook(path)
        snap_dir = ev / "notebook_snapshots" / run_id
        snap_dir.mkdir(parents=True, exist_ok=True)
        dest = snap_dir / "notebook.ipynb"
        shutil.copy2(path, dest)
        try:
            snap_rel = str(dest.resolve().relative_to(path.parent.resolve())).replace("\\", "/")
        except ValueError:
            snap_rel = str(dest.resolve())
    return h, snap_rel


def _variable_preview_stdout_blob(so_txt: str) -> str:
    si = so_txt.find(_PREVIEW_JSON_START)
    ei = so_txt.find(_PREVIEW_JSON_END)
    if si >= 0 and ei > si:
        return so_txt[si + len(_PREVIEW_JSON_START) : ei].strip()
    blob_lines = [ln.strip() for ln in so_txt.split("\n") if ln.strip()]
    return blob_lines[-1] if blob_lines else ""


class NotebookConcurrentBusy(RuntimeError):
    """Exclusive access to one ``.ipynb`` is unavailable (another tool call holds the notebook lock).

    MCP clients sometimes issue parallel requests; llm-jupyter serializes notebook-scoped work per path.
    Set ``LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC`` to empty or ``inf`` to queue indefinitely instead of timing out.

    Structured fields propagate to MCP tool ``status:error`` payloads via ``_notebook_exclusive_busy``.
    """

    def __init__(
        self,
        message: str,
        *,
        exclusive_notebook_resolved: str | None = None,
        lock_mode: str | None = None,
        timed_wait_seconds: float | None = None,
        contention_kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.exclusive_notebook_resolved = exclusive_notebook_resolved
        self.lock_mode = lock_mode
        self.timed_wait_seconds = timed_wait_seconds
        self.contention_kind = contention_kind


KERNEL_TOOL_FIELD_HINTS: dict[str, str] = {
    "kernel_alive": "ipykernel subprocess is running (False if exited or never started on this pooled handle slot).",
    "notebook_kernel_active": (
        "True when llm-jupyter holds a pooled kernel session slot for this notebook path "
        "(a NotebookKernelHandle); the subprocess may still be dead until restarted—see kernel_alive."
    ),
    "kernel_generation": "Monotonic bump on kernel (re)start for this notebook in this MCP process.",
    "interrupted_flag": "True after kernel_interrupt succeeded for this handle until the next restart.",
}


def notebook_exclusive_lock_timeout_seconds() -> float | None:
    """Return ``acquire`` timeout seconds, ``None`` = block forever, ``<= 0`` = non-blocking."""

    raw = os.environ.get(_NOTEBOOK_EXCLUSIVE_LOCK_ENV)
    if raw is None:
        return 900.0
    stripped = raw.strip()
    if stripped == "" or stripped.lower() in ("inf", "infinite", "none"):
        return None
    sec = float(stripped)
    if sec < 0:
        return None
    return sec


def assistant_quick_compact_requested(explicit_compact: bool) -> bool:
    """Slim ``assistant_quick`` in ``run`` when tool arg or env enables it."""

    if explicit_compact or _verbosity_compact():
        return True
    raw = os.environ.get(_COMPACT_ASSISTANT_QUICK_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def ansi_streams_strip_requested(explicit_strip: bool) -> bool:
    if explicit_strip:
        return True
    raw = os.environ.get(_STRIP_ANSI_STREAMS_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _server_tool_digest() -> dict[str, str]:
    """Stable metadata echoed on MCP replies so agents detect wrong interpreter/path."""
    from llm_jupyter import __version__ as ver

    return {"llm_jupyter_version": ver}


def _session_cap() -> int:
    raw = os.environ.get("LLM_JUPYTER_MAX_NOTEBOOK_KERNELS", "32").strip()
    try:
        n = int(raw)
    except ValueError:
        return 32
    if n <= 0:
        return 32
    return max(1, min(n, 256))


class NotebookKernelHandle:
    """ipykernel process + reusable NotebookClient for exactly one notebook path."""

    def __init__(self, *, execute_timeout_sec: int) -> None:
        self.execute_timeout_sec = execute_timeout_sec
        self.km: KernelManager | None = None
        self._nb_client: NotebookClient | None = None
        self.kernel_generation = 0
        self._generation_at_previous_tool_end: int | None = None
        self.full_top_to_bottom_at_generation: int | None = None
        self.interrupted = False

    def close(self) -> None:
        self.dispose_nb_client_shell()
        if self.km is not None:
            try:
                if self.km.is_alive():
                    self.km.shutdown_kernel(now=True)
            except Exception:
                pass
            try:
                self.km.cleanup_resources()
            except Exception:
                pass
            self.km = None

    def dispose_nb_client_shell(self) -> None:
        if self._nb_client and self._nb_client.kc:
            try:
                self._nb_client.kc.stop_channels()
            except Exception:
                pass
        self._nb_client = None

    def kernel_restart(self, art_prefix: str | None = None) -> dict[str, Any]:
        """Hard-restart kernel; bumps kernel_generation for this notebook only."""
        self.dispose_nb_client_shell()
        if self.km is not None:
            try:
                if self.km.is_alive():
                    self.km.shutdown_kernel(now=True)
            except Exception:
                pass
            try:
                self.km.cleanup_resources()
            except Exception:
                pass
            self.km = None

        km = KernelManager(kernel_name="python3")
        env = os.environ.copy()
        if art_prefix:
            env["LLM_NB_ART_PREFIX"] = art_prefix
        km.start_kernel(env=env)
        self.km = km
        self.kernel_generation += 1
        self.interrupted = False
        return {
            "ok": True,
            "kernel_generation": self.kernel_generation,
            "message": "Kernel restarted.",
        }

    def kernel_interrupt(self) -> dict[str, Any]:
        if not self.km or not self.km.is_alive():
            return {"ok": False, "message": "No alive kernel."}
        try:
            self.km.interrupt_kernel()
            self.interrupted = True
        except Exception as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "message": "Interrupt signal sent."}

    def kernel_status(self) -> dict[str, Any]:
        alive = bool(self.km and self.km.is_alive())
        return {
            "kernel_generation": self.kernel_generation,
            "kernel_alive": alive,
            "interrupted_flag": self.interrupted,
            "full_top_to_bottom_at_generation": self.full_top_to_bottom_at_generation,
        }

    def _ensure_kernel(self, art_prefix: str | None) -> None:
        if self.km is not None and self.km.is_alive():
            return
        self.dispose_nb_client_shell()
        if self.km is not None:
            try:
                self.km.cleanup_resources()
            except Exception:
                pass
            self.km = None

        km = KernelManager(kernel_name="python3")
        env = os.environ.copy()
        if art_prefix:
            env["LLM_NB_ART_PREFIX"] = art_prefix
        km.start_kernel(env=env)
        self.km = km
        self.kernel_generation += 1

    def _executor(self, nb: Any, notebook_path: Path) -> NotebookClient:
        if self._nb_client is None:
            assert self.km is not None
            self._nb_client = NotebookClient(
                nb,
                km=self.km,
                resources={"metadata": {"path": str(notebook_path.parent.resolve())}},
                timeout=self.execute_timeout_sec,
                shutdown_kernel="immediate",
                coalesce_streams=True,
            )
        else:
            self._nb_client.nb = nb
        return self._nb_client

    def transient_code_cell_execute(self, notebook_parent: Path, code: str) -> tuple[list[Any], CellExecutionError | None]:
        """Run a throwaway notebook cell sharing this kernel; returns nbformat outputs (+ optional CellExecutionError)."""
        import nbformat.v4 as nv

        assert self.km is not None
        nb_shell = nv.new_notebook(cells=[nv.new_code_cell(code)])
        client = NotebookClient(
            nb_shell,
            km=self.km,
            resources={"metadata": {"path": str(notebook_parent.resolve())}},
            timeout=self.execute_timeout_sec,
            shutdown_kernel="immediate",
            coalesce_streams=True,
        )
        caught: CellExecutionError | None = None
        # Do not stop client.kc here: this kernel may already be pooled with a NotebookClient for run();
        # extra stop_channels races with the pooled shell.
        with client.setup_kernel(cleanup_kc=False):
            try:
                client.execute_cell(nb_shell.cells[0], 0)
            except CellExecutionError as e:
                caught = e
        outs = list(nb_shell.cells[0].outputs or [])
        return outs, caught


class KernelSession:
    """Notebook-keyed kernels: Cursor shares one MCP process across chats/tools — isolate RAM per `.ipynb`."""

    def __init__(
        self,
        default_notebook: Path | None,
        extra_root_paths: list[Path],
        default_mode: str,
        execute_timeout_sec: int = 600,
        chunk_chars: int = 6000,
    ) -> None:
        self.default_notebook = default_notebook.resolve() if default_notebook else None
        self.extra_roots = [normalize_allowed_path(str(p)) for p in extra_root_paths]
        self.default_mode = default_mode if default_mode in ("explore", "record") else "explore"
        self.execute_timeout_sec = execute_timeout_sec
        self.chunk_chars = chunk_chars

        self._handles: OrderedDict[Path, NotebookKernelHandle] = OrderedDict()
        self._notebook_exclusive_locks: dict[Path, threading.Lock] = {}
        self._notebook_exclusive_registry_lock = threading.Lock()
        self._mru_notebook_path: Path | None = None

    def _canonical(self, notebook_path: Path) -> Path:
        return notebook_path.expanduser().resolve()

    def notebook_path_for_kernel_tool(self, notebook_path: str | None) -> Path:
        """Resolved path after ``-n`` default; same rules as MCP ``kernel_*`` tools."""
        return self._kernel_tools_path_arg(notebook_path)

    def _exclusive_lock_primitive(self, notebook_path: Path) -> threading.Lock:
        canon = self._canonical(notebook_path)
        with self._notebook_exclusive_registry_lock:
            lk = self._notebook_exclusive_locks.get(canon)
            if lk is None:
                lk = threading.Lock()
                self._notebook_exclusive_locks[canon] = lk
            return lk

    @contextmanager
    def notebook_exclusive(self, notebook_path: Path):
        """Serialize MCP handlers touching one notebook/kernel (per resolved path).

        Parallel ``run`` / ``cells_apply`` / ``notebook_cells_patch`` / ``variable_preview`` / ``kernel_*`` for the **same**
        ``notebook_path`` are queued; parallel calls targeting **different** notebooks may still run concurrently.
        """
        lk = self._exclusive_lock_primitive(notebook_path)
        canon = self._canonical(notebook_path)
        timeout_sec = notebook_exclusive_lock_timeout_seconds()
        if timeout_sec is None:
            lk.acquire()
        elif timeout_sec <= 0:
            if not lk.acquire(blocking=False):
                raise NotebookConcurrentBusy(
                    f"Notebook-exclusive lock busy for {canon}: another llm-jupyter tool is "
                    f"already running against this path. Serialize MCP calls for the same .ipynb, "
                    f"or set {_NOTEBOOK_EXCLUSIVE_LOCK_ENV} empty/inf for a blocking queue.",
                    exclusive_notebook_resolved=str(canon),
                    lock_mode="nonblocking",
                    timed_wait_seconds=None,
                    contention_kind="nonblocking_busy",
                )
        else:
            if not lk.acquire(timeout=timeout_sec):
                waited = timeout_sec
                raise NotebookConcurrentBusy(
                    f"Notebook-exclusive lock not acquired within {waited}s for {canon}. "
                    f"Likely concurrent MCP workload for one .ipynb. Wait and retry or raise "
                    f"{_NOTEBOOK_EXCLUSIVE_LOCK_ENV} if you intend to block longer.",
                    exclusive_notebook_resolved=str(canon),
                    lock_mode="timed",
                    timed_wait_seconds=float(waited),
                    contention_kind="timeout",
                )
        try:
            yield
        finally:
            lk.release()

    def close(self) -> None:
        for h in list(self._handles.values()):
            h.close()
        self._handles.clear()

    @property
    def kernel_generation(self) -> int:
        """Backward-compat for callers/tests that only use `-n` single notebook."""
        if not self.default_notebook:
            return 0
        k = self._canonical(self.default_notebook)
        h = self._handles.get(k)
        return h.kernel_generation if h else 0

    def dispose_nb_client_shell(self) -> None:
        """Close NotebookClient shells for all kernels (tests / agent selftest teardown)."""
        for h in self._handles.values():
            h.dispose_nb_client_shell()

    def _used_default_notebook_arg(self, notebook_path_arg: str | None) -> bool:
        return self.default_notebook is not None and (
            notebook_path_arg is None or not str(notebook_path_arg).strip()
        )

    def notebook_resolution_meta(self, notebook_path_arg: str | None, resolved: Path) -> dict[str, str | bool]:
        s = str(self._canonical(resolved))
        return {
            "notebook_path": s,
            "resolved_notebook_path": s,
            "used_default_notebook": self._used_default_notebook_arg(notebook_path_arg),
        }

    def _get_handle(self, notebook_resolved_path: Path) -> NotebookKernelHandle:
        cand = notebook_resolved_path.expanduser().resolve()

        existing = self._handles.pop(cand, None)
        if existing is not None:
            self._handles[cand] = existing
            return existing

        cap = _session_cap()
        if cap and len(self._handles) >= cap:
            _, evict_h = self._handles.popitem(last=False)
            evict_h.close()

        h = NotebookKernelHandle(execute_timeout_sec=self.execute_timeout_sec)
        self._handles[cand] = h
        return h

    def _touch_mru(self, path: Path) -> None:
        self._mru_notebook_path = path.expanduser().resolve()

    def _kernel_tools_resolve(self, notebook_path: str | None) -> tuple[Path, str]:
        """Return resolved ``.ipynb`` and how the path was inferred (explicit, MRU, or serve `-n`)."""

        if notebook_path and str(notebook_path).strip():
            path = normalize_allowed_path(notebook_path)
            self.check_allowed_notebook(path)
            resolved = path.resolve()
            self._touch_mru(resolved)
            return resolved, "explicit_notebook_path"
        if self._mru_notebook_path is not None:
            mr = self._canonical(self._mru_notebook_path)
            if mr.exists():
                try:
                    self.check_allowed_notebook(mr)
                    self._touch_mru(mr)
                    return mr, "last_notebook_tool_target_mru"
                except PermissionError:
                    pass
        if self.default_notebook:
            path = normalize_allowed_path(str(self.default_notebook))
            self.check_allowed_notebook(path)
            resolved = path.resolve()
            self._touch_mru(resolved)
            return resolved, "serve_default_notebook"
        raise ValueError(
            "notebook_path is required for kernel_restart / kernel_interrupt / kernel_status "
            "unless serve was started with --notebook / -n, or MRU applies after another notebook-scoped tool.",
        )

    def _kernel_tools_path_arg(self, notebook_path: str | None) -> Path:
        return self._kernel_tools_resolve(notebook_path)[0]

    def kernel_field_hints_fragment(self) -> dict[str, Any]:
        if _verbosity_compact():
            return {}
        return {"field_hints": dict(KERNEL_TOOL_FIELD_HINTS)}

    def kernel_restart(self, notebook_path: str | None = None, art_prefix: str | None = None) -> dict[str, Any]:
        path, basis = self._kernel_tools_resolve(notebook_path)
        out = dict(self._get_handle(path).kernel_restart(art_prefix=art_prefix))
        out["notebook_path"] = str(path)
        return {
            **_server_tool_digest(),
            **self.notebook_resolution_meta(notebook_path, path),
            "notebook_path_resolution_basis": basis,
            **self.kernel_field_hints_fragment(),
            **out,
        }

    def kernel_interrupt(self, notebook_path: str | None = None) -> dict[str, Any]:
        path, basis = self._kernel_tools_resolve(notebook_path)
        k = self._canonical(path)
        h = self._handles.get(k)
        base = {
            **_server_tool_digest(),
            **self.notebook_resolution_meta(notebook_path, path),
            "notebook_path_resolution_basis": basis,
            **self.kernel_field_hints_fragment(),
        }
        if h is None:
            return {
                **base,
                "ok": False,
                "message": "No kernel session for this notebook yet.",
                "notebook_path": str(path),
            }
        result = dict(h.kernel_interrupt())
        result["notebook_path"] = str(path)
        return {**base, **result}

    def kernel_status(self, notebook_path: str | None = None) -> dict[str, Any]:
        path, basis = self._kernel_tools_resolve(notebook_path)
        k = self._canonical(path)
        h = self._handles.get(k)
        base = {
            **_server_tool_digest(),
            **self.notebook_resolution_meta(notebook_path, path),
            "notebook_path_resolution_basis": basis,
            **self.kernel_field_hints_fragment(),
        }
        if h is None:
            return {
                **base,
                "notebook_path": str(path),
                "kernel_generation": 0,
                "kernel_alive": False,
                "interrupted_flag": False,
                "full_top_to_bottom_at_generation": None,
                "notebook_kernel_active": False,
                "note": "No kernel session for this notebook yet; call run(...) or kernel_restart.",
            }
        out = h.kernel_status()
        out["notebook_path"] = str(path)
        out["notebook_kernel_active"] = True
        return {**base, **out}

    def check_allowed_notebook(self, notebook_path: Path) -> None:
        cand = notebook_path.expanduser().resolve()
        if self.default_notebook:
            anchors = allowed_roots_for_notebook(
                self.default_notebook.expanduser().resolve(),
                self.extra_roots,
            )
        else:
            anchors = allowed_roots_for_notebook(cand, self.extra_roots)
        if not is_under_roots(cand, anchors):
            raise PermissionError(f"Notebook path not under allowed roots: {notebook_path}")

    def effective_allowed_roots_resolved_strings(self) -> list[str]:
        """Stable absolute paths enclosing ``notebook_path`` arguments permitted by ``-n`/extra_roots`."""

        if self.default_notebook is None:
            return sorted(str(r.expanduser().resolve()) for r in self.extra_roots)
        roots = allowed_roots_for_notebook(
            self.default_notebook.expanduser().resolve(),
            self.extra_roots,
        )
        return sorted(str(p) for p in roots)

    def notebook_kernel_pool_paths_resolved(self) -> list[str]:
        """Resolved `.ipynb` paths with an allocated kernel slot in this process (LRU-ordered MRU-last)."""

        return [str(p) for p in self._handles.keys()]

    def _companion_gate(
        self,
        notebook_path: Path,
        nb: Any,
        companion_path: str | None,
        companion_strict: bool,
    ) -> dict[str, Any]:
        """Validate optional companion (.apynb JSON or neighbouring .companion.yaml) vs code cells."""

        def _summarize(vf: Path, result: dict[str, Any]) -> dict[str, Any]:
            return {
                "status": "ok",
                "companion_file": str(vf),
                "code_cells_checked": result["companion_code_cells_checked"],
            }

        if companion_path:
            cf = normalize_allowed_path(companion_path)
            self.check_allowed_notebook(cf)
            if not cf.is_file():
                raise FileNotFoundError(f"Companion file not found: {cf}")
            vr = validate_companion_file(notebook_path=notebook_path, notebook=nb, companion_file=cf)
            return _summarize(cf, vr)

        cand = default_companion_path_for_notebook(notebook_path)
        if cand is None:
            if companion_strict:
                ap = companion_path_for_notebook(notebook_path)
                yprimary = companion_yaml_paths_for_notebook(notebook_path)[0]
                raise FileNotFoundError(
                    f"{COMPANION_STRICT_MISSING} Looked for "
                    f"{ap.name} or {yprimary.name} (or `.companion.yml`).",
                )
            return {"status": "skipped", "note": COMPANION_SKIPPED_NOTE}

        self.check_allowed_notebook(cand)
        vr = validate_companion_file(notebook_path=notebook_path, notebook=nb, companion_file=cand)
        return _summarize(cand, vr)

    def notebook_cells_patch(
        self,
        notebook_path: str | None = None,
        *,
        operations: Any,
        validate_first: bool = True,
        set_source_must_be_code: bool = False,
    ) -> dict[str, Any]:
        """Ordered cell mutations in one batch (optional full dry-run via deepcopy, then save)."""

        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required unless the MCP server started with --notebook / -n.",
            )
        path = normalize_allowed_path(nb_path_arg)
        if not path.exists():
            raise FileNotFoundError(f"Notebook not found: {path}")
        self.check_allowed_notebook(path)

        normalized = normalize_patch_operations(operations)
        nb, _ = load_notebook_ensuring_cell_ids(path)
        if validate_first:
            validate_notebook_node(nb)

        if set_source_must_be_code:
            for op in normalized:
                if op["op"] != "set_source":
                    continue
                try:
                    ix = cell_index_for_stable_id(nb, op["cell_id"])
                except LookupError:
                    raise LookupError(
                        f"Unknown code cell_id for cells_apply: {op['cell_id']}",
                    ) from None
                if getattr(nb.cells[ix], "cell_type", None) != "code":
                    raise ValueError(
                        "cells_apply targets code cells only; use notebook_cells_patch for markdown/raw.",
                    )

        if validate_first:
            dup = deepcopy(nb)
            apply_notebook_cells_patch(dup, normalized)
            validate_notebook_node(dup)

        patch_effect_log = apply_notebook_cells_patch(nb, normalized)
        validate_notebook_node(nb)
        save_notebook(nb, path)
        stamp = notebook_file_stamp(path)
        stale_note = (
            COMPANION_MIRROR_STALE_HINT if default_companion_path_for_notebook(path) is not None else None
        )
        edit_hint = NOTEBOOK_EDIT_PERSISTED_VS_KERNEL_HINT if patch_effect_log else None

        return {
            **_server_tool_digest(),
            "status": "ok",
            **self.notebook_resolution_meta(notebook_path, path),
            "notebook_file_stamp": stamp,
            "cells_summary": notebook_cells_summary(nb),
            "patch_effect_log": patch_effect_log,
            "companion_maybe_stale_note": stale_note,
            "notebook_edit_kernel_hint": edit_hint,
        }

    def cells_apply(
        self,
        notebook_path: str | None = None,
        *,
        edits: Any,
        validate_first: bool = True,
    ) -> dict[str, Any]:
        """Apply deterministic code-cell edits by ``cell_id``; saves the notebook and returns a stamp."""
        from llm_jupyter.cells_apply_helpers import normalize_edits

        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required unless the MCP server started with --notebook / -n.",
            )
        path = normalize_allowed_path(nb_path_arg)
        if not path.exists():
            raise FileNotFoundError(f"Notebook not found: {path}")
        self.check_allowed_notebook(path)
        edits_norm = normalize_edits(edits)
        merged: dict[str, str] = {}
        for cid, src in edits_norm:
            merged[cid] = src

        operations = [{"op": "set_source", "cell_id": k, "source": merged[k]} for k in merged]
        rep = self.notebook_cells_patch(
            notebook_path=notebook_path,
            operations=operations,
            validate_first=validate_first,
            set_source_must_be_code=True,
        )
        patch_log = rep.get("patch_effect_log") or []
        updated_rows = [
            {"cell_id": r["cell_id"], "cell_index": r["cell_index"]}
            for r in patch_log
            if r.get("op") == "set_source"
        ]
        stale_note = rep.get("companion_maybe_stale_note")
        return {
            **_server_tool_digest(),
            "status": "ok",
            **self.notebook_resolution_meta(notebook_path, Path(str(rep["notebook_path"]))),
            "cells_updated": updated_rows,
            "edits_applied_last_wins_duplicates": list(merged.keys()),
            "notebook_file_stamp": rep["notebook_file_stamp"],
            "companion_maybe_stale_note": stale_note,
            "notebook_edit_kernel_hint": rep.get("notebook_edit_kernel_hint"),
        }

    def variable_preview(
        self,
        notebook_path: str | None = None,
        *,
        names: Any,
        max_chars_each: int = 400,
        names_strict: bool = False,
    ) -> dict[str, Any]:
        """Return capped ``repr`` snapshots for identifiers in live kernel globals (identifiers only)."""

        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required unless the MCP server started with --notebook / -n.",
            )
        path = normalize_allowed_path(nb_path_arg)
        if not path.exists():
            raise FileNotFoundError(f"Notebook not found: {path}")
        self.check_allowed_notebook(path)

        if names is None:
            raise ValueError("names is required — pass identifiers like xs or df (no dotted lookups).")

        if isinstance(names, str):
            name_list = [names]
        elif isinstance(names, (list, tuple)):
            if len(names) == 0:
                raise ValueError("names must contain at least one identifier.")
            name_list = [str(x) for x in names]
        else:
            raise ValueError("names must be a string identifier or non-empty list of identifiers.")

        id_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        names_omitted_invalid: list[str] = []
        seen_inv: set[str] = set()
        ordered_valid: list[str] = []
        seen_ok: set[str] = set()
        for raw in name_list:
            rid = str(raw).strip()
            if not id_re.fullmatch(rid):
                key = str(raw)
                if key not in seen_inv:
                    seen_inv.add(key)
                    names_omitted_invalid.append(key)
                continue
            if rid not in seen_ok:
                seen_ok.add(rid)
                ordered_valid.append(rid)

        _MAX_PREVIEW_NAMES = 32
        picked = ordered_valid[:_MAX_PREVIEW_NAMES]
        names_truncated_after_pool_cap = ordered_valid[_MAX_PREVIEW_NAMES:]

        if bool(names_strict) and names_omitted_invalid:
            shown = ", ".join(names_omitted_invalid[:12])
            if len(names_omitted_invalid) > 12:
                shown += ", …"
            raise ValueError(
                f"names_strict=true rejects non-identifier names (no attributes/dots/spaces): {shown}",
            )

        if not picked:
            raise ValueError(
                "No valid identifiers after sanitization — pass dotted-free Python identifiers (e.g. df, xs).",
            )

        cap = max(48, min(int(max_chars_each), 8000))

        snippet = (
            "import json as _J\n"
            "_cap = int(__CAP__)\n"
            "_names = __NAMES__\n"
            "_ns = globals()\n"
            "_out = {}\n"
            "for _n in _names:\n"
            "    if _n not in _ns:\n"
            "        _out[_n] = '<not defined>'\n"
            "        continue\n"
            "    try:\n"
            "        _r = repr(_ns[_n])\n"
            "    except Exception as _ex:\n"
            "        _out[_n] = f'<repr error: {_ex!s}>'\n"
            "        continue\n"
            "    if len(_r) > _cap:\n"
            "        _r = _r[: max(1, _cap - 3)] + '...'\n"
            "    _out[_n] = _r\n"
            '_json_text = _J.dumps(_out, ensure_ascii=False)\n'
            "print(__PSTART__)\n"
            "print(_json_text)\n"
            "print(__PEND__)\n"
        )
        snippet = (
            snippet.replace("__CAP__", str(cap))
            .replace("__NAMES__", repr(picked))
            .replace("__PSTART__", repr(_PREVIEW_JSON_START))
            .replace("__PEND__", repr(_PREVIEW_JSON_END))
        )

        handle = self._get_handle(path)
        t0 = time.monotonic()
        handle._ensure_kernel(art_prefix=os.environ.get("LLM_NB_ART_PREFIX"))

        def _kern_ctx() -> dict[str, Any]:
            k2 = handle.kernel_status()
            return {"kernel_alive": k2["kernel_alive"], "kernel_generation": k2["kernel_generation"]}

        def _res_ctx() -> dict[str, str | bool]:
            return self.notebook_resolution_meta(notebook_path, path)

        outs, exc = handle.transient_code_cell_execute(path.parent, snippet)
        wall_ms = int((time.monotonic() - t0) * 1000)

        if exc is not None:
            return {
                **_server_tool_digest(),
                "status": "error",
                **_res_ctx(),
                **_kern_ctx(),
                "names_requested": picked,
                "preview_wall_clock_ms": wall_ms,
                "execution_error": {"ename": str(exc.ename), "evalue": str(exc.evalue)},
                "traceback": str(getattr(exc, "traceback", "") or ""),
            }

        kd = kernel_error_digest_from_outputs(outs)
        if kd is not None:
            tb = kd.get("traceback_text", "") or ""
            return {
                **_server_tool_digest(),
                "status": "error",
                **_res_ctx(),
                **_kern_ctx(),
                "names_requested": picked,
                "preview_wall_clock_ms": wall_ms,
                "execution_error": {"ename": kd["ename"], "evalue": kd["evalue"]},
                "traceback": tb.strip(),
            }

        so_txt, se_txt = collect_streams(outs)
        blob = _variable_preview_stdout_blob(so_txt)

        previews: dict[str, str] | None = None
        if blob:
            try:
                decoded = json.loads(blob)
                if isinstance(decoded, dict):
                    previews = {str(k): str(v) for k, v in decoded.items()}
            except json.JSONDecodeError:
                previews = None

        if previews is None:
            tail = (so_txt + se_txt).strip()
            return {
                **_server_tool_digest(),
                "status": "error",
                **_res_ctx(),
                **_kern_ctx(),
                "names_requested": picked,
                "preview_wall_clock_ms": wall_ms,
                "note": (
                    "Could not parse previews JSON printed by kernel. "
                    f"Captured stdout/stderr tail: {tail[-500:]}"
                ),
            }

        out_ok: dict[str, Any] = {
            **_server_tool_digest(),
            "status": "ok",
            **_res_ctx(),
            **_kern_ctx(),
            "names_requested": picked,
            "max_chars_each_used": cap,
            "preview_wall_clock_ms": wall_ms,
            "previews": previews,
        }
        if names_omitted_invalid:
            out_ok["names_omitted_invalid"] = names_omitted_invalid
        if names_truncated_after_pool_cap:
            out_ok["names_truncated_after_pool_cap"] = names_truncated_after_pool_cap
        if previews and all(v == "<not defined>" for v in previews.values()):
            diag_reasons = [
                "all_requested_names_absent_from_kernel_globals",
                "verify_resolved_notebook_path_matches_artefact_you_executed_with_run",
                "run_prerequisite_code_cells_if_definitions_not_yet_executed",
                "kernel_restart_or_fresh_kernel_clears_user_definitions",
            ]
            if len(picked) < len(name_list) or names_omitted_invalid or names_truncated_after_pool_cap:
                diag_reasons.append("some_requested_names_were_removed_invalid_or_truncated_to_pool_cap")
            out_ok["preview_diagnostic"] = {
                "reasons_checked": diag_reasons,
                "hint": (
                    "Every name is <not defined> in globals(); that does not single out a cause—confirm "
                    "notebook_path, rerun defining cells, or check for a recent kernel_restart."
                ),
            }
        return out_ok

    def inspect_companion(
        self,
        notebook_path: str | None = None,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, Any]:
        """Load notebook and validate companion only (no kernel)."""
        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required unless the MCP server started with --notebook / -n.",
            )
        path = normalize_allowed_path(nb_path_arg)
        if not path.exists():
            raise FileNotFoundError(f"Notebook not found: {path}")
        self.check_allowed_notebook(path)
        nb, _ = load_notebook_ensuring_cell_ids(path)
        validate_notebook_node(nb)
        return self._companion_gate(
            path, nb, self._strip_opt(companion_path), companion_strict
        )

    @staticmethod
    def _strip_opt(s: str | None) -> str | None:
        if s is None:
            return None
        t = str(s).strip()
        return t or None

    def _resolve_run_selector(
        self,
        *,
        notebook_has_code_cells: bool,
        cell_id: str | None,
        run_all: bool,
        run_until_cell_id: str | None,
    ) -> tuple[str, str | None]:
        """Return (kind, id_arg) where id_arg is set for kinds cell|until. Empty notebooks skip execution."""
        cid = self._strip_opt(cell_id)
        rid = self._strip_opt(run_until_cell_id)

        sel_cell = cid is not None
        sel_until = rid is not None
        sel_all = run_all is True

        picked = sel_cell + sel_until + sel_all
        if not notebook_has_code_cells:
            if picked > 1:
                raise ValueError(
                    "Use exactly one of cell_id, run_all=true, run_until_cell_id "
                    "(this notebook has no code cells; extra selectors are contradictory).",
                )
            return ("none", None)
        if picked == 0:
            raise ValueError(
                "Provide exactly one of: cell_id (non-empty string), "
                "run_all=true, or run_until_cell_id (non-empty string).",
            )
        if picked > 1:
            modes = []
            if sel_cell:
                modes.append("cell_id")
            if sel_all:
                modes.append("run_all=true")
            if sel_until:
                modes.append("run_until_cell_id")
            raise ValueError(
                "Conflicting run targets; pass only one mode. Activated: "
                + ", ".join(sorted(modes))
                + ".",
            )

        if sel_cell:
            return ("cell", cid)
        if sel_all:
            return ("all", None)
        return ("until", rid)

    def _indices_from_selector(self, nb: Any, selector: tuple[str, str | None]) -> list[int]:
        kind, sid = selector
        code_idx = indices_of_code_cells(nb)
        bulk = bulk_eligible_code_indices(nb)
        if kind == "none" or not code_idx:
            return []
        if kind == "cell":
            assert sid is not None
            return [cell_index_for_id(nb, sid)]
        if kind == "all":
            return bulk
        if kind == "until":
            assert sid is not None
            target_i = cell_index_for_id(nb, sid)
            return [i for i in bulk if i <= target_i]
        raise AssertionError(f"bad selector {kind}")

    def _canonical_run_path(self, notebook_path: str | None) -> Path:
        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required unless the MCP server started with --notebook / -n.",
            )
        path = normalize_allowed_path(nb_path_arg)
        if not path.exists():
            raise FileNotFoundError(f"Notebook not found: {path}")

        self.check_allowed_notebook(path)
        resolved = path.resolve()
        self._touch_mru(resolved)
        return resolved

    def _notebook_load_and_execution_plan(
        self,
        path: Path,
        *,
        cell_id: str | None,
        run_all: bool,
        run_until_cell_id: str | None,
        validate_first: bool,
        companion_path: str | None,
        companion_strict: bool,
    ) -> tuple[Any, dict[str, Any], list[int], tuple[str, str | None], list[int]]:
        nb, _ = load_notebook_ensuring_cell_ids(path)
        if validate_first:
            validate_notebook_node(nb)

        companion_summary = self._companion_gate(
            path, nb, self._strip_opt(companion_path), companion_strict
        )

        code_idx = indices_of_code_cells(nb)
        selector = self._resolve_run_selector(
            notebook_has_code_cells=bool(code_idx),
            cell_id=cell_id,
            run_all=run_all,
            run_until_cell_id=run_until_cell_id,
        )
        try:
            indices = self._indices_from_selector(nb, selector)
        except LookupError as e:
            raise LookupError(f"{e} (resolved notebook: {path})") from e

        return nb, companion_summary, code_idx, selector, indices

    def resolve_run_targets(
        self,
        notebook_path: str | None = None,
        cell_id: str | None = None,
        run_all: bool = False,
        run_until_cell_id: str | None = None,
        validate_first: bool = True,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, Any]:
        """Backward-compatible alias for ``notebook_execution_plan`` (tests / Python callers)."""

        return self.notebook_execution_plan(
            notebook_path=notebook_path,
            cell_id=cell_id,
            run_all=run_all,
            run_until_cell_id=run_until_cell_id,
            validate_first=validate_first,
            companion_path=companion_path,
            companion_strict=companion_strict,
        )

    def notebook_execution_plan(
        self,
        notebook_path: str | None = None,
        cell_id: str | None = None,
        run_all: bool = False,
        run_until_cell_id: str | None = None,
        validate_first: bool = True,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, Any]:
        """Notebook structure + companion; optional selectors (omit all three ⇒ structural_probe)."""

        path = self._canonical_run_path(notebook_path)
        handle = self._get_handle(path)
        nb, _ = load_notebook_ensuring_cell_ids(path)
        if validate_first:
            validate_notebook_node(nb)

        companion_summary = self._companion_gate(path, nb, self._strip_opt(companion_path), companion_strict)
        code_idx = indices_of_code_cells(nb)

        cid = self._strip_opt(cell_id)
        rid = self._strip_opt(run_until_cell_id)
        sel_cell = cid is not None
        sel_until = rid is not None
        sel_all = run_all is True
        picked = sel_cell + sel_until + sel_all

        if picked > 1:
            modes: list[str] = []
            if sel_cell:
                modes.append("cell_id")
            if sel_all:
                modes.append("run_all=true")
            if sel_until:
                modes.append("run_until_cell_id")
            raise ValueError(
                "Conflicting run targets; pass only one mode. Activated: " + ", ".join(sorted(modes)) + ".",
            )

        if picked == 0:
            kind, sid = ("structural_probe", None)
            indices: list[int] = []
        else:
            selector = self._resolve_run_selector(
                notebook_has_code_cells=bool(code_idx),
                cell_id=cell_id,
                run_all=run_all,
                run_until_cell_id=run_until_cell_id,
            )
            kind, sid = selector
            indices = self._indices_from_selector(nb, selector)

        cells_planned: list[dict[str, Any]] = []
        for idx in indices:
            cell = nb.cells[idx]
            cid_row = str(cell.get("metadata", {}).get("cell_id", "") or "").strip()
            cells_planned.append({"cell_index": idx, "cell_id": cid_row or None})

        if kind == "structural_probe":
            note = (
                "No execution—kernel not started. selector_kind=structural_probe: code_cell_indices lists all code cells; "
                "pass exactly one of cell_id / run_all / run_until_cell_id to mirror run execution_cell_indices."
            )
        else:
            note = (
                "No execution—kernel not started. kernel_status_preview reflects the pooled handle for this notebook."
            )

        out: dict[str, Any] = {
            **_server_tool_digest(),
            "status": "ok",
            **self.notebook_resolution_meta(notebook_path, path),
            "selector_kind": kind,
            "selector_arg": sid,
            "code_cell_indices": code_idx,
            "execution_cell_indices": indices,
            "cells_planned": cells_planned,
            "cells_planned_n": len(indices),
            "kernel_status_preview": handle.kernel_status(),
            "note": note,
        }
        if companion_summary is not None and companion_summary.get("status") != "skipped":
            out["companion"] = companion_summary
        return out

    def run(
        self,
        notebook_path: str | None = None,
        cell_id: str | None = None,
        run_all: bool = False,
        run_until_cell_id: str | None = None,
        halt_on_error: bool = True,
        mode: str | None = None,
        preview_rows: int = 8,
        max_image_side: int = 256,
        validate_first: bool = True,
        debug: bool = False,
        companion_path: str | None = None,
        companion_strict: bool = False,
        compact_assistant_quick: bool = False,
        strip_ansi_streams: bool = False,
        persist_stream_outputs: str = "full",
        omit_stream_chunks: bool | None = None,
    ) -> dict[str, Any]:
        t0 = time.monotonic()
        mode_eff = (mode or self.default_mode).lower()
        if mode_eff not in ("explore", "record"):
            mode_eff = "explore"

        path = self._canonical_run_path(notebook_path)

        handle = self._get_handle(path)
        compact_quick = assistant_quick_compact_requested(compact_assistant_quick)
        strip_esc = ansi_streams_strip_requested(strip_ansi_streams)
        restart_since_previous = (
            handle._generation_at_previous_tool_end is not None
            and handle._generation_at_previous_tool_end != handle.kernel_generation
        )

        nb, companion_summary, code_idx, _selector, indices = self._notebook_load_and_execution_plan(
            path,
            cell_id=cell_id,
            run_all=run_all,
            run_until_cell_id=run_until_cell_id,
            validate_first=validate_first,
            companion_path=companion_path,
            companion_strict=companion_strict,
        )

        run_id = uuid.uuid4().hex[:12]
        first_id_short = ""
        if code_idx:
            rid0 = nb.cells[code_idx[0]].get("metadata", {}).get("cell_id") or "cell"
            first_id_short = str(rid0)[:8]

        anchor_short = first_id_short
        if indices:
            i0 = indices[0]
            c0 = nb.cells[i0]
            if getattr(c0, "cell_type", "") == "code":
                cid0 = str(c0.get("metadata", {}).get("cell_id", "")).strip()
                if cid0:
                    anchor_short = cid0[:8]

        handle._ensure_kernel(art_prefix=os.environ.get("LLM_NB_ART_PREFIX"))

        from datetime import UTC, datetime

        prefix_hint = (
            f"{datetime.now(UTC).strftime('%Y%m%d')}_gen{handle.kernel_generation}_{anchor_short}"
        )

        if mode_eff == "record" and prefix_hint:
            os.environ.setdefault("LLM_NB_ART_PREFIX", prefix_hint)
        cells_executed_ids: list[str] = []
        status = "ok"
        error_cell_id: str | None = None
        stdout_acc: list[str] = []
        stderr_acc: list[str] = []
        preview_pairs: list[tuple[Any, int]] = []
        executed_in_order: list[int] = []
        execution_error: dict[str, str] | None = None

        if not indices:
            sm = stream_summary_for_tool("", "", stdout_chunks={}, stderr_chunks={})
            phase_ms_early = {"pre_execute_ms": int((time.monotonic() - t0) * 1000)}
            budget_early = mcp_stream_char_budget()
            persist_early = (persist_stream_outputs or "full").strip().lower()
            if persist_early not in ("full", "external_only"):
                persist_early = "full"
            payload = self._payload(
                mode_eff,
                path,
                run_id,
                [],
                "ok",
                None,
                restart_since_previous,
                False,
                [],
                "",
                [],
                {},
                {},
                t0,
                preview_rows,
                max_image_side,
                debug,
                [],
                [],
                companion_summary,
                sm,
                None,
                halt_on_error=halt_on_error,
                streams_by_cell_executed=None,
                streams_by_cell_truncated=False,
                kernel_errors_truncated=None,
                phase_timings_ms=phase_ms_early,
                kernel_generation=handle.kernel_generation,
                compact_assistant_quick=compact_quick,
                notebook_path_arg=notebook_path,
                stream_delivery="inline",
                stream_artifacts=None,
                mcp_stream_spilled=False,
                mcp_stream_char_budget=budget_early,
                persist_stream_outputs=persist_early,
            )
            stamp = notebook_file_stamp(path)
            src_hash, nb_snap_rel = _manifest_sources_and_optional_snapshot(nb, path, run_id, mode_eff)
            man_early: dict[str, Any] = {
                "run_id": run_id,
                "ts_ms": int(time.time() * 1000),
                "mode": mode_eff,
                "notebook_path": str(path),
                "notebook_file_stamp": stamp,
                "sources_concat_sha256_prefix": src_hash,
                "python_env_snapshot": payload["python_env_snapshot"],
                "kernel_generation": handle.kernel_generation,
                "cells_executed": [],
                "status": "ok",
                "note": "no_code_cells",
                "companion": companion_summary,
            }
            if nb_snap_rel is not None:
                man_early["notebook_snapshot_relative"] = nb_snap_rel
            if mode_eff == "record":
                meta_e = env_snapshot_ttl_meta_from_snapshot(payload["python_env_snapshot"])
                if meta_e:
                    man_early["python_env_snapshot_meta"] = meta_e
            t_ma0 = time.monotonic()
            append_manifest(path.parent / "manifest.jsonl", man_early)
            manifest_ms_early = int((time.monotonic() - t_ma0) * 1000)
            payload.setdefault("phase_timings_ms", {})["manifest_append_wall_ms"] = manifest_ms_early
            handle._generation_at_previous_tool_end = handle.kernel_generation
            return payload

        client = handle._executor(nb, path)
        client.allow_errors = not halt_on_error

        phase_ms: dict[str, int] = {}
        t_before_sk = time.monotonic()
        phase_ms["pre_execute_ms"] = int((t_before_sk - t0) * 1000)

        ran_ok_full = False
        streams_by_cell_raw: list[dict[str, Any]] = []
        kernel_errors_truncated_rows: list[dict[str, str]] = []

        def _maybe_push_kernel_errors_log(cid_logged: str, idx_logged: int, kd_logged: dict[str, str]) -> None:
            if len(kernel_errors_truncated_rows) >= MAX_KERNEL_ERROR_LOG_ENTRIES:
                return
            kernel_errors_truncated_rows.append(
                {
                    "cell_id": cid_logged,
                    "cell_index": str(idx_logged),
                    "ename": kd_logged["ename"],
                    "evalue": kd_logged["evalue"][:2400],
                },
            )

        t_loop_start = t_before_sk
        try:
            with client.setup_kernel(cleanup_kc=False):
                t_after_attach = time.monotonic()
                phase_ms["kernel_shell_setup_ms"] = int((t_after_attach - t_before_sk) * 1000)
                t_loop_start = t_after_attach
                for idx in indices:
                    cell = nb.cells[idx]
                    cid = str(cell.get("metadata", {}).get("cell_id", "") or "").strip()

                    exec_exc: CellExecutionError | None = None
                    try:
                        client.execute_cell(cell, idx)
                    except CellExecutionError as e:
                        exec_exc = e

                    outputs = list(cell.outputs or [])
                    kd = kernel_error_digest_from_outputs(outputs)
                    if kd is None and exec_exc is not None:
                        tb_txt = getattr(exec_exc, "traceback", "") or ""
                        kd = {
                            "ename": str(exec_exc.ename),
                            "evalue": str(exec_exc.evalue),
                            "traceback_text": str(tb_txt),
                        }

                    if cid and cid not in cells_executed_ids:
                        cells_executed_ids.append(cid)
                    executed_in_order.append(idx)

                    so, se = collect_streams(outputs)
                    if strip_esc:
                        so = strip_ansi_text(so)
                        se = strip_ansi_text(se)
                    if kd is not None:
                        tb_text = kd.get("traceback_text", "") or ""
                        se = append_kernel_traceback_stderr(se, tb_text)
                        if not se.strip() and exec_exc is not None:
                            se = append_kernel_traceback_stderr(se, str(exec_exc))
                        execution_error = {"ename": kd["ename"], "evalue": kd["evalue"]}
                        error_cell_id = cid or error_cell_id
                        status = "error"
                        _maybe_push_kernel_errors_log(cid, idx, kd)

                    stdout_acc.append(so)
                    stderr_acc.append(se)
                    preview_pairs.append((cell, idx))
                    streams_by_cell_raw.append(
                        cell_stream_row(
                            cell_id=cid,
                            cell_index=idx,
                            stdout_full=so,
                            stderr_full=se,
                        ),
                    )

                    if kd is not None and halt_on_error:
                        break

                ran_ok_full = bulk_eligible_code_indices(nb) == executed_in_order and status == "ok"
        except KeyboardInterrupt:
            status = "interrupted"
            handle.interrupted = True
        except Exception:
            status = "error"
            stderr_acc.append(traceback.format_exc())

        t_after_loop = time.monotonic()
        phase_ms["notebook_execute_loop_ms"] = int((t_after_loop - t_loop_start) * 1000)

        combined_stream_chars = sum(len(x) for x in stdout_acc) + sum(len(x) for x in stderr_acc)
        budget_eff = mcp_stream_char_budget()
        persist_eff = (persist_stream_outputs or "full").strip().lower()
        if persist_eff not in ("full", "external_only"):
            persist_eff = "full"
        phase_ms["mcp_stream_char_budget"] = budget_eff
        phase_ms["combined_stream_chars_observed"] = combined_stream_chars

        if persist_eff == "external_only" and combined_stream_chars > budget_eff and executed_in_order:
            strip_cell_outputs_matching_type(nb, executed_in_order, output_type="stream")

        t_before_save = time.monotonic()
        save_notebook(nb, path)
        t_after_save = time.monotonic()
        phase_ms["notebook_save_after_execute_ms"] = int((t_after_save - t_before_save) * 1000)

        if ran_ok_full:
            handle.full_top_to_bottom_at_generation = handle.kernel_generation

        stale, stale_notes = self._compute_stale_notes_after_run(
            ran_ok_full, status, handle, restart_since_previous
        )

        out_files = self._guess_output_files(path.parent, prefix_hint)

        prev = previews_from_cells(preview_pairs, preview_rows, max_image_side)
        tbl = prev["tables"]
        img = prev["images"]

        stdout_joined = "\n".join(stdout_acc).strip()
        stderr_joined = "\n".join(stderr_acc).strip()

        spill = combined_stream_chars > budget_eff
        stream_artifacts_meta: dict[str, Any] | None = None
        omit_chunks_effective = _omit_stream_chunks_requested(omit_stream_chunks) and not spill

        if spill:
            stream_artifacts_meta = write_run_stream_artifacts(
                path,
                run_id,
                stdout_text=stdout_joined,
                stderr_text=stderr_joined,
                extra_meta={
                    "mode": mode_eff,
                    "status": status,
                    "cells_executed": cells_executed_ids,
                    "persist_stream_outputs": persist_eff,
                },
            )
            so_chunks, se_chunks = {}, {}
        elif omit_chunks_effective:
            so_chunks, se_chunks = {}, {}
        else:
            so_chunks = chunk_text(stdout_joined, self.chunk_chars) if stdout_joined else {}
            se_chunks = chunk_text(stderr_joined, self.chunk_chars) if stderr_joined else {}

        stream_delivery = (
            "artifacts_plus_preview"
            if spill
            else ("inline_omit_chunk_maps" if omit_chunks_effective else "inline")
        )
        sm = stream_summary_for_tool(
            stdout_joined,
            stderr_joined,
            stdout_chunks=so_chunks,
            stderr_chunks=se_chunks,
        )

        streams_for_payload, strm_truncated = trim_streams_by_cell(streams_by_cell_raw)
        errs_for_payload = kernel_errors_truncated_rows or None

        t_before_payload = time.monotonic()
        # Roll-up from ZMQ execution end → ready for _payload: persist + previews + concatenating /
        # chunking / trimming stdout+stderr used in the MCP tool JSON (distinct from MCP transport serialize).
        phase_ms["post_execute_through_chunks_ms"] = int((t_before_payload - t_after_loop) * 1000)
        phase_ms["streams_previews_prepare_ms"] = int((t_before_payload - t_after_save) * 1000)

        payload = self._payload(
            mode_eff,
            path,
            run_id,
            cells_executed_ids,
            status,
            error_cell_id,
            restart_since_previous,
            stale,
            stale_notes,
            prefix_hint,
            out_files,
            so_chunks,
            se_chunks,
            t0,
            preview_rows,
            max_image_side,
            debug,
            tbl,
            img,
            companion_summary,
            sm,
            execution_error,
            halt_on_error=halt_on_error,
            streams_by_cell_executed=streams_for_payload if streams_for_payload else None,
            streams_by_cell_truncated=strm_truncated,
            kernel_errors_truncated=errs_for_payload,
            phase_timings_ms=phase_ms,
            kernel_generation=handle.kernel_generation,
            compact_assistant_quick=compact_quick,
            notebook_path_arg=notebook_path,
            stream_delivery=stream_delivery,
            stream_artifacts=stream_artifacts_meta,
            mcp_stream_spilled=spill,
            mcp_stream_char_budget=budget_eff,
            persist_stream_outputs=persist_eff,
        )

        src_hash2, nb_snap_rel2 = _manifest_sources_and_optional_snapshot(nb, path, run_id, mode_eff)
        man_row: dict[str, Any] = {
            "run_id": run_id,
            "ts_ms": int(time.time() * 1000),
            "mode": mode_eff,
            "notebook_path": str(path),
            "notebook_file_stamp": payload["notebook_file_stamp"],
            "sources_concat_sha256_prefix": src_hash2,
            "python_env_snapshot": payload["python_env_snapshot"],
            "kernel_generation": handle.kernel_generation,
            "cells_executed": cells_executed_ids,
            "status": status,
            "stderr_digest_tail": stderr_joined[-512:],
            "halt_on_error": halt_on_error,
            "companion": companion_summary,
        }
        if nb_snap_rel2 is not None:
            man_row["notebook_snapshot_relative"] = nb_snap_rel2
        if stream_artifacts_meta:
            man_row["stream_artifacts"] = stream_artifacts_meta
        if mode_eff == "record":
            meta_m = env_snapshot_ttl_meta_from_snapshot(payload["python_env_snapshot"])
            if meta_m:
                man_row["python_env_snapshot_meta"] = meta_m
        t_ma = time.monotonic()
        append_manifest(path.parent / "manifest.jsonl", man_row)
        payload.setdefault("phase_timings_ms", {})["manifest_append_wall_ms"] = int(
            (time.monotonic() - t_ma) * 1000
        )

        handle._generation_at_previous_tool_end = handle.kernel_generation
        return payload

    def _guess_output_files(self, nb_dir: Path, prefix: str) -> list[str]:
        if not prefix:
            return []
        return sorted(
            p.name
            for p in nb_dir.glob(f"{prefix}*")
            if p.is_file()
            and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".csv", ".json", ".pdf")
        )

    def _compute_stale_notes_after_run(
        self,
        ran_ok_full: bool,
        status: str,
        handle: NotebookKernelHandle,
        restart_since_previous: bool,
    ) -> tuple[bool, list[str]]:
        notes: list[str] = []
        full_mismatch = handle.full_top_to_bottom_at_generation != handle.kernel_generation
        if status == "interrupted":
            notes.append("Interrupted: persisted outputs may be incomplete versus kernel RAM.")
            return True, notes
        if status == "error":
            notes.append(
                "Execution exited with errors; some cells reflect this batch while others keep older persisted output.",
            )
            if full_mismatch:
                notes.append(
                    "No successful full-notebook rerun has completed yet at this kernel_generation; "
                    "persisted notebook outputs versus this kernel RAM may diverge.",
                )
            return True, notes if notes else ["outputs_might_be_stale."]
        if ran_ok_full:
            return False, []
        notes.append(
            "Partial run: cells not rerun may keep stale outputs versus live kernel RAM.",
        )
        if full_mismatch:
            notes.append(
                "No successful full-notebook rerun has completed yet at this kernel_generation; "
                "persisted plots/streams may not reflect an all-together rerun on this kernel.",
            )
            if restart_since_previous:
                notes.append(
                    "kernel_generation changed since the previous MCP tool ended for this notebook "
                    "(restart/interrupt/start); rerun all code cells once if you rely on persisted outputs.",
                )
        return True, notes if notes else ["outputs_might_be_stale."]

    def _payload(
        self,
        mode: str,
        notebook_path: Path,
        run_id: str,
        cells_executed: list[str],
        status: str,
        error_cell_id: str | None,
        restart_since_previous: bool,
        outputs_might_be_stale: bool,
        stale_notes: list[str],
        suggested_figure_prefix: str,
        output_files: list[str],
        stdout_chunks: dict[str, str],
        stderr_chunks: dict[str, str],
        t0: float,
        preview_rows: int,
        max_image_side: int,
        debug: bool,
        table_preview: list | None = None,
        image_preview: list | None = None,
        companion_summary: dict[str, Any] | None = None,
        stream_summary: dict[str, Any] | None = None,
        execution_error: dict[str, str] | None = None,
        *,
        halt_on_error: bool = True,
        streams_by_cell_executed: list[dict[str, Any]] | None = None,
        streams_by_cell_truncated: bool = False,
        kernel_errors_truncated: list[dict[str, str]] | None = None,
        phase_timings_ms: dict[str, int] | None = None,
        compact_assistant_quick: bool = False,
        kernel_generation: int,
        notebook_path_arg: str | None = None,
        stream_delivery: str = "inline",
        stream_artifacts: dict[str, Any] | None = None,
        mcp_stream_spilled: bool = False,
        mcp_stream_char_budget: int | None = None,
        persist_stream_outputs: str = "full",
    ) -> dict[str, Any]:
        t_pa = time.monotonic()
        stamp = notebook_file_stamp(notebook_path)
        t_fp = time.perf_counter()
        env_snap = python_env_snapshot(mode)
        fingerprint_ms = int((time.perf_counter() - t_fp) * 1000)
        if phase_timings_ms is not None:
            phase_timings_ms["record_env_fingerprint_ms"] = fingerprint_ms
        sm_eff = stream_summary or {}
        uch, sch = sm_eff.get("stdout_chars") or 0, sm_eff.get("stderr_chars") or 0
        if uch + sch == 0:
            stream_capture_hint = "no captured stdout/stderr"
        else:
            stream_capture_hint = (
                f"stdout ~{uch} chars ({sm_eff.get('stdout_chunk_count', 0)} chunks); "
                f"stderr ~{sch} chars ({sm_eff.get('stderr_chunk_count', 0)} chunks)"
            )

        error_one_liner: str | None = None
        if execution_error is not None:
            raw = f"{execution_error['ename']}: {execution_error['evalue']}"
            error_one_liner = raw if len(raw) <= 380 else raw[:377] + "..."

        assistant_quick: dict[str, Any] = {
            **_server_tool_digest(),
            "notebook_filename": notebook_path.name,
            "run_id": run_id,
            "status": status,
            "cells_executed_n": len(cells_executed),
            "kernel_generation": kernel_generation,
            "restart_since_previous_tool_call": restart_since_previous,
            "outputs_might_be_stale": outputs_might_be_stale,
            "stale_primary_note": stale_notes[0] if stale_notes else None,
            "error_one_liner": error_one_liner,
            "stream_capture": stream_capture_hint,
            "halt_on_error": halt_on_error,
        }
        if not compact_assistant_quick:
            assistant_quick["halt_on_false_means_continue_not_hide_errors"] = (
                "halt_on_error=false asks nbclient to keep going after notebook errors yet this server "
                'still surfaces them (status:error, execution_error, stderr/traceback)—not silent "OK". '
                "Repeated kernel errors accumulate in kernel_errors_truncated."
            )
            assistant_quick["kernel_wall_clock_hint"] = (
                "kernel_runtime_ms and server_run_handler_wall_ms (same scalar today) exclude manifest append "
                "and MCP UTF-8 JSON framing; phase_timings_ms.record_env_fingerprint_ms isolates record-mode env hashing; "
                "see timings_truncation_hint."
            )
        if mode == "record" and not compact_assistant_quick:
            for k in (
                "env_snapshot_cache_hit",
                "env_snapshot_ttl_sec_configured",
                "env_snapshot_cache_age_mono_sec",
                "env_snapshot_policy_version",
            ):
                if k in env_snap:
                    assistant_quick[k] = env_snap[k]

        res: dict[str, Any] = {
            "status": status,
            "run_id": run_id,
            "mode": mode,
        }
        res.update(self.notebook_resolution_meta(notebook_path_arg, notebook_path))
        if execution_error is not None:
            res["execution_error"] = execution_error
        if error_cell_id:
            res["error_cell_id"] = error_cell_id
        res["assistant_quick"] = assistant_quick
        res.update(
            {
                "cells_executed": cells_executed,
                "halt_on_error": halt_on_error,
                "kernel_generation": kernel_generation,
                "restart_since_previous_tool_call": restart_since_previous,
                "outputs_might_be_stale": outputs_might_be_stale,
                "stale_notes": stale_notes,
                "stream_summary": sm_eff,
                "suggested_figure_prefix": suggested_figure_prefix,
                "output_files": output_files,
                "previews": {"tables": table_preview or [], "images": image_preview or []},
                "stdout_chunks": stdout_chunks,
                "stderr_chunks": stderr_chunks,
                "preview_rows_used": preview_rows,
                "max_image_side_used": max_image_side,
                "notebook_file_stamp": stamp,
                "python_env_snapshot": env_snap,
            },
        )
        if companion_summary is not None and companion_summary.get("status") != "skipped":
            res["companion"] = companion_summary
        if streams_by_cell_executed:
            res["streams_by_cell_executed"] = streams_by_cell_executed
            if streams_by_cell_truncated:
                res["streams_by_cell_truncated"] = True
        if kernel_errors_truncated:
            res["kernel_errors_truncated"] = kernel_errors_truncated

        res["stream_truncation_semantics"] = dict(STREAM_SUFFIX_DESCRIPTOR)
        res["stream_delivery"] = stream_delivery
        res["persist_stream_outputs_used"] = persist_stream_outputs
        if mcp_stream_char_budget is not None:
            res["mcp_stream_char_budget_used"] = mcp_stream_char_budget
        if mcp_stream_spilled:
            res["mcp_stream_spilled"] = True
        if stream_artifacts:
            res["stream_artifacts"] = stream_artifacts

        if phase_timings_ms is not None:
            phase_timings_ms["payload_assembly_ms"] = int((time.monotonic() - t_pa) * 1000)
            res["phase_timings_ms"] = phase_timings_ms
            res["timings_truncation_hint"] = (
                "phase_timings_ms values are integer milliseconds from monotonic clocks; sub-ms work rounds to 0."
            )
        res["kernel_runtime_ms"] = int((time.monotonic() - t0) * 1000)
        res["server_run_handler_wall_ms"] = res["kernel_runtime_ms"]
        if debug:
            res["debug"] = True
        return res
