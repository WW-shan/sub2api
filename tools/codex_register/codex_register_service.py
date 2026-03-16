from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


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
    ) -> None:
        self.state_store = state_store
        self.chatgpt_service = chatgpt_service
        self.workflow_id = workflow_id
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.db_session = db_session
        self._run_once_lock = asyncio.Lock()

    async def handle_path(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        del payload
        if path == "/status":
            state = await self._load_state()
            return self._result(True, data=state)

        if path == "/logs":
            logs = await self._list_logs()
            return self._result(True, data=logs)

        if path == "/accounts":
            accounts = await self.state_store.list_registrations()
            return self._result(True, data=accounts)

        if path == "/enable":
            state = await self._load_state()
            state["enabled"] = True
            state["job_phase"] = "running:create_parent"
            state["waiting_reason"] = ""
            state["can_start"] = False
            state["can_resume"] = False
            state["can_abandon"] = True
            state["last_resume_gate_reason"] = ""
            state["last_transition"] = self._now_iso()
            await self._save_state(state)
            await self._append_log("enabled")
            return self._result(True, data=state)

        if path == "/resume":
            return await self._resume_from_waiting_manual()

        if path == "/disable":
            state = await self._load_state()
            state["enabled"] = False
            state["job_phase"] = "abandoned"
            state["waiting_reason"] = ""
            state["can_start"] = False
            state["can_resume"] = False
            state["can_abandon"] = False
            state["last_transition"] = self._now_iso()
            await self._save_state(state)
            await self._append_log("disabled")
            return self._result(True, data=state)

        return self._result(False, error=f"unsupported_path: {path}")

    async def run_once(self) -> Dict[str, Any]:
        async with self._run_once_lock:
            state = await self._load_state()
            if not state.get("enabled"):
                return self._result(True, data=state)

            current_phase = str(state.get("job_phase") or "")
            if current_phase not in {"running:create_parent", "running:create_children"}:
                return self._result(True, data=state)

            register_result = await self.chatgpt_service.register(
                db_session=self.db_session,
                identifier=self.workflow_id,
            )
            if not register_result or not register_result.get("success"):
                state["last_error"] = str((register_result or {}).get("error") or "registration_failed")
                await self._save_state(state)
                await self._append_log("register_failed", error=state["last_error"])
                return self._result(False, error=state["last_error"], data=state)

            register_payload = dict(register_result.get("data") or {})
            existing_accounts = await self.state_store.list_registrations()
            register_payload["codex_register_role"] = "parent" if len(existing_accounts) == 0 else "child"

            # Persist immediately on registration success.
            await self.state_store.persist_registration(register_payload)

            total_created = int(state.get("total_created") or 0) + 1
            state["total_created"] = total_created
            state["last_success"] = self._now_iso()
            state["last_error"] = ""

            if current_phase == "running:create_parent" and total_created >= 6:
                state["job_phase"] = "waiting_manual:parent_upgrade"
                state["waiting_reason"] = "parent_upgrade"
                state["can_start"] = False
                state["can_resume"] = True
                state["can_abandon"] = True
                state["last_transition"] = self._now_iso()
                await self._append_log("entered_waiting_manual_parent_upgrade")
            else:
                state["job_phase"] = current_phase
                state["waiting_reason"] = ""

            await self._save_state(state)
            return self._result(True, data=state)

    async def _resume_from_waiting_manual(self) -> Dict[str, Any]:
        state = await self._load_state()
        job_phase = str(state.get("job_phase") or "")

        if not job_phase.startswith("waiting_manual:"):
            await self._append_log("resume_request_ignored")
            return self._result(True, data=state)

        accounts = await self.state_store.list_registrations()
        if len(accounts) != 6:
            state["last_resume_gate_reason"] = "strict_six_member_verification_failed"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        parent_account = next((item for item in accounts if item.get("codex_register_role") == "parent"), None)
        if parent_account is None:
            state["last_resume_gate_reason"] = "parent_account_missing"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        parent_session_token = str(parent_account.get("session_token") or "")
        if not parent_session_token:
            state["last_resume_gate_reason"] = "parent_session_token_missing"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        parent_account_id = parent_account.get("account_id")
        parent_identifier = str(parent_account.get("identifier") or self.workflow_id)

        # Contract-required call order.
        refresh_result = await self.chatgpt_service.refresh_access_token_with_session_token(
            parent_session_token,
            self.db_session,
            account_id=parent_account_id,
            identifier=parent_identifier,
        )
        if not refresh_result or not refresh_result.get("success"):
            state["last_resume_gate_reason"] = "refresh_access_token_failed"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        refreshed_access_token = str(refresh_result.get("access_token") or "")
        if not refreshed_access_token:
            state["last_resume_gate_reason"] = "refresh_access_token_failed"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        account_info_result = await self.chatgpt_service.get_account_info(
            refreshed_access_token,
            self.db_session,
            identifier=parent_identifier,
        )
        if not account_info_result or not account_info_result.get("success"):
            state["last_resume_gate_reason"] = "account_info_failed"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        if not self._has_active_team_subscription(account_info_result, parent_account_id):
            state["last_resume_gate_reason"] = "parent_upgrade_not_verified"
            await self._save_state(state)
            await self._append_log("resume_gate_failed", reason=state["last_resume_gate_reason"])
            return self._result(False, error=state["last_resume_gate_reason"], data=state)

        state["job_phase"] = "running:create_children"
        state["waiting_reason"] = ""
        state["enabled"] = True
        state["can_start"] = False
        state["can_resume"] = False
        state["can_abandon"] = True
        state["last_resume_gate_reason"] = ""
        state["last_transition"] = self._now_iso()
        await self._save_state(state)
        await self._append_log("resumed")
        return self._result(True, data=state)

    async def _load_state(self) -> Dict[str, Any]:
        existing = await self.state_store.load_state()
        normalized = self._default_state()
        normalized.update(existing or {})
        normalized["workflow_id"] = normalized.get("workflow_id") or self.workflow_id
        normalized["sleep_min"] = normalized.get("sleep_min", self.sleep_min)
        normalized["sleep_max"] = normalized.get("sleep_max", self.sleep_max)
        if not isinstance(normalized.get("recent_logs_tail"), list):
            normalized["recent_logs_tail"] = []
        return normalized

    async def _save_state(self, state: Dict[str, Any]) -> None:
        await self.state_store.save_state(state)

    async def _append_log(self, message: str, **fields: Any) -> None:
        append = getattr(self.state_store, "append_log", None)
        if callable(append):
            await append(message, **fields)

    async def _list_logs(self) -> List[Dict[str, Any]]:
        list_logs = getattr(self.state_store, "list_logs", None)
        if callable(list_logs):
            return await list_logs()

        logs = getattr(self.state_store, "logs", None)
        if isinstance(logs, list):
            return [dict(item) if isinstance(item, dict) else {"message": str(item)} for item in logs]

        state = await self._load_state()
        tail = state.get("recent_logs_tail") or []
        if isinstance(tail, list):
            return [dict(item) if isinstance(item, dict) else {"message": str(item)} for item in tail]
        return []

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
            "last_transition": "",
            "last_resume_gate_reason": "",
            "recent_logs_tail": [],
        }

    def _has_active_team_subscription(self, account_info_result: Dict[str, Any], parent_account_id: Optional[str]) -> bool:
        accounts = account_info_result.get("accounts") or []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            if parent_account_id and str(account.get("account_id") or "") != str(parent_account_id):
                continue
            if account.get("plan_type") == "team" and bool(account.get("has_active_subscription")):
                return True
        return False

    def _result(self, success: bool, *, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
        return {
            "success": success,
            "data": data,
            "error": error,
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class InMemoryStateStore:
    def __init__(self) -> None:
        self._state: Dict[str, Any] = {}
        self._accounts: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []

    async def load_state(self) -> Dict[str, Any]:
        return dict(self._state)

    async def save_state(self, state: Dict[str, Any]) -> None:
        self._state = dict(state)

    async def persist_registration(self, payload: Dict[str, Any]) -> None:
        self._accounts.append(dict(payload))

    async def list_registrations(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._accounts]

    async def append_log(self, message: str, **fields: Any) -> None:
        entry = {"message": message, **fields}
        self.logs.append(entry)
        state_tail = list(self._state.get("recent_logs_tail") or [])
        state_tail.append(entry)
        self._state["recent_logs_tail"] = state_tail[-20:]


async def run_http(service: CodexRegisterService, *, host: str, port: int) -> None:
    handler = build_http_handler(service)
    server = ThreadingHTTPServer((host, port), handler)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, server.serve_forever)


def build_http_handler(service: CodexRegisterService):
    class CodexRegisterHTTPRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str) -> None:
            del method
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(service.handle_path(self.path))
            finally:
                loop.close()

            status_code = 200 if response.get("success") else 400
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
    from chatgpt import ChatGPTService

    workflow_id = os.getenv("CODEX_REGISTER_WORKFLOW_ID", "wf-runtime")
    sleep_min = int(os.getenv("CODEX_REGISTER_SLEEP_MIN", "1"))
    sleep_max = int(os.getenv("CODEX_REGISTER_SLEEP_MAX", "1"))
    host = os.getenv("CODEX_REGISTER_HOST", "0.0.0.0")
    port = int(os.getenv("CODEX_REGISTER_PORT", "5000"))

    service = CodexRegisterService(
        state_store=InMemoryStateStore(),
        chatgpt_service=ChatGPTService(),
        workflow_id=workflow_id,
        sleep_min=sleep_min,
        sleep_max=sleep_max,
        db_session=None,
    )

    asyncio.run(run_http(service, host=host, port=port))


if __name__ == "__main__":
    main()
