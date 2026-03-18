import asyncio
import importlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


MODULE_NAME = "tools.codex_register.codex_register_service"


class FakeProcess:
    def __init__(self, *, returncode=0, block=False):
        self._returncode_target = returncode
        self.returncode = None
        self._event = threading.Event()
        self._terminated = False
        self._killed = False
        if not block:
            self._event.set()

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if self._event.is_set() and not self._terminated and not self._killed:
            self.returncode = self._returncode_target
            return self.returncode
        return None

    def wait(self):
        self._event.wait(timeout=3)
        if self._killed:
            self.returncode = -9
            return self.returncode
        if self._terminated:
            self.returncode = -15
            return self.returncode
        if self.returncode is None:
            self.returncode = self._returncode_target
        return self.returncode

    def terminate(self):
        self._terminated = True
        self._event.set()

    def kill(self):
        self._killed = True
        self._event.set()

    def release(self):
        self._event.set()


class FakeCursor:
    def __init__(self, *, existing_accounts=None, current_groups=None, insert_ids=None):
        self.existing_accounts = existing_accounts or {}
        self.current_groups = list(current_groups or [])
        self.insert_ids = list(insert_ids or [101])
        self.executed = []
        self._fetchone_value = None
        self._fetchall_value = []
        self.closed = False

    def execute(self, query, params=None):
        params = tuple(params or ())
        self.executed.append((query, params))

        if query.startswith("SELECT id, name, credentials, extra FROM accounts"):
            result = None
            for param in params:
                result = self.existing_accounts.get(param)
                if result is not None:
                    break
            self._fetchone_value = result
        elif query.startswith("SELECT group_id, priority FROM account_groups"):
            self._fetchall_value = list(self.current_groups)
        elif query.startswith("INSERT INTO accounts"):
            next_id = self.insert_ids.pop(0) if self.insert_ids else 999
            self._fetchone_value = (next_id,)
        else:
            self._fetchone_value = None

    def fetchone(self):
        return self._fetchone_value

    def fetchall(self):
        return list(self._fetchall_value)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)
        service_cls = getattr(self.module, "CodexRegisterService")
        store_cls = getattr(self.module, "InMemoryStateStore")
        self.store = store_cls()
        self.service = service_cls(
            state_store=self.store,
            chatgpt_service=SimpleNamespace(),
            workflow_id="wf-test",
            sleep_min=1,
            sleep_max=1,
            auto_run=False,
        )


class StateStoreEnvContractRedTests(unittest.TestCase):
    def setUp(self):
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)

    def test_build_state_store_from_env_returns_in_memory_store(self):
        store = self.module._build_state_store_from_env()
        self.assertIsInstance(store, self.module.InMemoryStateStore)


