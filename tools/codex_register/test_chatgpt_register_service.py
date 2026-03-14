import sys
import types
import unittest
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
