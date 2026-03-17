import base64
import importlib
import json
import os
import re
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
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

        def decode_token(self, token: str):
            del token
            return {}

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

    async def test_prepare_identity_generates_password_with_minimum_length(self):
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
        generated_password = str(result["data"]["register_input"].get("fixed_password") or "")
        self.assertGreaterEqual(len(generated_password), 12)

    async def test_validate_otp_code_uses_email_otp_validate_endpoint(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(return_value=service._success_result({})),
        ) as mocked_make_register_request:
            result = await service._validate_otp_code(
                "user@example.com",
                "123456",
                db_session=None,
                identifier="acc_123",
            )

        self.assertTrue(result["success"])
        called_url = mocked_make_register_request.await_args.args[1]
        called_json = mocked_make_register_request.await_args.args[3]
        self.assertEqual(called_url, "https://auth.openai.com/api/accounts/email-otp/validate")
        self.assertEqual(called_json, {"code": "123456"})

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

    async def test_register_create_account_uses_letters_and_spaces_only_name(self):
        service = self.ChatGPTService()

        captured = {}

        async def _capture_create_account(name, birthdate, db_session, identifier, proxy=None):
            captured["name"] = name
            del birthdate, db_session, identifier, proxy
            return service._success_result({"callback_url": "https://auth.openai.com/callback?code=ok"})

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
            new=AsyncMock(side_effect=_capture_create_account),
        ), patch.object(
            service,
            "_execute_callback",
            new=AsyncMock(return_value=service._success_result({})),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        self.assertIn("name", captured)
        self.assertRegex(captured["name"], r"^[A-Za-z ]+$")

    async def test_register_persists_tokens_from_callback_session_response(self):
        service = self.ChatGPTService()

        async def _make_request(*args, **kwargs):
            del kwargs
            url = args[1] if len(args) > 1 else ""
            if str(url) == "https://chatgpt.com/api/auth/session":
                return service._success_result(
                    {
                        "accessToken": "at_token",
                        "refreshToken": "rt_token",
                        "sessionToken": "st_token",
                        "accounts": {"acc_123": {}},
                        "currentAccountId": "acc_123",
                    }
                )
            return service._success_result({})

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
            "_make_request",
            new=AsyncMock(side_effect=_make_request),
        ), patch.object(
            service,
            "_create_account_with_info",
            new=AsyncMock(return_value=service._success_result({"callback_url": "https://auth.openai.com/callback?code=ok"})),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        payload = result["data"]
        self.assertEqual(payload["account_id"], "acc_123")
        self.assertEqual(payload["access_token"], "at_token")
        self.assertEqual(payload["refresh_token"], "rt_token")
        self.assertEqual(payload["session_token"], "st_token")

    async def test_collect_register_session_tokens_falls_back_to_oauth_exchange(self):
        service = self.ChatGPTService()

        def _decode_token(token):
            del token
            return {
                "https://api.openai.com/auth": {
                    "chatgpt_account_id": "acc_from_jwt",
                }
            }

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=SimpleNamespace(cookies=[])),
        ), patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "accessToken": "at_token",
                        "sessionToken": "st_token",
                        "accounts": {"acc_fallback": {}},
                        "currentAccountId": "acc_fallback",
                    }
                )
            ),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "refresh_token": "rt_from_oauth",
                        "id_token": "id_token_value",
                    }
                )
            ),
        ), patch.object(
            service.jwt_parser,
            "decode_token",
            side_effect=_decode_token,
        ):
            payload = await service._collect_register_session_tokens(
                db_session=None,
                identifier="acc_123",
                proxy="",
                callback_url="https://chatgpt.com/api/auth/callback/openai?code=auth_code_123",
            )

        self.assertEqual(payload["access_token"], "at_token")
        self.assertEqual(payload["refresh_token"], "rt_from_oauth")
        self.assertEqual(payload["session_token"], "st_token")
        self.assertEqual(payload["account_id"], "acc_from_jwt")
        self.assertEqual(payload["id_token"], "id_token_value")

    async def test_register_callback_complete_collects_tokens(self):
        service = self.ChatGPTService()

        async def _make_request(*args, **kwargs):
            del kwargs
            url = args[1] if len(args) > 1 else ""
            if str(url) == "https://chatgpt.com/api/auth/session":
                return service._success_result(
                    {
                        "accessToken": "at_cb",
                        "refreshToken": "rt_cb",
                        "sessionToken": "st_cb",
                        "currentAccountId": "acc_cb",
                    }
                )
            return service._success_result({})

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
            new=AsyncMock(
                return_value=service._success_result(
                    {"final_url": "https://chatgpt.com/a/callback-complete?code=cbcode123"}
                )
            ),
        ), patch.object(
            service,
            "_make_request",
            new=AsyncMock(side_effect=_make_request),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        payload = result["data"]
        self.assertEqual(payload["access_token"], "at_cb")
        self.assertEqual(payload["refresh_token"], "rt_cb")
        self.assertEqual(payload["session_token"], "st_cb")
        self.assertEqual(payload["account_id"], "acc_cb")

    async def test_collect_register_session_tokens_prefers_oauth_refresh_token_when_present(self):
        service = self.ChatGPTService()

        class _Cookie:
            name = "oai-client-auth-session"
            value = ""

        cookie_payload = {
            "workspaces": [
                {
                    "code_verifier": "pkce-verifier-123",
                }
            ]
        }
        encoded_payload = base64.urlsafe_b64encode(json.dumps(cookie_payload).encode("utf-8")).decode("ascii").rstrip("=")
        _Cookie.value = encoded_payload

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=SimpleNamespace(cookies=[_Cookie()])),
        ), patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "accessToken": "at_token",
                        "refreshToken": "rt_session",
                        "sessionToken": "st_token",
                        "currentAccountId": "acc_session",
                    }
                )
            ),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "refreshToken": "rt_oauth",
                        "idToken": "id_oauth",
                    }
                )
            ),
        ) as mocked_exchange:
            payload = await service._collect_register_session_tokens(
                db_session=None,
                identifier="acc_123",
                proxy="",
                callback_url="https://chatgpt.com/api/auth/callback/openai?code=cbcode123",
            )

        self.assertEqual(payload["refresh_token"], "rt_oauth")
        self.assertEqual(payload["id_token"], "id_oauth")
        exchange_form_data = mocked_exchange.await_args.kwargs.get("form_data")
        self.assertEqual(exchange_form_data.get("code_verifier"), "pkce-verifier-123")

    async def test_collect_register_session_tokens_uses_code_verifier_from_auth_session_top_level(self):
        service = self.ChatGPTService()

        class _Cookie:
            name = "oai-client-auth-session"
            value = ""

        cookie_payload = {
            "code_verifier": "pkce-top-level-verifier-789",
            "workspaces": [
                {
                    "id": "ws_1",
                }
            ],
        }
        encoded_payload = base64.urlsafe_b64encode(json.dumps(cookie_payload).encode("utf-8")).decode("ascii").rstrip("=")
        _Cookie.value = encoded_payload

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=SimpleNamespace(cookies=[_Cookie()])),
        ), patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "accessToken": "at_token",
                        "sessionToken": "st_token",
                        "currentAccountId": "acc_session",
                    }
                )
            ),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(return_value=service._success_result({"refresh_token": "rt_oauth"})),
        ) as mocked_exchange:
            payload = await service._collect_register_session_tokens(
                db_session=None,
                identifier="acc_123",
                proxy="",
                callback_url="https://chatgpt.com/api/auth/callback/openai?code=cbcode123",
            )

        self.assertEqual(payload["refresh_token"], "rt_oauth")
        exchange_form_data = mocked_exchange.await_args.kwargs.get("form_data")
        self.assertEqual(exchange_form_data.get("code_verifier"), "pkce-top-level-verifier-789")


    async def test_collect_register_session_tokens_recovers_code_via_workspace_select_when_callback_has_no_code(self):
        service = self.ChatGPTService()

        class _Cookie:
            name = "oai-client-auth-session"
            value = ""

        cookie_payload = {
            "workspaces": [
                {
                    "id": "ws_123",
                    "code_verifier": "pkce-ws-verifier-456",
                }
            ]
        }
        encoded_payload = base64.urlsafe_b64encode(json.dumps(cookie_payload).encode("utf-8")).decode("ascii").rstrip("=")
        _Cookie.value = encoded_payload

        async def _make_register_request(method, url, headers, *args, **kwargs):
            del headers, args
            if method == "POST" and str(url) == "https://auth.openai.com/api/accounts/workspace/select":
                self.assertEqual(kwargs.get("json_data"), {"workspace_id": "ws_123"})
                return service._success_result(
                    {
                        "continue_url": "https://chatgpt.com/api/auth/callback/openai?code=ws_code_123",
                    }
                )
            if method == "POST" and str(url) == "https://auth.openai.com/oauth/token":
                form_data = kwargs.get("form_data") or {}
                self.assertEqual(form_data.get("code"), "ws_code_123")
                self.assertEqual(form_data.get("code_verifier"), "pkce-ws-verifier-456")
                return service._success_result(
                    {
                        "refresh_token": "rt_ws",
                        "id_token": "id_ws",
                    }
                )
            return service._error_result(404, "unexpected request", "unexpected_request")

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=SimpleNamespace(cookies=[_Cookie()])),
        ), patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "accessToken": "at_token",
                        "sessionToken": "st_token",
                        "currentAccountId": "acc_session",
                    }
                )
            ),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(side_effect=_make_register_request),
        ):
            payload = await service._collect_register_session_tokens(
                db_session=None,
                identifier="acc_123",
                proxy="",
                callback_url="https://chatgpt.com/a/callback-complete",
            )

        self.assertEqual(payload.get("refresh_token"), "rt_ws")
        self.assertEqual(payload.get("id_token"), "id_ws")

    async def test_collect_register_session_tokens_uses_dynamic_client_id_from_signin_authorize_url(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "accessToken": "at_session",
                        "sessionToken": "st_session",
                        "currentAccountId": "acc_session",
                    }
                )
            ),
        ), patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=SimpleNamespace(cookies=[])),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(return_value=service._success_result({"refresh_token": "rt_oauth"})),
        ) as mocked_exchange:
            payload = await service._collect_register_session_tokens(
                db_session=None,
                identifier="acc_123",
                proxy="",
                callback_url="https://chatgpt.com/api/auth/callback/openai?code=cbcode123",
                oauth_client_id="app_X8zY6vW2pQ9tR3dE7nK1jL5gH",
            )

        self.assertEqual(payload["refresh_token"], "rt_oauth")
        exchange_form_data = mocked_exchange.await_args.kwargs.get("form_data")
        self.assertEqual(exchange_form_data.get("client_id"), "app_X8zY6vW2pQ9tR3dE7nK1jL5gH")

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


    async def test_register_unknown_path_uses_dynamic_client_id_for_token_exchange(self):
        service = self.ChatGPTService()
        captured = {}

        async def _capture_tokens(db_session, identifier, proxy="", callback_url="", oauth_client_id=""):
            del db_session, identifier, proxy, callback_url
            captured["oauth_client_id"] = oauth_client_id
            return {
                "access_token": "at_final",
                "refresh_token": "rt_final",
                "session_token": "st_final",
                "account_id": "acc_final",
            }

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
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "authorize_url": "https://auth.openai.com/api/accounts/authorize?client_id=app_X8zY6vW2pQ9tR3dE7nK1jL5gH"
                    }
                )
            ),
        ), patch.object(
            service,
            "_authorize_and_redirect",
            new=AsyncMock(return_value=service._success_result({"final_url": "https://auth.openai.com/api/accounts/authorize"})),
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
            new=AsyncMock(
                return_value=service._success_result(
                    {
                        "callback_url": "https://chatgpt.com/api/auth/callback/openai?code=cbcode123"
                    }
                )
            ),
        ), patch.object(
            service,
            "_execute_callback",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_collect_register_session_tokens",
            new=AsyncMock(side_effect=_capture_tokens),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        self.assertEqual(captured["oauth_client_id"], "app_X8zY6vW2pQ9tR3dE7nK1jL5gH")


if __name__ == "__main__":
    unittest.main()