class JsonlParsingTests(ServiceTestCase):
    def test_parse_accounts_jsonl_and_track_offsets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            line1 = json.dumps({"email": "one@example.com", "access_token": "token-1", "invited": False}) + "\n"
            invalid = "not-json\n"
            line2 = json.dumps({"email": "two@example.com", "access_token": "token-2", "invited": True}) + "\n"
            path.write_bytes((line1 + invalid + line2).encode("utf-8"))
            self.service._accounts_jsonl_path = path

            records, next_offset = self.service._read_accounts_jsonl_records(start_offset=0)

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["email"], "one@example.com")
            self.assertFalse(records[0]["invited"])
            self.assertEqual(records[0]["line_offset"], 0)
            raw = path.read_bytes()
            first_end = raw.index(b"\n") + 1
            self.assertEqual(records[0]["line_end_offset"], first_end)
            second_start = raw.rindex(b'{"email": "two@example.com"')
            self.assertEqual(records[1]["email"], "two@example.com")
            self.assertTrue(records[1]["invited"])
            self.assertEqual(records[1]["line_offset"], second_start)
            self.assertEqual(records[1]["line_end_offset"], len(raw))
            self.assertEqual(next_offset, len((line1 + invalid + line2).encode("utf-8")))

    def test_extract_latest_valid_results_record_uses_new_jsonl_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            first = json.dumps({"email": "old@example.com", "access_token": "old-token", "team_name": "1"}) + "\n"
            path.write_text(first, encoding="utf-8")
            baseline = len(first.encode("utf-8"))
            appended = "garbage\n" + json.dumps(
                {
                    "email": "new@example.com",
                    "access_token": "new-token",
                    "team_name": "2",
                    "invited": True,
                }
            ) + "\n"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(appended)
            self.service._accounts_jsonl_path = path

            record = self.service._extract_latest_valid_results_record(baseline_offset=baseline)

            self.assertIsNotNone(record)
            self.assertEqual(record["email"], "new@example.com")
            self.assertEqual(record["team_name"], "2")
            self.assertTrue(record["invited"])
            self.assertGreater(record["line_end_offset"], baseline)

    def test_list_accounts_for_frontend_normalizes_jsonl_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            line1 = json.dumps(
                {
                    "email": "user1@example.com",
                    "access_token": "at1",
                    "refresh_token": "rt1",
                    "account_id": "acct-1",
                    "source": "gpt-team-new",
                    "created_at": "2026-03-19T00:00:00Z",
                }
            ) + "\n"
            line2 = json.dumps(
                {
                    "email": "user2@example.com",
                    "access_token": "at2",
                }
            ) + "\n"
            path.write_text(line1 + "not-json\n" + line2, encoding="utf-8")
            self.service._accounts_jsonl_path = path

            accounts = self.service._list_accounts_for_frontend()

        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["id"], 1)
        self.assertEqual(accounts[0]["email"], "user1@example.com")
        self.assertEqual(accounts[0]["access_token"], "at1")
        self.assertEqual(accounts[0]["account_id"], "acct-1")
        self.assertEqual(accounts[0]["source"], "gpt-team-new")
        self.assertEqual(accounts[1]["id"], 2)
        self.assertEqual(accounts[1]["email"], "user2@example.com")
        self.assertEqual(accounts[1]["access_token"], "at2")


class GroupRoutingTests(ServiceTestCase):
    def test_group_routing_uses_invited_flag_and_env_values(self):
        with patch.dict(
            os.environ,
            {
                "CODEX_GROUP_IDS_TEAM": "7, 8, bad, 8",
                "CODEX_GROUP_IDS_FREE": "3,4,0,-1,3",
            },
            clear=False,
        ):
            self.assertEqual(self.service._resolve_group_ids_for_record({"invited": True}), [7, 8])
            self.assertEqual(self.service._resolve_group_ids_for_record({"invited": False}), [3, 4])
            self.assertEqual(self.service._resolve_group_ids_for_record({}), [3, 4])


