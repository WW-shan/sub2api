import sys
import types
import unittest


def _install_chatgpt_import_stubs() -> None:
    if "curl_cffi.requests" not in sys.modules:
        curl_cffi_module = types.ModuleType("curl_cffi")
        curl_cffi_requests_module = types.ModuleType("curl_cffi.requests")

        class AsyncSession:  # pragma: no cover - import stub
            async def close(self):
                return None

        curl_cffi_requests_module.AsyncSession = AsyncSession
        curl_cffi_module.requests = curl_cffi_requests_module
        sys.modules["curl_cffi"] = curl_cffi_module
        sys.modules["curl_cffi.requests"] = curl_cffi_requests_module

    if "sqlalchemy.ext.asyncio" not in sys.modules:
        sqlalchemy_module = types.ModuleType("sqlalchemy")
        sqlalchemy_ext_module = types.ModuleType("sqlalchemy.ext")
        sqlalchemy_ext_asyncio_module = types.ModuleType("sqlalchemy.ext.asyncio")

        class DBAsyncSession:  # pragma: no cover - import stub
            pass

        sqlalchemy_ext_asyncio_module.AsyncSession = DBAsyncSession
        sqlalchemy_ext_module.asyncio = sqlalchemy_ext_asyncio_module
        sqlalchemy_module.ext = sqlalchemy_ext_module
        sys.modules["sqlalchemy"] = sqlalchemy_module
        sys.modules["sqlalchemy.ext"] = sqlalchemy_ext_module
        sys.modules["sqlalchemy.ext.asyncio"] = sqlalchemy_ext_asyncio_module

    if "app.utils.jwt_parser" not in sys.modules:
        app_module = types.ModuleType("app")
        app_utils_module = types.ModuleType("app.utils")
        app_jwt_parser_module = types.ModuleType("app.utils.jwt_parser")

        class JWTParser:  # pragma: no cover - import stub
            def extract_email(self, token: str):
                return None

        app_jwt_parser_module.JWTParser = JWTParser
        app_module.utils = app_utils_module
        app_utils_module.jwt_parser = app_jwt_parser_module
        sys.modules["app"] = app_module
        sys.modules["app.utils"] = app_utils_module
        sys.modules["app.utils.jwt_parser"] = app_jwt_parser_module


_install_chatgpt_import_stubs()

from tools.codex_register.chatgpt import ChatGPTService


class ChatGPTRegisterContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_response_contains_fixed_top_level_keys(self):
        service = ChatGPTService()
        result = await service.register({"mail_worker_base_url": "x"})
        self.assertEqual(
            set(result.keys()),
            {"success", "status_code", "data", "error", "error_code"},
        )
