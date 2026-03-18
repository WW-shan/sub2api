from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import re
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

        self._base_dir = Path(__file__).resolve().parent

    async def handle_path(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        if path in {"/enable", "/resume", "/disable"} and not self._is_authorized(payload):
            return self._result(False, error="unauthorized")

        if path == "/status":
            state = await self._load_state()
            return self._result(True, data=state)

        if path == "/logs":
            return self._result(True, data=await self._list_logs())

        if path == "/accounts":
            return self._result(True, data=[])

        if path == "/enable":
            return await self._handle_enable()

        if path == "/resume":
            return await self._handle_resume(payload)

        if path == "/disable":
            return await self._handle_disable()

        return self._result(False, error=f"unsupported_path: {path}")

    async def _handle_enable(self) -> Dict[str, Any]:
        command = [sys.executable, str(self._base_dir / "get_tokens.py")]

        async with self._state_lock:
            if self._has_active_process_locked():
                return self._result(False, error="already_running")

            state = await self._load_state()
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
            state["results_baseline_offset"] = self._capture_results_baseline_offset()
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
                    baseline_offset=int(state.get("results_baseline_offset") or 0)
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
                await self._save_state(state)
                await self._append_log("get_tokens_completed")
                return

            if return_code == 0 and mode == "resume":
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
                await self._append_log("gpt_batch_completed", email=context.get("email", ""))
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

    def _capture_results_baseline_offset(self) -> int:
        path = self._base_dir / "results.txt"
        try:
            return int(path.stat().st_size)
        except Exception:
            return 0

    def _extract_latest_valid_results_record(self, *, baseline_offset: int) -> Optional[Dict[str, Any]]:
        path = self._base_dir / "results.txt"
        try:
            with path.open("rb") as f:
                f.seek(max(0, int(baseline_offset)))
                chunk = f.read()
        except Exception:
            return None

        if not chunk:
            return None

        content = chunk.decode("utf-8", errors="ignore")
        latest: Optional[Dict[str, Any]] = None
        running_offset = max(0, int(baseline_offset))

        for line in content.splitlines(keepends=True):
            parsed = self._parse_results_line(line)
            if parsed is not None:
                latest = {
                    **parsed,
                    "line_offset": running_offset,
                    "line_end_offset": running_offset + len(line.encode("utf-8", errors="ignore")),
                }
            running_offset += len(line.encode("utf-8", errors="ignore"))

        return latest

    def _parse_results_line(self, line: str) -> Optional[Dict[str, str]]:
        normalized = str(line or "").strip()
        if not normalized:
            return None

        parts = normalized.split("|")
        if len(parts) != 4:
            return None

        email = parts[0].strip()
        password = parts[1].strip()
        access_token = parts[2].strip()
        refresh_token = parts[3].strip()

        if not email or "@" not in email:
            return None
        if not access_token:
            return None
        if re.search(r"\s", access_token):
            return None
        if not refresh_token:
            return None
        if re.search(r"\s", refresh_token):
            return None

        return {
            "email": email,
            "password": password,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    def _build_resume_context_from_parsed_result(self, parsed_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(parsed_result, dict):
            return {
                "email": "",
                "team_name": "1",
                "source": "parse_path",
            }

        return {
            "email": str(parsed_result.get("email") or "").strip(),
            "access_token_raw": str(parsed_result.get("access_token") or "").strip(),
            "team_name": "1",
            "source": "parse_path",
            "results_offset": int(parsed_result.get("line_end_offset") or 0),
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
            "results_baseline_offset": 0,
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
    del os
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
        "GET": {"/status", "/logs", "/accounts"},
        "POST": {"/enable", "/resume", "/disable"},
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

