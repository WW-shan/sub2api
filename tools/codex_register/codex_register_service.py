from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import importlib
import inspect
import json
import logging
import os
import random
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

try:
    psycopg2 = importlib.import_module("psycopg2")
    _psycopg2_extras = importlib.import_module("psycopg2.extras")
    RealDictCursor = getattr(_psycopg2_extras, "RealDictCursor", None)
except Exception:  # pragma: no cover - optional runtime dependency in local tests
    psycopg2 = None  # type: ignore[assignment]
    RealDictCursor = None


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
        self.state_store = state_store
        self.chatgpt_service = chatgpt_service
        self.workflow_id = workflow_id
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self.db_session = db_session
        self.control_token = control_token
        self.auto_run = auto_run
        self._run_once_lock = asyncio.Lock()
        self._auto_run_task: Optional[asyncio.Task[Any]] = None

    async def handle_path(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        if path in {"/enable", "/resume", "/disable", "/retry", "/accounts"}:
            if not self._is_authorized(payload):
                return self._result(False, error="unauthorized")

        if path == "/status":
            state = await self._load_state()
            return self._result(True, data=state)

        if path == "/logs":
            logs = await self._list_logs()
            return self._result(True, data=logs)

        if path == "/accounts":
            list_persisted = getattr(self.state_store, "list_persisted_registrations", None)
            if callable(list_persisted):
                maybe_accounts = list_persisted()
                accounts = await maybe_accounts if inspect.isawaitable(maybe_accounts) else maybe_accounts
            else:
                accounts = await self.state_store.list_registrations()
            return self._result(True, data=accounts)

        if path == "/enable":
            state = await self._load_state()
            state["enabled"] = True
            previous_phase = str(state.get("job_phase") or "")
            state["job_phase"] = "running:create_parent"
            state["waiting_reason"] = ""
            state["can_start"] = False
            state["can_resume"] = False
            state["can_abandon"] = True
            state["last_resume_gate_reason"] = ""
            self._set_transition(
                state,
                from_phase=previous_phase,
                to_phase="running:create_parent",
                reason="enabled",
            )
            await self._save_state(state)
            await self._append_log("enabled")
            await self._ensure_auto_worker_running()
            return self._result(True, data=state)

        if path == "/resume":
            return await self._resume_from_waiting_manual()

        if path == "/disable":
            state = await self._load_state()
            state["enabled"] = False
            previous_phase = str(state.get("job_phase") or "")
            state["job_phase"] = "abandoned"
            state["waiting_reason"] = ""
            state["can_start"] = False
            state["can_resume"] = False
            state["can_abandon"] = False
            self._set_transition(
                state,
                from_phase=previous_phase,
                to_phase="abandoned",
                reason="disabled",
            )
            await self._save_state(state)
            await self._append_log("disabled")
            await self._stop_auto_worker()
            return self._result(True, data=state)

        if path == "/retry":
            state = await self._load_state()
            previous_phase = str(state.get("job_phase") or "")
            clear_registrations = getattr(self.state_store, "clear_registrations", None)
            if callable(clear_registrations):
                maybe_result = clear_registrations()
                if inspect.isawaitable(maybe_result):
                    await maybe_result

            state["enabled"] = True
            state["job_phase"] = "running:create_parent"
            state["waiting_reason"] = ""
            state["can_start"] = False
            state["can_resume"] = False
            state["can_abandon"] = True
            state["total_created"] = 0
            state["last_success"] = ""
            state["last_error"] = ""
            state["last_resume_gate_reason"] = ""
            self._set_transition(
                state,
                from_phase=previous_phase,
                to_phase="running:create_parent",
                reason="retry",
            )
            await self._save_state(state)
            await self._append_log("retried")
            await self._ensure_auto_worker_running()
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
                previous_phase = current_phase
                state["job_phase"] = "waiting_manual:parent_upgrade"
                state["waiting_reason"] = "parent_upgrade"
                state["can_start"] = False
                state["can_resume"] = True
                state["can_abandon"] = True
                self._set_transition(
                    state,
                    from_phase=previous_phase,
                    to_phase="waiting_manual:parent_upgrade",
                    reason="parent_upgrade_wait",
                )
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

        previous_phase = str(state.get("job_phase") or "")
        state["job_phase"] = "running:accept_and_switch"
        state["waiting_reason"] = ""
        state["enabled"] = True
        state["can_start"] = False
        state["can_resume"] = False
        state["can_abandon"] = True
        state["last_resume_gate_reason"] = ""
        self._set_transition(
            state,
            from_phase=previous_phase,
            to_phase="running:accept_and_switch",
            reason="resumed",
        )
        await self._save_state(state)
        await self._append_log("resumed")

        workflow_ok = await self._run_resume_invite_and_verify(
            state=state,
            accounts=accounts,
            parent_account_id=str(parent_account_id or ""),
            parent_identifier=parent_identifier,
            refreshed_access_token=refreshed_access_token,
        )
        if not workflow_ok:
            latest = await self._load_state()
            return self._result(False, error=str(latest.get("last_error") or "resume_verify_failed"), data=latest)

        latest = await self._load_state()
        return self._result(True, data=latest)

    async def _run_resume_invite_and_verify(
        self,
        *,
        state: Dict[str, Any],
        accounts: List[Dict[str, Any]],
        parent_account_id: str,
        parent_identifier: str,
        refreshed_access_token: str,
    ) -> bool:
        invite_method = getattr(self.chatgpt_service, "send_invite", None)
        members_method = getattr(self.chatgpt_service, "get_members", None)
        if not callable(invite_method) or not callable(members_method):
            await self._fail_workflow_state(state, reason="invite_or_members_api_not_available")
            return False

        children = [item for item in accounts if item.get("codex_register_role") == "child"]
        previous_phase = str(state.get("job_phase") or "")
        state["job_phase"] = "running:invite_children"
        self._set_transition(
            state,
            from_phase=previous_phase,
            to_phase="running:invite_children",
            reason="begin_invite",
        )
        await self._save_state(state)

        for child in children:
            child_email = str(child.get("email") or "").strip()
            if not child_email:
                await self._fail_workflow_state(state, reason="child_email_missing")
                return False

            invite_call = invite_method(
                refreshed_access_token,
                parent_account_id,
                child_email,
                self.db_session,
                identifier=parent_identifier,
            )
            invite_result_raw = await invite_call if inspect.isawaitable(invite_call) else invite_call
            invite_result = invite_result_raw if isinstance(invite_result_raw, dict) else {}
            if not invite_result.get("success"):
                error_message = str(invite_result.get("error") or "send_invite_failed")
                await self._fail_workflow_state(state, reason=error_message)
                return False

            await self._append_log("child_invited", email=child_email)

        previous_phase = str(state.get("job_phase") or "")
        state["job_phase"] = "running:verify_and_bind"
        self._set_transition(
            state,
            from_phase=previous_phase,
            to_phase="running:verify_and_bind",
            reason="begin_verify",
        )
        await self._save_state(state)

        members_call = members_method(
            refreshed_access_token,
            parent_account_id,
            self.db_session,
            identifier=parent_identifier,
        )
        members_result_raw = await members_call if inspect.isawaitable(members_call) else members_call
        members_result = members_result_raw if isinstance(members_result_raw, dict) else {}
        if not members_result.get("success"):
            error_message = str(members_result.get("error") or "get_members_failed")
            await self._fail_workflow_state(state, reason=error_message)
            return False

        expected_tokens = self._build_expected_member_tokens(accounts)
        observed_tokens = self._build_observed_member_tokens(list(members_result.get("members") or []))
        missing_tokens = sorted(expected_tokens - observed_tokens)
        if missing_tokens:
            await self._fail_workflow_state(
                state,
                reason="strict_six_member_verification_failed",
                details={"missing": missing_tokens},
            )
            return False

        previous_phase = str(state.get("job_phase") or "")
        state["job_phase"] = "completed"
        state["enabled"] = False
        state["waiting_reason"] = ""
        state["can_start"] = True
        state["can_resume"] = False
        state["can_abandon"] = False
        state["last_error"] = ""
        state["last_success"] = self._now_iso()
        self._set_transition(
            state,
            from_phase=previous_phase,
            to_phase="completed",
            reason="verify_completed",
        )
        await self._save_state(state)
        await self._append_log("workflow_completed")
        return True

    async def _fail_workflow_state(self, state: Dict[str, Any], *, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
        previous_phase = str(state.get("job_phase") or "")
        state["job_phase"] = "failed"
        state["enabled"] = False
        state["can_start"] = False
        state["can_resume"] = True
        state["can_abandon"] = True
        state["last_error"] = reason
        self._set_transition(
            state,
            from_phase=previous_phase,
            to_phase="failed",
            reason=reason,
        )
        await self._save_state(state)
        payload = {"reason": reason}
        if details:
            payload.update(details)
        await self._append_log("workflow_failed", **payload)

    def _build_expected_member_tokens(self, accounts: List[Dict[str, Any]]) -> set[str]:
        tokens: set[str] = set()
        for account in accounts:
            email = str(account.get("email") or "").strip().lower()
            account_id = str(account.get("account_id") or "").strip()
            if account_id:
                tokens.add(f"account_id:{account_id}")
            elif email:
                tokens.add(f"email:{email}")
        return tokens

    def _build_observed_member_tokens(self, members: List[Dict[str, Any]]) -> set[str]:
        tokens: set[str] = set()
        for member in members:
            if not isinstance(member, dict):
                continue

            direct_email = str(member.get("email") or "").strip().lower()
            direct_account_id = str(member.get("account_id") or "").strip()
            nested_user = member.get("user") if isinstance(member.get("user"), dict) else {}
            nested_email = str((nested_user or {}).get("email") or "").strip().lower()
            nested_account_id = str((nested_user or {}).get("account_id") or "").strip()

            for email in (direct_email, nested_email):
                if email:
                    tokens.add(f"email:{email}")

            for account_id in (direct_account_id, nested_account_id):
                if account_id:
                    tokens.add(f"account_id:{account_id}")

        return tokens

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
        log_time = self._now_iso()
        log_level = str(fields.get("level") or "info")
        payload_fields = {"time": log_time, "level": log_level, **fields}
        if callable(append):
            maybe_result = append(message, **payload_fields)
            if inspect.isawaitable(maybe_result):
                await maybe_result

        log_payload = {"event": message, **payload_fields}
        LOGGER.info(json.dumps(log_payload, ensure_ascii=False, default=str))

    async def _ensure_auto_worker_running(self) -> None:
        if not self.auto_run:
            return

        if self._auto_run_task and not self._auto_run_task.done():
            return

        self._auto_run_task = asyncio.create_task(self._auto_worker_loop())
        await self._append_log("auto_worker_started")

    async def _stop_auto_worker(self) -> None:
        task = self._auto_run_task
        if task is None:
            return

        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._auto_run_task = None
        await self._append_log("auto_worker_stopped")

    async def _auto_worker_loop(self) -> None:
        try:
            while True:
                state = await self._load_state()
                if not state.get("enabled"):
                    break

                current_phase = str(state.get("job_phase") or "")
                if current_phase not in {"running:create_parent", "running:create_children"}:
                    break

                await self._append_log("auto_worker_tick", phase=current_phase)
                await self.run_once()

                state_after = await self._load_state()
                if not state_after.get("enabled"):
                    break

                phase_after = str(state_after.get("job_phase") or "")
                if phase_after not in {"running:create_parent", "running:create_children"}:
                    break

                min_delay = max(1, int(state_after.get("sleep_min") or self.sleep_min or 1))
                max_delay = max(min_delay, int(state_after.get("sleep_max") or self.sleep_max or min_delay))
                delay_seconds = random.randint(min_delay, max_delay)
                await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._append_log("auto_worker_crashed", error=str(exc))
        finally:
            self._auto_run_task = None

    async def _list_logs(self) -> List[Dict[str, Any]]:
        list_logs = getattr(self.state_store, "list_logs", None)
        if callable(list_logs):
            maybe_result = list_logs()
            if inspect.isawaitable(maybe_result):
                resolved = await maybe_result
            else:
                resolved = maybe_result

            if isinstance(resolved, list):
                return [dict(item) if isinstance(item, dict) else {"message": str(item)} for item in resolved]
            return []

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
            "last_transition": None,
            "last_resume_gate_reason": "",
            "recent_logs_tail": [],
        }

    def _set_transition(self, state: Dict[str, Any], *, from_phase: str, to_phase: str, reason: str) -> None:
        state["last_transition"] = {
            "time": self._now_iso(),
            "from": from_phase,
            "to": to_phase,
            "reason": reason,
        }

    def _is_authorized(self, payload: Dict[str, Any]) -> bool:
        if not self.control_token:
            return True

        headers = payload.get("headers") or {}
        normalized_headers = {str(k).lower(): v for k, v in headers.items()}
        token = str(normalized_headers.get("x-codex-token") or "")
        return token == self.control_token

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

    async def clear_registrations(self) -> None:
        self._accounts = []


class PostgresBackedStateStore:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        dbname: str,
    ) -> None:
        self._state: Dict[str, Any] = {}
        self._accounts: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        self._dsn = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "dbname": dbname,
        }

    async def load_state(self) -> Dict[str, Any]:
        return dict(self._state)

    async def save_state(self, state: Dict[str, Any]) -> None:
        self._state = dict(state)

    async def persist_registration(self, payload: Dict[str, Any]) -> None:
        row = dict(payload)
        source = str(row.get("source") or "codex-register")
        row["source"] = source

        await asyncio.to_thread(self._upsert_account_row, row)
        self._upsert_memory_account(row)

    async def list_registrations(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._accounts]

    async def list_persisted_registrations(self) -> List[Dict[str, Any]]:
        rows = await asyncio.to_thread(self._fetch_account_rows)
        return [dict(item) for item in rows]

    async def append_log(self, message: str, **fields: Any) -> None:
        entry = {"message": message, **fields}
        self.logs.append(entry)
        state_tail = list(self._state.get("recent_logs_tail") or [])
        state_tail.append(entry)
        self._state["recent_logs_tail"] = state_tail[-20:]

    async def clear_registrations(self) -> None:
        self._accounts = []

    def _connect(self):
        if psycopg2 is None:
            raise RuntimeError("psycopg2_not_available")
        return psycopg2.connect(**self._dsn)

    def _upsert_account_row(self, payload: Dict[str, Any]) -> None:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO codex_register_accounts (
                        email,
                        refresh_token,
                        access_token,
                        account_id,
                        source,
                        plan_type,
                        organization_id,
                        workspace_id,
                        codex_register_role,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (email, source)
                    DO UPDATE SET
                        refresh_token = EXCLUDED.refresh_token,
                        access_token = EXCLUDED.access_token,
                        account_id = EXCLUDED.account_id,
                        plan_type = EXCLUDED.plan_type,
                        organization_id = EXCLUDED.organization_id,
                        workspace_id = EXCLUDED.workspace_id,
                        codex_register_role = EXCLUDED.codex_register_role,
                        updated_at = NOW()
                    """,
                    (
                        str(payload.get("email") or "").strip(),
                        str(payload.get("refresh_token") or "").strip(),
                        str(payload.get("access_token") or "").strip(),
                        str(payload.get("account_id") or "").strip() or None,
                        str(payload.get("source") or "codex-register").strip(),
                        str(payload.get("plan_type") or "").strip() or None,
                        str(payload.get("organization_id") or "").strip() or None,
                        str(payload.get("workspace_id") or "").strip() or None,
                        str(payload.get("codex_register_role") or "").strip() or None,
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def _fetch_account_rows(self) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            cursor_factory = RealDictCursor if RealDictCursor is not None else None
            with connection.cursor(cursor_factory=cursor_factory) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        email,
                        refresh_token,
                        access_token,
                        account_id,
                        source,
                        created_at,
                        updated_at,
                        plan_type,
                        organization_id,
                        workspace_id,
                        codex_register_role
                    FROM codex_register_accounts
                    WHERE source = 'codex-register'
                    ORDER BY created_at ASC
                    """
                )
                rows = cursor.fetchall()
        finally:
            connection.close()

        result: List[Dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                record = dict(row)
            else:
                continue

            created_at = record.get("created_at")
            updated_at = record.get("updated_at")
            created_at_formatter = getattr(created_at, "isoformat", None)
            updated_at_formatter = getattr(updated_at, "isoformat", None)

            record["created_at"] = created_at_formatter() if callable(created_at_formatter) else str(created_at or "")
            record["updated_at"] = updated_at_formatter() if callable(updated_at_formatter) else str(updated_at or "")
            result.append(record)

        return result

    def _upsert_memory_account(self, payload: Dict[str, Any]) -> None:
        email = str(payload.get("email") or "").strip()
        source = str(payload.get("source") or "codex-register").strip()
        if not email:
            return

        index = next(
            (
                idx
                for idx, item in enumerate(self._accounts)
                if str(item.get("email") or "").strip() == email
                and str(item.get("source") or "codex-register").strip() == source
            ),
            -1,
        )

        if index >= 0:
            merged = dict(self._accounts[index])
            merged.update(payload)
            self._accounts[index] = merged
            return

        self._accounts.append(dict(payload))

def _build_state_store_from_env() -> Any:
    postgres_host = str(os.getenv("POSTGRES_HOST") or "").strip()
    postgres_user = str(os.getenv("POSTGRES_USER") or "").strip()
    postgres_password = str(os.getenv("POSTGRES_PASSWORD") or "").strip()
    postgres_db = str(os.getenv("POSTGRES_DB") or "").strip()
    postgres_port_raw = str(os.getenv("POSTGRES_PORT") or "5432").strip()

    if not postgres_host or not postgres_user or not postgres_db:
        return InMemoryStateStore()

    try:
        postgres_port = int(postgres_port_raw)
    except ValueError:
        postgres_port = 5432

    if psycopg2 is None:
        return InMemoryStateStore()

    return PostgresBackedStateStore(
        host=postgres_host,
        port=postgres_port,
        user=postgres_user,
        password=postgres_password,
        dbname=postgres_db,
    )


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
    class CodexRegisterHTTPRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str) -> None:
            headers = {k: v for k, v in self.headers.items()}
            payload = {"headers": headers, "method": method}

            future = None
            try:
                service_loop = getattr(self.server, "_service_loop", None)
                if service_loop is None:
                    raise RuntimeError("service_loop_not_initialized")
                future = asyncio.run_coroutine_threadsafe(
                    service.handle_path(self.path, payload=payload),
                    service_loop,
                )
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
                        "path": self.path,
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
    from chatgpt import ChatGPTService

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

    LOGGER.info(
        json.dumps(
            {
                "event": "service_start",
                "workflow_id": workflow_id,
                "host": host,
                "port": port,
                "sleep_min": sleep_min,
                "sleep_max": sleep_max,
            },
            ensure_ascii=False,
            default=str,
        )
    )

    service = CodexRegisterService(
        state_store=_build_state_store_from_env(),
        chatgpt_service=ChatGPTService(),
        workflow_id=workflow_id,
        sleep_min=sleep_min,
        sleep_max=sleep_max,
        db_session=None,
        control_token=control_token,
        auto_run=True,
    )

    asyncio.run(run_http(service, host=host, port=port))


if __name__ == "__main__":
    main()
