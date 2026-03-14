import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _build_chatgpt_import_stubs() -> dict:
    curl_cffi_module = types.ModuleType("curl_cffi")
    curl_cffi_requests_module = types.ModuleType("curl_cffi.requests")

    class AsyncSession:  # pragma: no cover - import stub
        async def close(self):
            return None

    curl_cffi_requests_module.AsyncSession = AsyncSession
    curl_cffi_module.requests = curl_cffi_requests_module

    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_ext_module = types.ModuleType("sqlalchemy.ext")
    sqlalchemy_ext_asyncio_module = types.ModuleType("sqlalchemy.ext.asyncio")

    class DBAsyncSession:  # pragma: no cover - import stub
        pass

    sqlalchemy_ext_asyncio_module.AsyncSession = DBAsyncSession
    sqlalchemy_ext_module.asyncio = sqlalchemy_ext_asyncio_module
    sqlalchemy_module.ext = sqlalchemy_ext_module

    app_module = types.ModuleType("app")
    app_utils_module = types.ModuleType("app.utils")
    app_jwt_parser_module = types.ModuleType("app.utils.jwt_parser")

    class JWTParser:  # pragma: no cover - import stub
        def extract_email(self, token: str):
            return None

    app_jwt_parser_module.JWTParser = JWTParser
    app_utils_module.jwt_parser = app_jwt_parser_module
    app_module.utils = app_utils_module

    return {
        "curl_cffi": curl_cffi_module,
        "curl_cffi.requests": curl_cffi_requests_module,
        "sqlalchemy": sqlalchemy_module,
        "sqlalchemy.ext": sqlalchemy_ext_module,
        "sqlalchemy.ext.asyncio": sqlalchemy_ext_asyncio_module,
        "app": app_module,
        "app.utils": app_utils_module,
        "app.utils.jwt_parser": app_jwt_parser_module,
    }


class MigrationDeletionGuardTests(unittest.TestCase):
    def test_legacy_service_file_is_deleted(self):
        legacy_module_filename = "_".join(("codex", "register", "service.py"))
        legacy_service_path = Path(__file__).resolve().parent / legacy_module_filename
        self.assertFalse(
            legacy_service_path.exists(),
            f"Expected legacy service file to be deleted: {legacy_service_path}",
        )


class ChatGPTRegisterContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._module_patch = patch.dict(sys.modules, _build_chatgpt_import_stubs())
        self._module_patch.start()
        sys.modules.pop("chatgpt", None)

        from chatgpt import ChatGPTService

        self.ChatGPTService = ChatGPTService

    def tearDown(self):
        sys.modules.pop("chatgpt", None)
        self._module_patch.stop()

    def _valid_register_input(self):
        return {
            "mail_worker_base_url": "https://mail.example.com",
            "mail_worker_token": "token",
            "fixed_email": "user@example.com",
            "fixed_password": "pw-123456",
            "mail_domain": "example.com",
        }

    async def test_register_response_contains_fixed_top_level_keys(self):
        service = self.ChatGPTService()
        result = await service.register({"mail_worker_base_url": "x"})
        self.assertEqual(
            set(result.keys()),
            {"success", "status_code", "data", "error", "error_code"},
        )

    async def test_register_success_payload_contains_identifier(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "a@b.com",
                        "account_id": "123",
                        "access_token": "at",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            result = await service.register(
                {
                    "mail_worker_base_url": "x",
                    "mail_worker_token": "y",
                    "fixed_email": "a@b.com",
                    "fixed_password": "pw",
                    "mail_domain": "b.com",
                },
                identifier="acc_123",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["identifier"], "acc_123")

    async def test_register_then_get_members_uses_returned_identifier_without_relogin(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "a@b.com",
                        "identifier": "acc_123",
                        "account_id": "123",
                        "access_token": "at",
                        "refresh_token": "rt",
                        "id_token": "id",
                        "session_token": "",
                        "expires_at": "x",
                        "plan_type": "",
                        "organization_id": "",
                        "workspace_id": "",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            reg = await service.register(
                {
                    "mail_worker_base_url": "x",
                    "mail_worker_token": "y",
                    "fixed_email": "a@b.com",
                    "mail_domain": "b.com",
                }
            )

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"items": [], "total": 0},
                    "error": None,
                }
            ),
        ) as mocked:
            await service.get_members(
                reg["data"]["access_token"],
                reg["data"]["account_id"],
                db_session=None,
                identifier=reg["data"]["identifier"],
            )

        self.assertEqual(mocked.await_args.kwargs["identifier"], "acc_123")

    async def test_register_input_invalid_when_mail_worker_base_url_missing_or_blank(self):
        service = self.ChatGPTService()

        test_cases = (
            {"mail_worker_token": "token", "fixed_email": "user@example.com"},
            {
                "mail_worker_base_url": "   ",
                "mail_worker_token": "token",
                "fixed_email": "user@example.com",
            },
        )

        for register_input in test_cases:
            with self.subTest(register_input=register_input):
                result = await service.register(register_input)
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_input_invalid_when_mail_worker_token_missing(self):
        service = self.ChatGPTService()

        result = await service.register(
            {
                "mail_worker_base_url": "https://mail.example.com",
                "fixed_email": "user@example.com",
            }
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_input_invalid_when_mail_domain_missing_without_fixed_email(self):
        service = self.ChatGPTService()

        result = await service.register(
            {
                "mail_worker_base_url": "https://mail.example.com",
                "mail_worker_token": "token",
            }
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_input_invalid_for_non_positive_runtime_values(self):
        service = self.ChatGPTService()
        base_input = {
            "mail_worker_base_url": "https://mail.example.com",
            "mail_worker_token": "token",
            "fixed_email": "user@example.com",
        }

        for field in (
            "register_http_timeout",
            "mail_poll_seconds",
            "mail_poll_max_attempts",
        ):
            invalid_input = dict(base_input)
            invalid_input[field] = 0

            with self.subTest(field=field):
                result = await service.register(invalid_input)
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_uses_build_browser_base_headers(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_build_browser_base_headers",
            wraps=service._build_browser_base_headers,
        ) as mocked_base_headers:
            headers = service._build_auth_headers("access-token")

        mocked_base_headers.assert_called_once()
        self.assertEqual(headers["Authorization"], "Bearer access-token")
        self.assertEqual(headers["Origin"], "https://auth.openai.com")

    async def test_register_uses_build_auth_headers(self):
        service = self.ChatGPTService()

        headers = service._build_auth_headers("token-123", {"X-Test": "1"})

        self.assertEqual(headers["Authorization"], "Bearer token-123")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["X-Test"], "1")
        self.assertEqual(headers["Referer"], "https://auth.openai.com/")

    async def test_register_uses_build_sentinel_headers(self):
        service = self.ChatGPTService()

        headers = service._build_sentinel_headers({"X-Sentinel": "yes"})

        self.assertEqual(headers["Origin"], "https://sentinel.openai.com")
        self.assertEqual(
            headers["Referer"],
            "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
        )
        self.assertEqual(headers["Content-Type"], "text/plain;charset=UTF-8")
        self.assertEqual(headers["X-Sentinel"], "yes")

    async def test_register_non_session_special_requests_go_through_make_request(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "error": None,
                }
            ),
        ) as mocked_make_request:
            result = await service._make_register_request(
                "POST",
                "https://auth.openai.com/api/accounts/user/register",
                {"Content-Type": "application/json"},
                {"username": "u@example.com"},
                db_session=None,
                identifier="acc_123",
                special_session_step=False,
            )

        self.assertTrue(result["success"])
        mocked_make_request.assert_awaited_once()
        self.assertEqual(mocked_make_request.await_args.args[0], "POST")

    async def test_register_maps_start_auth_flow_failure(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 502,
                    "error": "bad gateway",
                }
            ),
        ):
            result = await service._start_auth_flow(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "auth_flow_failed")

    async def test_register_maps_signup_non_200_to_signup_failed(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 409,
                    "error": "email already used",
                }
            ),
        ):
            result = await service._submit_signup(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "signup_failed")

    async def test_register_uses_fallback_when_passwordless_disabled(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 400,
                    "error": "passwordless disabled",
                    "error_code": "passwordless_signup_disabled",
                }
            ),
        ), patch.object(
            service,
            "_submit_signup",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ticket": "signup-fallback"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_submit_signup:
            result = await service._send_otp_with_fallback(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["used_fallback"])
        mocked_submit_signup.assert_awaited_once()

    async def test_register_maps_otp_validate_non_200_to_otp_validate_failed(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 400,
                    "error": "invalid otp",
                }
            ),
        ):
            result = await service._poll_and_validate_otp(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "otp_validate_failed")

    async def test_register_maps_create_account_non_200_to_create_account_failed(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 409,
                    "error": "cannot create account",
                }
            ),
        ):
            result = await service._create_account(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "create_account_failed")

    async def test_register_special_steps_share_single_session_cookie_jar(self):
        service = self.ChatGPTService()
        shared_session = object()
        call_sessions = {}

        async def _side_effect(
            method,
            url,
            headers,
            json_data=None,
            db_session=None,
            identifier="default",
            special_session_step=False,
            session=None,
        ):
            del method, headers, json_data, db_session, identifier, special_session_step
            call_sessions[url] = session
            if "sentinel/chat-requirements" in url:
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "session": shared_session,
                }
            return {
                "success": True,
                "status_code": 200,
                "data": {"ok": True},
            }

        with patch.object(service, "_make_register_request", new=AsyncMock(side_effect=_side_effect)):
            result = await service._run_register_pipeline(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        self.assertIs(
            call_sessions["https://auth.openai.com/api/accounts/check/v4"],
            shared_session,
        )
        self.assertIs(
            call_sessions["https://auth.openai.com/api/accounts/user/register"],
            shared_session,
        )
        self.assertIs(
            call_sessions["https://auth.openai.com/api/passwordless/start"],
            shared_session,
        )

        self.assertIs(
            call_sessions["https://auth.openai.com/api/accounts/create"],
            shared_session,
        )

    async def test_register_pipeline_fallback_calls_submit_signup_once(self):
        service = self.ChatGPTService()
        shared_session = object()

        async def _make_register_request_side_effect(
            method,
            url,
            headers,
            json_data=None,
            db_session=None,
            identifier="default",
            special_session_step=False,
            session=None,
        ):
            del method, headers, json_data, db_session, identifier, special_session_step
            if "sentinel/chat-requirements" in url:
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "session": shared_session,
                }
            if "api/passwordless/start" in url:
                return {
                    "success": False,
                    "status_code": 400,
                    "error": "passwordless disabled",
                    "error_code": "passwordless_signup_disabled",
                    "session": session,
                }
            return {
                "success": True,
                "status_code": 200,
                "data": {"ok": True},
                "session": session,
            }

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(side_effect=_make_register_request_side_effect),
        ), patch.object(
            service,
            "_start_auth_flow",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_submit_signup",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ticket": "signup"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_submit_signup, patch.object(
            service,
            "_poll_and_validate_otp",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_create_account",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"account_id": "acc"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            result = await service._run_register_pipeline(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        mocked_submit_signup.assert_awaited_once()

    async def test_register_token_finalize_success_payload_contains_tokens_and_context(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "a@b.com",
                        "account_id": "123",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_exchange_tokens",
            create=True,
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "access_token": "at",
                        "refresh_token": "rt",
                        "id_token": "id",
                        "session_token": "st",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_enrich_account_context",
            create=True,
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "plan_type": "team",
                        "organization_id": "org_1",
                        "workspace_id": "ws_1",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            result = await service.register(
                {
                    "mail_worker_base_url": "x",
                    "mail_worker_token": "y",
                    "fixed_email": "a@b.com",
                    "fixed_password": "pw",
                    "mail_domain": "b.com",
                },
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["email"], "a@b.com")
        self.assertEqual(result["data"]["account_id"], "123")
        self.assertEqual(result["data"]["identifier"], "acc_123")
        self.assertEqual(result["data"]["access_token"], "at")
        self.assertEqual(result["data"]["refresh_token"], "rt")
        self.assertEqual(result["data"]["id_token"], "id")
        self.assertEqual(result["data"]["session_token"], "st")
        self.assertEqual(result["data"]["expires_at"], "2099-01-01T00:00:00Z")
        self.assertEqual(result["data"]["plan_type"], "team")
        self.assertEqual(result["data"]["organization_id"], "org_1")
        self.assertEqual(result["data"]["workspace_id"], "ws_1")

    async def test_register_uses_token_payload_fallback_when_pipeline_tokens_blank(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "a@b.com",
                        "account_id": "123",
                        "access_token": "",
                        "refresh_token": "",
                        "id_token": "",
                        "session_token": "",
                        "expires_at": "",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_enrich_account_context",
            create=True,
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "plan_type": "",
                        "organization_id": "",
                        "workspace_id": "",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            result = await service.register(
                {
                    "mail_worker_base_url": "x",
                    "mail_worker_token": "y",
                    "fixed_email": "a@b.com",
                    "mail_domain": "b.com",
                    "token_payload": {
                        "access_token": "at_fallback",
                        "refresh_token": "rt_fallback",
                        "id_token": "id_fallback",
                        "session_token": "st_fallback",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertIsNone(result["error"])
        self.assertIsNone(result["error_code"])
        self.assertEqual(result["data"]["access_token"], "at_fallback")
        self.assertEqual(result["data"]["refresh_token"], "rt_fallback")
        self.assertEqual(result["data"]["id_token"], "id_fallback")
        self.assertEqual(result["data"]["session_token"], "st_fallback")
        self.assertEqual(result["data"]["expires_at"], "2099-01-01T00:00:00Z")

    async def test_register_maps_token_exchange_failure_to_token_finalize_failed(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "a@b.com",
                        "account_id": "123",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_exchange_tokens",
            create=True,
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 401,
                    "data": None,
                    "error": "token exchange failed",
                    "error_code": "upstream_failed",
                }
            ),
        ):
            result = await service.register(
                {
                    "mail_worker_base_url": "x",
                    "mail_worker_token": "y",
                    "fixed_email": "a@b.com",
                    "fixed_password": "pw",
                    "mail_domain": "b.com",
                },
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 401)
        self.assertEqual(result["error_code"], "token_finalize_failed")

    async def test_register_enrich_account_context_best_effort_fill_plan_org_workspace(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "get_account_info",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "accounts": [
                        {
                            "account_id": "123",
                            "plan_type": "team",
                            "organization_id": "org_1",
                            "workspace_id": "ws_1",
                        }
                    ],
                    "error": None,
                }
            ),
        ):
            result = await service._enrich_account_context(
                {
                    "access_token": "at",
                    "account_id": "123",
                    "plan_type": "",
                    "organization_id": "",
                    "workspace_id": "",
                },
                db_session=None,
                identifier="acc_123",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["plan_type"], "team")
        self.assertEqual(result["data"]["organization_id"], "org_1")
        self.assertEqual(result["data"]["workspace_id"], "ws_1")

    async def test_register_identifier_can_be_passed_to_get_members_without_relogin(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "a@b.com",
                        "account_id": "123",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_exchange_tokens",
            create=True,
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "access_token": "at",
                        "refresh_token": "rt",
                        "id_token": "id",
                        "session_token": "",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            reg = await service.register(
                {
                    "mail_worker_base_url": "x",
                    "mail_worker_token": "y",
                    "fixed_email": "a@b.com",
                    "fixed_password": "pw",
                    "mail_domain": "b.com",
                }
            )

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"items": [], "total": 0},
                    "error": None,
                }
            ),
        ) as mocked:
            await service.get_members(
                reg["data"]["access_token"],
                reg["data"]["account_id"],
                db_session=None,
                identifier=reg["data"]["identifier"],
            )

        self.assertEqual(mocked.await_args.kwargs["identifier"], "acc_123")