class UpsertHelperTests(ServiceTestCase):
    def test_upsert_account_inserts_new_account_and_binds_free_groups(self):
        cursor = FakeCursor(insert_ids=[501])
        record = {
            "email": "free@example.com",
            "access_token": "access-free",
            "refresh_token": "refresh-free",
            "account_id": "acct-free",
            "invited": False,
            "source": "accounts_jsonl",
        }

        with patch.dict(os.environ, {"CODEX_GROUP_IDS_FREE": "11,12"}, clear=False):
            with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "created")
        queries = [query for query, _params in cursor.executed]
        self.assertTrue(any(query.startswith("INSERT INTO accounts") for query in queries))
        self.assertTrue(any("INSERT INTO account_groups" in query for query in queries))
        insert_account_params = next(params for query, params in cursor.executed if query.startswith("INSERT INTO accounts"))
        self.assertEqual(insert_account_params[0], "free@example.com")
        credentials = insert_account_params[1]
        extra = insert_account_params[2]
        expected_model_mapping = {
            "gpt-5.4": "gpt-5.4",
            "gpt-5.4-mini": "gpt-5.4-mini",
            "gpt-5.4-nano": "gpt-5.4-nano",
            "gpt-5.4-pro": "gpt-5.4-pro",
            "gpt-5": "gpt-5",
            "gpt-5-mini": "gpt-5-mini",
            "gpt-5-nano": "gpt-5-nano",
            "gpt-5-codex": "gpt-5-codex",
            "gpt-5.3-codex": "gpt-5.3-codex",
            "gpt-5.2-codex": "gpt-5.2-codex",
            "gpt-5.1-codex": "gpt-5.1-codex",
            "gpt-5.1-codex-max": "gpt-5.1-codex-max",
            "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
            "codex-mini-latest": "codex-mini-latest",
            "claude-opus*": "gpt-5.4",
            "claude-sonnet*": "gpt-5.3-codex",
            "claude-haiku*": "gpt-5.4-mini",
        }
        self.assertEqual(credentials["email"], "free@example.com")
        self.assertEqual(credentials["account_id"], "acct-free")
        self.assertEqual(credentials["model_mapping"], expected_model_mapping)
        self.assertFalse(extra["invited"])

    def test_upsert_account_updates_existing_when_values_change_preserves_name_and_model_mapping(self):
        existing_model_mapping = {
            "gpt-4.1": "gpt-4.1",
            "custom-model": "custom-target",
        }
        existing = (
            55,
            "existing-account",
            {
                "email": "user@example.com",
                "access_token": "old-token",
                "refresh_token": "old-refresh",
                "model_mapping": existing_model_mapping,
            },
            {"codex_auto_register": True, "invited": False},
        )
        cursor = FakeCursor(existing_accounts={"user@example.com": existing}, current_groups=[])
        record = {
            "email": "user@example.com",
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "invited": True,
            "source": "accounts_jsonl",
        }

        with patch.dict(os.environ, {"CODEX_GROUP_IDS_TEAM": "21"}, clear=False):
            with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "updated")
        queries = [query for query, _params in cursor.executed]
        update_account_statements = [
            (query, params)
            for query, params in cursor.executed
            if query.startswith("UPDATE accounts")
        ]
        self.assertEqual(len(update_account_statements), 1)
        update_query, update_params = update_account_statements[0]
        update_set_clause = update_query.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        self.assertNotRegex(update_set_clause, r"\bname\s*=")
        self.assertTrue(any("INSERT INTO account_groups" in query for query in queries))
        updated_credentials = update_params[0]
        self.assertEqual(updated_credentials["access_token"], "new-token")
        self.assertEqual(updated_credentials["refresh_token"], "new-refresh")
        self.assertEqual(updated_credentials["model_mapping"], existing_model_mapping)

    def test_upsert_account_skips_create_when_email_missing(self):
        cursor = FakeCursor(insert_ids=[501])
        record = {
            "account_id": "acct-only",
            "access_token": "token-only",
        }

        action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "skipped")
        self.assertFalse(any(query.startswith("INSERT INTO accounts") for query, _ in cursor.executed))

    def test_upsert_account_skips_create_when_email_invalid_and_does_not_fallback_to_account_id_name(self):
        cursor = FakeCursor(insert_ids=[501])
        record = {
            "email": "not-an-email",
            "account_id": "acct-fallback",
            "access_token": "token-fallback",
            "refresh_token": "refresh-fallback",
        }

        action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "skipped")
        self.assertFalse(any(query.startswith("INSERT INTO accounts") for query, _ in cursor.executed))

    def test_upsert_account_updates_existing_when_email_malformed_but_account_id_matches(self):
        existing = (
            57,
            "existing-by-account-id",
            {
                "email": "valid@example.com",
                "access_token": "old-token",
                "refresh_token": "old-refresh",
                "account_id": "acct-existing",
            },
            {"codex_auto_register": True, "invited": False},
        )
        cursor = FakeCursor(existing_accounts={"acct-existing": existing}, current_groups=[])
        record = {
            "email": "not-an-email",
            "account_id": "acct-existing",
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "invited": False,
            "source": "accounts_jsonl",
        }

        with patch.dict(os.environ, {"CODEX_GROUP_IDS_FREE": "21"}, clear=False):
            with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "updated")
        self.assertFalse(any(query.startswith("INSERT INTO accounts") for query, _ in cursor.executed))
        update_account_statements = [
            (query, params)
            for query, params in cursor.executed
            if query.startswith("UPDATE accounts")
        ]
        self.assertEqual(len(update_account_statements), 1)
        _update_query, update_params = update_account_statements[0]
        updated_credentials = update_params[0]
        self.assertEqual(updated_credentials["email"], "not-an-email")
        self.assertEqual(updated_credentials["account_id"], "acct-existing")


    def test_upsert_account_updates_existing_without_adding_model_mapping_when_missing(self):
        existing = (
            56,
            "existing-account-no-mapping",
            {
                "email": "nomap@example.com",
                "access_token": "old-token",
                "refresh_token": "old-refresh",
            },
            {"codex_auto_register": True, "invited": False},
        )
        cursor = FakeCursor(existing_accounts={"nomap@example.com": existing}, current_groups=[])
        record = {
            "email": "nomap@example.com",
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "invited": True,
            "source": "accounts_jsonl",
        }

        with patch.dict(os.environ, {"CODEX_GROUP_IDS_TEAM": "21"}, clear=False):
            with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "updated")
        queries = [query for query, _params in cursor.executed]
        update_account_statements = [
            (query, params)
            for query, params in cursor.executed
            if query.startswith("UPDATE accounts")
        ]
        self.assertEqual(len(update_account_statements), 1)
        update_query, update_params = update_account_statements[0]
        update_set_clause = update_query.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        self.assertNotRegex(update_set_clause, r"\bname\s*=")
        updated_credentials = update_params[0]
        self.assertEqual(updated_credentials["access_token"], "new-token")
        self.assertEqual(updated_credentials["refresh_token"], "new-refresh")
        self.assertNotIn("model_mapping", updated_credentials)

    def test_upsert_account_skips_unchanged_existing_account_and_still_binds_groups(self):
        existing_credentials = {
            "email": "same@example.com",
            "access_token": "same-token",
            "refresh_token": "same-refresh",
            "source": "accounts_jsonl",
        }
        existing_extra = {"codex_auto_register": True, "invited": True, "source": "accounts_jsonl", "team_name": "red"}
        existing = (77, "same-account", existing_credentials, existing_extra)
        cursor = FakeCursor(existing_accounts={"same@example.com": existing}, current_groups=[(31, 1)])
        record = {
            "email": "same@example.com",
            "access_token": "same-token",
            "refresh_token": "same-refresh",
            "invited": True,
            "source": "accounts_jsonl",
            "team_name": "red",
        }

        with patch.dict(os.environ, {"CODEX_GROUP_IDS_TEAM": "31,32"}, clear=False):
            with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "skipped")
        queries = [query for query, _params in cursor.executed]
        self.assertFalse(any(query.startswith("UPDATE accounts SET credentials") for query in queries))
        self.assertTrue(any("SELECT group_id, priority FROM account_groups" in query for query in queries))
        self.assertTrue(any("INSERT INTO account_groups" in query for query in queries))


