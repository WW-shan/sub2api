import unittest
from unittest import mock

from tools.codex_register import smoke_test_codex_register_flow as smoke


class _FakeCursor:
    def __init__(self, fetchone_values):
        self.fetchone_values = list(fetchone_values)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if not self.fetchone_values:
            return None
        return self.fetchone_values.pop(0)

    def close(self):
        return None


class _FakeConn:
    def __init__(self, fetchone_values):
        self.cursor_obj = _FakeCursor(fetchone_values)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        return None


class SmokeTestCodexRegisterFlowTests(unittest.TestCase):
    def test_wait_for_phase_returns_matching_status(self):
        statuses = iter(
            [
                {"job_phase": "running:create_parent"},
                {"job_phase": "waiting_manual:parent_upgrade", "waiting_reason": "parent_upgrade"},
            ]
        )

        with mock.patch.object(smoke, "fetch_status", side_effect=lambda *_args, **_kwargs: next(statuses)):
            status = smoke.wait_for_phase(
                "http://127.0.0.1:5000",
                target_phases={"waiting_manual:parent_upgrade"},
                timeout_seconds=10,
                interval_seconds=1,
            )

        self.assertEqual(status["job_phase"], "waiting_manual:parent_upgrade")

    def test_wait_for_phase_raises_timeout(self):
        with mock.patch.object(smoke, "fetch_status", return_value={"job_phase": "running:create_parent"}):
            with self.assertRaisesRegex(RuntimeError, "timeout waiting for phases"):
                smoke.wait_for_phase(
                    "http://127.0.0.1:5000",
                    target_phases={"completed"},
                    timeout_seconds=0,
                    interval_seconds=1,
                )

    def test_verify_database_state_raises_when_parent_metadata_incomplete(self):
        conn = _FakeConn(
            [
                ("parent@example.com", "business", "org-1", "", True, True),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "parent metadata incomplete"):
            smoke.verify_database_state(conn, min_children=1)

    def test_verify_database_state_raises_when_child_invite_acceptance_incomplete(self):
        conn = _FakeConn(
            [
                ("parent@example.com", "business", "org-1", "ws-business", True, True),
                (2,),
                (0,),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "child invite acceptance incomplete"):
            smoke.verify_database_state(conn, min_children=1)

    def test_verify_database_state_raises_when_business_login_binding_incomplete(self):
        conn = _FakeConn(
            [
                ("parent@example.com", "business", "org-1", "ws-business", True, True),
                (2,),
                (2,),
                (0,),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "business login binding incomplete"):
            smoke.verify_database_state(conn, min_children=1)

    def test_verify_database_state_accepts_valid_parent_and_children(self):
        conn = _FakeConn(
            [
                ("parent@example.com", "business", "org-1", "ws-business", True, True),
                (2,),
                (2,),
                (2,),
            ]
        )

        summary = smoke.verify_database_state(conn, min_children=2)

        self.assertEqual(summary["parent_email"], "parent@example.com")
        self.assertEqual(summary["child_register_count"], 2)
        self.assertEqual(summary["child_invite_accept_count"], 2)
        self.assertEqual(summary["child_pool_count"], 2)

    def test_run_smoke_flow_calls_enable_resume_and_db_check(self):
        args = smoke.parse_args(
            [
                "--base-url",
                "http://127.0.0.1:5000",
                "--timeout",
                "5",
                "--interval",
                "1",
                "--min-children",
                "1",
            ]
        )

        wait_values = [
            {"job_phase": "waiting_manual:parent_upgrade", "waiting_reason": "parent_upgrade"},
            {"job_phase": "completed", "waiting_reason": ""},
        ]

        out_lines = []
        with mock.patch.object(smoke, "post_action") as post_action, mock.patch.object(
            smoke, "wait_for_phase", side_effect=wait_values
        ) as wait_for_phase, mock.patch.object(
            smoke, "create_db_connection", return_value=object()
        ) as create_db_connection, mock.patch.object(
            smoke, "verify_database_state", return_value={"child_pool_count": 1}
        ) as verify_database_state:
            exit_code = smoke.run_smoke_flow(args, out=out_lines.append)

        self.assertEqual(exit_code, 0)
        self.assertEqual(post_action.call_args_list, [mock.call("http://127.0.0.1:5000", "/enable"), mock.call("http://127.0.0.1:5000", "/resume")])
        self.assertEqual(wait_for_phase.call_count, 2)
        create_db_connection.assert_called_once()
        verify_database_state.assert_called_once()


if __name__ == "__main__":
    unittest.main()
