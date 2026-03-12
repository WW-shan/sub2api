import io
import json
import os
from pathlib import Path
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
    def __init__(self, status, body: bytes = b"{}"):
        self.status = status
        self._body = body

    def read(self):
        return self._body

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

        captured_requests = []

        def _urlopen(req, timeout=0):
            captured_requests.append((req, timeout))
            return _FakeHTTPResponse(200)

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service.urllib.request, 'urlopen', side_effect=_urlopen
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
        self.assertEqual(len(captured_requests), 2)
        first_req = captured_requests[0][0]
        self.assertIn('/backend-api/accounts/parent-1/invites', first_req.full_url)
        self.assertEqual(first_req.get_header('Authorization'), 'Bearer bearer-parent-token')
        normalized_headers = {k.lower(): v for k, v in first_req.header_items()}
        self.assertEqual(normalized_headers.get('chatgpt-account-id'), 'parent-1')

    def test_invite_recent_children_uses_target_email_without_db(self):
        parent = {
            "account_id": "parent-1",
            "access_token": "bearer-parent-token",
            "workspace_id": "ws-1",
            "organization_id": "org-1",
            "plan_type": "business",
        }
        captured = []

        def _urlopen(req, timeout=0):
            captured.append(req)
            return _FakeHTTPResponse(200)

        with mock.patch.object(service, "create_db_connection") as create_db, mock.patch.object(
            service.urllib.request, "urlopen", side_effect=_urlopen
        ):
            ok, reason = service.invite_recent_children(parent, expected_count=1, target_email="child@example.com")

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        create_db.assert_not_called()
        self.assertEqual(len(captured), 1)
        self.assertIn("/backend-api/accounts/parent-1/invites", captured[0].full_url)

    def test_invite_recent_children_treats_409_as_invited(self):
        conn = _FakeConn([[('child1@example.com',)]])

        http_409 = urllib.error.HTTPError(
            url='https://chatgpt.com/backend-api/accounts/parent-1/invites',
            code=409,
            msg='Conflict',
            hdrs=None,
            fp=io.BytesIO(b'{"error":"already invited"}'),
        )

        with mock.patch.object(service, 'create_db_connection', return_value=conn), mock.patch.object(
            service.urllib.request, 'urlopen', side_effect=http_409
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
        http_409 = urllib.error.HTTPError(
            url="https://chatgpt.com/backend-api/accounts/parent-1/invites",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=io.BytesIO(b"{\"error\":\"conflict\"}"),
        )
        calls = []

        def _urlopen(req, timeout=0):
            calls.append(req)
            if len(calls) == 1:
                raise http_409
            return _FakeHTTPResponse(200)

        with mock.patch.object(service, "create_db_connection") as create_db, mock.patch.object(
            service.urllib.request, "urlopen", side_effect=_urlopen
        ):
            ok, reason = service.invite_recent_children(parent, expected_count=1, target_email="child@example.com")

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(len(calls), 2)
        create_db.assert_not_called()

    def test_verify_child_business_plan_via_session_exchange_returns_true_for_matching_workspace_plan(self):
        status_json = b'{"user":{"account":{"current_account":{"id":"parent-1","workspace":{"id":"ws-1","subscription":{"plan_type":"business"}}}}}}'

        with mock.patch.object(service.urllib.request, 'urlopen', return_value=_FakeHTTPResponse(200, body=status_json)):
            ok, reason = service.verify_child_business_plan_via_session_exchange(
                {
                    'account_id': 'parent-1',
                    'access_token': 'child-access-token',
                },
                workspace_id='ws-1',
            )

        self.assertTrue(ok)
        self.assertEqual(reason, '')

    def test_verify_child_business_plan_via_session_exchange_detects_non_business_plan(self):
        status_json = b'{"user":{"account":{"current_account":{"id":"parent-1","workspace":{"id":"ws-1","subscription":{"plan_type":"free"}}}}}}'

        with mock.patch.object(service.urllib.request, 'urlopen', return_value=_FakeHTTPResponse(200, body=status_json)):
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
        status_json = b'{"user":{"account":{"current_account":{"id":"parent-1","workspace":{"id":"ws-other","subscription":{"plan_type":"business"}}}}}}'

        with mock.patch.object(service.urllib.request, 'urlopen', return_value=_FakeHTTPResponse(200, body=status_json)):
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
        status_json = b'{"accounts":{"7def":{"account":{"account_id":"7def","organization_id":"org-1","plan_type":"team"}},"3e48":{"account":{"account_id":"3e48","organization_id":null,"plan_type":"free"}},"default":{"account":{"account_id":"3e48","organization_id":null,"plan_type":"free"}}},"account_ordering":["7def","3e48"]}'

        with mock.patch.object(service.urllib.request, 'urlopen', return_value=_FakeHTTPResponse(200, body=status_json)):
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
        status_json = b'{"account":{"id":"ws-1","planType":"team","organizationId":"org-1","structure":"workspace"}}'

        with mock.patch.object(service.urllib.request, 'urlopen', return_value=_FakeHTTPResponse(200, body=status_json)):
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
        first_error = urllib.error.HTTPError(
            url='https://chatgpt.com/api/auth/session',
            code=400,
            msg='Bad Request',
            hdrs=None,
            fp=io.BytesIO(b'{}'),
        )
        second_ok = _FakeHTTPResponse(
            200,
            body=b'{"user":{"account":{"current_account":{"id":"parent-1","workspace":{"id":"parent-1","subscription":{"plan_type":"team"}}}}}}',
        )

        captured_urls = []

        def _urlopen(req, timeout=0):
            captured_urls.append(req.full_url)
            if len(captured_urls) == 1:
                raise first_error
            return second_ok

        with mock.patch.object(service.urllib.request, 'urlopen', side_effect=_urlopen):
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
        self.assertIn('workspace_id=ws-1', captured_urls[0])
        self.assertIn('workspace_id=parent-1', captured_urls[1])

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

    def test_run_workflow_once_resume_invokes_real_invite_step(self):
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
            return f"child{round_counter['value']}@example.com", "worker", "pw"

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

        verify_parent_switch.assert_called_once_with(parent_record)
        promote_parent.assert_called_once_with(parent_record)
        self.assertEqual(register_child_once.call_count, 5)
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

    def test_run_single_child_round_skips_persist_when_verify_fails(self):
        service.workflow_id = "wf-test"
        service.active_workflow_cancel_event.clear()
        parent = {
            "account_id": "parent-1",
            "access_token": "parent-token",
            "workspace_id": "ws-1",
            "organization_id": "org-1",
            "plan_type": "business",
        }
        token_info = {
            "email": "child@example.com",
            "account_id": "child-1",
            "access_token": "at-1",
            "refresh_token": "rt-1",
        }
        with mock.patch.object(service, "invite_recent_children", return_value=(True, "")), mock.patch.object(
            service, "register_child_once", return_value=(True, token_info)
        ), mock.patch.object(service, "verify_child_business_plan_via_session_exchange", return_value=(False, "child_plan_not_business")), mock.patch.object(
            service, "upsert_codex_register_account"
        ) as upsert, mock.patch.object(service, "_transition_workflow_phase", return_value=True):
            ok, reason = service.run_single_child_round(
                "wf-test", parent, tokens_dir=Path("/tmp"), round_index=1, total_rounds=1
            )

        self.assertFalse(ok)
        self.assertEqual(reason, "child_plan_not_business")
        upsert.assert_not_called()

    def test_child_round_reuses_identity_on_retry(self):
        state = {"email": "child@example.com", "password": "pw", "invite_ok": True}
        with mock.patch.object(service, "_get_child_round_state", return_value=state), mock.patch.object(
            service, "_set_child_round_state"
        ) as set_state:
            identity = service._get_or_create_child_identity("wf-test", 1)

        self.assertEqual(identity["email"], "child@example.com")
        set_state.assert_not_called()

    def test_finalize_workflow_clears_child_round_state_for_token(self):
        service.workflow_id = "wf-clear"
        service.job_phase = service.PHASE_RUNNING_CREATE_PARENT
        service._child_round_state.update(
            {
                "wf-clear:1": {"email": "child@example.com"},
                "wf-other:2": {"email": "other@example.com"},
            }
        )

        service._finalize_workflow_once("wf-clear", success=True, reason="")

        self.assertNotIn("wf-clear:1", service._child_round_state)
        self.assertIn("wf-other:2", service._child_round_state)

    def test_run_workflow_once_resume_blocks_when_parent_switch_verification_fails(self):
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
            service, 'verify_parent_business_context_after_resume', return_value=(False, 'parent_switch_failed')
        ) as verify_parent_switch, mock.patch.object(
            service, 'promote_parent_record_to_pool', return_value=(True, '')
        ) as promote_parent, mock.patch.object(
            service, 'run_one_cycle', return_value=(True, '')
        ) as run_one_cycle, mock.patch.object(
            service, 'invite_recent_children', return_value=(True, '')
        ) as invite_recent_children, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service.last_processed_records = 2
            service._run_workflow_once('wf-resume', 'resume')

        verify_parent_switch.assert_called_once_with(parent_record)
        promote_parent.assert_not_called()
        run_one_cycle.assert_not_called()
        invite_recent_children.assert_not_called()
        finalize.assert_called_once_with('wf-resume', success=False, reason='parent_switch_failed')

    def test_run_workflow_once_resume_blocks_when_parent_pool_promotion_fails(self):
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
            'email': 'parent@example.com',
            'refresh_token': 'parent-refresh-token',
        }

        with mock.patch.object(service, 'get_latest_parent_record', return_value=parent_record), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'verify_parent_business_context_after_resume', return_value=(True, '')
        ), mock.patch.object(
            service, 'promote_parent_record_to_pool', return_value=(False, 'parent_pool_promote_failed')
        ) as promote_parent, mock.patch.object(
            service, 'run_one_cycle', return_value=(True, '')
        ) as run_one_cycle, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service.last_processed_records = 2
            service._run_workflow_once('wf-resume', 'resume')

        promote_parent.assert_called_once_with(parent_record)
        run_one_cycle.assert_not_called()
        finalize.assert_called_once_with('wf-resume', success=False, reason='parent_pool_promote_failed')

    def test_run_workflow_once_resume_stops_on_failed_round(self):
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
            'email': 'parent@example.com',
            'refresh_token': 'parent-refresh-token',
        }

        with mock.patch.object(service, 'get_latest_parent_record', return_value=parent_record), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'verify_parent_business_context_after_resume', return_value=(True, '')
        ), mock.patch.object(
            service, 'promote_parent_record_to_pool', return_value=(True, '')
        ) as promote_parent, mock.patch.object(
            service, 'run_single_child_round', side_effect=[(True, ''), (True, ''), (False, 'child_register_failed')]
        ) as run_single_child_round, mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service._run_workflow_once('wf-resume', 'resume')

        promote_parent.assert_called_once_with(parent_record)
        self.assertEqual(run_single_child_round.call_count, 3)
        finalize.assert_called_once_with(
            'wf-resume',
            success=False,
            reason='child_round_failed:round=3:child_register_failed',
        )

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


if __name__ == '__main__':
    unittest.main()
