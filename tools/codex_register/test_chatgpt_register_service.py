import base64
import json
import os
import sys
import types
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, patch


def _build_chatgpt_import_stubs() -> dict:
    curl_cffi_module = types.ModuleType("curl_cffi")
    curl_cffi_requests_module = types.ModuleType("curl_cffi.requests")

    class AsyncSession:  # pragma: no cover - import stub
        def __init__(self, *args, **kwargs):
            del args, kwargs

        class _Response:
            status_code = 200
            text = "fl=29f88\nh=www.cloudflare.com\nip=127.0.0.1\nts=1\nvisit_scheme=https\nuag=test\ncolo=SJC\nloc=US\ntls=TLSv1.3\n"

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

    def _register_env(self, **overrides):
        base = {
            "REGISTER_MAIL_DOMAIN": "example.com",
            "REGISTER_MAIL_WORKER_BASE_URL": "https://worker.example.com",
            "REGISTER_MAIL_WORKER_TOKEN": "token",
        }
        base.update(overrides)
        return patch.dict(os.environ, base, clear=True)

    def _valid_register_input(self):
        return {
            "mail_worker_base_url": "https://mail.example.com",
            "mail_worker_token": "token",
            "fixed_email": "user@example.com",
            "fixed_password": "pw-123456",
            "mail_domain": "example.com",
        }

    async def test_register_reads_runtime_from_env(self):
        service = self.ChatGPTService()

        def _prepare_identity_stub(ctx):
            register_input = dict((ctx or {}).get("register_input") or {})
            register_input["fixed_email"] = "a@b.com"
            register_input["fixed_password"] = "pw"
            patched_ctx = dict(ctx or {})
            patched_ctx["register_input"] = register_input
            return service._success_result(patched_ctx)

        with self._register_env(), patch.object(
            service,
            "_check_network_and_region",
            new=AsyncMock(return_value=service._success_result({})),
        ), patch.object(
            service,
            "_prepare_identity",
            new=_prepare_identity_stub,
        ), patch.object(
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
        ), patch.object(
            service,
            "_finalize_registration_result",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"identifier": "acc_123"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_finalize, patch.object(
            service,
            "_resolve_register_proxy",
            new=AsyncMock(return_value=""),
        ):
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        runtime_register_input = mocked_finalize.await_args.kwargs["register_input"]
        self.assertEqual(runtime_register_input["mail_domain"], "example.com")
        self.assertEqual(
            runtime_register_input["mail_worker_base_url"],
            "https://worker.example.com",
        )
        self.assertEqual(runtime_register_input["mail_worker_token"], "token")
        self.assertEqual(runtime_register_input["register_http_timeout"], 15)
        self.assertEqual(runtime_register_input["mail_poll_seconds"], 3)
        self.assertEqual(runtime_register_input["mail_poll_max_attempts"], 40)
        self.assertEqual(runtime_register_input["fixed_email"], "a@b.com")
        self.assertEqual(runtime_register_input["fixed_password"], "pw")

    async def test_register_input_invalid_when_required_env_register_mail_domain_missing(self):
        service = self.ChatGPTService()

        with self._register_env(REGISTER_MAIL_DOMAIN=""):
            result = await service.register()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "input_invalid")

    async def test_register_success_payload_contains_identifier(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
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
            result = await service.register(identifier="acc_123")

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["identifier"], "acc_123")

    async def test_register_then_get_members_uses_returned_identifier_without_relogin(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
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
            reg = await service.register()

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

    async def test_resolve_register_proxy_prefers_register_input_over_settings_service(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_resolve_settings_service_proxy",
            new=AsyncMock(return_value="http://settings-proxy.example:9000"),
        ) as mocked_settings_proxy:
            resolved_proxy = await service._resolve_register_proxy(
                {
                    "proxy": "http://input-proxy.example:8000",
                },
                db_session=None,
            )

        self.assertEqual(resolved_proxy, "http://input-proxy.example:8000")
        mocked_settings_proxy.assert_not_awaited()

    async def test_resolve_register_proxy_falls_back_to_settings_service(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_resolve_settings_service_proxy",
            new=AsyncMock(return_value="http://settings-proxy.example:9000"),
        ) as mocked_settings_proxy:
            resolved_proxy = await service._resolve_register_proxy(
                {
                    "fixed_email": "user@example.com",
                },
                db_session=None,
            )

        self.assertEqual(resolved_proxy, "http://settings-proxy.example:9000")
        mocked_settings_proxy.assert_awaited_once()

    async def test_resolve_register_proxy_returns_empty_when_settings_service_unavailable(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_resolve_settings_service_proxy",
            new=AsyncMock(side_effect=RuntimeError("settings unavailable")),
        ):
            resolved_proxy = await service._resolve_register_proxy(
                {
                    "fixed_email": "user@example.com",
                },
                db_session=None,
            )

        self.assertEqual(resolved_proxy, "")

    async def test_check_network_and_region_uses_resolved_proxy_for_session_creation(self):
        service = self.ChatGPTService()

        trace_session = types.SimpleNamespace(
            get=AsyncMock(
                return_value=types.SimpleNamespace(
                    status_code=200,
                    text="fl=29f88\nloc=US\n",
                )
            )
        )

        with patch.object(
            service,
            "_create_session",
            new=AsyncMock(return_value=trace_session),
        ) as mocked_create_session:
            result = await service._check_network_and_region(
                {
                    "register_input": {
                        **self._valid_register_input(),
                        "resolved_proxy": "http://register-proxy.example:8080",
                    },
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        mocked_create_session.assert_awaited_once_with(
            None,
            "http://register-proxy.example:8080",
        )

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

    async def test_submit_signup_uses_password_register_referer_and_password(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request:
            result = await service._submit_signup(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        mocked_make_register_request.assert_awaited_once()
        self.assertEqual(
            mocked_make_register_request.await_args.args[1],
            "https://auth.openai.com/api/accounts/user/register",
        )
        headers = mocked_make_register_request.await_args.args[2]
        self.assertEqual(headers["Referer"], "https://auth.openai.com/create-account/password")
        body = (
            mocked_make_register_request.await_args.kwargs.get("json_data")
            if "json_data" in mocked_make_register_request.await_args.kwargs
            else mocked_make_register_request.await_args.args[3]
        )
        self.assertTrue(bool(str(body.get("password") or "").strip()))

    async def test_send_otp_uses_email_otp_send_endpoint_without_passwordless(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"delivery": "queued"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request, patch.object(
            service,
            "_submit_signup",
            new=AsyncMock(),
        ) as mocked_submit_signup:
            result = await service._send_otp_with_fallback(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["used_fallback"])
        mocked_submit_signup.assert_not_awaited()
        mocked_make_register_request.assert_awaited_once()
        self.assertEqual(mocked_make_register_request.await_args.args[0], "GET")
        self.assertEqual(
            mocked_make_register_request.await_args.args[1],
            "https://auth.openai.com/api/accounts/email-otp/send",
        )

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
                    "otp_code": "123456",
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
            proxy=None,
        ):
            del method, headers, json_data, db_session, identifier, special_session_step, proxy
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
                    "otp_code": "123456",
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
            call_sessions["https://auth.openai.com/api/accounts/email-otp/send"],
            shared_session,
        )

        self.assertIs(
            call_sessions["https://auth.openai.com/api/accounts/create"],
            shared_session,
        )

    async def test_register_pipeline_calls_submit_signup_once(self):
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
            proxy=None,
        ):
            del method, headers, json_data, db_session, identifier, special_session_step, proxy
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

        with self._register_env(), patch.object(
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
            result = await service.register()

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

        with self._register_env(), patch.object(
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
        ), patch.object(
            service,
            "_exchange_tokens",
            create=True,
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "access_token": "at_fallback",
                        "refresh_token": "rt_fallback",
                        "id_token": "id_fallback",
                        "session_token": "st_fallback",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_exchange_tokens:
            result = await service.register()

        mocked_exchange_tokens.assert_awaited_once()
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

        with self._register_env(), patch.object(
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
            result = await service.register()

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

        with self._register_env(), patch.object(
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
            reg = await service.register()

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

        result = service._prepare_identity(
            {
                "register_input": runtime_register_input,
            }
        )

        self.assertTrue(result["success"])
        prepared_input = result["data"]["register_input"]
        self.assertTrue(prepared_input["resolved_email"].endswith("@wwcloud.me"))
        self.assertTrue(prepared_input["fixed_password"])

    async def test_register_special_steps_use_resolved_email(self):
        service = self.ChatGPTService()
        resolved_email = "generated@example.com"
        ctx = {
            "register_input": {
                "fixed_email": "",
                "resolved_email": resolved_email,
                "fixed_password": "pw-123456",
            },
            "db_session": None,
            "identifier": "acc_123",
            "otp_code": "123456",
            "session": object(),
        }

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request:
            await service._start_auth_flow(ctx)
            await service._submit_signup(ctx)
            await service._send_otp_with_fallback(ctx)
            await service._poll_and_validate_otp(ctx)
            await service._create_account(ctx)

        request_payloads = [
            (
                call.kwargs.get("json_data")
                if "json_data" in call.kwargs
                else (call.args[3] if len(call.args) > 3 else None)
            )
            for call in mocked_make_register_request.await_args_list
        ]
        self.assertEqual(request_payloads[0]["username"], resolved_email)
        self.assertEqual(request_payloads[1]["username"], resolved_email)
        self.assertIsNone(request_payloads[2])
        self.assertEqual(request_payloads[3]["username"], resolved_email)
        self.assertEqual(request_payloads[4]["email"], resolved_email)

    async def test_register_special_session_step_uses_direct_session_request_path(self):
        service = self.ChatGPTService()

        class _Response:
            status_code = 200
            text = ""

            def json(self):
                return {"ok": True}

        special_session = types.SimpleNamespace(
            post=AsyncMock(return_value=_Response()),
            get=AsyncMock(return_value=_Response()),
            delete=AsyncMock(return_value=_Response()),
        )

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(side_effect=AssertionError("special steps should bypass _make_request")),
        ):
            result = await service._make_register_request(
                "POST",
                "https://auth.openai.com/api/accounts/check/v4",
                {"Content-Type": "application/json"},
                {"username": "u@example.com"},
                db_session=None,
                identifier="acc_123",
                special_session_step=True,
                session=special_session,
            )

        self.assertTrue(result["success"])
        self.assertIs(result.get("session"), special_session)
        special_session.post.assert_awaited_once()

    async def test_register_send_signup_fallback_otp_reuses_email_otp_send_endpoint(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"delivery": "queued"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request:
            result = await service._send_signup_fallback_otp(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        mocked_make_register_request.assert_awaited_once()
        self.assertEqual(mocked_make_register_request.await_args.args[0], "GET")
        self.assertEqual(
            mocked_make_register_request.await_args.args[1],
            "https://auth.openai.com/api/accounts/email-otp/send",
        )

    async def test_make_request_maps_timeout_to_network_timeout(self):
        service = self.ChatGPTService()
        service.MAX_RETRIES = 1

        failing_session = types.SimpleNamespace(
            post=AsyncMock(side_effect=TimeoutError("request timeout"))
        )

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=failing_session),
        ):
            result = await service._make_request(
                "POST",
                "https://auth.openai.com/api/accounts/check/v4",
                {"Content-Type": "application/json"},
                json_data={"username": "u@example.com"},
                db_session=None,
                identifier="acc_123",
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 0)
        self.assertEqual(result.get("error_code"), "network_timeout")

    async def test_make_request_maps_connection_error_to_network_error(self):
        service = self.ChatGPTService()
        service.MAX_RETRIES = 1

        failing_session = types.SimpleNamespace(
            post=AsyncMock(side_effect=ConnectionError("connection refused"))
        )

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=failing_session),
        ):
            result = await service._make_request(
                "POST",
                "https://auth.openai.com/api/accounts/check/v4",
                {"Content-Type": "application/json"},
                json_data={"username": "u@example.com"},
                db_session=None,
                identifier="acc_123",
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 0)
        self.assertEqual(result.get("error_code"), "network_error")


    async def test_register_blocks_on_network_region_check_failure(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_check_network_and_region",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 451,
                    "data": None,
                    "error": "region blocked: IR",
                    "error_code": "network_error",
                }
            ),
        ), patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(side_effect=AssertionError("pipeline should not run")),
        ):
            result = await service.register()

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 451)
        self.assertEqual(result["error_code"], "network_error")

    async def test_register_prepare_identity_result_is_used_by_pipeline(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_check_network_and_region",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {},
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_prepare_identity",
            return_value={
                "success": True,
                "status_code": 200,
                "data": {
                    "register_input": {
                        **self._valid_register_input(),
                        "resolved_email": "resolved@example.com",
                        "fixed_email": "resolved@example.com",
                        "fixed_password": "pw-123456",
                    }
                },
                "error": None,
                "error_code": None,
            },
        ) as mocked_prepare_identity, patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "identifier": "acc_123",
                        "email": "resolved@example.com",
                        "account_id": "123",
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
        ) as mocked_pipeline, patch.object(
            service,
            "_enrich_account_context",
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
            result = await service.register()

        self.assertTrue(result["success"])
        mocked_prepare_identity.assert_called_once()
        passed_ctx = mocked_pipeline.await_args.args[0]
        self.assertEqual(
            passed_ctx["register_input"]["resolved_email"],
            "resolved@example.com",
        )

    async def test_poll_and_validate_otp_invokes_mail_worker_when_otp_missing(self):
        service = self.ChatGPTService()
        ctx = {
            "register_input": self._valid_register_input(),
            "db_session": None,
            "identifier": "acc_123",
            "session": object(),
        }

        with patch.object(
            service,
            "_poll_otp_from_mail_worker",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"otp_code": "654321"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_poll_worker, patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request:
            result = await service._poll_and_validate_otp(ctx)

        self.assertTrue(result["success"])
        mocked_poll_worker.assert_awaited_once()
        validate_payload = (
            mocked_make_register_request.await_args.kwargs.get("json_data")
            if "json_data" in mocked_make_register_request.await_args.kwargs
            else mocked_make_register_request.await_args.args[3]
        )
        self.assertEqual(validate_payload["otp_code"], "654321")

    async def test_step_wrappers_preserve_network_error_codes_from_request_layer(self):
        service = self.ChatGPTService()
        base_ctx = {
            "register_input": self._valid_register_input(),
            "db_session": None,
            "identifier": "acc_123",
            "session": object(),
            "otp_code": "123456",
        }

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 0,
                    "error": "request timeout",
                    "error_code": "network_timeout",
                }
            ),
        ):
            start_result = await service._start_auth_flow(dict(base_ctx))
            send_result = await service._send_otp_with_fallback(dict(base_ctx))
            validate_result = await service._poll_and_validate_otp(dict(base_ctx))
            create_result = await service._create_account(dict(base_ctx))

        self.assertEqual(start_result["error_code"], "network_timeout")
        self.assertEqual(send_result["error_code"], "network_timeout")
        self.assertEqual(validate_result["error_code"], "network_timeout")
        self.assertEqual(create_result["error_code"], "network_timeout")

    async def test_build_register_oauth_url_contains_expected_query(self):
        service = self.ChatGPTService()

        oauth_url = service._build_register_oauth_url(
            {
                "authorize_endpoint": "https://auth.openai.com/oauth/authorize",
                "client_id": "client-123",
                "redirect_uri": "https://chatgpt.com/a/callback",
                "scope": "openid profile email",
                "code_challenge": "challenge-abc",
                "code_challenge_method": "S256",
                "audience": "chatgpt",
            },
            oauth_state="state-xyz",
        )

        parsed = urlparse(oauth_url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "auth.openai.com")
        self.assertEqual(parsed.path, "/oauth/authorize")
        self.assertEqual(query["client_id"][0], "client-123")
        self.assertEqual(query["redirect_uri"][0], "https://chatgpt.com/a/callback")
        self.assertEqual(query["scope"][0], "openid profile email")
        self.assertEqual(query["code_challenge"][0], "challenge-abc")
        self.assertEqual(query["code_challenge_method"][0], "S256")
        self.assertEqual(query["state"][0], "state-xyz")

    async def test_start_auth_flow_uses_pipeline_oauth_state_and_returns_authorize_url(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"ticket": "ok"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request:
            result = await service._start_auth_flow(
                {
                    "register_input": {
                        **self._valid_register_input(),
                        "authorize_endpoint": "https://auth.openai.com/oauth/authorize",
                        "client_id": "client-1",
                        "redirect_uri": "https://chatgpt.com/a/callback",
                    },
                    "db_session": None,
                    "identifier": "acc_123",
                    "oauth_state": "state-pipeline-123",
                    "session": object(),
                }
            )

        self.assertTrue(result["success"])
        payload = (
            mocked_make_register_request.await_args.kwargs.get("json_data")
            if "json_data" in mocked_make_register_request.await_args.kwargs
            else mocked_make_register_request.await_args.args[3]
        )
        self.assertEqual(payload["state"], "state-pipeline-123")

        returned_data = result["data"]
        self.assertEqual(returned_data["oauth_state"], "state-pipeline-123")
        authorize_query = parse_qs(urlparse(returned_data["authorize_url"]).query)
        self.assertEqual(authorize_query["state"][0], "state-pipeline-123")

    async def test_exchange_tokens_uses_form_post_contract_for_token_request(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "access_token": "at_from_callback",
                        "refresh_token": "rt_from_callback",
                        "id_token": "id_from_callback",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_request:
            result = await service._exchange_tokens(
                pipeline_data={
                    "callback_url": "https://auth.openai.com/callback?code=cb-code-789&state=st1"
                },
                register_input={
                    "token_endpoint": "https://auth.openai.com/oauth/token",
                    "client_id": "client-1",
                    "redirect_uri": "https://chatgpt.com/a/callback",
                    "code_verifier": "verifier-1",
                },
                db_session=None,
                identifier="acc_123",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["access_token"], "at_from_callback")
        mocked_make_request.assert_awaited_once()
        await_call = mocked_make_request.await_args
        self.assertEqual(await_call.args[0], "POST")
        self.assertEqual(await_call.args[1], "https://auth.openai.com/oauth/token")
        self.assertEqual(await_call.args[2]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(await_call.kwargs["form_data"]["code"], "cb-code-789")
        self.assertEqual(await_call.kwargs["form_data"]["client_id"], "client-1")
        self.assertEqual(await_call.kwargs["form_data"]["redirect_uri"], "https://chatgpt.com/a/callback")
        self.assertEqual(await_call.kwargs["form_data"]["code_verifier"], "verifier-1")

    async def test_exchange_tokens_extracts_session_access_token_from_exchange_payload(self):
        service = self.ChatGPTService()

        id_token_header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
        id_token_payload = base64.urlsafe_b64encode(
            json.dumps({"email": "flow@example.com", "sub": "acct_sub_001"}).encode()
        ).decode().rstrip("=")
        id_token = f"{id_token_header}.{id_token_payload}.signature"

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "id_token": id_token,
                        "session": {
                            "accessToken": "at_from_session_payload",
                        },
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ):
            result = await service._exchange_tokens(
                pipeline_data={
                    "callback_url": "https://auth.openai.com/callback?code=cb-code-900&state=st2"
                },
                register_input={
                    "token_endpoint": "https://auth.openai.com/oauth/token",
                    "client_id": "client-1",
                },
                db_session=None,
                identifier="acc_123",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["access_token"], "at_from_session_payload")

        service = self.ChatGPTService()
        shared_session = object()
        observed_state = {"value": ""}

        expected_state = service._build_deterministic_oauth_state(
            {
                "identifier": "acc_123",
                "register_input": self._valid_register_input(),
            }
        )

        async def _side_effect(
            method,
            url,
            headers,
            json_data=None,
            db_session=None,
            identifier="default",
            special_session_step=False,
            session=None,
            proxy=None,
        ):
            del method, headers, db_session, identifier, special_session_step, proxy
            if "sentinel/chat-requirements" in url:
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"ok": True},
                    "session": shared_session,
                }
            if "api/accounts/check/v4" in url:
                observed_state["value"] = str((json_data or {}).get("state") or "")
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"oauth_state": observed_state["value"]},
                    "session": session,
                }
            return {
                "success": True,
                "status_code": 200,
                "data": {"ok": True},
                "session": session,
            }

        with patch.object(service, "_make_register_request", new=AsyncMock(side_effect=_side_effect)):
            result = await service._run_register_pipeline(
                {
                    "register_input": self._valid_register_input(),
                    "db_session": None,
                    "identifier": "acc_123",
                    "otp_code": "123456",
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual(observed_state["value"], expected_state)

    async def test_extract_token_claims_without_verification_parses_jwt_payload(self):
        service = self.ChatGPTService()

        header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"email": "claims@example.com", "sub": "user_001", "exp": 1893456000}).encode()
        ).decode().rstrip("=")
        token = f"{header}.{payload}.signature"

        claims = service._extract_token_claims_without_verification(token)

        self.assertEqual(claims["email"], "claims@example.com")
        self.assertEqual(claims["sub"], "user_001")
        self.assertEqual(claims["exp"], 1893456000)

    async def test_extract_session_access_token_reads_nested_session_shapes(self):
        service = self.ChatGPTService()

        session_access_token = service._extract_session_access_token(
            {
                "session": {
                    "accessToken": "at-from-session",
                }
            }
        )

        self.assertEqual(session_access_token, "at-from-session")

    async def test_register_allows_token_finalize_when_callback_state_matches(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "user@example.com",
                        "account_id": "acc_001",
                        "oauth_state": "state-ok",
                        "callback_url": "https://auth.openai.com/callback?code=cb-ok-001&state=state-ok",
                        "token_endpoint": "https://auth.openai.com/oauth/token",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_exchange_tokens",
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
            result = await service.register()

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["access_token"], "at")

    async def test_register_fails_token_finalize_when_callback_state_mismatches(self):
        service = self.ChatGPTService()

        with self._register_env(), patch.object(
            service,
            "_run_register_pipeline",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "email": "user@example.com",
                        "account_id": "acc_001",
                        "oauth_state": "state-expected",
                        "callback_url": "https://auth.openai.com/callback?code=cb-mismatch-001&state=state-actual",
                        "token_endpoint": "https://auth.openai.com/oauth/token",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ), patch.object(
            service,
            "_exchange_tokens",
            new=AsyncMock(side_effect=AssertionError("token exchange should not run on state mismatch")),
        ):
            result = await service.register()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "token_finalize_failed")

    async def test_finalize_uses_pipeline_callback_artifacts_without_token_payload(self):
        service = self.ChatGPTService()

        with patch.object(
            service,
            "_make_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "access_token": "at_from_finalize",
                        "refresh_token": "rt_from_finalize",
                        "id_token": "id_from_finalize",
                    },
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_request, patch.object(
            service,
            "_enrich_account_context",
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
            result = await service._finalize_registration_result(
                pipeline_data={
                    "email": "user@example.com",
                    "account_id": "acc_001",
                    "callback_url": "https://auth.openai.com/callback?code=cb-final-123&state=state-final",
                    "token_endpoint": "https://auth.openai.com/oauth/token",
                },
                register_input={
                    "fixed_email": "user@example.com",
                    "mail_worker_base_url": "https://mail.example.com",
                    "mail_worker_token": "token",
                    "client_id": "client-1",
                },
                db_session=None,
                identifier="acc_123",
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["access_token"], "at_from_finalize")
        mocked_make_request.assert_awaited_once()
        await_call = mocked_make_request.await_args
        self.assertEqual(await_call.args[0], "POST")
        self.assertEqual(await_call.args[1], "https://auth.openai.com/oauth/token")
        self.assertEqual(await_call.args[2]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(await_call.kwargs["form_data"]["code"], "cb-final-123")

    async def test_check_network_and_region_blocks_detected_region_from_trace(self):
        service = self.ChatGPTService()

        trace_session = types.SimpleNamespace(
            get=AsyncMock(
                return_value=types.SimpleNamespace(
                    status_code=200,
                    text="fl=29f88\nloc=IR\n",
                )
            )
        )

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=trace_session),
        ):
            result = await service._check_network_and_region(
                {
                    "register_input": {
                        **self._valid_register_input(),
                    },
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"], 451)
        self.assertEqual(result["error_code"], "network_error")

    async def test_check_network_and_region_maps_timeout_to_network_timeout(self):
        service = self.ChatGPTService()

        trace_session = types.SimpleNamespace(
            get=AsyncMock(side_effect=TimeoutError("precheck timeout"))
        )

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=trace_session),
        ):
            result = await service._check_network_and_region(
                {
                    "register_input": {
                        **self._valid_register_input(),
                    },
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "network_timeout")

    async def test_check_network_and_region_maps_connection_to_network_error(self):
        service = self.ChatGPTService()

        trace_session = types.SimpleNamespace(
            get=AsyncMock(side_effect=ConnectionError("network down"))
        )

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=trace_session),
        ):
            result = await service._check_network_and_region(
                {
                    "register_input": {
                        **self._valid_register_input(),
                    },
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "network_error")

    async def test_check_network_and_region_success_passes_through_detected_region(self):
        service = self.ChatGPTService()

        trace_session = types.SimpleNamespace(
            get=AsyncMock(
                return_value=types.SimpleNamespace(
                    status_code=200,
                    text="fl=29f88\nloc=US\n",
                )
            )
        )

        base_ctx = {
            "register_input": {
                **self._valid_register_input(),
            },
            "db_session": None,
            "identifier": "acc_123",
        }

        with patch.object(
            service,
            "_get_session",
            new=AsyncMock(return_value=trace_session),
        ):
            result = await service._check_network_and_region(base_ctx)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["detected_region"], "US")
        self.assertEqual(result["data"]["identifier"], "acc_123")

    async def test_poll_otp_from_mail_worker_uses_v1_code_query_url(self):
        service = self.ChatGPTService()
        register_input = self._valid_register_input()
        register_input["mail_worker_base_url"] = "https://worker.example.com/"

        with patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "status_code": 200,
                    "data": {"code": "123456"},
                    "error": None,
                    "error_code": None,
                }
            ),
        ) as mocked_make_register_request:
            result = await service._poll_otp_from_mail_worker(
                {
                    "register_input": register_input,
                    "db_session": None,
                    "identifier": "acc_123",
                }
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["otp_code"], "123456")
        mocked_make_register_request.assert_awaited_once()
        self.assertEqual(mocked_make_register_request.await_args.args[0], "GET")
        called_url = mocked_make_register_request.await_args.args[1]
        self.assertEqual(
            called_url,
            "https://worker.example.com/v1/code?email=user%40example.com",
        )
        called_headers = mocked_make_register_request.await_args.args[2]
        self.assertEqual(called_headers.get("Authorization"), "Bearer token")

    async def test_poll_and_validate_otp_fails_when_mail_worker_fetch_fails(self):
        service = self.ChatGPTService()
        ctx = {
            "register_input": self._valid_register_input(),
            "db_session": None,
            "identifier": "acc_123",
            "session": object(),
        }

        with patch.object(
            service,
            "_poll_otp_from_mail_worker",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 502,
                    "data": None,
                    "error": "mail worker unavailable",
                    "error_code": "otp_fetch_failed",
                }
            ),
        ) as mocked_poll_worker, patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(side_effect=AssertionError("otp validate should not run")),
        ):
            result = await service._poll_and_validate_otp(ctx)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "otp_validate_failed")
        mocked_poll_worker.assert_awaited_once()


        service = self.ChatGPTService()
        ctx = {
            "register_input": self._valid_register_input(),
            "db_session": None,
            "identifier": "acc_123",
            "session": object(),
        }

        with patch.object(
            service,
            "_poll_otp_from_mail_worker",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 404,
                    "data": None,
                    "error": "otp code not found",
                    "error_code": "otp_not_found",
                }
            ),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(side_effect=AssertionError("otp validate should not run")),
        ):
            result = await service._poll_and_validate_otp(ctx)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "otp_validate_failed")

    async def test_poll_and_validate_otp_propagates_mail_worker_network_timeout_error(self):
        service = self.ChatGPTService()
        ctx = {
            "register_input": self._valid_register_input(),
            "db_session": None,
            "identifier": "acc_123",
            "session": object(),
        }

        with patch.object(
            service,
            "_poll_otp_from_mail_worker",
            new=AsyncMock(
                return_value={
                    "success": False,
                    "status_code": 0,
                    "data": None,
                    "error": "mail worker timeout",
                    "error_code": "network_timeout",
                }
            ),
        ), patch.object(
            service,
            "_make_register_request",
            new=AsyncMock(side_effect=AssertionError("otp validate should not run")),
        ):
            result = await service._poll_and_validate_otp(ctx)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "network_timeout")
