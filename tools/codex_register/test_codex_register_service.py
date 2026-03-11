import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import quote

from tools.codex_register import codex_register_service as service


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        return None


class _FakeHandler:
    def __init__(self, path):
        self.path = path
        self.status_code = None
        self.headers = []
        self.wfile = io.BytesIO()

    def send_response(self, code):
        self.status_code = code

    def send_header(self, key, value):
        self.headers.append((key, value))

    def end_headers(self):
        return None

    def _cors_headers(self):
        service.CodexRequestHandler._cors_headers(self)

    def body_json(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


class _FakeThread:
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args
        self.daemon = daemon
        self._alive = False

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive


class CodexRegisterServiceTests(unittest.TestCase):
    def setUp(self):
        self._state = {
            "enabled": service.enabled,
            "last_run": service.last_run,
            "last_success": service.last_success,
            "last_error": service.last_error,
            "total_created": service.total_created,
            "total_updated": service.total_updated,
            "total_skipped": service.total_skipped,
            "sleep_min_global": service.sleep_min_global,
            "sleep_max_global": service.sleep_max_global,
            "tokens_dir_global": service.tokens_dir_global,
            "last_token_email": service.last_token_email,
            "last_created_email": service.last_created_email,
            "last_created_account_id": service.last_created_account_id,
            "last_updated_email": service.last_updated_email,
            "last_updated_account_id": service.last_updated_account_id,
            "last_processed_records": service.last_processed_records,
            "workflow_id": service.workflow_id,
            "job_phase": service.job_phase,
            "waiting_reason": service.waiting_reason,
            "active_workflow_thread": service.active_workflow_thread,
            "recent_logs": list(service.recent_logs),
        }

        service.enabled = False
        service.last_run = None
        service.last_success = None
        service.last_error = ""
        service.total_created = 0
        service.total_updated = 0
        service.total_skipped = 0
        service.sleep_min_global = 0
        service.sleep_max_global = 0
        service.tokens_dir_global = None
        service.last_token_email = ""
        service.last_created_email = ""
        service.last_created_account_id = ""
        service.last_updated_email = ""
        service.last_updated_account_id = ""
        service.last_processed_records = 0
        service.workflow_id = ""
        service.job_phase = service.PHASE_IDLE
        service.waiting_reason = ""
        service.active_workflow_thread = None
        service.recent_logs.clear()

    def tearDown(self):
        service.enabled = self._state["enabled"]
        service.last_run = self._state["last_run"]
        service.last_success = self._state["last_success"]
        service.last_error = self._state["last_error"]
        service.total_created = self._state["total_created"]
        service.total_updated = self._state["total_updated"]
        service.total_skipped = self._state["total_skipped"]
        service.sleep_min_global = self._state["sleep_min_global"]
        service.sleep_max_global = self._state["sleep_max_global"]
        service.tokens_dir_global = self._state["tokens_dir_global"]
        service.last_token_email = self._state["last_token_email"]
        service.last_created_email = self._state["last_created_email"]
        service.last_created_account_id = self._state["last_created_account_id"]
        service.last_updated_email = self._state["last_updated_email"]
        service.last_updated_account_id = self._state["last_updated_account_id"]
        service.last_processed_records = self._state["last_processed_records"]
        service.workflow_id = self._state["workflow_id"]
        service.job_phase = self._state["job_phase"]
        service.waiting_reason = self._state["waiting_reason"]
        service.active_workflow_thread = self._state["active_workflow_thread"]
        service.recent_logs.clear()
        service.recent_logs.extend(self._state["recent_logs"])

    def test_extract_session_access_token_returns_value(self):
        self.assertEqual(service.extract_session_access_token({"accessToken": "abc123"}), "abc123")

    def test_extract_session_access_token_returns_empty_when_missing(self):
        self.assertEqual(service.extract_session_access_token({"user": {"id": "x"}}), "")

    def test_upsert_codex_register_account_uses_upsert_sql(self):
        cur = mock.Mock()

        service.upsert_codex_register_account(
            cur,
            {
                "email": "a@example.com",
                "password": "pw",
                "refresh_token": "rt",
                "session_access_token": "at",
                "account_id": "acct-1",
            },
        )

        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        self.assertIn("INSERT INTO codex_register_accounts", sql)
        self.assertIn("ON CONFLICT (email, source) DO UPDATE", sql)
        self.assertEqual(params[0], "a@example.com")
        self.assertEqual(params[1], "pw")
        self.assertEqual(params[2], "rt")
        self.assertEqual(params[3], "at")
        self.assertEqual(params[4], "acct-1")

    def test_service_default_disabled_until_enable(self):
        self.assertFalse(service.enabled)

    def _build_default_model_mapping(self):
        with mock.patch.dict("os.environ", {"CODEX_MODEL_MAPPING_JSON": ""}, clear=False):
            return service.build_model_mapping()

    def test_build_model_mapping_contains_supported_defaults(self):
        self.assertEqual(self._build_default_model_mapping(), dict(service.DEFAULT_MODEL_MAPPING))

    def test_build_model_mapping_points_claude_to_52_codex(self):
        mapping = self._build_default_model_mapping()

        self.assertEqual(mapping["claude-haiku*"], "gpt-5.2-codex")
        self.assertEqual(mapping["claude-sonnet*"], "gpt-5.2-codex")
        self.assertEqual(mapping["claude-opus*"], "gpt-5.2-codex")

        self.assertEqual(mapping["gpt-5.4"], "gpt-5.4")
        self.assertEqual(mapping["gpt-5.3-codex-spark"], "gpt-5.3-codex-spark")
        self.assertEqual(mapping["gpt-5-codex"], "gpt-5.1-codex")

    def test_build_model_mapping_includes_common_gpt_aliases(self):
        mapping = self._build_default_model_mapping()

        self.assertEqual(mapping["gpt-5"], "gpt-5")
        self.assertEqual(mapping["gpt-5-mini"], "gpt-5-mini")
        self.assertEqual(mapping["gpt-5-nano"], "gpt-5-nano")
        self.assertEqual(mapping["gpt-5.3-codex-spark"], "gpt-5.3-codex-spark")
        self.assertEqual(mapping["gpt-5.3-codex-spark-high"], "gpt-5.3-codex-spark")
        self.assertEqual(mapping["gpt-5-codex"], "gpt-5.1-codex")
        self.assertEqual(mapping["codex-mini-latest"], "gpt-5.1-codex-mini")
        self.assertEqual(mapping["gpt-5.2-codex-xhigh"], "gpt-5.2-codex")

    def test_build_model_mapping_can_be_overridden_by_env(self):
        custom_mapping = '{"claude-haiku*":"spark-max","claude-sonnet*":"gpt-5.4"}'

        with mock.patch.dict("os.environ", {"CODEX_MODEL_MAPPING_JSON": custom_mapping}, clear=False):
            self.assertEqual(
                service.build_model_mapping(),
                {
                    "claude-haiku*": "spark-max",
                    "claude-sonnet*": "gpt-5.4",
                },
            )

    def test_normalize_extra_ignores_transient_timestamp(self):
        before = {
            "codex_auto_register": True,
            "codex_auto_register_updated_at": "2026-03-07T10:00:00Z",
            "codex_auth_file": "a.json",
        }
        after = {
            "codex_auto_register": True,
            "codex_auto_register_updated_at": "2026-03-07T10:01:00Z",
            "codex_auth_file": "a.json",
        }

        self.assertEqual(
            service.normalize_extra_for_compare(before),
            service.normalize_extra_for_compare(after),
        )

    def test_archive_processed_file_moves_json_out_of_active_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp) / "tokens"
            processed_dir = tokens_dir / "processed"
            tokens_dir.mkdir(parents=True)
            source = tokens_dir / "token.json"
            source.write_text('{"email":"a@example.com"}', encoding="utf-8")

            archived = service.archive_processed_file(source, processed_dir)

            self.assertFalse(source.exists())
            self.assertTrue(archived.exists())
            self.assertEqual(archived.parent, processed_dir)

    def test_should_update_account_returns_false_for_timestamp_only_change(self):
        current_credentials = {"email": "a@example.com", "access_token": "same"}
        next_credentials = {"email": "a@example.com", "access_token": "same"}
        current_extra = {
            "codex_auto_register": True,
            "codex_auto_register_updated_at": "2026-03-07T10:00:00Z",
        }
        next_extra = {
            "codex_auto_register": True,
            "codex_auto_register_updated_at": "2026-03-07T10:01:00Z",
        }

        self.assertFalse(
            service.should_update_account(
                current_credentials,
                next_credentials,
                current_extra,
                next_extra,
            )
        )

    def test_compute_group_binding_changes_returns_add_remove_sets(self):
        to_add, to_remove = service.compute_group_binding_changes(
            current_group_ids={1, 2},
            next_group_ids={2, 3},
        )

        self.assertEqual(to_add, {3})
        self.assertEqual(to_remove, {1})

    def test_bind_groups_updates_by_diff_without_wholesale_delete(self):
        cur = _FakeCursor(rows=[(1, 1), (2, 5)])

        service.bind_groups(cur, account_id=42, group_ids=[2, 3])

        sqls = [sql for sql, _params in cur.queries]
        self.assertIn("SELECT group_id, priority FROM account_groups WHERE account_id = %s", sqls)
        self.assertIn("DELETE FROM account_groups WHERE account_id = %s AND group_id = %s", sqls)
        self.assertIn(
            "INSERT INTO account_groups (account_id, group_id, priority, created_at) VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id, group_id) DO UPDATE SET priority = EXCLUDED.priority",
            sqls,
        )
        self.assertIn(
            "UPDATE account_groups SET priority = %s WHERE account_id = %s AND group_id = %s",
            sqls,
        )
        self.assertNotIn("DELETE FROM account_groups WHERE account_id = %s", sqls)

    def test_upsert_account_skips_meaningless_update(self):
        existing = (
            9,
            "codex-a@example.com",
            {
                "email": "a@example.com",
                "access_token": "same",
                "refresh_token": "",
                "id_token": "",
                "source": "codex-auto-register",
                "model_mapping": service.build_model_mapping(),
            },
            {
                "codex_auto_register": True,
                "codex_auto_register_model_mapping": service.build_model_mapping(),
                "codex_auto_register_updated_at": "2026-03-07T10:00:00Z",
            },
        )
        cur = mock.Mock()

        with mock.patch.object(service, "get_existing_account", return_value=existing), mock.patch.object(
            service, "parse_group_ids", return_value=[1]
        ), mock.patch.object(service, "bind_groups") as bind_groups:
            action = service.upsert_account(cur, {"email": "a@example.com", "access_token": "same"})

        self.assertEqual(action, "skipped")
        bind_groups.assert_called_once_with(cur, 9, [1])
        executed_sql = "\n".join(call.args[0] for call in cur.execute.call_args_list)
        self.assertNotIn("UPDATE accounts SET credentials", executed_sql)

    def test_canonical_phase_values_include_required_phases(self):
        self.assertIn(service.PHASE_IDLE, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_RUNNING_CREATE_PARENT, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_WAITING_PARENT_UPGRADE, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_RUNNING_PRE_RESUME_CHECK, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_RUNNING_INVITE_CHILDREN, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_RUNNING_ACCEPT_AND_SWITCH, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_RUNNING_VERIFY_AND_BIND, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_COMPLETED, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_ABANDONED, service.CANONICAL_JOB_PHASES)
        self.assertIn(service.PHASE_FAILED, service.CANONICAL_JOB_PHASES)

    def test_get_status_payload_exposes_single_run_lifecycle_fields(self):
        service.job_phase = service.PHASE_IDLE
        service.workflow_id = ""
        service.waiting_reason = ""

        payload = service.get_status_payload()

        self.assertIn("job_phase", payload)
        self.assertIn("workflow_id", payload)
        self.assertIn("waiting_reason", payload)
        self.assertIn("can_start", payload)
        self.assertIn("can_resume", payload)
        self.assertIn("can_abandon", payload)
        self.assertEqual(payload["job_phase"], service.PHASE_IDLE)
        self.assertIsNone(payload["workflow_id"])
        self.assertIsNone(payload["waiting_reason"])
        self.assertTrue(payload["can_start"])
        self.assertFalse(payload["can_resume"])
        self.assertTrue(payload["can_abandon"])

    def test_get_status_payload_waiting_manual_flags(self):
        service.job_phase = service.PHASE_WAITING_PARENT_UPGRADE
        service.waiting_reason = "parent_upgrade"

        payload = service.get_status_payload()

        self.assertFalse(payload["can_start"])
        self.assertTrue(payload["can_resume"])
        self.assertTrue(payload["can_abandon"])
        self.assertEqual(payload["waiting_reason"], "parent_upgrade")

    def test_run_one_cycle_stage_failure_returns_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp) / "tokens"
            tokens_dir.mkdir(parents=True)
            bad = tokens_dir / "bad.json"

            cur = mock.Mock()
            conn = _FakeConn(cur)

            with mock.patch.object(service, "create_db_connection", return_value=conn), mock.patch.object(
                service,
                "run_codex_once",
                return_value=[(bad, [{"email": "fail@example.com"}])],
            ), mock.patch.object(service, "upsert_account", side_effect=RuntimeError("boom")), mock.patch.object(
                service,
                "archive_processed_file",
            ) as archive_processed_file:
                ok, reason = service.run_one_cycle(tokens_dir)

        self.assertFalse(ok)
        self.assertEqual(reason, "token_process_failed:bad.json")
        archive_processed_file.assert_not_called()

    def test_run_one_cycle_surfaces_script_exit_nonzero_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp) / "tokens"
            tokens_dir.mkdir(parents=True)

            cur = mock.Mock()
            conn = _FakeConn(cur)

            with mock.patch.object(service, "create_db_connection", return_value=conn), mock.patch.object(
                service,
                "run_codex_once",
                side_effect=RuntimeError("script_exit_nonzero:1"),
            ):
                ok, reason = service.run_one_cycle(tokens_dir)

        self.assertFalse(ok)
        self.assertEqual(reason, "script_exit_nonzero:1")
        self.assertEqual(service.last_error, "script_exit_nonzero:1")

    def test_run_codex_once_timeout_raises_script_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp) / "tokens"

            with mock.patch.dict(
                "os.environ",
                {"CODEX_PROXY": "", "CODEX_REGISTER_SUBPROCESS_TIMEOUT": "12"},
                clear=False,
            ), mock.patch.object(
                service.subprocess,
                "run",
                side_effect=service.subprocess.TimeoutExpired(cmd=["python"], timeout=12),
            ), mock.patch.object(service, "append_log") as append_log:
                with self.assertRaisesRegex(RuntimeError, "script_timeout"):
                    service.run_codex_once(tokens_dir)

        append_log.assert_called_with("error", "script_timeout:12")

    def test_run_one_cycle_surfaces_script_timeout_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp) / "tokens"
            tokens_dir.mkdir(parents=True)

            cur = mock.Mock()
            conn = _FakeConn(cur)

            with mock.patch.object(service, "create_db_connection", return_value=conn), mock.patch.object(
                service,
                "run_codex_once",
                side_effect=RuntimeError("script_timeout"),
            ):
                ok, reason = service.run_one_cycle(tokens_dir)

        self.assertFalse(ok)
        self.assertEqual(reason, "script_timeout")
        self.assertEqual(service.last_error, "script_timeout")

    def test_run_one_cycle_archives_successful_file_and_leaves_failed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokens_dir = Path(tmp) / "tokens"
            tokens_dir.mkdir(parents=True)
            good = tokens_dir / "good.json"
            bad = tokens_dir / "bad.json"

            cur = mock.Mock()
            conn = _FakeConn(cur)

            with mock.patch.object(service, "create_db_connection", return_value=conn), mock.patch.object(
                service,
                "run_codex_once",
                return_value=[
                    (good, [{"email": "ok@example.com"}]),
                    (bad, [{"email": "fail@example.com"}]),
                ],
            ), mock.patch.object(service, "upsert_account", side_effect=["skipped", RuntimeError("boom")]), mock.patch.object(
                service,
                "archive_processed_file",
                side_effect=lambda source, processed_dir: processed_dir / source.name,
            ) as archive_processed_file:
                ok, reason = service.run_one_cycle(tokens_dir)

        self.assertFalse(ok)
        self.assertEqual(reason, "token_process_failed:bad.json")
        archived_sources = [call.args[0] for call in archive_processed_file.call_args_list]
        self.assertEqual(archived_sources, [good])

    def test_finalize_workflow_failure_sets_waiting_manual_phase_and_reason_not_failed(self):
        service.workflow_id = "wf-1"
        service.job_phase = service.PHASE_RUNNING_CREATE_PARENT
        service.enabled = True

        service._finalize_workflow_once("wf-1", success=False, reason="db_connect_failed")

        self.assertEqual(service.job_phase, "waiting_manual:db_connect_failed")
        self.assertEqual(service.waiting_reason, "db_connect_failed")
        self.assertNotEqual(service.job_phase, service.PHASE_FAILED)

    def test_start_workflow_once_has_reentry_guard(self):
        service.tokens_dir_global = Path("/tmp")
        with mock.patch.object(service.threading, "Thread", _FakeThread):
            first = service.start_workflow_once(allow_resume=False)
            second = service.start_workflow_once(allow_resume=False)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(service.job_phase, service.PHASE_RUNNING_CREATE_PARENT)

    def test_start_from_completed_enters_running_create_parent(self):
        service.job_phase = service.PHASE_COMPLETED
        service.tokens_dir_global = Path("/tmp")
        with mock.patch.object(service.threading, "Thread", _FakeThread):
            started = service.start_workflow_once(allow_resume=False)

        self.assertTrue(started)
        self.assertEqual(service.job_phase, service.PHASE_RUNNING_CREATE_PARENT)

    def test_resume_from_non_parent_waiting_restarts_from_create_parent(self):
        service.job_phase = "waiting_manual:db_connect_failed"
        service.waiting_reason = "db_connect_failed"
        service.tokens_dir_global = Path("/tmp")

        with mock.patch.object(service.threading, "Thread", _FakeThread):
            started = service.start_workflow_once(allow_resume=True)

        self.assertTrue(started)
        self.assertEqual(service.job_phase, service.PHASE_RUNNING_CREATE_PARENT)

    def test_disable_sets_abandoned_and_prevents_progression(self):
        service.job_phase = service.PHASE_RUNNING_CREATE_PARENT
        service.workflow_id = "wf-1"
        handler = _FakeHandler("/disable")

        service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        self.assertEqual(body["job_phase"], service.PHASE_ABANDONED)
        self.assertFalse(body["can_abandon"])
        self.assertFalse(service.start_workflow_once(allow_resume=False))

    def test_enable_and_run_once_are_start_once_triggers(self):
        enable_handler = _FakeHandler("/enable")
        run_once_handler = _FakeHandler("/run-once")

        with mock.patch.object(service, "start_workflow_once", side_effect=[True, False]) as start_workflow_once:
            service.CodexRequestHandler.do_POST(enable_handler)
            service.CodexRequestHandler.do_POST(run_once_handler)

        self.assertEqual(enable_handler.status_code, 200)
        self.assertEqual(run_once_handler.status_code, 200)
        self.assertEqual(start_workflow_once.call_args_list, [mock.call(allow_resume=False), mock.call(allow_resume=False)])

    def test_resume_http_noop_when_not_waiting_manual(self):
        service.job_phase = service.PHASE_RUNNING_CREATE_PARENT
        service.waiting_reason = ""
        service.workflow_id = "wf-keep"
        handler = _FakeHandler("/resume")

        with mock.patch.object(service, "get_latest_parent_record") as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate"
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once") as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        self.assertEqual(body["job_phase"], service.PHASE_RUNNING_CREATE_PARENT)
        get_latest_parent.assert_not_called()
        evaluate_resume_gate.assert_not_called()
        start_workflow_once.assert_not_called()

    def test_resume_http_rereads_parent_and_advances_when_gate_passes(self):
        service.job_phase = service.PHASE_WAITING_PARENT_UPGRADE
        service.waiting_reason = "parent_upgrade"

        parent_record = {
            "plan_type": "business",
            "organization_id": "org-1",
            "workspace_reachable": True,
            "members_page_accessible": True,
        }

        def _start_resume(*, allow_resume):
            self.assertTrue(allow_resume)
            service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK
            service.waiting_reason = ""
            return True

        handler = _FakeHandler("/resume")
        with mock.patch.object(service, "get_latest_parent_record", return_value=parent_record) as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate", return_value=""
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once", side_effect=_start_resume) as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        get_latest_parent.assert_called_once()
        evaluate_resume_gate.assert_called_once_with(parent_record)
        start_workflow_once.assert_called_once_with(allow_resume=True)
        self.assertEqual(body["job_phase"], service.PHASE_RUNNING_PRE_RESUME_CHECK)
        self.assertFalse(body["can_resume"])

    def test_resume_http_gate_fail_plan_type_missing(self):
        service.job_phase = service.PHASE_WAITING_PARENT_UPGRADE
        service.waiting_reason = "parent_upgrade"
        parent_record = {
            "plan_type": "",
            "organization_id": "org-1",
            "workspace_reachable": True,
            "members_page_accessible": True,
        }
        handler = _FakeHandler("/resume")

        with mock.patch.object(service, "get_latest_parent_record", return_value=parent_record) as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate", return_value="plan_type_missing"
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once") as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        get_latest_parent.assert_called_once()
        evaluate_resume_gate.assert_called_once_with(parent_record)
        start_workflow_once.assert_not_called()
        self.assertEqual(body["job_phase"], "waiting_manual:plan_type_missing")
        self.assertEqual(body["waiting_reason"], "plan_type_missing")
        self.assertTrue(body["can_resume"])

    def test_resume_http_gate_fail_plan_type_invalid(self):
        service.job_phase = service.PHASE_WAITING_PARENT_UPGRADE
        service.waiting_reason = "parent_upgrade"
        parent_record = {
            "plan_type": "personal",
            "organization_id": "org-1",
            "workspace_reachable": True,
            "members_page_accessible": True,
        }
        handler = _FakeHandler("/resume")

        with mock.patch.object(service, "get_latest_parent_record", return_value=parent_record) as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate", return_value="plan_type_invalid"
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once") as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        get_latest_parent.assert_called_once()
        evaluate_resume_gate.assert_called_once_with(parent_record)
        start_workflow_once.assert_not_called()
        self.assertEqual(body["job_phase"], "waiting_manual:plan_type_invalid")
        self.assertEqual(body["waiting_reason"], "plan_type_invalid")

    def test_resume_http_gate_rechecks_parent_reasons_after_first_failure(self):
        service.job_phase = "waiting_manual:plan_type_missing"
        service.waiting_reason = "plan_type_missing"
        parent_record = {
            "plan_type": "",
            "organization_id": "org-1",
            "workspace_reachable": True,
            "members_page_accessible": True,
        }
        handler = _FakeHandler("/resume")

        with mock.patch.object(service, "get_latest_parent_record", return_value=parent_record) as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate", return_value="plan_type_missing"
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once") as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        get_latest_parent.assert_called_once()
        evaluate_resume_gate.assert_called_once_with(parent_record)
        start_workflow_once.assert_not_called()
        self.assertEqual(body["job_phase"], "waiting_manual:plan_type_missing")
        self.assertEqual(body["waiting_reason"], "plan_type_missing")

    def test_resume_http_parent_gate_reason_advances_when_gate_passes(self):
        service.job_phase = "waiting_manual:plan_type_missing"
        service.waiting_reason = "plan_type_missing"

        parent_record = {
            "plan_type": "business",
            "organization_id": "org-1",
            "workspace_reachable": True,
            "members_page_accessible": True,
        }

        def _start_resume(*, allow_resume):
            self.assertTrue(allow_resume)
            service.job_phase = service.PHASE_RUNNING_PRE_RESUME_CHECK
            service.waiting_reason = ""
            return True

        handler = _FakeHandler("/resume")
        with mock.patch.object(service, "get_latest_parent_record", return_value=parent_record) as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate", return_value=""
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once", side_effect=_start_resume) as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        get_latest_parent.assert_called_once()
        evaluate_resume_gate.assert_called_once_with(parent_record)
        start_workflow_once.assert_called_once_with(allow_resume=True)
        self.assertEqual(body["job_phase"], service.PHASE_RUNNING_PRE_RESUME_CHECK)

    def test_resume_http_non_parent_waiting_reason_skips_parent_gate(self):
        service.job_phase = "waiting_manual:db_connect_failed"
        service.waiting_reason = "db_connect_failed"

        def _start_resume(*, allow_resume):
            self.assertTrue(allow_resume)
            service.job_phase = service.PHASE_RUNNING_CREATE_PARENT
            service.waiting_reason = ""
            return True

        handler = _FakeHandler("/resume")
        with mock.patch.object(service, "get_latest_parent_record") as get_latest_parent, mock.patch.object(
            service, "evaluate_resume_gate"
        ) as evaluate_resume_gate, mock.patch.object(service, "start_workflow_once", side_effect=_start_resume) as start_workflow_once:
            service.CodexRequestHandler.do_POST(handler)

        body = handler.body_json()
        self.assertEqual(handler.status_code, 200)
        get_latest_parent.assert_not_called()
        evaluate_resume_gate.assert_not_called()
        start_workflow_once.assert_called_once_with(allow_resume=True)
        self.assertEqual(body["job_phase"], service.PHASE_RUNNING_CREATE_PARENT)

    def test_evaluate_resume_gate_returns_reason_codes(self):
        service.tokens_dir_global = Path("/tmp")

        self.assertEqual(service.evaluate_resume_gate({}), "plan_type_missing")
        self.assertEqual(
            service.evaluate_resume_gate({"plan_type": "personal", "organization_id": "org-1"}),
            "plan_type_invalid",
        )
        self.assertEqual(
            service.evaluate_resume_gate({"plan_type": "business", "organization_id": ""}),
            "organization_id_missing",
        )
        self.assertEqual(
            service.evaluate_resume_gate(
                {
                    "plan_type": "business",
                    "organization_id": "org-1",
                    "workspace_reachable": False,
                }
            ),
            "workspace_unreachable",
        )
        self.assertEqual(
            service.evaluate_resume_gate(
                {
                    "plan_type": "business",
                    "organization_id": "org-1",
                    "workspace_reachable": True,
                    "members_page_accessible": False,
                }
            ),
            "members_page_inaccessible",
        )

    def test_get_email_and_token_uses_custom_domain(self):
        with mock.patch.dict("os.environ", {"CODEX_MAIL_DOMAIN": "mail.example.com"}, clear=False):
            email, worker_token, password = service.get_email_and_token()

        self.assertTrue(email.endswith("@mail.example.com"))
        self.assertEqual(worker_token, "worker")
        self.assertTrue(password)

    def test_get_oai_code_returns_code_when_worker_returns_200(self):
        requests = mock.Mock()
        requests.get.return_value = mock.Mock(status_code=200, json=mock.Mock(return_value={"ok": True, "code": "123456"}))

        def fake_get_env(name, default=None, required=False):
            mapping = {
                "CODEX_MAIL_WORKER_BASE_URL": "https://worker.example.com",
                "CODEX_MAIL_WORKER_TOKEN": "secret-token",
                "CODEX_MAIL_POLL_SECONDS": "1",
                "CODEX_MAIL_POLL_MAX_ATTEMPTS": "3",
            }
            value = mapping.get(name, default or "")
            if required and not value:
                raise RuntimeError(f"missing env:{name}")
            return value

        with mock.patch.object(service, "get_requests_module", return_value=requests), mock.patch.object(
            service, "get_env", side_effect=fake_get_env
        ), mock.patch.object(service.time, "sleep") as sleep_mock:
            code = service.get_oai_code("unused", "oc123@mail.example.com")

        self.assertEqual(code, "123456")
        self.assertIn("/v1/code?email=oc123%40mail.example.com", requests.get.call_args.kwargs["url"])
        self.assertEqual(requests.get.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        sleep_mock.assert_not_called()

    def test_get_oai_code_retries_on_404_then_succeeds(self):
        requests = mock.Mock()
        requests.get.side_effect = [
            mock.Mock(status_code=404, json=mock.Mock(return_value={"ok": False, "error": "code_not_ready"})),
            mock.Mock(status_code=200, json=mock.Mock(return_value={"ok": True, "code": "654321"})),
        ]

        def fake_get_env(name, default=None, required=False):
            mapping = {
                "CODEX_MAIL_WORKER_BASE_URL": "https://worker.example.com",
                "CODEX_MAIL_WORKER_TOKEN": "secret-token",
                "CODEX_MAIL_POLL_SECONDS": "1",
                "CODEX_MAIL_POLL_MAX_ATTEMPTS": "4",
            }
            value = mapping.get(name, default or "")
            if required and not value:
                raise RuntimeError(f"missing env:{name}")
            return value

        with mock.patch.object(service, "get_requests_module", return_value=requests), mock.patch.object(
            service, "get_env", side_effect=fake_get_env
        ), mock.patch.object(service.time, "sleep") as sleep_mock:
            code = service.get_oai_code("unused", "oc123@mail.example.com")

        self.assertEqual(code, "654321")
        self.assertEqual(requests.get.call_count, 2)
        sleep_mock.assert_called_once_with(1)

    def test_get_oai_code_returns_empty_on_401(self):
        requests = mock.Mock()
        requests.get.return_value = mock.Mock(status_code=401, json=mock.Mock(return_value={"ok": False, "error": "unauthorized"}))

        def fake_get_env(name, default=None, required=False):
            mapping = {
                "CODEX_MAIL_WORKER_BASE_URL": "https://worker.example.com",
                "CODEX_MAIL_WORKER_TOKEN": "secret-token",
                "CODEX_MAIL_POLL_SECONDS": "1",
                "CODEX_MAIL_POLL_MAX_ATTEMPTS": "2",
            }
            value = mapping.get(name, default or "")
            if required and not value:
                raise RuntimeError(f"missing env:{name}")
            return value

        with mock.patch.object(service, "get_requests_module", return_value=requests), mock.patch.object(
            service, "get_env", side_effect=fake_get_env
        ), mock.patch.object(service.time, "sleep") as sleep_mock:
            code = service.get_oai_code("unused", "oc123@mail.example.com")

        self.assertEqual(code, "")
        sleep_mock.assert_not_called()

    def test_run_prints_custom_domain_mail_label(self):
        fake_session = mock.Mock()
        fake_session.get.side_effect = [
            mock.Mock(text="loc=SG\n"),
            mock.Mock(status_code=200),
        ]
        fake_session.cookies.get.return_value = "did-1"

        fake_requests = mock.Mock()
        fake_requests.Session.return_value = fake_session
        fake_requests.post.return_value = mock.Mock(status_code=503)

        with mock.patch.object(service, "get_requests_module", return_value=fake_requests), mock.patch.object(
            service, "get_email_and_token", return_value=("oc123@mail.example.com", "worker", "pw")
        ), mock.patch("builtins.print") as print_mock:
            result = service.run(None)

        self.assertIsNone(result)
        printed = "\n".join(" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list)
        self.assertIn("成功获取自定义邮箱与授权: oc123@mail.example.com", printed)

    def test_get_oai_code_logs_worker_poll_status_lines(self):
        requests = mock.Mock()
        requests.get.side_effect = [
            mock.Mock(status_code=404, json=mock.Mock(return_value={"ok": False, "error": "code_not_ready"})),
            mock.Mock(status_code=404, json=mock.Mock(return_value={"ok": False, "error": "code_not_ready"})),
            mock.Mock(status_code=200, json=mock.Mock(return_value={"ok": True, "code": "654321"})),
        ]

        def fake_get_env(name, default=None, required=False):
            mapping = {
                "CODEX_MAIL_WORKER_BASE_URL": "https://worker.example.com",
                "CODEX_MAIL_WORKER_TOKEN": "secret-token",
                "CODEX_MAIL_POLL_SECONDS": "1",
                "CODEX_MAIL_POLL_MAX_ATTEMPTS": "4",
            }
            value = mapping.get(name, default or "")
            if required and not value:
                raise RuntimeError(f"missing env:{name}")
            return value

        with mock.patch.object(service, "get_requests_module", return_value=requests), mock.patch.object(
            service, "get_env", side_effect=fake_get_env
        ), mock.patch.object(service.time, "sleep"), mock.patch("builtins.print") as print_mock:
            code = service.get_oai_code("unused", "oc123@mail.example.com")

        self.assertEqual(code, "654321")
        lines = [" ".join(str(arg) for arg in call.args) for call in print_mock.call_args_list]
        status_lines = [line for line in lines if "Worker 轮询状态" in line]
        self.assertEqual(status_lines, [
            " [poll#1] Worker 轮询状态: 404",
            " [poll#2] Worker 轮询状态: 404",
            " [poll#3] Worker 轮询状态: 200",
        ])
        requests.get.assert_any_call(
            url=f"https://worker.example.com/v1/code?email={quote('oc123@mail.example.com')}",
            headers={"Accept": "application/json", "Authorization": "Bearer secret-token"},
            proxies=None,
            impersonate="chrome",
            timeout=15,
        )

    def test_main_removes_infinite_worker_loop(self):
        args = SimpleNamespace(
            register_only=False,
            proxy=None,
            once=False,
            sleep_min=5,
            sleep_max=30,
            tokens_dir="",
        )

        fake_server = mock.Mock()

        def fake_get_env(name, default=None, required=False):
            mapping = {
                "CODEX_SLEEP_MIN": "5",
                "CODEX_SLEEP_MAX": "30",
                "CODEX_HTTP_PORT": "5000",
            }
            return mapping.get(name, default or "")

        with mock.patch("argparse.ArgumentParser.parse_args", return_value=args), mock.patch.object(
            service, "get_env", side_effect=fake_get_env
        ), mock.patch.object(service.threading, "Thread") as thread_cls, mock.patch.object(
            service, "ThreadingHTTPServer", return_value=fake_server
        ):
            service.main()

        thread_cls.assert_not_called()
        fake_server.serve_forever.assert_called_once()


if __name__ == "__main__":
    unittest.main()
