import asyncio
import io
import importlib
import pathlib
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


MODULE_NAME = "tools.codex_register.codex_register_service"


class FakeProcess:
    def __init__(self, *, returncode=0, block=False):
        self._returncode_target = returncode
        self.returncode = None
        self._event = threading.Event()
        self._terminated = False
        self._killed = False
        if not block:
            self._event.set()

    def wait(self):
        self._event.wait(timeout=3)
        if self._killed:
            self.returncode = -9
            return self.returncode
        if self._terminated:
            self.returncode = -15
            return self.returncode
        if self.returncode is None:
            self.returncode = self._returncode_target
        return self.returncode

    def terminate(self):
        self._terminated = True
        self._event.set()

    def kill(self):
        self._killed = True
        self._event.set()

    def release(self):
        self._event.set()


class MinimalServiceContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)
        service_cls = getattr(self.module, "CodexRegisterService")
        store_cls = getattr(self.module, "InMemoryStateStore")
        self.store = store_cls()
        self.service = service_cls(
            state_store=self.store,
            chatgpt_service=SimpleNamespace(),
            workflow_id="wf-test",
            sleep_min=1,
            sleep_max=1,
            auto_run=False,
        )

    async def _wait_for_phase(self, expected_phase: str, timeout_seconds: float = 1.5):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            status = (await self.service.handle_path("/status"))["data"]
            if status["job_phase"] == expected_phase:
                return status
            await asyncio.sleep(0.01)
        self.fail(f"timed out waiting for phase: {expected_phase}")

    async def test_status_has_frontend_required_fields(self):
        result = await self.service.handle_path("/status")
        self.assertTrue(result["success"])

        payload = result["data"]
        required = {
            "enabled",
            "job_phase",
            "waiting_reason",
            "can_start",
            "can_resume",
            "can_abandon",
            "last_error",
            "last_success",
            "recent_logs_tail",
        }
        self.assertTrue(required.issubset(set(payload.keys())))

    async def test_enable_is_non_blocking_and_enters_running_get_tokens(self):
        fake = FakeProcess(block=True)

        with patch.object(self.module.subprocess, "Popen", return_value=fake):
            result = await self.service.handle_path("/enable")

        self.assertTrue(result["success"])
        status = (await self.service.handle_path("/status"))["data"]
        self.assertEqual(status["job_phase"], "running:get_tokens")
        self.assertFalse(status["can_start"])
        self.assertFalse(status["can_resume"])
        self.assertTrue(status["can_abandon"])

        fake.release()
        await self._wait_for_phase("waiting_manual:resume_email")

    async def test_enable_completion_moves_to_waiting_resume_email(self):
        fake = FakeProcess(returncode=0)

        with patch.object(self.module.subprocess, "Popen", return_value=fake):
            result = await self.service.handle_path("/enable")
            self.assertTrue(result["success"])

        status = await self._wait_for_phase("waiting_manual:resume_email")
        self.assertEqual(status["waiting_reason"], "resume_email")
        self.assertTrue(status["can_resume"])

    async def test_resume_requires_waiting_phase_and_single_string_email(self):
        invalid_phase = await self.service.handle_path("/resume", payload={"email": "a@b.com"})
        self.assertFalse(invalid_phase["success"])
        self.assertEqual(invalid_phase["error"], "invalid_phase")

        await self.store.save_state(
            {
                **(await self.store.load_state()),
                "job_phase": "waiting_manual:resume_email",
                "waiting_reason": "resume_email",
                "can_start": False,
                "can_resume": True,
                "can_abandon": True,
            }
        )

        missing_email = await self.service.handle_path("/resume", payload={})
        self.assertFalse(missing_email["success"])
        self.assertEqual(missing_email["error"], "email_required")

        non_string = await self.service.handle_path("/resume", payload={"email": ["a@b.com"]})
        self.assertFalse(non_string["success"])
        self.assertEqual(non_string["error"], "email_required")

    async def test_resume_starts_gpt_batch_with_injected_team_email(self):
        await self.store.save_state(
            {
                **(await self.store.load_state()),
                "job_phase": "waiting_manual:resume_email",
                "waiting_reason": "resume_email",
                "can_start": False,
                "can_resume": True,
                "can_abandon": True,
            }
        )

        fake = FakeProcess(block=True)
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return fake

        with patch.object(self.module.subprocess, "Popen", side_effect=_fake_popen):
            result = await self.service.handle_path("/resume", payload={"email": "mother@example.com"})

        self.assertTrue(result["success"])
        command_text = " ".join(captured["cmd"])
        self.assertIn("module.TEAMS", command_text)
        self.assertIn("mother@example.com", command_text)

        status = (await self.service.handle_path("/status"))["data"]
        self.assertEqual(status["job_phase"], "running:gpt_team_batch")

        fake.release()
        await self._wait_for_phase("completed")

    async def test_disable_terminates_running_process_and_sets_abandoned(self):
        fake = FakeProcess(block=True)

        with patch.object(self.module.subprocess, "Popen", return_value=fake):
            await self.service.handle_path("/enable")

        result = await self.service.handle_path("/disable")
        self.assertTrue(result["success"])
        self.assertTrue(fake._terminated or fake._killed)

        status = (await self.service.handle_path("/status"))["data"]
        self.assertEqual(status["job_phase"], "abandoned")
        self.assertFalse(status["enabled"])
        self.assertTrue(status["can_start"])

    async def test_shell_endpoints_logs_and_accounts(self):
        logs = await self.service.handle_path("/logs")
        self.assertTrue(logs["success"])
        self.assertIsInstance(logs["data"], list)

        accounts = await self.service.handle_path("/accounts")
        self.assertTrue(accounts["success"])
        self.assertEqual(accounts["data"], [])


