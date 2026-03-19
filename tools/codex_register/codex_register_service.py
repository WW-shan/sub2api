from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


LOGGER = logging.getLogger("codex_register")


class CodexRegisterService:
    def __init__(
        self,
        *,
        state_store: Any,
        chatgpt_service: Any,
        workflow_id: str,
        sleep_min: int,
        sleep_max: int,
        db_session: Any = None,
        control_token: Optional[str] = None,
        auto_run: bool = False,
    ) -> None:
        del chatgpt_service, db_session, auto_run
        self.state_store = state_store
        self.workflow_id = workflow_id
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.control_token = control_token

        self._state_lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._active_process: Optional[Any] = None
        self._active_context: Optional[Dict[str, Any]] = None
        self._stop_requested = False

        self._loop_generation_counter = 0
        self._loop_active_generation: Optional[int] = None
        self._loop_worker_generation: Optional[int] = None
        self._loop_owned_process_generation: Optional[int] = None
        self._loop_worker_thread: Optional[threading.Thread] = None
        self._loop_stop_event = threading.Event()
        self._loop_owned_process: Optional[Any] = None

        self._base_dir = Path(__file__).resolve().parent
        self._data_dir = Path(os.getenv("CODEX_REGISTER_DATA_DIR") or str(self._base_dir)).resolve()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._accounts_jsonl_path = self._data_dir / "accounts.jsonl"

    async def handle_path(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        if path in {"/enable", "/resume", "/disable", "/loop/start", "/loop/stop"} and not self._is_authorized(payload):
            return self._result(False, error="unauthorized")

        if path == "/status":
            state = await self._load_state()
            return self._result(True, data=state)

        if path == "/loop/status":
            return await self._handle_loop_status()

        if path == "/logs":
            return self._result(True, data=await self._list_logs())

        if path == "/accounts":
            accounts = self._list_accounts_for_frontend()
            return self._result(True, data=accounts)

        if path == "/enable":
            return await self._handle_enable()

        if path == "/resume":
            return await self._handle_resume(payload)

        if path == "/disable":
            return await self._handle_disable()

        if path == "/loop/start":
            return await self._handle_loop_start()

        if path == "/loop/stop":
            return await self._handle_loop_stop()

        return self._result(False, error=f"unsupported_path: {path}")

    async def _handle_enable(self) -> Dict[str, Any]:
        command = [sys.executable, str(self._base_dir / "get_tokens.py")]

        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)
            if self._coerce_bool(state.get("loop_running")):
                return self._result(False, error="loop_running", data=state)
            if self._has_active_process_locked():
                return self._result(False, error="already_running")

            self._set_phase(
                state,
                to_phase="running:get_tokens",
                waiting_reason="",
                enabled=True,
                can_start=False,
                can_resume=False,
                can_abandon=True,
                reason="enabled",
            )
            state["last_error"] = ""
            self._clear_resume_fields(state)
            state["accounts_jsonl_baseline_offset"] = self._capture_accounts_jsonl_offset()
            await self._save_state(state)
            await self._append_log("enable_started", command=command)

            process, error = self._spawn_process(command)
            if error:
                self._set_phase(
                    state,
                    to_phase="failed",
                    waiting_reason="",
                    enabled=False,
                    can_start=True,
                    can_resume=False,
                    can_abandon=True,
                    reason="enable_spawn_failed",
                )
                state["last_error"] = error
                self._clear_resume_fields(state)
                await self._save_state(state)
                await self._append_log("enable_spawn_failed", error=error)
                return self._result(False, error="spawn_failed", data=state)

            self._active_process = process
            self._active_context = {"mode": "enable", "name": "get_tokens"}
            self._stop_requested = False
            self._start_monitor_thread(process, self._active_context)

            return self._result(True, data=state)

    async def _handle_resume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)
            if self._coerce_bool(state.get("loop_running")):
                return self._result(
                    False,
                    error={"code": "loop_running", "message": "loop is already running"},
                    data=state,
                )
            phase = str(state.get("job_phase") or "")
            waiting_phases = {"waiting_manual:resume_email", "waiting_manual:subscribe_then_resume"}

            if self._has_active_process_locked():
                return self._result(
                    False,
                    error={"code": "already_running", "message": "resume already in progress"},
                    data=state,
                )

            if phase not in waiting_phases:
                return self._result(
                    False,
                    error={"code": "invalid_phase", "message": f"resume not allowed in phase: {phase or 'unknown'}"},
                    data=state,
                )

            if phase == "waiting_manual:subscribe_then_resume":
                resume_context = state.get("resume_context")
                if not isinstance(resume_context, dict) or not str(resume_context.get("email") or "").strip():
                    return self._result(
                        False,
                        error={"code": "resume_context_missing", "message": "resume_context.email is required"},
                        data=state,
                    )
                email = str(resume_context.get("email") or "").strip()
            else:
                email, email_error = self._extract_resume_email(payload)
                if email_error:
                    return self._result(False, error=email_error, data=state)

            wrapper_code = self._build_gpt_wrapper_code()
            command = [
                sys.executable,
                "-c",
                wrapper_code,
                str(self._base_dir / "gpt-team-new.py"),
                email,
            ]

            self._set_phase(
                state,
                to_phase="running:gpt_team_batch",
                waiting_reason="",
                enabled=True,
                can_start=False,
                can_resume=False,
                can_abandon=True,
                reason="resumed",
            )
            state["last_error"] = ""
            await self._save_state(state)
            await self._append_log("resume_started", email=email)

            process, error = self._spawn_process(command)
            if error:
                self._set_phase(
                    state,
                    to_phase="failed",
                    waiting_reason="",
                    enabled=False,
                    can_start=True,
                    can_resume=False,
                    can_abandon=True,
                    reason="resume_spawn_failed",
                )
                state["last_error"] = error
                self._clear_resume_fields(state)
                await self._save_state(state)
                await self._append_log("resume_spawn_failed", error=error)
                return self._result(False, error="spawn_failed", data=state)

            self._active_process = process
            self._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": email}
            self._stop_requested = False
            self._start_monitor_thread(process, self._active_context)

            return self._result(True, data=state)

    async def _handle_disable(self) -> Dict[str, Any]:
        process: Optional[Any] = None

        async with self._state_lock:
            state = await self._load_state()
            self._set_phase(
                state,
                to_phase="abandoned",
                waiting_reason="",
                enabled=False,
                can_start=True,
                can_resume=False,
                can_abandon=False,
                reason="disabled",
            )
            self._clear_resume_fields(state)
            await self._save_state(state)
            await self._append_log("disabled")

            if self._active_process is not None:
                self._stop_requested = True
                if self._has_active_process_locked():
                    process = self._active_process

        if process is not None:
            try:
                process.terminate()
            except Exception as exc:
                await self._append_log("disable_terminate_failed", error=str(exc))
                try:
                    process.kill()
                except Exception:
                    pass

        latest = await self._load_state()
        return self._result(True, data=latest)

    async def _handle_loop_status(self) -> Dict[str, Any]:
        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)
            return self._result(True, data=state)

    async def _handle_loop_start(self) -> Dict[str, Any]:
        worker: Optional[threading.Thread] = None
        error_state: Optional[Dict[str, Any]] = None

        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)

            if self._coerce_bool(state.get("loop_stopping")):
                return self._result(False, error="loop_stopping", data=state)
            if self._coerce_bool(state.get("loop_running")):
                return self._result(False, error="already_running", data=state)
            if self._has_active_loop_worker_locked():
                state["loop_stopping"] = True
                await self._save_state(state)
                return self._result(False, error="loop_stopping", data=state)
            if self._has_active_process_locked():
                return self._result(False, error="main_workflow_running", data=state)

            self._loop_generation_counter += 1
            generation = self._loop_generation_counter
            self._loop_active_generation = generation
            self._loop_owned_process_generation = None
            self._loop_stop_event.clear()
            state["loop_running"] = True
            state["loop_stopping"] = False
            state["loop_started_at"] = self._now_iso()
            state["loop_last_error"] = ""

            worker, error = self._start_loop_worker(generation)
            if error:
                state["loop_running"] = False
                state["loop_stopping"] = False
                state["loop_started_at"] = ""
                state["loop_last_error"] = error
                self._loop_active_generation = None
                await self._save_state(state)
                error_state = state
            else:
                if worker is not None:
                    self._loop_worker_thread = worker
                    self._loop_worker_generation = generation
                await self._save_state(state)
                return self._result(True, data=state)

        return self._result(False, error="loop_worker_start_failed", data=error_state)

    async def _handle_loop_stop(self) -> Dict[str, Any]:
        process: Optional[Any] = None
        process_generation: Optional[int] = None

        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)

            self._loop_stop_event.set()
            process = self._loop_owned_process
            process_generation = self._loop_owned_process_generation

            if not self._coerce_bool(state.get("loop_running")):
                if self._has_active_loop_worker_locked():
                    state["loop_stopping"] = True
                    await self._save_state(state)
                else:
                    state["loop_stopping"] = False
                    self._clear_loop_runtime_ownership_locked()
                    await self._save_state(state)
                    return self._result(True, data=state)
            else:
                state["loop_running"] = False
                state["loop_stopping"] = True
                await self._save_state(state)

        self._terminate_process(process)

        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)
                return self._result(True, data=state)
            state["loop_running"] = False
            if not self._has_active_loop_worker_locked():
                state["loop_stopping"] = False
                self._clear_loop_runtime_ownership_locked(generation=process_generation)
            await self._save_state(state)
            return self._result(True, data=state)

    def _start_loop_worker(self, generation: int) -> Tuple[Optional[threading.Thread], str]:
        if self._loop is None:
            return None, "service_loop_unavailable"

        worker = threading.Thread(
            target=self._loop_worker_main,
            args=(generation,),
            name=f"codex-register-loop-worker-{generation}",
            daemon=True,
        )
        worker.start()
        return worker, ""

    def _loop_worker_main(self, generation: int) -> None:
        loop = self._loop
        if loop is None:
            return

        try:
            while not self._loop_stop_event.is_set():
                future = asyncio.run_coroutine_threadsafe(self._loop_worker_iteration(generation), loop)
                try:
                    should_continue = bool(future.result())
                except Exception:
                    should_continue = False
                if not should_continue:
                    break
        finally:
            future = asyncio.run_coroutine_threadsafe(self._finalize_loop_worker_shutdown(generation), loop)
            try:
                future.result(timeout=30)
            except Exception:
                pass

    async def _loop_worker_iteration(self, generation: Optional[int] = None) -> bool:
        async with self._state_lock:
            state = await self._load_state()
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)
            active_generation = self._loop_active_generation
            if generation is None:
                generation = active_generation
            if generation != active_generation:
                return False
            if not self._coerce_bool(state.get("loop_running")):
                return False

        if generation is None:
            await self._run_loop_round(state)
        else:
            await self._run_loop_round(state, generation)

        async with self._state_lock:
            latest_state = await self._load_state()
            if self._repair_stale_loop_state_locked(latest_state):
                await self._save_state(latest_state)
                return False
            active_generation = self._loop_active_generation
            if generation != active_generation:
                return False

            self._merge_loop_round_state(latest_state, state)
            await self._save_state(latest_state)
            active_generation = self._loop_active_generation
            if generation != active_generation:
                return False
            if not self._coerce_bool(latest_state.get("loop_running")):
                return False

        sleep_seconds = max(0, int(self.sleep_max or self.sleep_min or 0))
        if sleep_seconds <= 0:
            return not self._loop_stop_event.is_set()
        return not self._loop_stop_event.wait(timeout=sleep_seconds)

    def _merge_loop_round_state(self, target_state: Dict[str, Any], round_state: Dict[str, Any]) -> None:
        for key in (
            "loop_current_round",
            "loop_last_round_started_at",
            "loop_last_round_finished_at",
            "loop_last_round_created",
            "loop_last_round_updated",
            "loop_last_round_skipped",
            "loop_last_round_failed",
            "loop_total_created",
            "loop_last_error",
            "loop_history",
            "loop_committed_accounts_jsonl_offset",
        ):
            if key in round_state:
                value = round_state.get(key)
                if key == "loop_history" and isinstance(value, list):
                    target_state[key] = [dict(item) if isinstance(item, dict) else item for item in value]
                else:
                    target_state[key] = value

    async def _finalize_loop_worker_shutdown(self, generation: int) -> None:
        async with self._state_lock:
            state = await self._load_state()
            if generation != self._loop_active_generation:
                self._clear_loop_runtime_ownership_locked(generation=generation)
                return
            if self._repair_stale_loop_state_locked(state):
                await self._save_state(state)
                return
            if self._coerce_bool(state.get("loop_running")) and self._loop_stop_event.is_set():
                state["loop_running"] = False
            if not self._coerce_bool(state.get("loop_running")):
                state["loop_stopping"] = False
                self._clear_loop_runtime_ownership_locked(generation=generation)
                await self._save_state(state)

    def _clear_loop_runtime_ownership_locked(self, generation: Optional[int] = None) -> None:
        if generation is None or generation == self._loop_owned_process_generation:
            self._loop_owned_process = None
            self._loop_owned_process_generation = None
        if generation is None or generation == self._loop_worker_generation:
            self._loop_worker_thread = None
            self._loop_worker_generation = None
        if generation is None or generation == self._loop_active_generation:
            self._loop_active_generation = None
            self._loop_stop_event.clear()

    def _has_loop_worker_thread_locked(self, generation: Optional[int] = None) -> bool:
        worker = self._loop_worker_thread
        if worker is None:
            return False
        if generation is not None and generation != self._loop_worker_generation:
            return False

        is_alive = getattr(worker, "is_alive", None)
        if callable(is_alive):
            try:
                return bool(is_alive())
            except Exception:
                return True

        return True

    def _has_active_loop_process_locked(self, generation: Optional[int] = None) -> bool:
        process = self._loop_owned_process
        if process is None:
            return False
        if generation is not None and generation != self._loop_owned_process_generation:
            return False

        poll = getattr(process, "poll", None)
        if callable(poll):
            if poll() is None:
                return True
            return False
        return getattr(process, "returncode", None) is None

    def _has_active_loop_worker_locked(self) -> bool:
        if self._has_active_loop_process_locked():
            return True

        worker = self._loop_worker_thread
        if worker is None:
            return False

        is_alive = getattr(worker, "is_alive", None)
        if callable(is_alive):
            try:
                return bool(is_alive())
            except Exception:
                return True

        return True

    def _repair_stale_loop_state_locked(self, state: Dict[str, Any]) -> bool:
        if self._coerce_bool(state.get("loop_running")):
            if self._has_active_loop_worker_locked():
                return False

            state["loop_running"] = False
            state["loop_stopping"] = False
            state["loop_started_at"] = ""
            state["loop_last_error"] = "loop_worker_missing_after_restart"
            self._clear_loop_runtime_ownership_locked()
            return True

        if self._coerce_bool(state.get("loop_stopping")) and not self._has_active_loop_worker_locked():
            state["loop_stopping"] = False
            self._clear_loop_runtime_ownership_locked()
            return True

        return False

    def _spawn_process(self, command: List[str]) -> Tuple[Optional[Any], str]:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self._base_dir),
                text=True,
            )
            return process, ""
        except Exception as exc:
            return None, str(exc)

    def _start_monitor_thread(self, process: Any, context: Dict[str, Any]) -> None:
        thread = threading.Thread(
            target=self._monitor_process,
            args=(process, dict(context)),
            daemon=True,
        )
        thread.start()

    def _monitor_process(self, process: Any, context: Dict[str, Any]) -> None:
        return_code = -1
        try:
            return_code = int(process.wait())
        except Exception:
            return_code = -1

        loop = self._loop
        if loop is None:
            return

        future = asyncio.run_coroutine_threadsafe(
            self._handle_process_exit(process, context, return_code),
            loop,
        )
        try:
            future.result(timeout=30)
        except Exception:
            pass

    async def _handle_process_exit(self, process: Any, context: Dict[str, Any], return_code: int) -> None:
        async with self._state_lock:
            if process is not self._active_process:
                return

            self._active_process = None
            self._active_context = None

            state = await self._load_state()
            mode = str(context.get("mode") or "")
            name = str(context.get("name") or "")

            if self._stop_requested or str(state.get("job_phase") or "") == "abandoned":
                self._stop_requested = False
                await self._append_log("process_stopped", process=name)
                return

            if return_code == 0 and mode == "enable":
                parsed_result = self._extract_latest_valid_results_record(
                    baseline_offset=int(state.get("accounts_jsonl_baseline_offset") or 0)
                )
                resume_context = self._build_resume_context_from_parsed_result(parsed_result)
                resume_email = str(resume_context.get("email") or "").strip()
                if not resume_email:
                    self._set_phase(
                        state,
                        to_phase="failed",
                        waiting_reason="",
                        enabled=False,
                        can_start=True,
                        can_resume=False,
                        can_abandon=True,
                        reason="tokens_result_missing",
                    )
                    state["last_error"] = "tokens_result_missing"
                    state["last_success"] = ""
                    self._clear_resume_fields(state)
                    await self._save_state(state)
                    await self._append_log("get_tokens_result_missing")
                    return

                resume_hint = self._build_resume_hint(resume_context)
                line_end_offset = int(parsed_result.get("line_end_offset") or 0) if isinstance(parsed_result, dict) else 0

                self._set_phase(
                    state,
                    to_phase="waiting_manual:subscribe_then_resume",
                    waiting_reason="subscribe_then_resume",
                    enabled=True,
                    can_start=False,
                    can_resume=True,
                    can_abandon=True,
                    reason="get_tokens_done",
                )
                state["last_error"] = ""
                state["last_success"] = self._now_iso()
                state["manual_gate"] = {"name": "subscribe_then_resume", "status": "waiting"}
                state["resume_context"] = resume_context
                state["resume_hint"] = resume_hint
                state["accounts_jsonl_offset"] = line_end_offset
                state["accounts_jsonl_baseline_offset"] = line_end_offset
                await self._save_state(state)
                await self._append_log("get_tokens_completed")
                return

            if return_code == 0 and mode == "resume":
                try:
                    processing_summary = self._process_accounts_jsonl_records(state)
                    state["last_parent_persist_action"] = ""
                    normalized_state = await self._normalize_parent_record_after_resume(
                        state,
                        email=str(context.get("email") or "").strip().lower(),
                    )
                    if isinstance(normalized_state, dict):
                        state.update(normalized_state)
                except Exception as exc:
                    self._set_phase(
                        state,
                        to_phase="failed",
                        waiting_reason="",
                        enabled=False,
                        can_start=True,
                        can_resume=False,
                        can_abandon=True,
                        reason="accounts_processing_failed",
                    )
                    state["last_error"] = f"accounts_processing_failed:{exc}"
                    self._clear_resume_fields(state)
                    await self._save_state(state)
                    await self._append_log("accounts_processing_failed", error=str(exc))
                    return

                parent_action = str(state.get("last_parent_persist_action") or "").strip().lower()
                parent_created_delta = 1 if parent_action == "created" else 0
                state["codex_total_persisted_accounts"] = (
                    int(state.get("codex_total_persisted_accounts") or 0)
                    + int(processing_summary.get("created") or 0)
                    + parent_created_delta
                )

                self._set_phase(
                    state,
                    to_phase="completed",
                    waiting_reason="",
                    enabled=False,
                    can_start=True,
                    can_resume=False,
                    can_abandon=False,
                    reason="gpt_batch_done",
                )
                state["last_error"] = ""
                state["last_success"] = self._now_iso()
                self._clear_resume_fields(state)
                await self._save_state(state)
                if int(processing_summary.get("failed") or 0) > 0:
                    await self._append_log("accounts_processing_partial", summary=processing_summary)
                await self._append_log(
                    "gpt_batch_completed",
                    email=context.get("email", ""),
                    accounts_summary=processing_summary,
                )
                return

            self._set_phase(
                state,
                to_phase="failed",
                waiting_reason="",
                enabled=False,
                can_start=True,
                can_resume=False,
                can_abandon=True,
                reason=f"{name}_failed",
            )
            state["last_error"] = f"{name}_exit_{return_code}"
            self._clear_resume_fields(state)
            await self._save_state(state)
            await self._append_log("process_failed", process=name, return_code=return_code)

    def _list_accounts_for_frontend(self) -> List[Dict[str, Any]]:
        """List persisted Codex register accounts from the accounts table.

        Fields:
          - id: persisted account row id
          - email: normalized email
          - refresh_token/access_token: optional, may be empty strings
          - account_id: optional string or None
          - source: persisted record source when available
          - codex_register_role, plan_type, organization_id, workspace_id: optional metadata
          - created_at/updated_at: best-effort timestamps from persisted account metadata or row timestamps
        """
        conn = self._create_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, credentials, extra, created_at, updated_at FROM accounts "
                "WHERE platform = 'openai' AND type = 'oauth' AND deleted_at IS NULL "
                "AND COALESCE(extra ->> 'codex_auto_register', 'false') = 'true' "
                "ORDER BY id ASC"
            )
            rows = cur.fetchall()
        finally:
            self._safe_close(cur)
            self._safe_close(conn)

        accounts: List[Dict[str, Any]] = []
        for row in rows:
            account = self._build_frontend_account_from_db_row(row)
            if account is not None:
                accounts.append(account)
        return accounts

    def _build_frontend_account_from_db_row(self, row: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
        if not isinstance(row, tuple) or len(row) < 5:
            return None

        account_id_value, credentials_value, extra_value, row_created_at, row_updated_at = row[:5]
        credentials = self._ensure_dict(credentials_value)
        extra = self._ensure_dict(extra_value)

        email = str(credentials.get("email") or "").strip().lower()
        if not email:
            return None

        created_at = self._serialize_optional_timestamp(
            extra.get("created_at") or credentials.get("created_at") or row_created_at
        )
        updated_at = self._serialize_optional_timestamp(
            extra.get("updated_at") or credentials.get("updated_at") or row_updated_at or created_at
        )

        return {
            "id": int(account_id_value),
            "email": email,
            "refresh_token": str(credentials.get("refresh_token") or "").strip(),
            "access_token": str(credentials.get("access_token") or "").strip(),
            "account_id": str(credentials.get("account_id") or "").strip() or None,
            "source": str(extra.get("source") or credentials.get("source") or "codex-auto-register").strip()
            or "codex-auto-register",
            "codex_register_role": str(credentials.get("codex_register_role") or extra.get("codex_register_role") or "").strip()
            or None,
            "plan_type": str(credentials.get("plan_type") or extra.get("plan_type") or "").strip() or None,
            "organization_id": str(credentials.get("organization_id") or extra.get("organization_id") or "").strip()
            or None,
            "workspace_id": str(credentials.get("workspace_id") or extra.get("workspace_id") or "").strip() or None,
            "created_at": created_at or None,
            "updated_at": updated_at or None,
        }

    def _serialize_optional_timestamp(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        isoformat = getattr(value, "isoformat", None)
        if callable(isoformat):
            try:
                return str(isoformat())
            except Exception:
                pass
        return str(value).strip()

    def _capture_accounts_jsonl_offset(self) -> int:
        try:
            return int(self._accounts_jsonl_path.stat().st_size)
        except Exception:
            return 0

    def _extract_latest_valid_results_record(self, *, baseline_offset: int) -> Optional[Dict[str, Any]]:
        records, _next_offset = self._read_accounts_jsonl_records(start_offset=baseline_offset)
        if not records:
            return None
        return records[-1]

    def _read_accounts_jsonl_records(self, *, start_offset: int) -> Tuple[List[Dict[str, Any]], int]:
        try:
            with self._accounts_jsonl_path.open("rb") as f:
                f.seek(max(0, int(start_offset)))
                chunk = f.read()
        except Exception:
            return [], max(0, int(start_offset))

        if not chunk:
            return [], max(0, int(start_offset))

        content = chunk.decode("utf-8", errors="ignore")
        running_offset = max(0, int(start_offset))
        records: List[Dict[str, Any]] = []

        for line in content.splitlines(keepends=True):
            line_size = len(line.encode("utf-8", errors="ignore"))
            parsed = self._parse_account_jsonl_line(line)
            if parsed is not None:
                records.append(
                    {
                        **parsed,
                        "line_offset": running_offset,
                        "line_end_offset": running_offset + line_size,
                    }
                )
            running_offset += line_size

        return records, max(0, int(start_offset)) + len(chunk)

    def _parse_account_jsonl_line(self, line: str) -> Optional[Dict[str, Any]]:
        normalized = str(line or "").strip()
        if not normalized:
            return None

        try:
            parsed = json.loads(normalized)
        except Exception:
            return None

        if not isinstance(parsed, dict):
            return None

        email = str(parsed.get("email") or "").strip().lower()
        access_token = str(parsed.get("access_token") or "").strip()
        if not email or "@" not in email:
            return None
        if not access_token or re.search(r"\s", access_token):
            return None

        record = dict(parsed)
        record["email"] = email
        record["access_token"] = access_token
        record["password"] = str(parsed.get("password") or "").strip()
        record["refresh_token"] = str(parsed.get("refresh_token") or "").strip()
        record["id_token"] = str(parsed.get("id_token") or "").strip()
        record["account_id"] = str(parsed.get("account_id") or "").strip()
        record["auth_file"] = str(parsed.get("auth_file") or "").strip()
        record["expires_at"] = str(parsed.get("expires_at") or parsed.get("expired") or "").strip()
        record["team_name"] = str(parsed.get("team_name") or "").strip()
        record["created_at"] = str(parsed.get("created_at") or "").strip()
        record["updated_at"] = str(parsed.get("updated_at") or record.get("created_at") or "").strip()
        record["source"] = str(parsed.get("source") or "accounts_jsonl").strip() or "accounts_jsonl"
        record["invited"] = self._coerce_bool(parsed.get("invited"))
        record["plan_type"] = str(parsed.get("plan_type") or "").strip()
        record["organization_id"] = str(parsed.get("organization_id") or "").strip()
        record["workspace_id"] = str(parsed.get("workspace_id") or "").strip()
        record["codex_register_role"] = str(parsed.get("codex_register_role") or "").strip()
        return record

    def _build_resume_context_from_parsed_result(self, parsed_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(parsed_result, dict):
            return {
                "email": "",
                "team_name": "1",
                "source": "parse_path",
                "accounts_jsonl_offset": 0,
            }

        return {
            "email": str(parsed_result.get("email") or "").strip(),
            "access_token_raw": str(parsed_result.get("access_token") or "").strip(),
            "team_name": str(parsed_result.get("team_name") or "1").strip() or "1",
            "source": "parse_path",
            "accounts_jsonl_offset": int(parsed_result.get("line_end_offset") or 0),
        }

    def _build_resume_hint(self, resume_context: Dict[str, Any]) -> Dict[str, Any]:
        del resume_context
        return {
            "action": "call_resume",
            "path": "/resume",
            "required_fields": ["resume_context.email"],
        }

    def _extract_resume_email(self, payload: Dict[str, Any]) -> Tuple[str, str]:
        email_raw = payload.get("email")
        if not isinstance(email_raw, str):
            return "", "email_required"

        email = email_raw.strip()
        if not email:
            return "", "email_required"

        if "," in email or ";" in email:
            return "", "email_required"

        return email, ""

    def _build_gpt_wrapper_code(self) -> str:
        return (
            "import importlib.util, sys;"
            "script=sys.argv[1];"
            "email=sys.argv[2];"
            "spec=importlib.util.spec_from_file_location('gpt_team_new_runtime', script);"
            "module=importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(module);"
            "module.TEAMS=[{'name':'1','email':email,'password':''}];"
            "module.run_batch()"
        )

    def _coerce_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    def _get_env(self, name: str, default: Any = None, *, required: bool = False) -> str:
        value = os.getenv(name, default)
        if required and not value:
            raise RuntimeError(f"missing_required_env:{name}")
        return str(value or "")

    def _parse_group_ids_from_env(self, env_name: str) -> List[int]:
        raw = self._get_env(env_name, "")
        if not raw:
            return []

        group_ids: List[int] = []
        seen = set()
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError:
                continue
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            group_ids.append(value)
        return group_ids

    def _resolve_group_ids_for_record(self, record: Dict[str, Any]) -> List[int]:
        plan_type = str(record.get("plan_type") or "").lower()

        # 有 plan_type 就完全按它来
        if plan_type == "team":
            return self._parse_group_ids_from_env("CODEX_GROUP_IDS_TEAM")
        if plan_type:
            # 有 plan_type 且不是 team，一律 free
            return self._parse_group_ids_from_env("CODEX_GROUP_IDS_FREE")

        # 老数据没有 plan_type，保留原来的 invited 逻辑
        env_name = "CODEX_GROUP_IDS_TEAM" if self._coerce_bool(record.get("invited")) else "CODEX_GROUP_IDS_FREE"
        return self._parse_group_ids_from_env(env_name)

    def _create_db_connection(self) -> Any:
        psycopg2 = importlib.import_module("psycopg2")

        conn = psycopg2.connect(
            host=self._get_env("POSTGRES_HOST", "postgres"),
            port=int(self._get_env("POSTGRES_PORT", "5432") or "5432"),
            user=self._get_env("POSTGRES_USER", required=True),
            password=self._get_env("POSTGRES_PASSWORD", required=True),
            dbname=self._get_env("POSTGRES_DB", required=True),
            connect_timeout=int(self._get_env("POSTGRES_CONNECT_TIMEOUT", "5") or "5"),
        )
        conn.autocommit = True
        return conn

    def _pg_json(self, value: Dict[str, Any]) -> Any:
        return importlib.import_module("psycopg2.extras").Json(value)

    def _ensure_dict(self, value: object) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except Exception:
                return {}
            if isinstance(parsed, dict):
                return dict(parsed)
        return {}

    def _get_existing_account(self, cur: Any, email: str, account_id: str) -> Optional[Tuple[Any, ...]]:
        conditions: List[str] = []
        params: List[str] = []

        if email:
            conditions.append("LOWER(credentials ->> 'email') = LOWER(%s)")
            params.append(email)
        if account_id:
            conditions.append("credentials ->> 'account_id' = %s")
            params.append(account_id)

        if not conditions:
            return None

        cur.execute(
            "SELECT id, name, credentials, extra FROM accounts "
            "WHERE platform = 'openai' AND type = 'oauth' AND deleted_at IS NULL "
            f"AND ({' OR '.join(conditions)}) ORDER BY id LIMIT 1",
            tuple(params),
        )
        return cur.fetchone()

    def _build_account_credentials(self, existing: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
        credentials = dict(existing)
        credentials["email"] = str(record.get("email") or credentials.get("email") or "").strip().lower()
        credentials["access_token"] = str(record.get("access_token") or credentials.get("access_token") or "").strip()

        refresh_token = str(record.get("refresh_token") or credentials.get("refresh_token") or "").strip()
        if refresh_token:
            credentials["refresh_token"] = refresh_token
        else:
            credentials.pop("refresh_token", None)

        id_token = str(record.get("id_token") or credentials.get("id_token") or "").strip()
        if id_token:
            credentials["id_token"] = id_token
        else:
            credentials.pop("id_token", None)

        account_id = str(record.get("account_id") or credentials.get("account_id") or "").strip()
        if account_id:
            credentials["account_id"] = account_id
            credentials["chatgpt_account_id"] = account_id

        expires_at = str(record.get("expires_at") or credentials.get("expires_at") or "").strip()
        if expires_at:
            credentials["expires_at"] = expires_at

        auth_file = str(record.get("auth_file") or credentials.get("codex_auth_file") or "").strip()
        if auth_file:
            credentials["codex_auth_file"] = auth_file

        source = str(record.get("source") or credentials.get("source") or "codex-auto-register").strip()
        credentials["source"] = source or "codex-auto-register"

        plan_type = str(record.get("plan_type") or credentials.get("plan_type") or "").strip()
        if plan_type:
            credentials["plan_type"] = plan_type
        else:
            credentials.pop("plan_type", None)

        organization_id = str(record.get("organization_id") or credentials.get("organization_id") or "").strip()
        if organization_id:
            credentials["organization_id"] = organization_id
        else:
            credentials.pop("organization_id", None)

        workspace_id = str(record.get("workspace_id") or credentials.get("workspace_id") or "").strip()
        if workspace_id:
            credentials["workspace_id"] = workspace_id
        else:
            credentials.pop("workspace_id", None)

        codex_register_role = str(record.get("codex_register_role") or credentials.get("codex_register_role") or "").strip()
        if codex_register_role:
            credentials["codex_register_role"] = codex_register_role
        else:
            credentials.pop("codex_register_role", None)
        return credentials

    def _build_account_extra(self, existing: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
        extra = dict(existing)
        extra["codex_auto_register"] = True
        extra["invited"] = self._coerce_bool(record.get("invited"))

        team_name = str(record.get("team_name") or extra.get("team_name") or "").strip()
        if team_name:
            extra["team_name"] = team_name

        created_at = str(record.get("created_at") or extra.get("created_at") or "").strip()
        if created_at:
            extra["created_at"] = created_at

        source = str(record.get("source") or extra.get("source") or "accounts_jsonl").strip()
        if source:
            extra["source"] = source

        auth_file = str(record.get("auth_file") or extra.get("codex_auth_file") or "").strip()
        if auth_file:
            extra["codex_auth_file"] = auth_file

        return extra

    def _normalize_extra_for_compare(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._ensure_dict(extra)
        normalized.pop("codex_auto_register_updated_at", None)
        return normalized

    def _should_update_account(
        self,
        current_credentials: Dict[str, Any],
        next_credentials: Dict[str, Any],
        current_extra: Dict[str, Any],
        next_extra: Dict[str, Any],
    ) -> bool:
        return current_credentials != next_credentials or self._normalize_extra_for_compare(current_extra) != self._normalize_extra_for_compare(next_extra)

    def _compute_group_binding_changes(self, current_group_ids: set[int], next_group_ids: set[int]) -> Tuple[set[int], set[int]]:
        return next_group_ids - current_group_ids, current_group_ids - next_group_ids

    def _bind_account_groups(self, cur: Any, account_id: int, group_ids: List[int]) -> None:
        if not group_ids:
            return

        desired_priority = {group_id: index for index, group_id in enumerate(group_ids, start=1)}
        desired_ids = set(desired_priority.keys())

        cur.execute("SELECT group_id, priority FROM account_groups WHERE account_id = %s", (account_id,))
        current_rows = cur.fetchall()
        current_priority = {int(row[0]): int(row[1]) for row in current_rows}
        current_ids = set(current_priority.keys())

        to_add, to_remove = self._compute_group_binding_changes(current_ids, desired_ids)
        for group_id in sorted(to_remove):
            cur.execute("DELETE FROM account_groups WHERE account_id = %s AND group_id = %s", (account_id, group_id))

        for group_id in sorted(to_add):
            cur.execute(
                "INSERT INTO account_groups (account_id, group_id, priority, created_at) VALUES (%s, %s, %s, NOW()) "
                "ON CONFLICT (account_id, group_id) DO UPDATE SET priority = EXCLUDED.priority",
                (account_id, group_id, desired_priority[group_id]),
            )

        for group_id in sorted(desired_ids.intersection(current_ids)):
            next_priority = desired_priority[group_id]
            if current_priority[group_id] != next_priority:
                cur.execute(
                    "UPDATE account_groups SET priority = %s WHERE account_id = %s AND group_id = %s",
                    (next_priority, account_id, group_id),
                )

    def _record_identifier(self, record: Dict[str, Any]) -> str:
        email = str(record.get("email") or "").strip()
        account_id = str(record.get("account_id") or "").strip()
        return email or account_id or "unknown"

    def _upsert_account(self, cur: Any, record: Dict[str, Any]) -> str:
        email = str(record.get("email") or "").strip().lower()
        access_token = str(record.get("access_token") or "").strip()
        account_id = str(record.get("account_id") or "").strip()
        if not email or not access_token:
            return "skipped"

        existing = self._get_existing_account(cur, email, account_id)
        group_ids = self._resolve_group_ids_for_record(record)

        if existing is not None:
            existing_id, _existing_name, existing_credentials, existing_extra = existing
            current_credentials = self._ensure_dict(existing_credentials)
            current_extra = self._ensure_dict(existing_extra)
            next_credentials = self._build_account_credentials(current_credentials, record)
            next_extra = self._build_account_extra(current_extra, record)

            if not self._should_update_account(current_credentials, next_credentials, current_extra, next_extra):
                self._bind_account_groups(cur, int(existing_id), group_ids)
                return "skipped"

            next_extra["codex_auto_register_updated_at"] = self._now_iso()
            cur.execute(
                "UPDATE accounts SET credentials = %s, extra = %s, status = 'active', schedulable = true, updated_at = NOW() WHERE id = %s",
                (self._pg_json(next_credentials), self._pg_json(next_extra), existing_id),
            )
            self._bind_account_groups(cur, int(existing_id), group_ids)
            return "updated"

        identifier = account_id or email
        name = f"codex-{identifier}"
        credentials = self._build_account_credentials({}, record)
        extra = self._build_account_extra({}, record)
        extra["codex_auto_register_updated_at"] = self._now_iso()

        cur.execute(
            "INSERT INTO accounts (name, platform, type, credentials, extra, concurrency, priority, rate_multiplier, status, schedulable, auto_pause_on_expired) "
            "VALUES (%s, 'openai', 'oauth', %s, %s, 3, 50, 1.0, 'active', true, true) RETURNING id",
            (name, self._pg_json(credentials), self._pg_json(extra)),
        )
        created_row = cur.fetchone()
        created_id = int(created_row[0])
        self._bind_account_groups(cur, created_id, group_ids)
        return "created"

    def _build_parent_replacement_record(
        self,
        *,
        resume_context: Dict[str, Any],
        existing_credentials: Dict[str, Any],
        existing_extra: Dict[str, Any],
        old_parent_record: Optional[Dict[str, Any]],
        existing_parent_jsonl_record: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        old_parent_record = old_parent_record or {}
        existing_parent_jsonl_record = existing_parent_jsonl_record or {}
        normalized_email = str(
            resume_context.get("email")
            or existing_credentials.get("email")
            or old_parent_record.get("email")
            or existing_parent_jsonl_record.get("email")
            or ""
        ).strip().lower()
        created_at = str(
            old_parent_record.get("created_at")
            or existing_parent_jsonl_record.get("created_at")
            or existing_extra.get("created_at")
            or existing_credentials.get("created_at")
            or self._now_iso()
        ).strip()
        return {
            "email": normalized_email,
            "password": str(
                old_parent_record.get("password")
                or existing_parent_jsonl_record.get("password")
                or ""
            ).strip(),
            "access_token": str(
                existing_credentials.get("access_token")
                or existing_parent_jsonl_record.get("access_token")
                or old_parent_record.get("access_token")
                or ""
            ).strip(),
            "refresh_token": str(
                existing_credentials.get("refresh_token")
                or existing_parent_jsonl_record.get("refresh_token")
                or old_parent_record.get("refresh_token")
                or ""
            ).strip(),
            "id_token": str(
                existing_credentials.get("id_token")
                or existing_parent_jsonl_record.get("id_token")
                or old_parent_record.get("id_token")
                or ""
            ).strip(),
            "account_id": str(
                existing_credentials.get("account_id")
                or existing_parent_jsonl_record.get("account_id")
                or old_parent_record.get("account_id")
                or ""
            ).strip(),
            "auth_file": str(
                existing_credentials.get("codex_auth_file")
                or existing_extra.get("codex_auth_file")
                or existing_parent_jsonl_record.get("auth_file")
                or old_parent_record.get("auth_file")
                or ""
            ).strip(),
            "expires_at": str(
                existing_credentials.get("expires_at")
                or existing_parent_jsonl_record.get("expires_at")
                or old_parent_record.get("expires_at")
                or old_parent_record.get("expired")
                or ""
            ).strip(),
            "invited": False,
            "team_name": str(
                resume_context.get("team_name")
                or existing_parent_jsonl_record.get("team_name")
                or old_parent_record.get("team_name")
                or existing_extra.get("team_name")
                or ""
            ).strip(),
            "plan_type": str(
                existing_credentials.get("plan_type")
                or existing_parent_jsonl_record.get("plan_type")
                or old_parent_record.get("plan_type")
                or ""
            ).strip(),
            "organization_id": str(
                existing_credentials.get("organization_id")
                or existing_parent_jsonl_record.get("organization_id")
                or old_parent_record.get("organization_id")
                or ""
            ).strip(),
            "workspace_id": str(
                existing_credentials.get("workspace_id")
                or existing_parent_jsonl_record.get("workspace_id")
                or old_parent_record.get("workspace_id")
                or ""
            ).strip(),
            "codex_register_role": "parent",
            "created_at": created_at,
            "updated_at": self._now_iso(),
            "source": "gpt-team-new",
        }

    def _replace_parent_record_after_resume(self, state: Dict[str, Any]) -> None:
        resume_context = state.get("resume_context")
        if not isinstance(resume_context, dict):
            raise RuntimeError("resume_context_missing")

        resume_email = str(resume_context.get("email") or "").strip().lower()
        if not resume_email:
            raise RuntimeError("resume_context_missing")

        existing_records, _next_offset = self._read_accounts_jsonl_records(start_offset=0)
        old_parent_record = next(
            (
                record for record in existing_records
                if str(record.get("email") or "").strip().lower() == resume_email
                and str(record.get("source") or "").strip() == "get_tokens"
            ),
            None,
        )
        existing_parent_jsonl_record = next(
            (
                record for record in existing_records
                if str(record.get("email") or "").strip().lower() == resume_email
                and str(record.get("source") or "").strip() == "gpt-team-new"
                and str(record.get("codex_register_role") or "").strip() == "parent"
            ),
            None,
        )

        conn = self._create_db_connection()
        cur = conn.cursor()
        try:
            existing = self._get_existing_account(cur, resume_email, str((old_parent_record or {}).get("account_id") or "").strip())
            if existing is None:
                raise RuntimeError("parent_account_missing")
            _existing_id, _existing_name, existing_credentials_raw, existing_extra_raw = existing
            existing_credentials = self._ensure_dict(existing_credentials_raw)
            existing_extra = self._ensure_dict(existing_extra_raw)
            replacement_record = self._build_parent_replacement_record(
                resume_context=resume_context,
                existing_credentials=existing_credentials,
                existing_extra=existing_extra,
                old_parent_record=old_parent_record,
                existing_parent_jsonl_record=existing_parent_jsonl_record,
            )
            parent_persist_action = self._upsert_account(cur, replacement_record)
        finally:
            self._safe_close(cur)
            self._safe_close(conn)

        preserved_lines: List[str] = []
        replacement_written = False
        try:
            raw_lines = self._accounts_jsonl_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            raw_lines = []

        for raw_line in raw_lines:
            parsed = self._parse_account_jsonl_line(raw_line)
            if parsed is None:
                preserved_lines.append(raw_line)
                continue

            email = str(parsed.get("email") or "").strip().lower()
            source = str(parsed.get("source") or "").strip()
            role = str(parsed.get("codex_register_role") or "").strip()
            if email == resume_email and (
                source == "get_tokens" or (source == "gpt-team-new" and role == "parent")
            ):
                if not replacement_written:
                    preserved_lines.append(json.dumps(replacement_record, ensure_ascii=False))
                    replacement_written = True
                continue
            preserved_lines.append(raw_line)

        if not replacement_written:
            preserved_lines.append(json.dumps(replacement_record, ensure_ascii=False))

        content = "\n".join(preserved_lines)
        if content:
            content += "\n"

        fd, temp_path = tempfile.mkstemp(dir=str(self._accounts_jsonl_path.parent), prefix="accounts.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(temp_path, self._accounts_jsonl_path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

        final_offset = self._capture_accounts_jsonl_offset()
        state["accounts_jsonl_offset"] = final_offset
        state["accounts_jsonl_baseline_offset"] = final_offset
        state["last_processed_offset"] = final_offset
        state["last_parent_persist_action"] = str(parent_persist_action or "").strip().lower()

    async def _normalize_parent_record_after_resume(self, state: Dict[str, Any], *, email: str) -> Dict[str, Any]:
        del email
        self._replace_parent_record_after_resume(state)
        return state

    def _process_accounts_jsonl_records(self, state: Dict[str, Any]) -> Dict[str, Any]:
        start_offset = int(state.get("accounts_jsonl_offset") or 0)
        records, next_offset = self._read_accounts_jsonl_records(start_offset=start_offset)
        summary = {
            "start_offset": start_offset,
            "end_offset": next_offset,
            "records_seen": len(records),
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        if not records:
            state["accounts_jsonl_offset"] = next_offset
            state["last_processed_records"] = 0
            state["last_processed_offset"] = next_offset
            state["last_processed_summary"] = dict(summary)
            return summary

        conn = self._create_db_connection()
        cur = conn.cursor()
        last_successful_offset = start_offset
        processed_records = 0
        try:
            for record in records:
                try:
                    action = self._upsert_account(cur, record)
                except Exception as exc:
                    summary["failed"] += 1
                    summary["errors"].append(f"{self._record_identifier(record)}:{exc}")
                    summary["end_offset"] = last_successful_offset
                    break

                processed_records += 1
                last_successful_offset = int(record.get("line_end_offset") or last_successful_offset)
                summary["end_offset"] = last_successful_offset

                if action == "created":
                    summary["created"] += 1
                elif action == "updated":
                    summary["updated"] += 1
                else:
                    summary["skipped"] += 1
        finally:
            self._safe_close(cur)
            self._safe_close(conn)

        state["accounts_jsonl_offset"] = int(summary["end_offset"])
        state["last_processed_records"] = processed_records
        state["last_processed_offset"] = int(summary["end_offset"])
        state["total_created"] = int(state.get("total_created") or 0) + int(summary["created"])
        state["total_updated"] = int(state.get("total_updated") or 0) + int(summary["updated"])
        state["total_skipped"] = int(state.get("total_skipped") or 0) + int(summary["skipped"])
        state["total_failed"] = int(state.get("total_failed") or 0) + int(summary["failed"])
        state["last_processed_summary"] = dict(summary)
        return summary

    def _process_loop_accounts_jsonl_round(self, state: Dict[str, Any]) -> Dict[str, Any]:
        main_owned_offset = int(state.get("accounts_jsonl_offset") or 0)
        committed_offset = int(state.get("loop_committed_accounts_jsonl_offset") or 0)
        baseline_total_created = int(state.get("total_created") or 0)
        baseline_total_updated = int(state.get("total_updated") or 0)
        baseline_total_skipped = int(state.get("total_skipped") or 0)
        baseline_total_failed = int(state.get("total_failed") or 0)
        baseline_last_processed_records = int(state.get("last_processed_records") or 0)
        baseline_last_processed_offset = int(state.get("last_processed_offset") or 0)
        baseline_last_processed_summary = state.get("last_processed_summary")

        state["accounts_jsonl_offset"] = committed_offset
        try:
            summary = self._process_accounts_jsonl_records(state)
            if int(summary.get("failed") or 0) == 0:
                state["loop_committed_accounts_jsonl_offset"] = int(summary.get("end_offset") or committed_offset)
            return summary
        finally:
            state["accounts_jsonl_offset"] = main_owned_offset
            state["total_created"] = baseline_total_created
            state["total_updated"] = baseline_total_updated
            state["total_skipped"] = baseline_total_skipped
            state["total_failed"] = baseline_total_failed
            state["last_processed_records"] = baseline_last_processed_records
            state["last_processed_offset"] = baseline_last_processed_offset
            state["last_processed_summary"] = baseline_last_processed_summary

    async def _run_loop_round(self, state: Dict[str, Any], generation: Optional[int] = None) -> Dict[str, Any]:
        state["loop_current_round"] = int(state.get("loop_current_round") or 0) + 1
        round_number = int(state["loop_current_round"])
        started_at = self._now_iso()
        state["loop_last_round_started_at"] = started_at

        history_entry: Dict[str, Any] = {
            "round": round_number,
            "started_at": started_at,
            "finished_at": "",
            "status": "running",
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "summary": None,
            "error": "",
        }
        summary: Optional[Dict[str, Any]] = None

        try:
            return_code = await self._run_loop_process_once(generation)
            if self._loop_stop_event.is_set() and return_code != 0:
                history_entry["status"] = "stopped"
                summary = {
                    "start_offset": int(state.get("loop_committed_accounts_jsonl_offset") or 0),
                    "end_offset": int(state.get("loop_committed_accounts_jsonl_offset") or 0),
                    "records_seen": 0,
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "failed": 0,
                    "errors": [],
                }
            elif return_code != 0:
                raise RuntimeError(f"gpt_team_new_exit_{return_code}")
            else:
                summary = self._process_loop_accounts_jsonl_round(state)
                if int(summary.get("failed") or 0) > 0:
                    raise RuntimeError("loop_accounts_processing_failed")
                history_entry["status"] = "success"
                state["loop_last_error"] = ""
                state["loop_committed_accounts_jsonl_offset"] = int(summary.get("end_offset") or state.get("loop_committed_accounts_jsonl_offset") or 0)
                state["loop_last_round_created"] = int(summary.get("created") or 0)
                state["loop_last_round_updated"] = int(summary.get("updated") or 0)
                state["loop_last_round_skipped"] = int(summary.get("skipped") or 0)
                state["loop_last_round_failed"] = int(summary.get("failed") or 0)
                state["loop_total_created"] = int(state.get("loop_total_created") or 0) + int(summary.get("created") or 0)
                state["codex_total_persisted_accounts"] = int(state.get("codex_total_persisted_accounts") or 0) + int(summary.get("created") or 0)

            history_entry["created"] = int(summary.get("created") or 0)
            history_entry["updated"] = int(summary.get("updated") or 0)
            history_entry["skipped"] = int(summary.get("skipped") or 0)
            history_entry["failed"] = int(summary.get("failed") or 0)
            history_entry["summary"] = dict(summary)
        except Exception as exc:
            history_entry["status"] = "stopped" if self._loop_stop_event.is_set() else "failed"
            history_entry["error"] = str(exc)
            state["loop_last_error"] = str(exc)
            if isinstance(summary, dict):
                history_entry["created"] = int(summary.get("created") or 0)
                history_entry["updated"] = int(summary.get("updated") or 0)
                history_entry["skipped"] = int(summary.get("skipped") or 0)
                history_entry["failed"] = int(summary.get("failed") or 0)
                history_entry["summary"] = dict(summary)
                state["loop_last_round_created"] = int(summary.get("created") or 0)
                state["loop_last_round_updated"] = int(summary.get("updated") or 0)
                state["loop_last_round_skipped"] = int(summary.get("skipped") or 0)
                state["loop_last_round_failed"] = int(summary.get("failed") or 0)
            else:
                state["loop_last_round_created"] = 0
                state["loop_last_round_updated"] = 0
                state["loop_last_round_skipped"] = 0
                state["loop_last_round_failed"] = 1
        finally:
            finished_at = self._now_iso()
            state["loop_last_round_finished_at"] = finished_at
            history_entry["finished_at"] = finished_at
            history = list(state.get("loop_history") or [])
            history.append(history_entry)
            state["loop_history"] = history[-20:]

        return history_entry

    async def _run_loop_process_once(self, generation: Optional[int] = None) -> int:
        command = [sys.executable, str(self._base_dir / "gpt-team-new.py")]
        process, error = self._spawn_process(command)
        if error or process is None:
            raise RuntimeError(error or "loop_spawn_failed")

        should_terminate = False
        async with self._state_lock:
            self._loop_owned_process = process
            self._loop_owned_process_generation = generation
            state = await self._load_state()
            active_generation = self._loop_active_generation
            if generation is not None and generation != active_generation:
                should_terminate = True
            elif self._loop_stop_event.is_set() or self._coerce_bool(state.get("loop_stopping")):
                should_terminate = True

        if should_terminate:
            self._terminate_process(process)
        try:
            return int(await asyncio.to_thread(process.wait))
        finally:
            async with self._state_lock:
                if self._loop_owned_process is process:
                    self._loop_owned_process = None
                    self._loop_owned_process_generation = None

    def _terminate_process(self, process: Optional[Any]) -> None:
        if process is None:
            return

        try:
            process.terminate()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _safe_close(self, value: Any) -> None:
        close = getattr(value, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _build_accounts_status_data(self, state: Dict[str, Any]) -> Dict[str, Any]:
        summary = state.get("last_processed_summary")
        return {
            "accounts_jsonl_offset": int(state.get("accounts_jsonl_offset") or 0),
            "accounts_jsonl_baseline_offset": int(state.get("accounts_jsonl_baseline_offset") or 0),
            "last_processed_offset": int(state.get("last_processed_offset") or 0),
            "last_processed_records": int(state.get("last_processed_records") or 0),
            "total_created": int(state.get("total_created") or 0),
            "total_updated": int(state.get("total_updated") or 0),
            "total_skipped": int(state.get("total_skipped") or 0),
            "total_failed": int(state.get("total_failed") or 0),
            "codex_total_persisted_accounts": int(state.get("codex_total_persisted_accounts") or 0),
            "last_processed_summary": dict(summary) if isinstance(summary, dict) else None,
        }

    def _has_active_process_locked(self) -> bool:
        process = self._active_process
        if process is None:
            return False

        poll = getattr(process, "poll", None)
        if callable(poll):
            return poll() is None

        return getattr(process, "returncode", None) is None

    async def _load_state(self) -> Dict[str, Any]:
        existing = await self.state_store.load_state()
        state = self._default_state()
        state.update(existing or {})
        state["workflow_id"] = state.get("workflow_id") or self.workflow_id
        if not isinstance(state.get("recent_logs_tail"), list):
            state["recent_logs_tail"] = []
        return state

    async def _save_state(self, state: Dict[str, Any]) -> None:
        await self.state_store.save_state(state)

    async def _append_log(self, event: str, **fields: Any) -> None:
        payload = {
            "time": self._now_iso(),
            "level": str(fields.pop("level", "info")),
            **fields,
        }

        append = getattr(self.state_store, "append_log", None)
        if callable(append):
            maybe_result = append(event, **payload)
            if asyncio.iscoroutine(maybe_result):
                await maybe_result

        LOGGER.info(json.dumps({"event": event, **payload}, ensure_ascii=False, default=str))

    async def _list_logs(self) -> List[Dict[str, Any]]:
        list_logs = getattr(self.state_store, "list_logs", None)
        if callable(list_logs):
            maybe_logs = list_logs()
            if asyncio.iscoroutine(maybe_logs):
                resolved = await maybe_logs
            else:
                resolved = maybe_logs
            if isinstance(resolved, list):
                return [dict(item) if isinstance(item, dict) else {"message": str(item)} for item in resolved]

        logs = getattr(self.state_store, "logs", None)
        if isinstance(logs, list):
            return [dict(item) if isinstance(item, dict) else {"message": str(item)} for item in logs]

        state = await self._load_state()
        tail = state.get("recent_logs_tail") or []
        if isinstance(tail, list):
            return [dict(item) if isinstance(item, dict) else {"message": str(item)} for item in tail]
        return []

    def _set_phase(
        self,
        state: Dict[str, Any],
        *,
        to_phase: str,
        waiting_reason: str,
        enabled: bool,
        can_start: bool,
        can_resume: bool,
        can_abandon: bool,
        reason: str,
    ) -> None:
        previous = str(state.get("job_phase") or "")
        state["enabled"] = enabled
        state["job_phase"] = to_phase
        state["waiting_reason"] = waiting_reason
        state["can_start"] = can_start
        state["can_resume"] = can_resume
        state["can_abandon"] = can_abandon
        state["last_transition"] = {
            "time": self._now_iso(),
            "from": previous,
            "to": to_phase,
            "reason": reason,
        }

    def _clear_resume_fields(self, state: Dict[str, Any]) -> None:
        state["manual_gate"] = None
        state["resume_context"] = None
        state["resume_hint"] = None

    def _default_state(self) -> Dict[str, Any]:
        return {
            "enabled": False,
            "sleep_min": self.sleep_min,
            "sleep_max": self.sleep_max,
            "total_created": 0,
            "total_updated": 0,
            "total_skipped": 0,
            "total_failed": 0,
            "codex_total_persisted_accounts": 0,
            "last_success": "",
            "last_error": "",
            "proxy": "",
            "job_phase": "idle",
            "workflow_id": self.workflow_id,
            "waiting_reason": "",
            "can_start": True,
            "can_resume": False,
            "can_abandon": False,
            "last_transition": None,
            "last_resume_gate_reason": "",
            "recent_logs_tail": [],
            "manual_gate": None,
            "resume_context": None,
            "resume_hint": None,
            "accounts_jsonl_offset": 0,
            "accounts_jsonl_baseline_offset": 0,
            "last_processed_offset": 0,
            "last_processed_records": 0,
            "last_processed_summary": None,
            "loop_running": False,
            "loop_stopping": False,
            "loop_started_at": None,
            "loop_current_round": 0,
            "loop_last_round_started_at": None,
            "loop_last_round_finished_at": None,
            "loop_last_round_created": 0,
            "loop_last_round_updated": 0,
            "loop_last_round_skipped": 0,
            "loop_last_round_failed": 0,
            "loop_total_created": 0,
            "loop_last_error": "",
            "loop_history": [],
            "loop_committed_accounts_jsonl_offset": 0,
        }

    def _is_authorized(self, payload: Dict[str, Any]) -> bool:
        if not self.control_token:
            return True

        headers = payload.get("headers") or {}
        normalized_headers = {str(k).lower(): v for k, v in headers.items()}
        token = str(normalized_headers.get("x-codex-token") or "")
        return token == self.control_token

    def _result(self, success: bool, *, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
        return {"success": success, "data": data, "error": error}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class InMemoryStateStore:
    def __init__(self) -> None:
        self._state: Dict[str, Any] = {}
        self.logs: List[Dict[str, Any]] = []

    async def load_state(self) -> Dict[str, Any]:
        return dict(self._state)

    async def save_state(self, state: Dict[str, Any]) -> None:
        self._state = dict(state)

    async def append_log(self, message: str, **fields: Any) -> None:
        entry = {"message": message, **fields}
        self.logs.append(entry)
        tail = list(self._state.get("recent_logs_tail") or [])
        tail.append(entry)
        self._state["recent_logs_tail"] = tail[-20:]


def _build_state_store_from_env() -> Any:
    return InMemoryStateStore()


async def run_http(service: CodexRegisterService, *, host: str, port: int) -> None:
    handler = build_http_handler(service)
    server = HTTPServer((host, port), handler)

    service_loop = asyncio.new_event_loop()
    setattr(server, "_service_loop", service_loop)

    loop_thread = threading.Thread(target=service_loop.run_forever, daemon=True)
    loop_thread.start()

    main_loop = asyncio.get_running_loop()
    try:
        await main_loop.run_in_executor(None, server.serve_forever)
    finally:
        server.shutdown()
        service_loop.call_soon_threadsafe(service_loop.stop)
        loop_thread.join(timeout=2)
        service_loop.close()


def build_http_handler(service: CodexRegisterService):
    method_allowlist = {
        "GET": {"/status", "/logs", "/accounts", "/loop/status"},
        "POST": {"/enable", "/resume", "/disable", "/loop/start", "/loop/stop"},
    }

    class CodexRegisterHTTPRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str) -> None:
            path = urlparse(self.path).path
            allowed_paths = method_allowlist.get(method, set())
            if path not in allowed_paths:
                response = {"success": False, "data": None, "error": "method_not_allowed"}
                body = json.dumps(response).encode("utf-8")
                self.send_response(405)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            headers = {k: v for k, v in self.headers.items()}
            payload: Dict[str, Any] = {"headers": headers, "method": method}

            if method == "POST":
                length_raw = self.headers.get("Content-Length", "0")
                try:
                    length = int(length_raw)
                except ValueError:
                    length = 0

                if length > 0:
                    body = self.rfile.read(length)
                    try:
                        parsed = json.loads(body.decode("utf-8"))
                        if isinstance(parsed, dict):
                            payload.update(parsed)
                    except Exception:
                        payload["invalid_json"] = True

            future = None
            try:
                service_loop = getattr(self.server, "_service_loop", None)
                if service_loop is None:
                    raise RuntimeError("service_loop_not_initialized")

                future = asyncio.run_coroutine_threadsafe(service.handle_path(path, payload=payload), service_loop)
                response = future.result(timeout=30)

                if response.get("error") == "unauthorized":
                    status_code = 401
                else:
                    status_code = 200 if response.get("success") else 400
            except FutureTimeout:
                if future is not None:
                    future.cancel()
                response = {"success": False, "data": None, "error": "request_timeout"}
                status_code = 504
            except Exception as exc:
                response = {"success": False, "data": None, "error": str(exc)}
                status_code = 500

            LOGGER.info(
                json.dumps(
                    {
                        "http_method": method,
                        "path": path,
                        "status_code": status_code,
                        "success": bool(response.get("success")),
                        "error": response.get("error") or "",
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )

            body = json.dumps(response).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # pragma: no cover
            del format, args

    return CodexRegisterHTTPRequestHandler


def main() -> None:
    logging.basicConfig(
        level=os.getenv("CODEX_REGISTER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    workflow_id = os.getenv("CODEX_REGISTER_WORKFLOW_ID", "wf-runtime")
    sleep_min = int((os.getenv("CODEX_SLEEP_MIN") or os.getenv("CODEX_REGISTER_SLEEP_MIN") or "1"))
    sleep_max = int((os.getenv("CODEX_SLEEP_MAX") or os.getenv("CODEX_REGISTER_SLEEP_MAX") or "1"))
    host = os.getenv("CODEX_REGISTER_HOST", "0.0.0.0")
    port = int(os.getenv("CODEX_REGISTER_PORT", "5000"))
    control_token = str(os.getenv("CODEX_REGISTER_CONTROL_TOKEN") or "").strip() or None

    service = CodexRegisterService(
        state_store=_build_state_store_from_env(),
        chatgpt_service=SimpleNamespace(),
        workflow_id=workflow_id,
        sleep_min=sleep_min,
        sleep_max=sleep_max,
        control_token=control_token,
        auto_run=False,
    )

    asyncio.run(run_http(service, host=host, port=port))


if __name__ == "__main__":
    main()
