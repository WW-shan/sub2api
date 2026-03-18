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

        with patch.object(
            self.service,
            "_extract_latest_valid_results_record",
            return_value={"email": "mother@example.com", "password": "p", "access_token": "t", "line_end_offset": 1},
        ):
            with patch.object(self.module.subprocess, "Popen", return_value=fake):
                result = await self.service.handle_path("/enable")

            self.assertTrue(result["success"])
            status = (await self.service.handle_path("/status"))["data"]
            self.assertEqual(status["job_phase"], "running:get_tokens")
            self.assertFalse(status["can_start"])
            self.assertFalse(status["can_resume"])
            self.assertTrue(status["can_abandon"])

            fake.release()
            await self._wait_for_phase("waiting_manual:subscribe_then_resume")

    async def test_enable_completion_moves_to_waiting_resume_email(self):
        fake = FakeProcess(returncode=0)

        with patch.object(
            self.service,
            "_extract_latest_valid_results_record",
            return_value={"email": "mother@example.com", "password": "p", "access_token": "t", "line_end_offset": 1},
        ):
            with patch.object(self.module.subprocess, "Popen", return_value=fake):
                result = await self.service.handle_path("/enable")
                self.assertTrue(result["success"])

            status = await self._wait_for_phase("waiting_manual:subscribe_then_resume")
            self.assertEqual(status["waiting_reason"], "subscribe_then_resume")
            self.assertTrue(status["can_resume"])

    async def test_resume_requires_waiting_phase_and_single_string_email(self):
        invalid_phase = await self.service.handle_path("/resume", payload={"email": "a@b.com"})
        self.assertFalse(invalid_phase["success"])
        self.assertIsInstance(invalid_phase["error"], dict)
        self.assertEqual(invalid_phase["error"].get("code"), "invalid_phase")

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


class StateStoreEnvContractRedTests(unittest.TestCase):
    def setUp(self):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)

    def test_build_state_store_from_env_returns_in_memory_store(self):
        store = self.module._build_state_store_from_env()
        self.assertIsInstance(store, self.module.InMemoryStateStore)


class FourSegmentParserContractRedTests(unittest.IsolatedAsyncioTestCase):
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

    def test_three_segment_line_rejected_by_parse_results_line(self):
        parsed = self.service._parse_results_line("mother@example.com|pw-123|access-token")
        self.assertIsNone(parsed)

    def test_four_segment_line_accepted_and_exposes_refresh_token(self):
        parsed = self.service._parse_results_line(
            "mother@example.com|pw-123|access-token|refresh-token"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["email"], "mother@example.com")
        self.assertEqual(parsed["password"], "pw-123")
        self.assertEqual(parsed["access_token"], "access-token")
        self.assertEqual(parsed["refresh_token"], "refresh-token")

    async def test_enable_tokens_result_missing_for_incremental_four_segment_line_without_refresh_token(self):
        fake = FakeProcess(returncode=0)

        with patch.object(self.service, "_capture_results_baseline_offset", return_value=0):
            with patch.object(self.module.Path, "open") as open_mock:
                open_mock.return_value.__enter__.return_value.read.return_value = (
                    b"mother@example.com|pw-123|access-token|\n"
                )
                with patch.object(self.module.subprocess, "Popen", return_value=fake):
                    result = await self.service.handle_path("/enable")
                    self.assertTrue(result["success"])

                status = await self._wait_for_phase("failed")
                self.assertEqual(status["job_phase"], "failed")
                self.assertEqual(status["last_error"], "tokens_result_missing")
                self.assertEqual(status["waiting_reason"], "")


class ManualSubscribeGateContractTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_enable_transitions_to_subscribe_waiting_gate_contract(self):
        fake = FakeProcess(returncode=0)

        with patch.object(
            self.service,
            "_extract_latest_valid_results_record",
            return_value={"email": "mother@example.com", "password": "p", "access_token": "t", "line_end_offset": 1},
        ):
            with patch.object(self.module.subprocess, "Popen", return_value=fake):
                result = await self.service.handle_path("/enable")
                self.assertTrue(result["success"])

            status = await self._wait_for_phase("waiting_manual:subscribe_then_resume")
            self.assertEqual(status["waiting_reason"], "subscribe_then_resume")
            self.assertTrue(status["can_resume"])
            self.assertFalse(status["can_start"])
            self.assertTrue(status["can_abandon"])

            self.assertIn("manual_gate", status)
            self.assertIsInstance(status["manual_gate"], dict)
            self.assertEqual(status["manual_gate"].get("name"), "subscribe_then_resume")
            self.assertEqual(status["manual_gate"].get("status"), "waiting")

    async def test_resume_invalid_phase_returns_contract_error_and_preserves_state(self):
        before = await self.store.load_state()

        result = await self.service.handle_path("/resume", payload={"resume_context": {"email": "a@b.com"}})

        self.assertFalse(result["success"])
        self.assertIsInstance(result["error"], dict)
        self.assertEqual(result["error"].get("code"), "invalid_phase")
        after = await self.store.load_state()
        self.assertEqual(after, before)

    async def test_resume_context_missing_returns_contract_error_and_preserves_state(self):
        seeded = {
            **(await self.store.load_state()),
            "job_phase": "waiting_manual:subscribe_then_resume",
            "waiting_reason": "subscribe_then_resume",
            "can_start": False,
            "can_resume": True,
            "can_abandon": True,
            "manual_gate": {"name": "subscribe_then_resume", "status": "waiting"},
        }
        await self.store.save_state(seeded)

        result = await self.service.handle_path("/resume", payload={})

        self.assertFalse(result["success"])
        self.assertIsInstance(result["error"], dict)
        self.assertEqual(result["error"].get("code"), "resume_context_missing")
        after = await self.store.load_state()
        self.assertEqual(after, seeded)

    async def test_status_exposes_resume_context_and_resume_hint_after_parse_path(self):
        seeded = {
            **(await self.store.load_state()),
            "job_phase": "waiting_manual:subscribe_then_resume",
            "waiting_reason": "subscribe_then_resume",
            "can_start": False,
            "can_resume": True,
            "can_abandon": True,
            "resume_context": {
                "email": "mother@example.com",
                "team_name": "1",
                "source": "parse_path",
                "access_token_raw": "token-value",
            },
            "resume_hint": {
                "action": "call_resume",
                "path": "/resume",
                "required_fields": ["resume_context.email"],
            },
        }
        await self.store.save_state(seeded)

        status_result = await self.service.handle_path("/status")

        self.assertTrue(status_result["success"])
        status = status_result["data"]
        self.assertIn("resume_context", status)
        self.assertEqual(status["resume_context"].get("email"), "mother@example.com")
        self.assertEqual(status["resume_context"].get("source"), "parse_path")
        self.assertEqual(status["resume_context"].get("access_token_raw"), "token-value")
        self.assertNotIn("password", status["resume_context"])
        self.assertNotIn("access_token", status["resume_context"])
        self.assertIn("resume_hint", status)
        self.assertEqual(status["resume_hint"].get("action"), "call_resume")
        self.assertEqual(status["resume_hint"].get("path"), "/resume")
        self.assertIn("resume_context.email", status["resume_hint"].get("required_fields", []))

    async def test_enable_tokens_result_missing_transitions_to_failed_not_waiting(self):
        fake = FakeProcess(returncode=0)

        with patch.object(self.service, "_extract_latest_valid_results_record", return_value=None):
            with patch.object(self.module.subprocess, "Popen", return_value=fake):
                result = await self.service.handle_path("/enable")
                self.assertTrue(result["success"])

            status = await self._wait_for_phase("failed")
            self.assertEqual(status["job_phase"], "failed")
            self.assertEqual(status["last_error"], "tokens_result_missing")
            self.assertEqual(status["waiting_reason"], "")
            self.assertFalse(status["enabled"])
            self.assertTrue(status["can_start"])
            self.assertFalse(status["can_resume"])
            self.assertTrue(status["can_abandon"])
            self.assertIsNone(status.get("manual_gate"))
            self.assertIsNone(status.get("resume_context"))
            self.assertIsNone(status.get("resume_hint"))


class LifecycleIdempotencyRedTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_clears_resume_context_on_disable_and_completed_state(self):
        waiting_seed = {
            **(await self.store.load_state()),
            "job_phase": "waiting_manual:subscribe_then_resume",
            "waiting_reason": "subscribe_then_resume",
            "enabled": True,
            "can_start": False,
            "can_resume": True,
            "can_abandon": True,
            "manual_gate": {"name": "subscribe_then_resume", "status": "waiting"},
            "resume_context": {"email": "mother@example.com", "source": "parse_path", "team_name": "1"},
            "resume_hint": {"action": "call_resume", "path": "/resume", "required_fields": ["resume_context.email"]},
        }
        await self.store.save_state(waiting_seed)

        disable_result = await self.service.handle_path("/disable")
        self.assertTrue(disable_result["success"])
        after_disable = (await self.service.handle_path("/status"))["data"]
        self.assertIsNone(after_disable.get("manual_gate"))
        self.assertIsNone(after_disable.get("resume_context"))
        self.assertIsNone(after_disable.get("resume_hint"))

        second_store = getattr(self.module, "InMemoryStateStore")()
        second_service = getattr(self.module, "CodexRegisterService")(
            state_store=second_store,
            chatgpt_service=SimpleNamespace(),
            workflow_id="wf-test-2",
            sleep_min=1,
            sleep_max=1,
            auto_run=False,
        )
        await second_store.save_state(waiting_seed)
        fake = FakeProcess(returncode=0)

        with patch.object(self.module.subprocess, "Popen", return_value=fake):
            first_resume = await second_service.handle_path("/resume", payload={"email": "ignored@example.com"})
            self.assertTrue(first_resume["success"])

        loop = asyncio.get_running_loop()
        deadline = loop.time() + 1.5
        while loop.time() < deadline:
            status = (await second_service.handle_path("/status"))["data"]
            if status["job_phase"] == "completed":
                break
            await asyncio.sleep(0.01)
        else:
            self.fail("timed out waiting for completed phase")

        completed_state = (await second_service.handle_path("/status"))["data"]
        self.assertIsNone(completed_state.get("manual_gate"))
        self.assertIsNone(completed_state.get("resume_context"))
        self.assertIsNone(completed_state.get("resume_hint"))

    async def test_double_resume_already_running_contract(self):
        await self.store.save_state(
            {
                **(await self.store.load_state()),
                "job_phase": "waiting_manual:subscribe_then_resume",
                "waiting_reason": "subscribe_then_resume",
                "enabled": True,
                "can_start": False,
                "can_resume": True,
                "can_abandon": True,
                "resume_context": {"email": "mother@example.com", "team_name": "1", "source": "parse_path"},
            }
        )

        fake = FakeProcess(block=True)
        with patch.object(self.module.subprocess, "Popen", return_value=fake):
            first = await self.service.handle_path("/resume", payload={"email": "ignored@example.com"})
            self.assertTrue(first["success"])

            second = await self.service.handle_path("/resume", payload={"email": "ignored@example.com"})

        self.assertFalse(second["success"])
        self.assertIsInstance(second["error"], dict)
        self.assertEqual(second["error"].get("code"), "already_running")

        fake.release()
        await self._wait_for_phase("completed")

    async def test_disable_twice_waiting_is_idempotent_and_clears_resume_context(self):
        await self.store.save_state(
            {
                **(await self.store.load_state()),
                "job_phase": "waiting_manual:subscribe_then_resume",
                "waiting_reason": "subscribe_then_resume",
                "enabled": True,
                "can_start": False,
                "can_resume": True,
                "can_abandon": True,
                "manual_gate": {"name": "subscribe_then_resume", "status": "waiting"},
                "resume_context": {"email": "mother@example.com", "team_name": "1", "source": "parse_path"},
                "resume_hint": {"action": "call_resume", "path": "/resume", "required_fields": ["resume_context.email"]},
            }
        )

        first_disable = await self.service.handle_path("/disable")
        second_disable = await self.service.handle_path("/disable")

        self.assertTrue(first_disable["success"])
        self.assertTrue(second_disable["success"])

        status = (await self.service.handle_path("/status"))["data"]
        self.assertEqual(status["job_phase"], "abandoned")
        self.assertIsNone(status.get("manual_gate"))
        self.assertIsNone(status.get("resume_context"))
        self.assertIsNone(status.get("resume_hint"))

    async def test_disable_during_parse_precedence_disable_wins_over_waiting_transition(self):
        fake = FakeProcess(block=True)
        await self.store.save_state(
            {
                **(await self.store.load_state()),
                "job_phase": "running:get_tokens",
                "waiting_reason": "",
                "enabled": True,
                "can_start": False,
                "can_resume": False,
                "can_abandon": True,
                "manual_gate": {"name": "subscribe_then_resume", "status": "waiting"},
                "resume_context": {"email": "stale@example.com", "team_name": "1", "source": "parse_path"},
                "resume_hint": {"action": "call_resume", "path": "/resume", "required_fields": ["resume_context.email"]},
            }
        )
        self.service._active_process = fake
        self.service._active_context = {"mode": "enable", "name": "get_tokens"}
        self.service._stop_requested = False

        disable_result = await self.service.handle_path("/disable")
        self.assertTrue(disable_result["success"])

        with patch.object(
            self.service,
            "_extract_latest_valid_results_record",
            return_value={"email": "mother@example.com", "password": "p", "access_token": "t", "line_end_offset": 1},
        ):
            await self.service._handle_process_exit(fake, {"mode": "enable", "name": "get_tokens"}, 0)

        status = (await self.service.handle_path("/status"))["data"]
        self.assertEqual(status["job_phase"], "abandoned")
        self.assertIsNone(status.get("manual_gate"))
        self.assertIsNone(status.get("resume_context"))
        self.assertIsNone(status.get("resume_hint"))

    async def test_failed_state_flags_parse_failure_path_are_deterministic(self):
        await self.store.save_state(
            {
                **(await self.store.load_state()),
                "last_success": "2026-03-18T00:00:00+00:00",
            }
        )
        fake = FakeProcess(returncode=0)

        with patch.object(self.service, "_extract_latest_valid_results_record", return_value=None):
            with patch.object(self.module.subprocess, "Popen", return_value=fake):
                result = await self.service.handle_path("/enable")
                self.assertTrue(result["success"])

        failed = await self._wait_for_phase("failed")
        self.assertEqual(failed["last_error"], "tokens_result_missing")
        self.assertEqual(failed["waiting_reason"], "")
        self.assertFalse(failed["enabled"])
        self.assertTrue(failed["can_start"])
        self.assertFalse(failed["can_resume"])
        self.assertTrue(failed["can_abandon"])
        self.assertEqual(failed["last_success"], "")


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
