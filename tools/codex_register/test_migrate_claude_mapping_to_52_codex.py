import sys
import unittest
from unittest import mock


from tools.codex_register import migrate_claude_mapping_to_52_codex as migration


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return list(self._rows)


class _FailingCursor(_FakeCursor):
    def __init__(self, rows, fail_on_update_index=1):
        super().__init__(rows)
        self._update_count = 0
        self._fail_on_update_index = fail_on_update_index

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        if sql.startswith("UPDATE accounts SET"):
            self._update_count += 1
            if self._update_count == self._fail_on_update_index:
                raise RuntimeError("forced update failure")


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.autocommit = True
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FailingConn(_FakeConn):
    def __init__(self, rows, fail_on_update_index=1):
        self.cursor_obj = _FailingCursor(rows, fail_on_update_index=fail_on_update_index)
        self.autocommit = True
        self.committed = False
        self.rolled_back = False


class MigrateClaudeMappingTests(unittest.TestCase):
    def test_rewrite_claude_mapping_changes_only_claude_keys(self):
        mapping = {
            "claude-sonnet*": "legacy-a",
            "claude-opus*": "legacy-b",
            "gpt-5": "gpt-5",
            "other": "x",
        }

        rewritten, changed = migration.rewrite_claude_mapping(mapping)

        self.assertTrue(changed)
        self.assertEqual(rewritten["claude-sonnet*"], "gpt-5.2-codex")
        self.assertEqual(rewritten["claude-opus*"], "gpt-5.2-codex")
        self.assertEqual(rewritten["gpt-5"], "gpt-5")
        self.assertEqual(rewritten["other"], "x")

    def test_rewrite_claude_mapping_unchanged_when_no_claude_keys(self):
        mapping = {
            "gpt-5": "gpt-5",
            "gpt-5.4": "gpt-5.4",
        }

        rewritten, changed = migration.rewrite_claude_mapping(mapping)

        self.assertFalse(changed)
        self.assertEqual(rewritten, mapping)

    def test_dry_run_mode_does_not_execute_updates(self):
        rows = [
            (
                1,
                {"model_mapping": {"claude-sonnet*": "old", "gpt-5": "gpt-5"}},
                {"codex_auto_register_model_mapping": {"claude-opus*": "old", "x": "y"}},
            ),
            (
                2,
                {"model_mapping": {"gpt-5": "gpt-5"}},
                {"codex_auto_register_model_mapping": {"gpt-5.4": "gpt-5.4"}},
            ),
        ]
        conn = _FakeConn(rows)

        with mock.patch.object(migration, "pg_json", side_effect=lambda value: value):
            counters = migration.run_migration(conn, apply=False, out=lambda *_args: None)

        update_queries = [q for q in conn.cursor_obj.queries if q[0].startswith("UPDATE accounts SET")]
        self.assertEqual(update_queries, [])
        self.assertFalse(conn.committed)
        self.assertFalse(conn.rolled_back)
        self.assertEqual(
            counters,
            {
                "scanned": 2,
                "changed": 1,
                "unchanged": 1,
                "updated": 0,
            },
        )

    def test_apply_mode_updates_only_changed_rows(self):
        rows = [
            (
                10,
                {"model_mapping": {"claude-haiku*": "legacy", "gpt-5": "gpt-5"}},
                {"codex_auto_register_model_mapping": {"gpt-5.4": "gpt-5.4"}},
            ),
            (
                20,
                {"model_mapping": {"gpt-5": "gpt-5"}},
                {"codex_auto_register_model_mapping": {"claude-opus*": "legacy"}},
            ),
            (
                30,
                {"model_mapping": {"gpt-5": "gpt-5"}},
                {"codex_auto_register_model_mapping": {"gpt-5.4": "gpt-5.4"}},
            ),
        ]
        conn = _FakeConn(rows)

        with mock.patch.object(migration, "pg_json", side_effect=lambda value: value):
            counters = migration.run_migration(conn, apply=True, out=lambda *_args: None)

        update_queries = [q for q in conn.cursor_obj.queries if q[0].startswith("UPDATE accounts SET")]
        self.assertEqual(len(update_queries), 2)
        updated_ids = [params[2] for _sql, params in update_queries]
        self.assertEqual(updated_ids, [10, 20])
        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)
        self.assertTrue(conn.autocommit)
        self.assertEqual(
            counters,
            {
                "scanned": 3,
                "changed": 2,
                "unchanged": 1,
                "updated": 2,
            },
        )

    def test_non_dict_missing_fields_are_safely_handled(self):
        rows = [
            (1, None, None),
            (2, "not-json", {"codex_auto_register_model_mapping": "bad"}),
            (3, {"model_mapping": ["not", "dict"]}, {"codex_auto_register_model_mapping": {"gpt-5": "gpt-5"}}),
            (
                4,
                {"model_mapping": {"claude-sonnet*": "legacy"}},
                {"codex_auto_register_model_mapping": {"claude-opus*": "legacy"}},
            ),
        ]
        conn = _FakeConn(rows)

        with mock.patch.object(migration, "pg_json", side_effect=lambda value: value):
            counters = migration.run_migration(conn, apply=True, out=lambda *_args: None)

        update_queries = [q for q in conn.cursor_obj.queries if q[0].startswith("UPDATE accounts SET")]
        self.assertEqual(len(update_queries), 1)
        self.assertEqual(update_queries[0][1][2], 4)
        self.assertEqual(
            counters,
            {
                "scanned": 4,
                "changed": 1,
                "unchanged": 3,
                "updated": 1,
            },
        )

    def test_apply_failure_rolls_back_and_restores_autocommit(self):
        rows = [
            (
                11,
                {"model_mapping": {"claude-sonnet*": "legacy"}},
                {"codex_auto_register_model_mapping": {"gpt-5": "gpt-5"}},
            )
        ]
        conn = _FailingConn(rows)

        with mock.patch.object(migration, "pg_json", side_effect=lambda value: value):
            with self.assertRaisesRegex(RuntimeError, "forced update failure"):
                migration.run_migration(conn, apply=True, out=lambda *_args: None)

        self.assertFalse(conn.committed)
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.autocommit)

    def test_apply_preserves_malformed_top_level_credentials_and_extra(self):
        rows = [
            (
                1,
                "not-json",
                {"codex_auto_register_model_mapping": {"claude-opus*": "legacy"}},
            ),
            (
                2,
                {"model_mapping": {"claude-sonnet*": "legacy"}},
                "also-not-json",
            ),
        ]
        conn = _FakeConn(rows)

        with mock.patch.object(migration, "pg_json", side_effect=lambda value: value):
            counters = migration.run_migration(conn, apply=True, out=lambda *_args: None)

        update_queries = [q for q in conn.cursor_obj.queries if q[0].startswith("UPDATE accounts SET")]
        self.assertEqual(len(update_queries), 2)

        first_params = update_queries[0][1]
        self.assertEqual(first_params[0], "not-json")
        self.assertEqual(
            first_params[1],
            {"codex_auto_register_model_mapping": {"claude-opus*": "gpt-5.2-codex"}},
        )

        second_params = update_queries[1][1]
        self.assertEqual(second_params[1], "also-not-json")
        self.assertEqual(
            second_params[0],
            {"model_mapping": {"claude-sonnet*": "gpt-5.2-codex"}},
        )

        self.assertEqual(
            counters,
            {
                "scanned": 2,
                "changed": 2,
                "unchanged": 0,
                "updated": 2,
            },
        )

    def test_query_includes_expected_scope_filters(self):
        conn = _FakeConn([])

        migration.run_migration(conn, apply=False, out=lambda *_args: None)

        self.assertTrue(conn.cursor_obj.queries)
        select_sql, params = conn.cursor_obj.queries[0]
        self.assertIsNone(params)
        self.assertIn("FROM accounts", select_sql)
        self.assertIn("platform = 'openai'", select_sql)
        self.assertIn("type = 'oauth'", select_sql)

    def test_parse_args_defaults_to_non_apply_mode(self):
        with mock.patch.object(sys, "argv", ["migrate_claude_mapping_to_52_codex.py"]):
            args = migration.parse_args()

        self.assertFalse(args.apply)
        self.assertFalse(args.dry_run)

    def test_parse_args_rejects_mutually_exclusive_apply_and_dry_run(self):
        with mock.patch.object(sys, "argv", ["migrate_claude_mapping_to_52_codex.py", "--apply", "--dry-run"]):
            with self.assertRaises(SystemExit):
                migration.parse_args()


if __name__ == "__main__":
    unittest.main()
