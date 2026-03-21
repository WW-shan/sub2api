import base64
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


class GptTeamRunBatchProxyTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location(
            "tools.codex_register.gpt_team_new_proxy_test",
            str(pathlib.Path(__file__).resolve().parent / "gpt-team-new.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None

        fake_requests = types.ModuleType("requests")
        fake_requests.Session = lambda: types.SimpleNamespace(mount=lambda *args, **kwargs: None, proxies={})
        fake_adapters = types.ModuleType("requests.adapters")
        fake_adapters.HTTPAdapter = lambda *args, **kwargs: object()
        fake_urllib3 = types.ModuleType("urllib3")
        fake_urllib3.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
        fake_urllib3.disable_warnings = lambda *args, **kwargs: None
        fake_urllib3_util = types.ModuleType("urllib3.util")
        fake_urllib3_retry = types.ModuleType("urllib3.util.retry")
        fake_urllib3_retry.Retry = lambda *args, **kwargs: object()

        with patch.dict(
            sys.modules,
            {
                "requests": fake_requests,
                "requests.adapters": fake_adapters,
                "urllib3": fake_urllib3,
                "urllib3.util": fake_urllib3_util,
                "urllib3.util.retry": fake_urllib3_retry,
            },
        ), patch("builtins.print"):
            spec.loader.exec_module(module)
        return module

    def test_run_batch_reads_register_proxy_url_and_passes_it_to_register_one_account(self):
        module = self._load_module()
        module.TOTAL_ACCOUNTS = 1

        captured = []

        def fake_register_one_account(proxy=""):
            captured.append(proxy)
            return "user@example.com", "pw", True

        with patch.object(module, "register_one_account", side_effect=fake_register_one_account), \
             patch.object(module.random, "randint", return_value=0), \
             patch.object(module.os, "getenv", side_effect=lambda name, default=None: "http://loop-proxy:8080" if name == "REGISTER_PROXY_URL" else default), \
             patch.object(module.logger, "info"), \
             patch.object(module.logger, "warning"):
            module.run_batch()

        self.assertEqual(captured, ["http://loop-proxy:8080"])


class GptTeamChatGPTLoginTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location(
            "tools.codex_register.gpt_team_new_login_test",
            str(pathlib.Path(__file__).resolve().parent / "gpt-team-new.py"),
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None

        fake_requests = types.ModuleType("requests")
        fake_requests.Session = lambda: types.SimpleNamespace(mount=lambda *args, **kwargs: None, proxies={})
        fake_adapters = types.ModuleType("requests.adapters")
        fake_adapters.HTTPAdapter = lambda *args, **kwargs: object()
        fake_urllib3 = types.ModuleType("urllib3")
        fake_urllib3.exceptions = types.SimpleNamespace(InsecureRequestWarning=Warning)
        fake_urllib3.disable_warnings = lambda *args, **kwargs: None
        fake_urllib3_util = types.ModuleType("urllib3.util")
        fake_urllib3_retry = types.ModuleType("urllib3.util.retry")
        fake_urllib3_retry.Retry = lambda *args, **kwargs: object()

        with patch.dict(
            sys.modules,
            {
                "requests": fake_requests,
                "requests.adapters": fake_adapters,
                "urllib3": fake_urllib3,
                "urllib3.util": fake_urllib3_util,
                "urllib3.util.retry": fake_urllib3_retry,
            },
        ), patch("builtins.print"):
            spec.loader.exec_module(module)
        return module

    def test_chatgpt_http_login_recovers_callback_via_workspace_select_after_non_chatgpt_landing(self):
        module = self._load_module()

        class FakeCookie:
            def __init__(self, name, value):
                self.name = name
                self.value = value

        class FakeResponse:
            def __init__(self, status_code=200, *, url="", json_data=None, text="", headers=None):
                self.status_code = status_code
                self.url = url
                self._json_data = json_data
                self.text = text
                self.headers = headers or {}

            def json(self):
                if self._json_data is None:
                    raise ValueError("no json")
                return self._json_data

        class FakeCookies(list):
            def set(self, name, value, domain=None):
                del domain
                self.append(FakeCookie(name, value))

        cookie_payload = {"workspaces": [{"id": "ws_123"}]}
        encoded_payload = base64.urlsafe_b64encode(json.dumps(cookie_payload).encode("utf-8")).decode("ascii").rstrip("=")

        class FakeSession:
            def __init__(self):
                self.cookies = FakeCookies([FakeCookie("oai-client-auth-session", encoded_payload)])
                self.callback_completed = False

            def get(self, url, headers=None, allow_redirects=True, verify=False, timeout=0):
                del headers, verify, timeout
                url = str(url)
                if url == module.CHATGPT_BASE:
                    return FakeResponse(status_code=200, url=module.CHATGPT_BASE)
                if url == f"{module.CHATGPT_BASE}/api/auth/csrf":
                    return FakeResponse(status_code=200, url=url, json_data={"csrfToken": "csrf-token"})
                if url.startswith(f"{module.OPENAI_AUTH_BASE}/oauth/authorize"):
                    self.cookies.append(FakeCookie("login_session", "login-cookie"))
                    return FakeResponse(status_code=200, url=f"{module.OPENAI_AUTH_BASE}/u/login")
                if url == f"{module.OPENAI_AUTH_BASE}/sign-in-with-chatgpt/codex/consent":
                    if allow_redirects:
                        return FakeResponse(
                            status_code=200,
                            url="https://chatgpt.com/auth/error?error=Callback",
                        )
                    return FakeResponse(
                        status_code=302,
                        url=url,
                        headers={"Location": "https://auth.openai.com/api/oauth/oauth2/auth?audience=test"},
                    )
                if url == "https://chatgpt.com/api/auth/callback/openai?code=ws-code-123":
                    self.callback_completed = True
                    return FakeResponse(status_code=200, url="https://chatgpt.com/")
                if url == f"{module.CHATGPT_BASE}/api/auth/session":
                    if not self.callback_completed:
                        return FakeResponse(
                            status_code=200,
                            url=url,
                            json_data={"WARNING_BANNER": "callback not established"},
                        )
                    return FakeResponse(
                        status_code=200,
                        url=url,
                        json_data={
                            "accessToken": "chatgpt-access",
                            "account": {
                                "id": "acct-uuid-123",
                                "planType": "team",
                            },
                        },
                    )
                return FakeResponse(status_code=200, url=url)

            def post(self, url, json=None, data=None, headers=None, allow_redirects=True, verify=False, timeout=0):
                del data, headers, allow_redirects, verify, timeout
                url = str(url)
                if url == f"{module.CHATGPT_BASE}/api/auth/signin/openai":
                    return FakeResponse(status_code=200, url=f"{module.OPENAI_AUTH_BASE}/u/login")
                if url == f"{module.OPENAI_AUTH_BASE}/api/accounts/authorize/continue":
                    return FakeResponse(
                        status_code=200,
                        url=url,
                        json_data={
                            "continue_url": "/sign-in-with-chatgpt/codex/consent",
                            "page": {"type": "password"},
                        },
                    )
                if url == f"{module.OPENAI_AUTH_BASE}/api/accounts/password/verify":
                    return FakeResponse(
                        status_code=200,
                        url=url,
                        json_data={
                            "continue_url": f"{module.OPENAI_AUTH_BASE}/sign-in-with-chatgpt/codex/consent",
                            "page": {"type": "consent"},
                        },
                    )
                if url == f"{module.OPENAI_AUTH_BASE}/api/accounts/workspace/select":
                    self.workspace_select_payload = dict(json or {})
                    return FakeResponse(
                        status_code=200,
                        url=url,
                        json_data={
                            "continue_url": "https://chatgpt.com/api/auth/callback/openai?code=ws-code-123",
                        },
                    )
                raise AssertionError(f"Unexpected POST {url}")

        fake_session = FakeSession()

        with patch.object(module, "create_session", return_value=fake_session), \
             patch.object(module, "generate_datadog_trace", return_value={}), \
             patch.object(module, "build_sentinel_token", return_value=None):
            access_token, account_id, plan_type = module.chatgpt_http_login(
                email="parent@example.com",
                password="pw",
                proxy="",
                tag="1",
            )

        self.assertEqual(getattr(fake_session, "workspace_select_payload", None), {"workspace_id": "ws_123"})
        self.assertEqual(access_token, "chatgpt-access")
        self.assertEqual(account_id, "acct-uuid-123")
        self.assertEqual(plan_type, "team")


if __name__ == "__main__":
    unittest.main()
