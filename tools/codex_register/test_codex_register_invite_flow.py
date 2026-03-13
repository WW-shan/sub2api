import ast
import base64
import io
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

from tools.codex_register import codex_register_service as service


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        if not self._rows:
            return []
        return self._rows.pop(0)

    def close(self):
        return None


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        return None


class _FakeHTTPResponse:
    def __init__(self, status, body: bytes = b"{}", text: str = "", json_data=None):
        self.status = status
        self.status_code = status
        self._body = body
        self.text = text
        self._json_data = json_data

    def read(self):
        return self._body

    def json(self):
        if self._json_data is not None:
            return dict(self._json_data)
        if self._body:
            try:
                return json.loads(self._body.decode("utf-8"))
            except Exception:
                return {}
        if self.text:
            try:
                return json.loads(self.text)
            except Exception:
                return {}
        return {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


class _FakeRequestHandler:
    def __init__(self, path: str, headers=None):
        self.path = path
        self.headers = dict(headers or {})
        self.response_code = None
        self.response_headers = []
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.response_code = code

    def _cors_headers(self):
        return service.CodexRequestHandler._cors_headers(self)

    def send_header(self, key, value):
        self.response_headers.append((key, value))

    def end_headers(self):
        return None


class CodexRegisterInviteFlowTests(unittest.TestCase):
    def setUp(self):
        service.enabled = False
        service.last_run = None
        service.last_success = None
        service.last_error = ""
        service.total_created = 0
        service.total_updated = 0
        service.total_skipped = 0
        service.last_token_email = ""
        service.last_created_email = ""
        service.last_created_account_id = ""
        service.last_updated_email = ""
        service.last_updated_account_id = ""
        service.last_processed_records = 0
        service.recent_logs = []
        service.workflow_id = ""
        service.job_phase = service.PHASE_IDLE
        service.waiting_reason = ""
        service.last_transition = {}
        service.last_resume_gate_reason = ""
        service.active_workflow_thread = None
        service.active_workflow_cancel_event.clear()
        service.tokens_dir_global = Path('/tmp')
        service._child_round_state.clear()

    def test_run_codex_once_only_reads_new_json_files_created_during_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp)
            stale = tokens_dir / 'stale.json'
            stale.write_text(json.dumps({'email': 'stale@example.com'}), encoding='utf-8')

            def _fake_run(*_args, **_kwargs):
                fresh = tokens_dir / 'fresh.json'
                fresh.write_text(json.dumps({'email': 'fresh@example.com'}), encoding='utf-8')
                return mock.Mock(returncode=0, stdout='', stderr='')

            with mock.patch.object(service.subprocess, 'run', side_effect=_fake_run):
                batches = service.run_codex_once(tokens_dir)

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][0].name, 'fresh.json')
        self.assertEqual(batches[0][1], [{'email': 'fresh@example.com'}])

    def test_run_codex_once_timeout_uses_mail_poll_budget_when_timeout_not_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp)
            captured = {}

            def _fake_run(*_args, **kwargs):
                captured["timeout"] = kwargs.get("timeout")
                raise subprocess.TimeoutExpired(cmd=["python", "script.py"], timeout=kwargs.get("timeout"), output="", stderr="")

            with mock.patch.dict(
                os.environ,
                {
                    "CODEX_MAIL_POLL_SECONDS": "5",
                    "CODEX_MAIL_POLL_MAX_ATTEMPTS": "50",
                    "CODEX_REGISTER_SUBPROCESS_TIMEOUT": "",
                },
                clear=False,
            ), mock.patch.object(service.subprocess, "run", side_effect=_fake_run):
                with self.assertRaisesRegex(RuntimeError, "script_timeout"):
                    service.run_codex_once(tokens_dir)

        self.assertEqual(captured.get("timeout"), 280)

    def test_run_codex_once_timeout_logs_subprocess_stdout_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp)
            info_messages = []

            timeout_exc = subprocess.TimeoutExpired(
                cmd=["python", "script.py"],
                timeout=120,
                output="mid-stdout",
                stderr="mid-stderr",
            )

            with mock.patch.object(service.subprocess, "run", side_effect=timeout_exc), mock.patch.object(
                service, "info_log", side_effect=lambda *args, **kwargs: info_messages.append(" ".join(str(arg) for arg in args))
            ):
                with self.assertRaisesRegex(RuntimeError, "script_timeout"):
                    service.run_codex_once(tokens_dir)

        merged = "\n".join(info_messages)
        self.assertIn("subprocess timeout stdout", merged)
        self.assertIn("mid-stdout", merged)
        self.assertIn("subprocess timeout stderr", merged)
        self.assertIn("mid-stderr", merged)


    def test_run_uses_timeout_for_all_session_post_requests(self):
        workspace_payload = {
            "workspaces": [
                {
                    "id": "ws-parent",
                    "subscription": {"plan_type": "business"},
                    "organization_id": "org-1",
                }
            ]
        }
        auth_segment = base64.urlsafe_b64encode(json.dumps(workspace_payload).encode("utf-8")).decode("ascii").rstrip("=")

        class _FakeResponse:
            def __init__(self, *, status_code=200, text="", headers=None, json_data=None):
                self.status_code = status_code
                self.text = text
                self.headers = dict(headers or {})
                self._json_data = dict(json_data or {})

            def json(self):
                return dict(self._json_data)

        class _FakeSession:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self.cookies = {
                    "oai-did": "did-1",
                    "oai-client-auth-session": f"{auth_segment}.payload.signature",
                }

            def get(self, url, **kwargs):
                del kwargs
                if "cloudflare.com/cdn-cgi/trace" in url:
                    return _FakeResponse(text="loc=US\n")
                if url == "https://auth.local/continue":
                    return _FakeResponse(
                        status_code=302,
                        headers={
                            "Location": "http://localhost:1455/auth/callback?code=ok-code&state=state-1"
                        },
                    )
                return _FakeResponse()

            def post(self, url, *, headers=None, data=None, timeout=None):
                del headers, data
                self.post_timeouts.append(timeout)
                if url.endswith("/workspace/select"):
                    return _FakeResponse(status_code=200, json_data={"continue_url": "https://auth.local/continue"})
                return _FakeResponse(status_code=200)

        post_timeouts = []

        fake_requests = mock.Mock()

        def _build_session(*args, **kwargs):
            session = _FakeSession(*args, **kwargs)
            session.post_timeouts = post_timeouts
            return session

        def _sentinel_post(*_args, **_kwargs):
            return _FakeResponse(status_code=200, json_data={"token": "sentinel-token"})

        fake_requests.Session = _build_session
        fake_requests.post = _sentinel_post

        with mock.patch.dict(os.environ, {"CODEX_REGISTER_HTTP_TIMEOUT": "17", "CODEX_PARENT_WORKSPACE_ID": "ws-parent"}, clear=False), mock.patch.object(
            service, "get_requests_module", return_value=fake_requests
        ), mock.patch.object(
            service, "get_email_and_token", return_value=("child@example.com", "worker", "pw")
        ), mock.patch.object(
            service,
            "generate_oauth_url",
            return_value=service.OAuthStart(
                auth_url="https://auth.local/start",
                state="state-1",
                code_verifier="verifier",
                redirect_uri="http://localhost:1455/auth/callback",
            ),
        ), mock.patch.object(service, "get_oai_code", return_value="123456"), mock.patch.object(
            service,
            "submit_callback_url",
            return_value=json.dumps(
                {
                    "email": "child@example.com",
                    "account_id": "child-1",
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                }
            ),
        ), mock.patch.object(service, "fetch_session_access_token", return_value=""):
            token_json = service.run(proxy=None)

        self.assertIsNotNone(token_json)
        self.assertEqual(post_timeouts, [17, 17, 17, 17, 17])

        source = Path(service.__file__).read_text(encoding='utf-8')
        module = ast.parse(source)

        def _find(name: str) -> ast.FunctionDef:
            for node in module.body:
                if isinstance(node, ast.FunctionDef) and node.name == name:
                    return node
            self.fail(f'function not found: {name}')

        def _has_status_lock_with(func: ast.FunctionDef) -> bool:
            for node in ast.walk(func):
                if isinstance(node, ast.With):
                    for item in node.items:
                        expr = item.context_expr
                        if isinstance(expr, ast.Name) and expr.id == 'status_lock':
                            return True
            return False

        for name in ('_get_child_round_state', '_set_child_round_state', '_clear_child_round_state'):
            self.assertTrue(_has_status_lock_with(_find(name)), f'{name} should use status_lock')

    def test_service_module_does_not_use_print_calls(self):
        source = Path(service.__file__).read_text(encoding='utf-8')
        module = ast.parse(source)

        print_calls = [
            node.lineno
            for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print'
        ]

        self.assertEqual(print_calls, [], f'print calls found: {print_calls}')

    def test_run_returns_none_without_polling_code_when_send_otp_fails(self):
        class _FakeResponse:
            def __init__(self, *, status_code=200, text="", headers=None, json_data=None):
                self.status_code = status_code
                self.text = text
                self.headers = dict(headers or {})
                self._json_data = dict(json_data or {})

            def json(self):
                return dict(self._json_data)

        class _FakeSession:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self.cookies = {
                    "oai-did": "did-1",
                    "oai-client-auth-session": "header.payload.signature",
                }

            def get(self, url, **kwargs):
                del kwargs
                if "cloudflare.com/cdn-cgi/trace" in url:
                    return _FakeResponse(text="loc=US\n")
                return _FakeResponse()

            def post(self, url, *, headers=None, data=None, timeout=None):
                del headers, data, timeout
                if url.endswith("/authorize/continue"):
                    return _FakeResponse(status_code=200)
                if url.endswith("/passwordless/send-otp"):
                    return _FakeResponse(status_code=429, text='{"error":"rate_limited"}')
                return _FakeResponse(status_code=200)

        fake_requests = mock.Mock()
        fake_requests.Session = _FakeSession
        fake_requests.post = lambda *_args, **_kwargs: _FakeResponse(status_code=200, json_data={"token": "sentinel-token"})

        with mock.patch.object(service, "get_requests_module", return_value=fake_requests), mock.patch.object(
            service, "get_email_and_token", return_value=("child@example.com", "worker", "pw")
        ), mock.patch.object(
            service,
            "generate_oauth_url",
            return_value=service.OAuthStart(
                auth_url="https://auth.local/start",
                state="state-1",
                code_verifier="verifier",
                redirect_uri="http://localhost:1455/auth/callback",
            ),
        ), mock.patch.object(service, "get_oai_code") as get_oai_code_mock:
            token_json = service.run(proxy=None)

        self.assertIsNone(token_json)
        get_oai_code_mock.assert_not_called()

    def test_append_log_emits_to_python_logger_by_level(self):
        with mock.patch.object(service, "logger") as fake_logger:
            service.append_log("info", "info-message")
            service.append_log("warn", "warn-message")
            service.append_log("error", "error-message")

        fake_logger.info.assert_called_once_with("info-message")
        fake_logger.warning.assert_called_once_with("warn-message")
        fake_logger.error.assert_called_once_with("error-message")

    def test_get_email_and_token_prefers_fixed_env(self):
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_FIXED_EMAIL": "fixed@example.com",
                "CODEX_FIXED_PASSWORD": "fixed-pass",
                "CODEX_MAIL_DOMAIN": "ignored.example.com",
            },
            clear=True,
        ):
            email, dev_token, password = service.get_email_and_token()

        self.assertEqual(email, "fixed@example.com")
        self.assertEqual(dev_token, "worker")
        self.assertEqual(password, "fixed-pass")

    def test_get_email_and_token_uses_domain_when_fixed_missing(self):
        with mock.patch.dict(
            os.environ,
            {"CODEX_MAIL_DOMAIN": "example.com", "CODEX_FIXED_PASSWORD": "fixed-pass"},
            clear=True,
        ):
            email, dev_token, password = service.get_email_and_token()

        self.assertTrue(email.endswith("@example.com"))
        self.assertEqual(dev_token, "worker")
        self.assertEqual(password, "fixed-pass")

    def test_get_email_and_token_generates_password_when_fixed_missing(self):
        with mock.patch.dict(os.environ, {"CODEX_MAIL_DOMAIN": "example.com"}, clear=True):
            email, dev_token, password = service.get_email_and_token()

        self.assertTrue(email.endswith("@example.com"))
        self.assertEqual(dev_token, "worker")
        self.assertTrue(password)

    def test_invite_recent_children_requires_parent_account_id(self):
        ok, reason = service.invite_recent_children(
            {"access_token": "tok", "workspace_id": "ws", "organization_id": "org", "plan_type": "business"},
            expected_count=1,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "parent_account_id_missing")

    def test_invite_recent_children_requires_parent_access_token(self):
        ok, reason = service.invite_recent_children(
            {"account_id": "parent", "workspace_id": "ws", "organization_id": "org", "plan_type": "business"},
            expected_count=1,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "parent_access_token_missing")

    def test_invite_recent_children_invites_with_parent_headers(self):
        conn = _FakeConn([[('child1@example.com',), ('child2@example.com',)]])
        session = mock.Mock()
        session.post.side_effect = [_FakeHTTPResponse(200), _FakeHTTPResponse(200)]

        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service, 'get_requests_module', return_value=fake_requests
        ):
            ok, reason = service.invite_recent_children(
                {
                    'account_id': 'parent-1',
                    'access_token': 'bearer-parent-token',
                    'workspace_id': 'ws-1',
                    'organization_id': 'org-1',
                    'plan_type': 'business',
                },
                expected_count=2,
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')
        self.assertEqual(session.post.call_count, 2)
        first_call = session.post.call_args_list[0]
        self.assertIn('/backend-api/accounts/parent-1/invites', first_call.args[0])
        self.assertEqual(first_call.kwargs.get('headers', {}).get('Authorization'), 'Bearer bearer-parent-token')
        self.assertEqual(first_call.kwargs.get('headers', {}).get('chatgpt-account-id'), 'parent-1')
        self.assertEqual(first_call.kwargs.get('json', {}).get('email'), 'child1@example.com')
        self.assertEqual(first_call.kwargs.get('timeout'), 20)

    def test_invite_recent_children_uses_target_email_without_db(self):
        parent = {
            "account_id": "parent-1",
            "access_token": "bearer-parent-token",
            "workspace_id": "ws-1",
            "organization_id": "org-1",
            "plan_type": "business",
        }
        session = mock.Mock()
        session.post.return_value = _FakeHTTPResponse(200)
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, "create_db_connection") as create_db, mock.patch.object(
            service, "get_requests_module", return_value=fake_requests
        ):
            ok, reason = service.invite_recent_children(parent, expected_count=1, target_email="child@example.com")

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        create_db.assert_not_called()
        self.assertEqual(session.post.call_count, 1)
        self.assertIn("/backend-api/accounts/parent-1/invites", session.post.call_args.args[0])
        self.assertEqual(session.post.call_args.kwargs.get('json', {}).get('email'), 'child@example.com')

    def test_invite_recent_children_treats_409_as_invited(self):
        conn = _FakeConn([[('child1@example.com',)]])
        session = mock.Mock()
        session.post.return_value = _FakeHTTPResponse(409, text='{"error":"already invited"}')
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service, 'get_requests_module', return_value=fake_requests
        ):
            ok, reason = service.invite_recent_children(
                {
                    'account_id': 'parent-1',
                    'access_token': 'bearer-parent-token',
                    'workspace_id': 'ws-1',
                    'organization_id': 'org-1',
                    'plan_type': 'business',
                },
                expected_count=1,
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')

    def test_invite_recent_children_retries_once_on_409_without_marker(self):
        parent = {
            "account_id": "parent-1",
            "access_token": "bearer-parent-token",
            "workspace_id": "ws-1",
            "organization_id": "org-1",
            "plan_type": "business",
        }
        session = mock.Mock()
        session.post.side_effect = [_FakeHTTPResponse(409, text='{"error":"conflict"}'), _FakeHTTPResponse(200)]
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, "create_db_connection") as create_db, mock.patch.object(
            service, "get_requests_module", return_value=fake_requests
        ):
            ok, reason = service.invite_recent_children(parent, expected_count=1, target_email="child@example.com")

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(session.post.call_count, 2)
        create_db.assert_not_called()

    def test_verify_child_business_plan_via_session_exchange_returns_true_for_matching_workspace_plan(self):
        status_payload = {"user": {"account": {"current_account": {"id": "parent-1", "workspace": {"id": "ws-1", "subscription": {"plan_type": "business"}}}}}}
        session = mock.Mock()
        session.get.return_value = _FakeHTTPResponse(200, json_data=status_payload)
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'get_requests_module', return_value=fake_requests):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'parent-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='ws-1',
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')
        self.assertEqual(session.get.call_count, 1)

    def test_verify_child_business_plan_via_session_exchange_detects_non_business_plan(self):
        status_payload = {"user": {"account": {"current_account": {"id": "parent-1", "workspace": {"id": "ws-1", "subscription": {"plan_type": "free"}}}}}}
        session = mock.Mock()
        session.get.return_value = _FakeHTTPResponse(200, json_data=status_payload)
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'get_requests_module', return_value=fake_requests):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'parent-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='ws-1',
            )

        self.assertFalse(ok)
        self.assertEqual(reason, 'child_plan_not_business')

    def test_verify_child_business_plan_via_session_exchange_detects_workspace_mismatch(self):
        status_payload = {"user": {"account": {"current_account": {"id": "parent-1", "workspace": {"id": "ws-other", "subscription": {"plan_type": "business"}}}}}}
        session = mock.Mock()
        session.get.return_value = _FakeHTTPResponse(200, json_data=status_payload)
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'get_requests_module', return_value=fake_requests):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'parent-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='ws-1',
            )

        self.assertFalse(ok)
        self.assertEqual(reason, 'child_workspace_mismatch')

    def test_verify_child_business_plan_via_session_exchange_parses_accounts_map_payload(self):
        status_payload = {
            "accounts": {
                "7def": {"account": {"account_id": "7def", "organization_id": "org-1", "plan_type": "team"}},
                "3e48": {"account": {"account_id": "3e48", "organization_id": None, "plan_type": "free"}},
                "default": {"account": {"account_id": "3e48", "organization_id": None, "plan_type": "free"}},
            },
            "account_ordering": ["7def", "3e48"],
        }
        session = mock.Mock()
        session.get.return_value = _FakeHTTPResponse(200, json_data=status_payload)
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'get_requests_module', return_value=fake_requests):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'child-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='7def',
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')

    def test_verify_child_business_plan_via_session_exchange_reads_root_account_plan_type(self):
        status_payload = {"account": {"id": "ws-1", "planType": "team", "organizationId": "org-1", "structure": "workspace"}}
        session = mock.Mock()
        session.get.return_value = _FakeHTTPResponse(200, json_data=status_payload)
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'get_requests_module', return_value=fake_requests):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'child-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='ws-1',
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')

    def test_verify_child_business_plan_via_session_exchange_falls_back_to_parent_account_id_workspace(self):
        second_ok_payload = {
            "user": {
                "account": {
                    "current_account": {
                        "id": "parent-1",
                        "workspace": {
                            "id": "parent-1",
                            "subscription": {"plan_type": "team"},
                        },
                    }
                }
            }
        }

        session = mock.Mock()
        session.get.side_effect = [
            _FakeHTTPResponse(400, text='{}'),
            _FakeHTTPResponse(200, json_data=second_ok_payload),
        ]
        fake_requests = mock.Mock()
        fake_requests.Session.return_value = session

        with mock.patch.object(service, 'get_requests_module', return_value=fake_requests):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'child-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='ws-1',
                parent_account_id='parent-1',
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')
        self.assertIn('workspace_id=ws-1', session.get.call_args_list[0].args[0])
        self.assertIn('workspace_id=parent-1', session.get.call_args_list[1].args[0])

    def test_evaluate_resume_gate_requires_parent_account_and_access_token(self):
        service.tokens_dir_global = Path('/tmp')

        reason_missing_account = service.evaluate_resume_gate(
            {
                'plan_type': 'business',
                'organization_id': 'org-1',
                'workspace_id': 'ws-1',
                'workspace_reachable': True,
                'members_page_accessible': True,
                'account_id': '',
                'access_token': 'parent-token',
            }
        )
        self.assertEqual(reason_missing_account, 'parent_account_id_missing')

        reason_missing_token = service.evaluate_resume_gate(
            {
                'plan_type': 'business',
                'organization_id': 'org-1',
                'workspace_id': 'ws-1',
                'workspace_reachable': True,
                'members_page_accessible': True,
                'account_id': 'parent-1',
                'access_token': '',
                'session_access_token': '',
            }
        )
        self.assertEqual(reason_missing_token, 'parent_access_token_missing')

    def test_run_single_child_round_stops_when_invite_fails(self):
        service.workflow_id = "wf-test"
        service.active_workflow_cancel_event.clear()
        parent = {
            "account_id": "parent-1",
            "access_token": "parent-token",
            "workspace_id": "ws-1",
            "organization_id": "org-1",
            "plan_type": "business",
        }
        with mock.patch.object(service, "invite_recent_children", return_value=(False, "invite_failed")), mock.patch.object(
            service, "register_child_once"
        ) as register_child, mock.patch.object(service, "_transition_workflow_phase", return_value=True):
            ok, reason = service.run_single_child_round(
                "wf-test", parent, tokens_dir=Path("/tmp"), round_index=1, total_rounds=1
            )

        self.assertFalse(ok)
        self.assertEqual(reason, "invite_failed")
        register_child.assert_not_called()

    def test_run_workflow_once_resume_completes_with_five_child_invites(self):
        service.workflow_id = 'wf-resume'
        service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK

        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'workspace_reachable': True,
            'members_page_accessible': True,
        }

        round_counter = {'value': 0}

        def _get_email_and_token(*_args, **_kwargs):
            round_counter['value'] += 1
            return f"child{round_counter['value']}@example.com", 'worker', 'pw'

        def _register_child_once(_tokens_dir, *, email, password, preferred_workspace_id):
            return (
                True,
                {
                    'email': email,
                    'account_id': f"child-{round_counter['value']}",
                    'access_token': 'child-access-token',
                    'refresh_token': 'child-refresh-token',
                    'workspace_id': preferred_workspace_id,
                    'organization_id': parent_record['organization_id'],
                },
            )

        with mock.patch.object(service, 'get_latest_parent_record', return_value=parent_record), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'verify_parent_business_context_after_resume', return_value=(True, '')
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool', return_value=(True, '')
        ) as promote_parent, mock.patch.object(
            service, 'get_email_and_token', side_effect=_get_email_and_token
        ), mock.patch.object(
            service, 'register_child_once', side_effect=_register_child_once
        ) as register_child_once, mock.patch.object(
            service, 'verify_child_business_plan_via_session_exchange', return_value=(True, '')
        ), mock.patch.object(
            service, 'create_db_connection', return_value=_FakeConn([])
        ), mock.patch.object(
            service, 'invite_recent_children', return_value=(True, '')
        ) as invite_recent_children, mock.patch.object(
            service, 'promote_recent_child_records_to_pool', return_value=(True, '')
        ) as promote_recent_child_records_to_pool, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        verify_parent_switch.assert_called_once()
        promote_parent.assert_called_once()
        verified_parent_record = verify_parent_switch.call_args.args[0]
        self.assertEqual(verified_parent_record.get('account_id'), parent_record.get('account_id'))
        self.assertEqual(verified_parent_record.get('workspace_id'), parent_record.get('workspace_id'))
        self.assertEqual(verified_parent_record.get('organization_id'), parent_record.get('organization_id'))
        self.assertEqual(verified_parent_record.get('plan_type'), parent_record.get('plan_type'))
        self.assertEqual(verified_parent_record.get('codex_register_role'), 'parent')
        self.assertEqual(verified_parent_record.get('session_access_token'), parent_record.get('access_token'))
        self.assertEqual(verified_parent_record.get('access_token'), parent_record.get('access_token'))
        self.assertEqual(promote_parent.call_args.args[0], verified_parent_record)
        self.assertEqual(invite_recent_children.call_count, 5)
        self.assertEqual(promote_recent_child_records_to_pool.call_count, 5)

        invite_targets = [call.kwargs.get('target_email') for call in invite_recent_children.call_args_list]
        expected_targets = [
            'child1@example.com',
            'child2@example.com',
            'child3@example.com',
            'child4@example.com',
            'child5@example.com',
        ]
        self.assertEqual(invite_targets, expected_targets)

        finalize.assert_called_once_with('wf-resume', success=True, reason='')

    def test_run_workflow_once_resume_reauth_propagates_reauthed_workspace_to_child_round(self):
        service.workflow_id = 'wf-resume'
        service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK

        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token',
            'workspace_id': 'ws-old',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'workspace_reachable': True,
            'members_page_accessible': True,
        }
        reauthed_parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token-reauth',
            'workspace_id': 'ws-new',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'codex_register_role': 'parent',
        }

        child_round_workspaces = []

        def _run_single_child_round(_workflow_token, parent, *, tokens_dir, round_index, total_rounds):
            del tokens_dir, round_index, total_rounds
            child_round_workspaces.append(parent.get('workspace_id'))
            return True, ''

        with mock.patch.object(service, 'get_latest_parent_record', return_value=parent_record), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service,
            'reauthenticate_parent_for_resume',
            return_value=(True, '', reauthed_parent_record),
        ) as reauth_parent, mock.patch.object(
            service, 'verify_parent_business_context_after_resume', return_value=(True, '')
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool', return_value=(True, '')
        ) as promote_parent, mock.patch.object(
            service, 'run_single_child_round', side_effect=_run_single_child_round
        ) as run_single_child_round, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        reauth_parent.assert_called_once_with(parent_record, tokens_dir=service.tokens_dir_global)
        verify_parent_switch.assert_called_once_with(reauthed_parent_record)
        promote_parent.assert_called_once_with(reauthed_parent_record)
        self.assertEqual(run_single_child_round.call_count, 5)
        self.assertEqual(child_round_workspaces, ['ws-new'] * 5)
        finalize.assert_called_once_with('wf-resume', success=True, reason='')

    def test_run_workflow_once_resume_short_circuits_when_parent_reauth_fails(self):
        service.workflow_id = 'wf-resume'
        service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK

        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'workspace_reachable': True,
            'members_page_accessible': True,
        }

        with mock.patch.object(service, 'get_latest_parent_record', return_value=parent_record), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'reauthenticate_parent_for_resume', return_value=(False, 'parent_reauth_failed', {})
        ) as reauth_parent, mock.patch.object(
            service, 'verify_parent_business_context_after_resume'
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool'
        ) as promote_parent, mock.patch.object(
            service, 'register_child_once'
        ) as register_child_once, mock.patch.object(
            service, 'invite_recent_children'
        ) as invite_recent_children, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        reauth_parent.assert_called_once_with(parent_record, tokens_dir=service.tokens_dir_global)
        verify_parent_switch.assert_not_called()
        promote_parent.assert_not_called()
        register_child_once.assert_not_called()
        invite_recent_children.assert_not_called()
        finalize.assert_called_once_with('wf-resume', success=False, reason='parent_reauth_failed')

        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'workspace_reachable': True,
            'members_page_accessible': True,
        }
        reauthed_parent_record = {
            'account_id': 'parent-2',
            'access_token': 'bearer-parent-token-reauth',
            'workspace_id': 'ws-2',
            'organization_id': 'org-2',
            'plan_type': 'business',
            'codex_register_role': 'parent',
        }

        with mock.patch.object(
            service,
            'get_latest_parent_record',
            side_effect=[parent_record, reauthed_parent_record],
        ), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'reauthenticate_parent_for_resume', return_value=(False, 'parent_reauth_account_mismatch', reauthed_parent_record)
        ) as reauth_parent, mock.patch.object(
            service, 'verify_parent_business_context_after_resume'
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool'
        ) as promote_parent, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        reauth_parent.assert_called_once_with(parent_record, tokens_dir=service.tokens_dir_global)
        verify_parent_switch.assert_not_called()
        promote_parent.assert_not_called()
        finalize.assert_called_once_with('wf-resume', success=False, reason='parent_reauth_account_mismatch')

    def test_run_workflow_once_resume_stops_when_parent_reauth_workspace_missing(self):
        service.workflow_id = 'wf-resume'
        service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK

        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'workspace_reachable': True,
            'members_page_accessible': True,
        }
        reauthed_parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token-reauth',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'codex_register_role': 'parent',
        }

        with mock.patch.object(
            service,
            'get_latest_parent_record',
            side_effect=[parent_record, reauthed_parent_record],
        ), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'reauthenticate_parent_for_resume', return_value=(False, 'parent_reauth_workspace_missing', reauthed_parent_record)
        ) as reauth_parent, mock.patch.object(
            service, 'verify_parent_business_context_after_resume'
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool'
        ) as promote_parent, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        reauth_parent.assert_called_once_with(parent_record, tokens_dir=service.tokens_dir_global)
        verify_parent_switch.assert_not_called()
        promote_parent.assert_not_called()
        finalize.assert_called_once_with('wf-resume', success=False, reason='parent_reauth_workspace_missing')

    def test_run_workflow_once_resume_stops_when_parent_reauth_not_team(self):
        service.workflow_id = 'wf-resume'
        service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK

        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'business',
            'workspace_reachable': True,
            'members_page_accessible': True,
        }
        reauthed_parent_record = {
            'account_id': 'parent-1',
            'access_token': 'bearer-parent-token-reauth',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'free',
            'codex_register_role': 'parent',
        }

        with mock.patch.object(
            service,
            'get_latest_parent_record',
            side_effect=[parent_record, reauthed_parent_record],
        ), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'reauthenticate_parent_for_resume', return_value=(False, 'parent_reauth_not_team', reauthed_parent_record)
        ) as reauth_parent, mock.patch.object(
            service, 'verify_parent_business_context_after_resume'
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool'
        ) as promote_parent, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        reauth_parent.assert_called_once_with(parent_record, tokens_dir=service.tokens_dir_global)
        verify_parent_switch.assert_not_called()
        promote_parent.assert_not_called()
        finalize.assert_called_once_with('wf-resume', success=False, reason='parent_reauth_not_team')

    def test_run_single_child_round_stops_when_invite_fails_retry_path(self):
        service.workflow_id = "wf-test"
        service.active_workflow_cancel_event.clear()
        parent = {
            "account_id": "parent-1",
            "access_token": "parent-token",
            "workspace_id": "ws-1",
            "organization_id": "org-1",
            "plan_type": "business",
        }
        with mock.patch.object(service, "invite_recent_children", return_value=(False, "invite_failed")), mock.patch.object(
            service, "register_child_once"
        ) as register_child, mock.patch.object(service, "_transition_workflow_phase", return_value=True):
            ok, reason = service.run_single_child_round(
                "wf-test", parent, tokens_dir=Path("/tmp"), round_index=1, total_rounds=1
            )

        self.assertFalse(ok)
        self.assertEqual(reason, "invite_failed")
        register_child.assert_not_called()

    def test_do_post_resume_logs_not_waiting_state(self):
        handler = _FakeRequestHandler('/resume')

        with mock.patch.object(service, 'append_log') as append_log:
            service.CodexRequestHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 200)
        append_log.assert_any_call('info', 'http_post_received:path=/resume')
        self.assertTrue(
            any(
                call.args[0] == 'warn' and str(call.args[1]).startswith('resume_request_ignored:not_waiting:')
                for call in append_log.call_args_list
            )
        )

    def test_do_post_resume_logs_gate_block_reason(self):
        service.job_phase = service.PHASE_WAITING_PARENT_UPGRADE
        service.waiting_reason = 'parent_upgrade'
        handler = _FakeRequestHandler('/resume')
        parent_record = {
            'account_id': 'parent-1',
            'access_token': 'parent-token',
            'workspace_id': 'ws-1',
            'organization_id': 'org-1',
            'plan_type': 'business',
        }

        with mock.patch.object(service, 'append_log') as append_log, mock.patch.object(
            service, 'get_latest_parent_record', return_value=parent_record
        ), mock.patch.object(
            service, 'evaluate_resume_gate', return_value='parent_account_id_missing'
        ), mock.patch.object(
            service, '_log_resume_gate_decision'
        ) as log_gate_decision, mock.patch.object(
            service, 'set_waiting_manual_locked'
        ) as set_waiting:
            service.CodexRequestHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 200)
        append_log.assert_any_call('info', 'http_post_received:path=/resume')
        log_gate_decision.assert_called_once_with('parent_account_id_missing', parent_record)
        set_waiting.assert_called_once_with('parent_account_id_missing')
        self.assertTrue(
            any(
                call.args[0] == 'warn' and call.args[1] == 'resume_gate_blocked:parent_account_id_missing'
                for call in append_log.call_args_list
            )
        )

    def test_register_child_once_returns_token_without_persist(self):
        token_info = {
            "email": "child@example.com",
            "account_id": "child-1",
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "workspace_id": "ws-1",
        }
        with mock.patch.object(service, "run_codex_once", return_value=[(Path("/tmp/t.json"), [token_info])]), mock.patch.object(
            service, "upsert_codex_register_account"
        ) as upsert:
            ok, result = service.register_child_once(Path("/tmp"), email="child@example.com", password="pw", preferred_workspace_id="ws-1")

        self.assertTrue(ok)
        self.assertEqual(result.get("email"), "child@example.com")
        upsert.assert_not_called()

    def test_run_one_cycle_child_stage_forces_child_role(self):
        conn = _FakeConn([])
        token = {
            'email': 'child1@example.com',
            'account_id': 'child-1',
            'access_token': 'child-access-token',
            'refresh_token': 'child-refresh-token',
            'codex_register_role': 'parent',
        }

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service, 'run_codex_once', return_value=[(Path('/tmp/tokens/token_child.json'), [token])]
        ), mock.patch.object(
            service, 'archive_processed_file', return_value=Path('/tmp/tokens/processed/token_child.json')
        ), mock.patch.object(
            service, 'upsert_account', return_value='created'
        ) as upsert_account, mock.patch.object(
            service, 'upsert_codex_register_account'
        ) as upsert_codex_register_account:
            success, reason = service.run_one_cycle(Path('/tmp/tokens'), write_to_accounts=True, register_role='child')

        self.assertTrue(success)
        self.assertEqual(reason, '')
        self.assertEqual(token.get('codex_register_role'), 'child')
        upsert_account.assert_called_once()
        self.assertEqual(upsert_account.call_args.kwargs.get('account_role'), 'child')
        upsert_codex_register_account.assert_called_once()

    def test_promote_recent_child_records_requires_complete_tokens(self):
        conn = _FakeConn([[('child1@example.com', 'rt-1', 'at-1', 'child-1', 'business', 'org-1', 'ws-1')]])

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service, 'upsert_account', return_value='updated'
        ):
            ok, reason = service.promote_recent_child_records_to_pool(
                {'workspace_id': 'ws-1', 'organization_id': 'org-1', 'plan_type': 'business'},
                expected_count=1,
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')
        self.assertTrue(conn.cursor_obj.executed)
        first_sql = conn.cursor_obj.executed[0][0]
        self.assertIn("COALESCE(refresh_token, '') <> ''", first_sql)
        self.assertIn("COALESCE(access_token, '') <> ''", first_sql)
        self.assertIn("COALESCE(account_id, '') <> ''", first_sql)

    def test_promote_recent_child_records_counts_skipped_as_success(self):
        conn = _FakeConn([[('child1@example.com', 'rt-1', 'at-1', 'child-1', 'business', 'org-1', 'ws-1')]])

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service, 'upsert_account', return_value='skipped'
        ):
            ok, reason = service.promote_recent_child_records_to_pool(
                {'workspace_id': 'ws-1', 'organization_id': 'org-1', 'plan_type': 'business'},
                expected_count=1,
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')

    def test_do_post_disable_marks_cancel_waiting_when_workflow_running(self):
        service.job_phase = service.PHASE_RUNNING_INVITE_CHILDREN
        service.workflow_id = 'wf-active'
        service.active_workflow_thread = mock.Mock(is_alive=mock.Mock(return_value=True))
        handler = _FakeRequestHandler('/disable')

        with mock.patch.object(service, 'append_log'):
            service.CodexRequestHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 200)
        self.assertTrue(service.is_waiting_phase(service.job_phase))
        self.assertEqual(service.waiting_reason, 'cancelled')

    def test_do_post_retry_starts_workflow_from_waiting_cancelled(self):
        service.job_phase = service.build_waiting_phase('cancelled')
        service.waiting_reason = 'cancelled'
        handler = _FakeRequestHandler('/retry')

        with mock.patch.object(service, 'start_workflow_once', return_value=True) as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 200)
        start_workflow_once.assert_called_once_with(allow_resume=True)

    def test_do_post_retry_logs_not_waiting_state(self):
        service.job_phase = service.PHASE_IDLE
        service.waiting_reason = ''
        handler = _FakeRequestHandler('/retry')

        with mock.patch.object(service, 'append_log') as append_log, mock.patch.object(
            service, 'start_workflow_once'
        ) as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        self.assertEqual(handler.response_code, 200)
        start_workflow_once.assert_not_called()
        self.assertTrue(
            any(
                call.args[0] == 'warn' and str(call.args[1]).startswith('retry_request_ignored:not_waiting:')
                for call in append_log.call_args_list
            )
        )

    def test_do_get_accounts_masks_tokens(self):
        handler = _FakeRequestHandler('/accounts')

        with mock.patch.object(
            service,
            'list_codex_register_accounts',
            return_value=[
                {
                    'email': 'user@example.com',
                    'refresh_token': 'refresh-token-123',
                    'access_token': 'access-token-456',
                }
            ],
        ):
            service.CodexRequestHandler.do_GET(handler)

        self.assertEqual(handler.response_code, 200)
        payload = json.loads(handler.wfile.getvalue().decode('utf-8'))
        account = payload['accounts'][0]
        self.assertNotEqual(account['refresh_token'], 'refresh-token-123')
        self.assertNotEqual(account['access_token'], 'access-token-456')

    def test_do_get_accounts_rejects_when_auth_enabled_and_missing_api_key(self):
        handler = _FakeRequestHandler('/accounts')

        with mock.patch.dict(os.environ, {'CODEX_HTTP_API_KEY': 'secret-key'}, clear=False):
            service.CodexRequestHandler.do_GET(handler)

        self.assertEqual(handler.response_code, 401)

    def test_do_options_allows_x_api_key_header(self):
        handler = _FakeRequestHandler('/status')

        service.CodexRequestHandler.do_OPTIONS(handler)

        self.assertEqual(handler.response_code, 204)
        allow_headers = [value for key, value in handler.response_headers if key == 'Access-Control-Allow-Headers']
        self.assertTrue(any('X-API-Key' in value for value in allow_headers))
