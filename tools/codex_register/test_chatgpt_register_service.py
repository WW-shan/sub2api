import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _build_chatgpt_import_stubs() -> dict:
    curl_cffi_module = types.ModuleType("curl_cffi")
    curl_cffi_requests_module = types.ModuleType("curl_cffi.requests")

    class AsyncSession:  # pragma: no cover - import stub
        def __init__(self, *args, **kwargs):
            del args, kwargs

        class _Response:
            status_code = 200
            text = ""

            def json(self):
                return {}

        async def get(self, url, headers=None):
            del url, headers
            return self._Response()

        async def post(self, url, headers=None, json=None, data=None):
            del url, headers, json, data
            return self._Response()

        async def delete(self, url, headers=None, json=None, data=None):
            del url, headers, json, data
            return self._Response()

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

    utils_module = types.ModuleType("utils")
    utils_jwt_parser_module = types.ModuleType("utils.jwt_parser")

    class JWTParser:  # pragma: no cover - import stub
        def extract_email(self, token: str):
            del token
            return None

    app_jwt_parser_module.JWTParser = JWTParser
    app_utils_module.jwt_parser = app_jwt_parser_module
    app_module.utils = app_utils_module

    utils_jwt_parser_module.JWTParser = JWTParser
    utils_module.jwt_parser = utils_jwt_parser_module

    return {
        "curl_cffi": curl_cffi_module,
        "curl_cffi.requests": curl_cffi_requests_module,
        "sqlalchemy": sqlalchemy_module,
        "sqlalchemy.ext": sqlalchemy_ext_module,
        "sqlalchemy.ext.asyncio": sqlalchemy_ext_asyncio_module,
        "app": app_module,
        "app.utils": app_utils_module,
        "app.utils.jwt_parser": app_jwt_parser_module,
        "utils": utils_module,
        "utils.jwt_parser": utils_jwt_parser_module,
    }


class ChatGPTRegisterContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._module_patch = patch.dict(sys.modules, _build_chatgpt_import_stubs())
        self._module_patch.start()
        if "chatgpt" in sys.modules:
            del sys.modules["chatgpt"]

        module = importlib.import_module("chatgpt")
        self.ChatGPTService = getattr(module, "ChatGPTService")

    def tearDown(self):
        sys.modules.pop("chatgpt", None)
        self._module_patch.stop()

    def _register_env(self, **overrides):
        base = {
            "REGISTER_MAIL_DOMAIN": "example.com",
            "REGISTER_MAIL_WORKER_BASE_URL": "https://worker.example.com",
            "REGISTER_MAIL_WORKER_TOKEN": "token",
        }
        base.update(overrides)
        return patch.dict(os.environ, base, clear=True)

    def test_codex_register_service_file_exists_for_workflow_runtime(self):
        service_path = Path(__file__).resolve().parent / "codex_register_service.py"
        self.assertTrue(service_path.exists())

    async def test_register_input_invalid_when_required_env_register_mail_domain_missing(self):
        service = self.ChatGPTService()
        with self._register_env(REGISTER_MAIL_DOMAIN=""):
            result = await service.register()
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_input_invalid_when_required_env_register_mail_worker_base_url_missing(self):
        service = self.ChatGPTService()
        with self._register_env(REGISTER_MAIL_WORKER_BASE_URL=""):
            result = await service.register()
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_input_invalid_when_required_env_register_mail_worker_token_missing(self):
        service = self.ChatGPTService()
        with self._register_env(REGISTER_MAIL_WORKER_TOKEN=""):
            result = await service.register()
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_callback_complete_shortcuts_with_compat_payload(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ), patch.object(
            service,
            "_visit_homepage",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_get_csrf_token",
            new=AsyncMock(return_value=service._success_result({"csrf_token": "csrf"})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=lambda ctx: service._success_result(
                {
                    **(ctx or {}),
                    "register_input": {
                        **dict((ctx or {}).get("register_input") or {}),
                        "fixed_email": "user@example.com",
                        "fixed_password": "pw",
                    },
                }
            ),
        ), patch.object(
            service,
            "_signin_with_email",
            new=AsyncMock(return_value=service._success_result({"authorize_url": "https://auth.openai.com/authorize"})),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://chatgpt.com/a/callback-complete"})),
        ), patch.object(
            service,
            "_create_account_with_info",
            new=AsyncMock(side_effect=AssertionError("create account should not run after callback-complete")),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["identifier"], "acc_123")
        self.assertEqual(result["data"]["email"], "user@example.com")
        self.assertEqual(result["data"]["status"], "completed")

    async def test_register_unknown_path_returns_register_user_failure_immediately(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ), patch.object(
            service,
            "_visit_homepage",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_get_csrf_token",
            new=AsyncMock(return_value=service._success_result({"csrf_token": "csrf"})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=lambda ctx: service._success_result(
                {
                    **(ctx or {}),
                    "register_input": {
                        **dict((ctx or {}).get("register_input") or {}),
                        "fixed_email": "user@example.com",
                        "fixed_password": "pw",
                    },
                }
            ),
        ), patch.object(
            service,
            "_signin_with_email",
            new=AsyncMock(return_value=service._success_result({"authorize_url": "https://auth.openai.com/authorize"})),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://auth.openai.com/unknown-step"})),
        ), patch.object(
            service,
            "_register_user_with_password",
            new=AsyncMock(return_value=service._error_result(400, "signup blocked", "signup_failed")),
        ) as mocked_register_user, patch.object(
            service,
            "_send_otp_email",
            new=AsyncMock(side_effect=AssertionError("send otp should not run when register step fails")),
        ):
            result = await service.register(identifier="acc_123")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "signup_failed")
        mocked_register_user.assert_awaited_once()

    async def test_register_unknown_path_returns_send_otp_failure_immediately(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ), patch.object(
            service,
            "_visit_homepage",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_get_csrf_token",
            new=AsyncMock(return_value=service._success_result({"csrf_token": "csrf"})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=lambda ctx: service._success_result(
                {
                    **(ctx or {}),
                    "register_input": {
                        **dict((ctx or {}).get("register_input") or {}),
                        "fixed_email": "user@example.com",
                        "fixed_password": "pw",
                    },
                }
            ),
        ), patch.object(
            service,
            "_signin_with_email",
            new=AsyncMock(return_value=service._success_result({"authorize_url": "https://auth.openai.com/authorize"})),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://auth.openai.com/unknown-step"})),
        ), patch.object(
            service,
            "_register_user_with_password",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_send_otp_email",
            new=AsyncMock(return_value=service._error_result(429, "otp throttled", "otp_send_failed")),
        ) as mocked_send_otp, patch.object(
            service,
            "_poll_and_validate_otp",
            new=AsyncMock(side_effect=AssertionError("otp poll should not run when send otp fails")),
        ):
            result = await service.register(identifier="acc_123")

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "otp_send_failed")
        mocked_send_otp.assert_awaited_once()

    async def test_register_does_not_short_circuit_on_generic_chatgpt_domain_url(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ), patch.object(
            service,
            "_visit_homepage",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_get_csrf_token",
            new=AsyncMock(return_value=service._success_result({"csrf_token": "csrf"})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=lambda ctx: service._success_result(
                {
                    **(ctx or {}),
                    "register_input": {
                        **dict((ctx or {}).get("register_input") or {}),
                        "fixed_email": "user@example.com",
                        "fixed_password": "pw",
                    },
                }
            ),
        ), patch.object(
            service,
            "_signin_with_email",
            new=AsyncMock(return_value=service._success_result({"authorize_url": "https://auth.openai.com/authorize"})),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://chatgpt.com/some/other/path"})),
        ), patch.object(
            service,
            "_register_user_with_password",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_send_otp_email",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_poll_and_validate_otp",
            new=AsyncMock(return_value=service._success_result({"otp_code": "123456"})),
        ), patch.object(
            service,
            "_create_account_with_info",
            new=AsyncMock(return_value=service._success_result({"callback_url": "https://auth.openai.com/callback?code=ok"})),
        ) as mocked_create_account, patch.object(
            service,
            "_execute_callback",
            new=AsyncMock(return_value=service._success_result({})),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        mocked_create_account.assert_awaited_once()
        self.assertEqual(result["data"]["identifier"], "acc_123")
        self.assertEqual(result["data"]["status"], "completed")

    async def test_register_about_you_path_returns_compat_payload(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ), patch.object(
            service,
            "_visit_homepage",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_get_csrf_token",
            new=AsyncMock(return_value=service._success_result({"csrf_token": "csrf"})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=lambda ctx: service._success_result(
                {
                    **(ctx or {}),
                    "register_input": {
                        **dict((ctx or {}).get("register_input") or {}),
                        "fixed_email": "user@example.com",
                        "fixed_password": "pw",
                    },
                }
            ),
        ), patch.object(
            service,
            "_signin_with_email",
            new=AsyncMock(return_value=service._success_result({"authorize_url": "https://auth.openai.com/authorize"})),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://auth.openai.com/about-you"})),
        ), patch.object(
            service,
            "_create_account_with_info",
            new=AsyncMock(return_value=service._success_result({"callback_url": "https://auth.openai.com/callback?code=ok"})),
        ) as mocked_create_account, patch.object(
            service,
            "_execute_callback",
            new=AsyncMock(return_value=service._success_result({})),
        ) as mocked_execute_callback:
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        mocked_create_account.assert_awaited_once()
        mocked_execute_callback.assert_awaited_once()
        self.assertEqual(result["data"]["status"], "completed")

    async def test_register_then_get_members_uses_returned_identifier_without_relogin(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ), patch.object(
            service,
            "_visit_homepage",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_get_csrf_token",
            new=AsyncMock(return_value=service._success_result({"csrf_token": "csrf"})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=lambda ctx: service._success_result(
                {
                    **(ctx or {}),
                    "register_input": {
                        **dict((ctx or {}).get("register_input") or {}),
                        "fixed_email": "a@b.com",
                        "fixed_password": "pw",
                    },
                }
            ),
        ), patch.object(
            service,
            "_signin_with_email",
            new=AsyncMock(return_value=service._success_result({"authorize_url": "https://auth.openai.com/authorize"})),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://chatgpt.com/a/callback-complete"})),
        ):
            reg = await service.register(identifier="acc_123")

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

    async def test_prepare_identity_generates_email_from_register_mail_domain(self):
        service = self.ChatGPTService()

        with self._register_env(
            REGISTER_MAIL_DOMAIN="wwcloud.me",
            REGISTER_MAIL_WORKER_BASE_URL="https://worker.example.com",
            REGISTER_MAIL_WORKER_TOKEN="token",
        ):
            runtime_context_result = service._build_runtime_context("acc_123")

        self.assertTrue(runtime_context_result["success"])
        runtime_register_input = runtime_context_result["data"]["register_input"]

        result = service._prepare_identity({"register_input": runtime_register_input})

        self.assertTrue(result["success"])
        prepared_input = result["data"]["register_input"]
        self.assertTrue(prepared_input["resolved_email"].endswith("@wwcloud.me"))
        self.assertTrue(prepared_input["fixed_password"])


if __name__ == "__main__":
    unittest.main()