class ProcessingFlowTests(ServiceTestCase):
    def test_process_accounts_jsonl_records_updates_state_counters_and_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"email": "one@example.com", "access_token": "t1", "invited": False}),
                        "not-json",
                        json.dumps({"email": "two@example.com", "access_token": "t2", "invited": True}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path
            cursor = FakeCursor(insert_ids=[1001, 1002])
            conn = FakeConnection(cursor)
            state = self.service._default_state()

            with patch.dict(
                os.environ,
                {"CODEX_GROUP_IDS_FREE": "1", "CODEX_GROUP_IDS_TEAM": "2"},
                clear=False,
            ):
                with patch.object(self.service, "_create_db_connection", return_value=conn):
                    with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                        summary = self.service._process_accounts_jsonl_records(state)

        self.assertEqual(summary["records_seen"], 2)
        self.assertEqual(summary["created"], 2)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(state["total_created"], 2)
        self.assertEqual(state["last_processed_records"], 2)
        self.assertEqual(state["accounts_jsonl_offset"], summary["end_offset"])
        self.assertEqual(state["last_processed_summary"]["created"], 2)
        self.assertTrue(cursor.closed)
        self.assertTrue(conn.closed)

    def test_process_accounts_jsonl_records_stops_at_failed_upsert_and_preserves_offset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            line1 = json.dumps({"email": "one@example.com", "access_token": "t1", "invited": False}) + "\n"
            line2 = json.dumps({"email": "two@example.com", "access_token": "t2", "invited": True}) + "\n"
            path.write_text(line1 + line2, encoding="utf-8")
            self.service._accounts_jsonl_path = path
            conn = FakeConnection(FakeCursor())
            state = self.service._default_state()

            records, _next_offset = self.service._read_accounts_jsonl_records(start_offset=0)
            first_end_offset = records[0]["line_end_offset"]
            second_end_offset = records[1]["line_end_offset"]

            with patch.object(self.service, "_create_db_connection", return_value=conn):
                with patch.object(
                    self.service,
                    "_upsert_account",
                    side_effect=["created", RuntimeError("db write failed")],
                ):
                    summary = self.service._process_accounts_jsonl_records(state)

        self.assertEqual(summary["records_seen"], 2)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["end_offset"], first_end_offset)
        self.assertNotEqual(summary["end_offset"], second_end_offset)
        self.assertEqual(state["accounts_jsonl_offset"], first_end_offset)
        self.assertEqual(state["last_processed_offset"], first_end_offset)
        self.assertEqual(state["last_processed_records"], 1)
        self.assertEqual(state["total_created"], 1)
        self.assertEqual(state["total_failed"], 1)
        self.assertEqual(state["last_processed_summary"]["errors"], ["two@example.com:db write failed"])
        self.assertTrue(conn.closed)

    def test_process_accounts_jsonl_records_updates_existing_when_email_malformed_but_account_id_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "email": "not-an-email",
                        "account_id": "acct-existing",
                        "access_token": "new-token",
                        "refresh_token": "new-refresh",
                        "invited": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            existing = (
                57,
                "existing-by-account-id",
                {
                    "email": "valid@example.com",
                    "access_token": "old-token",
                    "refresh_token": "old-refresh",
                    "account_id": "acct-existing",
                },
                {"codex_auto_register": True, "invited": False},
            )
            cursor = FakeCursor(existing_accounts={"acct-existing": existing}, current_groups=[])
            conn = FakeConnection(cursor)
            state = self.service._default_state()

            with patch.dict(os.environ, {"CODEX_GROUP_IDS_FREE": "21"}, clear=False):
                with patch.object(self.service, "_create_db_connection", return_value=conn):
                    with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                        summary = self.service._process_accounts_jsonl_records(state)

        self.assertEqual(summary["records_seen"], 1)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(state["total_updated"], 1)
        self.assertFalse(any(query.startswith("INSERT INTO accounts") for query, _ in cursor.executed))
        update_account_statements = [
            (query, params)
            for query, params in cursor.executed
            if query.startswith("UPDATE accounts")
        ]
        self.assertEqual(len(update_account_statements), 1)

    def test_process_accounts_jsonl_records_skips_create_when_email_malformed_and_no_existing_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "email": "not-an-email",
                        "account_id": "acct-no-match",
                        "access_token": "token-only",
                        "refresh_token": "refresh-only",
                        "invited": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            cursor = FakeCursor(insert_ids=[9001])
            conn = FakeConnection(cursor)
            state = self.service._default_state()

            with patch.dict(os.environ, {"CODEX_GROUP_IDS_FREE": "21"}, clear=False):
                with patch.object(self.service, "_create_db_connection", return_value=conn):
                    with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                        summary = self.service._process_accounts_jsonl_records(state)

        self.assertEqual(summary["records_seen"], 1)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(state["total_skipped"], 1)
        self.assertFalse(any(query.startswith("INSERT INTO accounts") for query, _ in cursor.executed))
    def test_accounts_path_returns_list_of_accounts_from_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"email": "one@example.com", "access_token": "t1", "source": "gpt-team-new"}),
                        json.dumps({"email": "two@example.com", "access_token": "t2", "source": "get_tokens"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            async def _run():
                return await self.service.handle_path("/accounts")

            result = asyncio.run(_run())

        self.assertTrue(result["success"])
        accounts = result["data"]
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["email"], "one@example.com")
        self.assertEqual(accounts[1]["email"], "two@example.com")


    def test_service_uses_configured_data_dir_for_accounts_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CODEX_REGISTER_DATA_DIR": tmpdir}, clear=False):
                if MODULE_NAME in sys.modules:
                    del sys.modules[MODULE_NAME]
                module = importlib.import_module(MODULE_NAME)
                service_cls = getattr(module, "CodexRegisterService")
                store_cls = getattr(module, "InMemoryStateStore")
                service = service_cls(
                    state_store=store_cls(),
                    chatgpt_service=SimpleNamespace(),
                    workflow_id="wf-test",
                    sleep_min=1,
                    sleep_max=1,
                    auto_run=False,
                )

        self.assertEqual(service._accounts_jsonl_path, pathlib.Path(tmpdir) / "accounts.jsonl")

    def test_list_accounts_for_frontend_includes_plan_and_role_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "email": "parent@example.com",
                        "access_token": "at1",
                        "refresh_token": "rt1",
                        "account_id": "acct-1",
                        "source": "gpt-team-new",
                        "plan_type": "team",
                        "organization_id": "org-1",
                        "workspace_id": "ws-1",
                        "codex_register_role": "parent",
                        "created_at": "2026-03-19T00:00:00Z",
                        "updated_at": "2026-03-19T01:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            accounts = self.service._list_accounts_for_frontend()

        self.assertEqual(accounts[0]["codex_register_role"], "parent")
        self.assertEqual(accounts[0]["plan_type"], "team")
        self.assertEqual(accounts[0]["organization_id"], "org-1")
        self.assertEqual(accounts[0]["workspace_id"], "ws-1")
        self.assertEqual(accounts[0]["updated_at"], "2026-03-19T01:00:00Z")


class GetTokensPersistenceContractTests(unittest.TestCase):
    def test_get_tokens_uses_configured_data_dir(self):
        module_name = "tools.codex_register.get_tokens"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CODEX_REGISTER_DATA_DIR": tmpdir}, clear=False):
                if module_name in sys.modules:
                    del sys.modules[module_name]
                module = importlib.import_module(module_name)

        self.assertEqual(module.RESULTS_FILE, str(pathlib.Path(tmpdir) / "results.txt"))
        self.assertEqual(module.ACCOUNTS_JSONL_FILE, str(pathlib.Path(tmpdir) / "accounts.jsonl"))


class GptTeamPersistenceContractTests(unittest.TestCase):
    def test_gpt_team_uses_configured_data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CODEX_REGISTER_DATA_DIR": tmpdir}, clear=False):
                spec = importlib.util.spec_from_file_location(
                    "tools.codex_register.gpt_team_new_persistence_test",
                    str(pathlib.Path(__file__).resolve().parent / "gpt-team-new.py"),
                )
                module = importlib.util.module_from_spec(spec)
                assert spec.loader is not None
                with patch("builtins.print"):
                    spec.loader.exec_module(module)

        self.assertEqual(module.ACCOUNTS_FILE, str(pathlib.Path(tmpdir) / "accounts.txt"))
        self.assertEqual(module.ACCOUNTS_JSONL_FILE, str(pathlib.Path(tmpdir) / "accounts.jsonl"))
        self.assertEqual(module.INVITE_TRACKER_FILE, str(pathlib.Path(tmpdir) / "invite_tracker.json"))
        self.assertEqual(module.OUTPUT_TOKENS_DIR, str(pathlib.Path(tmpdir) / "output_tokens"))