class HTTPMethodContractTests(unittest.TestCase):
    def setUp(self):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)

    def test_get_enable_returns_405(self):
        class _StubService:
            async def handle_path(self, path, payload=None):
                del path, payload
                return {"success": True, "data": {"ok": True}, "error": None}

        handler_cls = self.module.build_http_handler(_StubService())
        handler = object.__new__(handler_cls)
        handler.path = "/enable"
        handler.headers = {}
        handler.server = SimpleNamespace(_service_loop=object())
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()

        status_codes = []
        handler.send_response = lambda status: status_codes.append(status)
        handler.send_header = lambda key, value: None
        handler.end_headers = lambda: None

        handler._handle("GET")

        self.assertEqual(status_codes, [405])




class AuthAndFailureContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)
        service_cls = getattr(self.module, "CodexRegisterService")
        store_cls = getattr(self.module, "InMemoryStateStore")
        self.store = store_cls()
        self.service = service_cls(
            state_store=self.store,
            chatgpt_service=SimpleNamespace(),
            workflow_id="wf-test",
            sleep_min=1,
            sleep_max=1,
            control_token="secret-token",
            auto_run=False,
        )

    async def _wait_for_phase(self, expected_phase: str, timeout_seconds: float = 1.5):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            status = (await self.service.handle_path("/status"))["data"]
            if status["job_phase"] == expected_phase:
                return status
            await asyncio.sleep(0.01)
        self.fail(f"timed out waiting for phase: {expected_phase}")

    async def test_mutating_endpoints_require_token(self):
        for path, payload in (
            ("/enable", {}),
            ("/resume", {"email": "x@y.com"}),
            ("/disable", {}),
        ):
            with self.subTest(path=path):
                result = await self.service.handle_path(path, payload=payload)
                self.assertFalse(result["success"])
                self.assertEqual(result["error"], "unauthorized")

    async def test_enable_spawn_failure_sets_failed_state(self):
        with patch.object(self.module.subprocess, "Popen", side_effect=RuntimeError("boom")):
            result = await self.service.handle_path(
                "/enable",
                payload={"headers": {"X-CODEX-TOKEN": "secret-token"}},
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "spawn_failed")

        status = (await self.service.handle_path("/status"))["data"]
        self.assertEqual(status["job_phase"], "failed")
        self.assertIn("boom", status["last_error"])

    async def test_enable_nonzero_exit_sets_failed_state(self):
        fake = FakeProcess(returncode=2)

        with patch.object(self.module.subprocess, "Popen", return_value=fake):
            result = await self.service.handle_path(
                "/enable",
                payload={"headers": {"x-codex-token": "secret-token"}},
            )
            self.assertTrue(result["success"])

        status = await self._wait_for_phase("failed")
        self.assertEqual(status["last_error"], "get_tokens_exit_2")


if __name__ == "__main__":
    unittest.main()
