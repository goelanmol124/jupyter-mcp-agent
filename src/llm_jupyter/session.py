from __future__ import annotations

import os
import time
import traceback
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from jupyter_client import KernelManager
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

from llm_jupyter.chunks import chunk_text, collect_streams, stream_summary_for_tool
from llm_jupyter.companion import companion_path_for_notebook, validate_companion_file
from llm_jupyter.env_snapshot import python_env_snapshot
from llm_jupyter.manifest import append_manifest
from llm_jupyter.notebook import (
    cell_index_for_id,
    ensure_cell_ids,
    indices_of_code_cells,
    load_notebook,
    save_notebook,
    validate_notebook_node,
)
from llm_jupyter.paths import allowed_roots_for_notebook, is_under_roots, normalize_allowed_path
from llm_jupyter.previews import previews_from_cells
from llm_jupyter.stamp import notebook_file_stamp


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
    return max(1, min(n, 256)) if n != 0 else 0


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

    def _canonical(self, notebook_path: Path) -> Path:
        return notebook_path.expanduser().resolve()

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

    def _kernel_tools_path_arg(self, notebook_path: str | None) -> Path:
        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required for kernel_restart / kernel_interrupt / kernel_status "
                "unless the MCP server was started with --notebook / -n "
                "(one default notebook implied).",
            )
        path = normalize_allowed_path(nb_path_arg)
        self.check_allowed_notebook(path)
        return path.resolve()

    def kernel_restart(self, notebook_path: str | None = None, art_prefix: str | None = None) -> dict[str, Any]:
        path = self._kernel_tools_path_arg(notebook_path)
        out = dict(self._get_handle(path).kernel_restart(art_prefix=art_prefix))
        out["notebook_path"] = str(path)
        return {**_server_tool_digest(), **out}

    def kernel_interrupt(self, notebook_path: str | None = None) -> dict[str, Any]:
        path = self._kernel_tools_path_arg(notebook_path)
        k = self._canonical(path)
        h = self._handles.get(k)
        if h is None:
            return {
                **_server_tool_digest(),
                "ok": False,
                "message": "No kernel session for this notebook yet.",
                "notebook_path": str(path),
            }
        result = dict(h.kernel_interrupt())
        result["notebook_path"] = str(path)
        return {**_server_tool_digest(), **result}

    def kernel_status(self, notebook_path: str | None = None) -> dict[str, Any]:
        path = self._kernel_tools_path_arg(notebook_path)
        k = self._canonical(path)
        h = self._handles.get(k)
        if h is None:
            return {
                **_server_tool_digest(),
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
        return {**_server_tool_digest(), **out}

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

    def _companion_gate(
        self,
        notebook_path: Path,
        nb: Any,
        companion_path: str | None,
        companion_strict: bool,
    ) -> dict[str, Any]:
        """Validate optional .apynb sidecar against code cells."""

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

        side = companion_path_for_notebook(notebook_path)
        if not side.exists():
            if companion_strict:
                raise FileNotFoundError(
                    f"companion_strict=true but companion file missing: expected {side}",
                )
            return {"status": "skipped", "note": "No same-stem .apynb beside this notebook."}

        self.check_allowed_notebook(side)
        vr = validate_companion_file(notebook_path=notebook_path, notebook=nb, companion_file=side)
        return _summarize(side, vr)

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
        ensure_cell_ids(load_notebook(path), persist_path=path)
        nb = load_notebook(path)
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
        if kind == "none" or not code_idx:
            return []
        if kind == "cell":
            assert sid is not None
            return [cell_index_for_id(nb, sid)]
        if kind == "all":
            return code_idx
        if kind == "until":
            assert sid is not None
            target_i = cell_index_for_id(nb, sid)
            return [i for i in code_idx if i <= target_i]
        raise AssertionError(f"bad selector {kind}")

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
    ) -> dict[str, Any]:
        t0 = time.monotonic()
        mode_eff = (mode or self.default_mode).lower()
        if mode_eff not in ("explore", "record"):
            mode_eff = "explore"

        nb_path_arg = notebook_path or (str(self.default_notebook) if self.default_notebook else "")
        if not str(nb_path_arg).strip():
            raise ValueError(
                "notebook_path is required unless the MCP server started with --notebook / -n.",
            )
        path = normalize_allowed_path(nb_path_arg)
        if not path.exists():
            raise FileNotFoundError(f"Notebook not found: {path}")

        self.check_allowed_notebook(path)

        handle = self._get_handle(path)
        restart_since_previous = (
            handle._generation_at_previous_tool_end is not None
            and handle._generation_at_previous_tool_end != handle.kernel_generation
        )

        ensure_cell_ids(load_notebook(path), persist_path=path)
        nb = load_notebook(path)
        if validate_first:
            validate_notebook_node(nb)

        companion_summary = self._companion_gate(
            path, nb, self._strip_opt(companion_path), companion_strict
        )

        run_id = uuid.uuid4().hex[:12]

        code_idx = indices_of_code_cells(nb)
        selector = self._resolve_run_selector(
            notebook_has_code_cells=bool(code_idx),
            cell_id=cell_id,
            run_all=run_all,
            run_until_cell_id=run_until_cell_id,
        )
        indices = self._indices_from_selector(nb, selector)
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
                kernel_generation=handle.kernel_generation,
            )
            stamp = notebook_file_stamp(path)
            append_manifest(
                path.parent / "manifest.jsonl",
                {
                    "run_id": run_id,
                    "ts_ms": int(time.time() * 1000),
                    "mode": mode_eff,
                    "notebook_path": str(path),
                    "notebook_file_stamp": stamp,
                    "python_env_snapshot": python_env_snapshot(mode_eff),
                    "kernel_generation": handle.kernel_generation,
                    "cells_executed": [],
                    "status": "ok",
                    "note": "no_code_cells",
                    "companion": companion_summary,
                },
            )
            handle._generation_at_previous_tool_end = handle.kernel_generation
            return payload

        client = handle._executor(nb, path)
        client.allow_errors = not halt_on_error

        ran_ok_full = False
        try:
            with client.setup_kernel(cleanup_kc=False):
                for idx in indices:
                    cell = nb.cells[idx]
                    cid = str(cell.get("metadata", {}).get("cell_id", ""))
                    try:
                        client.execute_cell(cell, idx)
                        if cid:
                            cells_executed_ids.append(cid)
                        executed_in_order.append(idx)
                        so, se = collect_streams(list(cell.outputs or []))
                        stdout_acc.append(so)
                        stderr_acc.append(se)
                        preview_pairs.append((cell, idx))
                    except CellExecutionError as e:
                        # nbclient's CellExecutionError has traceback / ename / evalue — not `.cell`;
                        # use the loop's notebook node.
                        err_cell = cell
                        ecid = str(err_cell.get("metadata", {}).get("cell_id", ""))
                        error_cell_id = ecid or error_cell_id
                        if ecid and ecid not in cells_executed_ids:
                            cells_executed_ids.append(ecid)
                        executed_in_order.append(idx)
                        so, se = collect_streams(list(err_cell.outputs or []))
                        if not se.strip():
                            se = str(e)
                        stdout_acc.append(so)
                        stderr_acc.append(se)
                        preview_pairs.append((err_cell, idx))
                        execution_error = {"ename": str(e.ename), "evalue": str(e.evalue)}
                        status = "error"
                        if halt_on_error:
                            break
                ran_ok_full = indices_of_code_cells(nb) == executed_in_order and status == "ok"
        except KeyboardInterrupt:
            status = "interrupted"
            handle.interrupted = True
        except Exception:
            status = "error"
            stderr_acc.append(traceback.format_exc())

        save_notebook(nb, path)

        if ran_ok_full:
            handle.full_top_to_bottom_at_generation = handle.kernel_generation

        stale, stale_notes = self._compute_stale_notes_after_run(ran_ok_full, status, handle)

        out_files = self._guess_output_files(path.parent, prefix_hint)

        prev = previews_from_cells(preview_pairs, preview_rows, max_image_side)
        tbl = prev["tables"]
        img = prev["images"]

        stdout_joined = "\n".join(stdout_acc).strip()
        stderr_joined = "\n".join(stderr_acc).strip()

        so_chunks = chunk_text(stdout_joined, self.chunk_chars) if stdout_joined else {}
        se_chunks = chunk_text(stderr_joined, self.chunk_chars) if stderr_joined else {}
        sm = stream_summary_for_tool(
            stdout_joined,
            stderr_joined,
            stdout_chunks=so_chunks,
            stderr_chunks=se_chunks,
        )

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
            kernel_generation=handle.kernel_generation,
        )

        append_manifest(
            path.parent / "manifest.jsonl",
            {
                "run_id": run_id,
                "ts_ms": int(time.time() * 1000),
                "mode": mode_eff,
                "notebook_path": str(path),
                "notebook_file_stamp": payload["notebook_file_stamp"],
                "python_env_snapshot": payload["python_env_snapshot"],
                "kernel_generation": handle.kernel_generation,
                "cells_executed": cells_executed_ids,
                "status": status,
                "stderr_digest_tail": stderr_joined[-512:],
                "halt_on_error": halt_on_error,
                "companion": companion_summary,
            },
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
        self, ran_ok_full: bool, status: str, handle: NotebookKernelHandle
    ) -> tuple[bool, list[str]]:
        notes: list[str] = []
        if status == "interrupted":
            notes.append("Interrupted: persisted outputs may be incomplete versus kernel RAM.")
            return True, notes
        if status == "error":
            notes.append(
                "Execution exited with errors; some cells reflect this batch while others keep older persisted output.",
            )
            if handle.full_top_to_bottom_at_generation != handle.kernel_generation:
                notes.append(
                    "No successful full-notebook rerun yet at the current kernel_generation "
                    "(including after restart).",
                )
            return True, notes if notes else ["outputs_might_be_stale."]
        if ran_ok_full:
            return False, []
        notes.append(
            "Partial run: cells not rerun may keep stale outputs versus live kernel RAM.",
        )
        if handle.full_top_to_bottom_at_generation != handle.kernel_generation:
            notes.append(
                "Kernel restarted since the last full-notebook rerun; rerun all cells to align saved plots.",
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
        kernel_generation: int,
    ) -> dict[str, Any]:
        stamp = notebook_file_stamp(notebook_path)
        env_snap = python_env_snapshot(mode)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
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
        }

        # Outcomes first for primacy/recency bias; chunks and env blobs last.
        res: dict[str, Any] = {
            "assistant_quick": assistant_quick,
            "run_id": run_id,
            "mode": mode,
            "status": status,
        }
        if execution_error is not None:
            res["execution_error"] = execution_error
        if error_cell_id:
            res["error_cell_id"] = error_cell_id
        res.update(
            {
                "cells_executed": cells_executed,
                "kernel_generation": kernel_generation,
                "restart_since_previous_tool_call": restart_since_previous,
                "outputs_might_be_stale": outputs_might_be_stale,
                "stale_notes": stale_notes,
                "notebook_path": str(notebook_path),
                "stream_summary": sm_eff,
                "suggested_figure_prefix": suggested_figure_prefix,
                "output_files": output_files,
                "previews": {"tables": table_preview or [], "images": image_preview or []},
                "stdout_chunks": stdout_chunks,
                "stderr_chunks": stderr_chunks,
                "preview_rows_used": preview_rows,
                "max_image_side_used": max_image_side,
                "kernel_runtime_ms": elapsed_ms,
                "notebook_file_stamp": stamp,
                "python_env_snapshot": env_snap,
            },
        )
        if companion_summary is not None and companion_summary.get("status") != "skipped":
            res["companion"] = companion_summary
        if debug:
            res["debug"] = True
        return res
