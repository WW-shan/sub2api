import sys
import types
import unittest
from unittest.mock import patch


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
