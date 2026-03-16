import asyncio
import importlib
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


STATUS_PAYLOAD_FIELDS = {
    "enabled",
    "sleep_min",
    "sleep_max",
    "total_created",
    "last_success",
    "last_error",
    "proxy",
    "job_phase",
    "workflow_id",
    "waiting_reason",
    "can_start",
    "can_resume",
    "can_abandon",
    "last_transition",
    "last_resume_gate_reason",
    "recent_logs_tail",
}


class InMemoryWorkflowStore:
    def __init__(self):
        self.state = {
            "enabled": False,
            "sleep_min": 1,
            "sleep_max": 1,
            "total_created": 0,
            "last_success": "",
            "last_error": "",
            "proxy": "",
            "job_phase": "idle",
            "workflow_id": "wf-test",
            "waiting_reason": "",
            "can_start": True,
            "can_resume": False,
            "can_abandon": False,
            "last_transition": "",
            "last_resume_gate_reason": "",
            "recent_logs_tail": [],
        }
        self.accounts = []
        self.logs = []

    async def load_state(self):
        return dict(self.state)

    async def save_state(self, state):
        self.state = dict(state)

    async def persist_registration(self, payload):
        self.accounts.append(dict(payload))

    async def list_registrations(self):
        return [dict(item) for item in self.accounts]

    async def append_log(self, message, **fields):
        entry = {"message": message, **fields}
        self.logs.append(entry)
        tail = list(self.state.get("recent_logs_tail") or [])
        tail.append(entry)
        self.state["recent_logs_tail"] = tail[-20:]


class _MissingCodexRegisterService:
    def __init__(self, *args, **kwargs):
        del args, kwargs

    async def handle_path(self, path, payload=None):
        del path, payload
        raise AssertionError(
            "CodexRegisterService contract target missing. "
            "Expected class CodexRegisterService in tools.codex_register.codex_register_service"
        )

    async def run_once(self):
        raise AssertionError(
            "CodexRegisterService contract target missing. "
            "Expected run_once() implementation"
        )


def _load_service_class():
    module_name = "tools.codex_register.codex_register_service"
    try:
        if module_name in sys.modules:
            del sys.modules[module_name]
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return _MissingCodexRegisterService
        raise

    service_cls = getattr(module, "CodexRegisterService", None)
    if service_cls is not None:
        return service_cls
    return _MissingCodexRegisterService


def _register_success(index):
    return {
        "success": True,
        "status_code": 200,
        "data": {
            "email": f"child{index}@example.com",
            "account_id": f"acc_{index}",
            "access_token": f"at_{index}",
            "refresh_token": f"rt_{index}",
            "session_token": f"st_{index}",
            "identifier": f"ident_{index}",
        },
        "error": None,
        "error_code": None,
    }


class CodexRegisterServiceContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = InMemoryWorkflowStore()
        self.chatgpt = SimpleNamespace(
            register=AsyncMock(side_effect=[_register_success(i) for i in range(1, 20)]),
            refresh_access_token_with_session_token=AsyncMock(
                return_value={"success": True, "access_token": "parent-at"}
            ),
            get_account_info=AsyncMock(
                return_value={
                    "success": True,
                    "accounts": [
                        {
                            "account_id": "acc_1",
                            "plan_type": "team",
                            "has_active_subscription": True,
                        }
                    ],
                    "error": None,
                }
            ),
        )
        service_cls = _load_service_class()
        self.service = service_cls(
            state_store=self.store,
            chatgpt_service=self.chatgpt,
            workflow_id="wf-test",
            sleep_min=1,
            sleep_max=1,
        )

    async def _enable_and_create(self, count):
        await self.service.handle_path("/enable")
        for _ in range(count):
            await self.service.run_once()

    async def test_status_payload_contains_frontend_contract_fields(self):
        status_result = await self.service.handle_path("/status")
        self.assertTrue(status_result["success"])
        payload = status_result["data"]
        self.assertTrue(
            STATUS_PAYLOAD_FIELDS.issubset(set(payload.keys())),
            f"missing status keys: {STATUS_PAYLOAD_FIELDS - set(payload.keys())}",
        )

    async def test_enable_path_transitions_to_running_create_parent(self):
        await self.service.handle_path("/enable")

        status_result = await self.service.handle_path("/status")
        payload = status_result["data"]
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["job_phase"], "running:create_parent")

    async def test_create_phase_enters_waiting_manual_parent_upgrade_after_six_successes(self):
        await self._enable_and_create(6)

        status_result = await self.service.handle_path("/status")
        payload = status_result["data"]
        self.assertEqual(payload["total_created"], 6)
        self.assertEqual(payload["job_phase"], "waiting_manual:parent_upgrade")
        self.assertEqual(payload["waiting_reason"], "parent_upgrade")

    async def test_resume_orders_set_current_account_before_subscription_gate(self):
        await self._enable_and_create(6)

        call_order = []

        async def _refresh(*args, **kwargs):
            del args, kwargs
            call_order.append("refresh_access_token_with_session_token")
            return {"success": True, "access_token": "parent-at"}

        async def _account_info(*args, **kwargs):
            del args, kwargs
            call_order.append("get_account_info")
            return {
                "success": True,
                "accounts": [
                    {
                        "account_id": "acc_1",
                        "plan_type": "team",
                        "has_active_subscription": True,
                    }
                ],
                "error": None,
            }

        self.chatgpt.refresh_access_token_with_session_token = AsyncMock(side_effect=_refresh)
        self.chatgpt.get_account_info = AsyncMock(side_effect=_account_info)

        await self.service.handle_path("/resume")

        self.assertGreaterEqual(len(call_order), 2)
        self.assertEqual(
            call_order[:2],
            ["refresh_access_token_with_session_token", "get_account_info"],
        )

    async def test_resume_requires_strict_six_member_verification(self):
        for created_count, should_pass in ((5, False), (6, True)):
            with self.subTest(created_count=created_count, should_pass=should_pass):
                self.store = InMemoryWorkflowStore()
                self.chatgpt = SimpleNamespace(
                    register=AsyncMock(side_effect=[_register_success(i) for i in range(1, 20)]),
                    refresh_access_token_with_session_token=AsyncMock(
                        return_value={"success": True, "access_token": "parent-at"}
                    ),
                    get_account_info=AsyncMock(
                        return_value={
                            "success": True,
                            "accounts": [
                                {
                                    "account_id": "acc_1",
                                    "plan_type": "team",
                                    "has_active_subscription": True,
                                }
                            ],
                            "error": None,
                        }
                    ),
                )
                self.service = _load_service_class()(
                    state_store=self.store,
                    chatgpt_service=self.chatgpt,
                    workflow_id="wf-test",
                    sleep_min=1,
                    sleep_max=1,
                )
                await self._enable_and_create(created_count)

                if created_count == 5:
                    self.store.state.update(
                        {
                            "job_phase": "waiting_manual:parent_upgrade",
                            "waiting_reason": "parent_upgrade",
                            "can_start": False,
                            "can_resume": True,
                            "can_abandon": True,
                        }
                    )

                status_before_resume = (await self.service.handle_path("/status"))["data"]
                self.assertEqual(status_before_resume["job_phase"], "waiting_manual:parent_upgrade")
                self.assertEqual(status_before_resume["waiting_reason"], "parent_upgrade")

                result = await self.service.handle_path("/resume")
                status_payload = (await self.service.handle_path("/status"))["data"]

                if should_pass:
                    self.assertTrue(result["success"])
                    self.assertNotEqual(
                        status_payload.get("last_resume_gate_reason"),
                        "strict_six_member_verification_failed",
                    )
                else:
                    self.assertFalse(result["success"])
                    self.assertEqual(
                        status_payload.get("last_resume_gate_reason"),
                        "strict_six_member_verification_failed",
                    )

    async def test_registration_success_persists_immediately_with_parent_child_roles(self):
        await self.service.handle_path("/enable")

        await self.service.run_once()
        self.assertEqual(len(self.store.accounts), 1)
        self.assertEqual(self.store.accounts[0]["codex_register_role"], "parent")

        await self.service.run_once()
        self.assertEqual(len(self.store.accounts), 2)
        self.assertEqual(self.store.accounts[1]["codex_register_role"], "child")

    async def test_resume_when_not_waiting_manual_is_noop_and_logs_resume_request_ignored(self):
        await self.service.handle_path("/enable")

        resume_result = await self.service.handle_path("/resume")
        status_payload = (await self.service.handle_path("/status"))["data"]

        self.assertTrue(resume_result["success"])
        self.assertEqual(status_payload["job_phase"], "running:create_parent")
        self.assertTrue(
            any(log.get("message") == "resume_request_ignored" for log in self.store.logs),
            "expected resume_request_ignored log entry",
        )

    async def test_resume_transitions_to_create_children_and_run_once_creates_next_child(self):
        await self._enable_and_create(6)

        resume_result = await self.service.handle_path("/resume")
        status_after_resume = (await self.service.handle_path("/status"))["data"]

        self.assertTrue(resume_result["success"])
        self.assertEqual(status_after_resume["job_phase"], "running:create_children")

        run_result = await self.service.run_once()
        status_after_run = (await self.service.handle_path("/status"))["data"]

        self.assertTrue(run_result["success"])
        self.assertEqual(status_after_run["total_created"], 7)
        self.assertEqual(status_after_run["job_phase"], "running:create_children")
        self.assertEqual(status_after_run["waiting_reason"], "")

    async def test_resume_fails_when_refresh_access_token_fails(self):
        await self._enable_and_create(6)

        self.chatgpt.refresh_access_token_with_session_token = AsyncMock(
            return_value={"success": False, "error": "refresh_failed"}
        )

        result = await self.service.handle_path("/resume")
        status_payload = (await self.service.handle_path("/status"))["data"]

        self.assertFalse(result["success"])
        self.assertEqual(status_payload["job_phase"], "waiting_manual:parent_upgrade")
        self.assertEqual(status_payload["last_resume_gate_reason"], "refresh_access_token_failed")
        self.chatgpt.get_account_info.assert_not_awaited()

    async def test_resume_fails_when_get_account_info_fails(self):
        await self._enable_and_create(6)

        self.chatgpt.refresh_access_token_with_session_token = AsyncMock(
            return_value={"success": True, "access_token": "parent-at"}
        )
        self.chatgpt.get_account_info = AsyncMock(return_value={"success": False, "error": "forbidden"})

        result = await self.service.handle_path("/resume")
        status_payload = (await self.service.handle_path("/status"))["data"]

        self.assertFalse(result["success"])
        self.assertEqual(status_payload["job_phase"], "waiting_manual:parent_upgrade")
        self.assertEqual(status_payload["last_resume_gate_reason"], "account_info_failed")

    async def test_run_once_is_serialized_by_async_lock(self):
        await self._enable_and_create(5)

        async def _slow_register(*args, **kwargs):
            del args, kwargs
            await asyncio.sleep(0.01)
            return _register_success(6)

        self.chatgpt.register = AsyncMock(side_effect=_slow_register)

        await asyncio.gather(self.service.run_once(), self.service.run_once())
        status_payload = (await self.service.handle_path("/status"))["data"]

        self.assertEqual(self.chatgpt.register.await_count, 1)
        self.assertEqual(status_payload["total_created"], 6)
        self.assertEqual(status_payload["job_phase"], "waiting_manual:parent_upgrade")



    async def test_resume_fails_when_parent_not_upgraded_to_active_team(self):
        await self._enable_and_create(6)

        self.chatgpt.get_account_info = AsyncMock(
            return_value={
                "success": True,
                "accounts": [
                    {
                        "account_id": "acc_1",
                        "plan_type": "team",
                        "has_active_subscription": False,
                    }
                ],
                "error": None,
            }
        )

        result = await self.service.handle_path("/resume")
        status_payload = (await self.service.handle_path("/status"))["data"]

        self.assertFalse(result["success"])
        self.assertEqual(status_payload["job_phase"], "waiting_manual:parent_upgrade")
        self.assertEqual(status_payload["last_resume_gate_reason"], "parent_upgrade_not_verified")


