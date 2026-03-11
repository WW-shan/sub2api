import io
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
    def __init__(self, path: str):
        self.path = path
        self.response_code = None
        self.headers = []
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.response_code = code

    def _cors_headers(self):
        return None

    def send_header(self, key, value):
        self.headers.append((key, value))

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
        service.tokens_dir_global = Path('/tmp')

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

    def test_invite_recent_children_treats_409_as_invited(self):
        conn = _FakeConn([[('child1@example.com',)]])

        http_409 = urllib.error.HTTPError(
            url='https://chatgpt.com/backend-api/accounts/parent-1/invites',
            code=409,
            msg='Conflict',
            hdrs=None,
            fp=io.BytesIO(b'{}'),
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

        with mock.patch.object(service, 'get_latest_parent_record', return_value=parent_record), mock.patch.object(
            service, 'evaluate_resume_gate', return_value=''
        ), mock.patch.object(
            service, 'run_one_cycle', return_value=(True, '')
        ), mock.patch.object(
            service, 'invite_recent_children', return_value=(True, '')
        ) as invite_recent_children, mock.patch.object(
            service, 'validate_recent_child_records', return_value=(True, '')
        ), mock.patch.object(
            service, 'promote_recent_child_records_to_pool', return_value=(True, '')
        ), mock.patch.object(
            service, '_finalize_workflow_once'
        ) as finalize:
            service.last_processed_records = 2
            service._run_workflow_once('wf-resume', 'resume')

        invite_recent_children.assert_called_once_with(parent_record, expected_count=2)
        finalize.assert_called_once_with('wf-resume', success=True, reason='')

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


if __name__ == '__main__':
    unittest.main()