class _StubWorkflowStore:
    def __init__(self):
        self._state = {}
        self._accounts = []
        self.logs = []

    async def load_state(self):
        return dict(self._state)

    async def save_state(self, state):
        self._state = dict(state)

    async def persist_registration(self, payload):
        self._accounts.append(dict(payload))

    async def list_registrations(self):
        return [dict(item) for item in self._accounts]

    async def append_log(self, message, **fields):
        self.logs.append({"message": message, **fields})


class _StubDBSession:
    pass


class _StubChatGPTService:
    def __init__(self):
        self.register_calls = []
        self.refresh_calls = []
        self.account_info_calls = []

    async def register(self, *, db_session=None, identifier="default"):
        self.register_calls.append({"db_session": db_session, "identifier": identifier})
        return {
            "success": True,
            "data": {
                "email": "parent@example.com",
                "account_id": "acc_1",
                "access_token": "at_1",
                "refresh_token": "rt_1",
                "session_token": "st_1",
                "identifier": "ident_1",
            },
            "error": None,
            "error_code": None,
        }

    async def refresh_access_token_with_session_token(
        self,
        session_token,
        db_session,
        account_id=None,
        identifier="default",
    ):
        self.refresh_calls.append(
            {
                "session_token": session_token,
                "db_session": db_session,
                "account_id": account_id,
                "identifier": identifier,
            }
        )
        return {"success": True, "access_token": "refreshed-at"}

    async def get_account_info(self, access_token, db_session, identifier="default"):
        self.account_info_calls.append(
            {
                "access_token": access_token,
                "db_session": db_session,
                "identifier": identifier,
            }
        )
        return {
            "success": True,
            "accounts": [
                {
                    "account_id": "acc_1",
                    "plan_type": "team",
                    "has_active_subscription": True,
                }
            ],
            "error": None,
        }


class CodexRegisterServiceRuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_calls_chatgpt_service_with_required_arguments(self):
        store = _StubWorkflowStore()
        chatgpt = _StubChatGPTService()
        service = _load_service_class()(
            state_store=store,
            chatgpt_service=chatgpt,
            workflow_id="wf-runtime",
            sleep_min=1,
            sleep_max=1,
            db_session=_StubDBSession(),
        )

        await service.handle_path("/enable")
        for _ in range(6):
            await service.run_once()

        resume_result = await service.handle_path("/resume")
        self.assertTrue(resume_result["success"])
        self.assertEqual(len(chatgpt.refresh_calls), 1)
        self.assertEqual(len(chatgpt.account_info_calls), 1)

        refresh_call = chatgpt.refresh_calls[0]
        self.assertEqual(refresh_call["session_token"], "st_1")
        self.assertEqual(refresh_call["account_id"], "acc_1")

        account_info_call = chatgpt.account_info_calls[0]
        self.assertEqual(account_info_call["access_token"], "refreshed-at")




class CodexRegisterServiceEntrypointContractTests(unittest.TestCase):
    def test_service_module_exports_build_http_handler(self):
        module_name = "tools.codex_register.codex_register_service"
        module = importlib.import_module(module_name)
        self.assertTrue(hasattr(module, "build_http_handler"))

    def test_service_module_exports_main(self):
        module_name = "tools.codex_register.codex_register_service"
        module = importlib.import_module(module_name)
        self.assertTrue(hasattr(module, "main"))


if __name__ == "__main__":
    unittest.main()
