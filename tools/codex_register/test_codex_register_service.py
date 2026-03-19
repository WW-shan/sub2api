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
from unittest.mock import AsyncMock, patch


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
    def __init__(self, *, existing_accounts=None, current_groups=None, insert_ids=None, list_account_rows=None):
        self.existing_accounts = existing_accounts or {}
        self.current_groups = list(current_groups or [])
        self.insert_ids = list(insert_ids or [101])
        self.list_account_rows = list(list_account_rows or [])
        self.executed = []
        self._fetchone_value = None
        self._fetchall_value = []
        self.closed = False

    def execute(self, query, params=None):
        params = tuple(params or ())
        self.executed.append((query, params))

        if query.startswith("SELECT id, credentials, extra, created_at, updated_at FROM accounts"):
            self._fetchall_value = list(self.list_account_rows)
        elif query.startswith("SELECT id, name, credentials, extra FROM accounts"):
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


class FakeWorker:
    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive


class GenerationAwareWorker:
    def __init__(self, service, generation, active=True):
        self._service = service
        self.generation = generation
        self._active = active

    def is_alive(self):
        return self._active and self._service._loop_worker_generation == self.generation


class ControllableStartLoopWorker:
    def __init__(self, service):
        self.service = service
        self.calls = []
        self.created = []

    def __call__(self, generation):
        self.calls.append(generation)
        worker = GenerationAwareWorker(self.service, generation)
        self.created.append(worker)
        return worker, ""


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

    def test_list_accounts_for_frontend_reads_persisted_codex_accounts_from_db(self):
        cursor = FakeCursor(
            list_account_rows=[
                (
                    17,
                    {
                        "email": "Parent@Example.com",
                        "access_token": "at-parent",
                        "refresh_token": "rt-parent",
                        "account_id": "acct-parent",
                        "source": "gpt-team-new",
                        "plan_type": "team",
                        "organization_id": "org-1",
                        "workspace_id": "ws-1",
                        "codex_register_role": "parent",
                    },
                    {
                        "codex_auto_register": True,
                        "source": "gpt-team-new",
                        "created_at": "2026-03-19T00:00:00Z",
                    },
                    "2026-03-18T12:00:00+00:00",
                    "2026-03-19T01:00:00+00:00",
                ),
                (
                    18,
                    {
                        "email": "child@example.com",
                        "access_token": "at-child",
                    },
                    {
                        "codex_auto_register": True,
                        "source": "accounts_jsonl",
                        "updated_at": "2026-03-19T02:00:00Z",
                    },
                    "2026-03-19T00:30:00+00:00",
                    "2026-03-19T01:30:00+00:00",
                ),
                (
                    19,
                    {
                        "access_token": "missing-email",
                    },
                    {
                        "codex_auto_register": True,
                    },
                    "2026-03-19T00:45:00+00:00",
                    "2026-03-19T01:45:00+00:00",
                ),
            ]
        )
        conn = FakeConnection(cursor)

        with patch.object(self.service, "_create_db_connection", return_value=conn):
            accounts = self.service._list_accounts_for_frontend()

        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]["id"], 17)
        self.assertEqual(accounts[0]["email"], "parent@example.com")
        self.assertEqual(accounts[0]["refresh_token"], "rt-parent")
        self.assertEqual(accounts[0]["access_token"], "at-parent")
        self.assertEqual(accounts[0]["account_id"], "acct-parent")
        self.assertEqual(accounts[0]["source"], "gpt-team-new")
        self.assertEqual(accounts[0]["codex_register_role"], "parent")
        self.assertEqual(accounts[0]["plan_type"], "team")
        self.assertEqual(accounts[0]["organization_id"], "org-1")
        self.assertEqual(accounts[0]["workspace_id"], "ws-1")
        self.assertEqual(accounts[0]["created_at"], "2026-03-19T00:00:00Z")
        self.assertEqual(accounts[0]["updated_at"], "2026-03-19T01:00:00+00:00")
        self.assertEqual(accounts[1]["id"], 18)
        self.assertEqual(accounts[1]["email"], "child@example.com")
        self.assertEqual(accounts[1]["refresh_token"], "")
        self.assertEqual(accounts[1]["account_id"], None)
        self.assertEqual(accounts[1]["source"], "accounts_jsonl")
        self.assertIsNone(accounts[1]["codex_register_role"])
        self.assertIsNone(accounts[1]["plan_type"])
        self.assertIsNone(accounts[1]["organization_id"])
        self.assertIsNone(accounts[1]["workspace_id"])
        self.assertEqual(accounts[1]["created_at"], "2026-03-19T00:30:00+00:00")
        self.assertEqual(accounts[1]["updated_at"], "2026-03-19T02:00:00Z")
        self.assertTrue(cursor.closed)
        self.assertTrue(conn.closed)
        list_query, list_params = cursor.executed[0]
        self.assertIn("COALESCE(extra ->> 'codex_auto_register', 'false') = 'true'", list_query)
        self.assertEqual(list_params, ())


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
        self.assertEqual(insert_account_params[0], "codex-acct-free")
        credentials = insert_account_params[1]
        extra = insert_account_params[2]
        self.assertEqual(credentials["email"], "free@example.com")
        self.assertEqual(credentials["account_id"], "acct-free")
        self.assertFalse(extra["invited"])

    def test_upsert_account_updates_existing_when_values_change(self):
        existing = (
            55,
            "existing-account",
            {"email": "user@example.com", "access_token": "old-token", "refresh_token": "old-refresh"},
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
        self.assertTrue(any(query.startswith("UPDATE accounts SET credentials") for query in queries))
        self.assertTrue(any("INSERT INTO account_groups" in query for query in queries))


    def test_upsert_account_persists_plan_and_role_metadata(self):
        cursor = FakeCursor(insert_ids=[777])
        record = {
            "email": "team@example.com",
            "access_token": "access-team",
            "refresh_token": "refresh-team",
            "account_id": "acct-team",
            "plan_type": "team",
            "organization_id": "org-team",
            "workspace_id": "ws-team",
            "codex_register_role": "parent",
            "invited": False,
            "source": "gpt-team-new",
        }

        with patch.dict(os.environ, {"CODEX_GROUP_IDS_TEAM": "41"}, clear=False):
            with patch.object(self.service, "_pg_json", side_effect=lambda value: value):
                action = self.service._upsert_account(cursor, record)

        self.assertEqual(action, "created")
        insert_account_params = next(params for query, params in cursor.executed if query.startswith("INSERT INTO accounts"))
        credentials = insert_account_params[1]
        self.assertEqual(credentials["plan_type"], "team")
        self.assertEqual(credentials["organization_id"], "org-team")
        self.assertEqual(credentials["workspace_id"], "ws-team")
        self.assertEqual(credentials["codex_register_role"], "parent")

    def test_resume_parent_record_replacement_preserves_metadata_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            old_parent = {
                "email": "Parent@Example.com",
                "password": "pw-parent",
                "access_token": "access-old",
                "refresh_token": "refresh-old",
                "account_id": "acct-parent",
                "source": "get_tokens",
                "created_at": "2026-03-19T00:00:00Z",
            }
            child = {
                "email": "child@example.com",
                "password": "pw-child",
                "access_token": "access-child",
                "refresh_token": "refresh-child",
                "account_id": "acct-child",
                "source": "gpt-team-new",
                "plan_type": "team",
                "organization_id": "org-child",
                "workspace_id": "ws-child",
                "codex_register_role": "child",
            }
            path.write_text(
                json.dumps(old_parent, ensure_ascii=False) + "\n" + json.dumps(child, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            state = self.service._default_state()
            state["job_phase"] = "running:gpt_team_batch"
            state["resume_context"] = {
                "email": "Parent@Example.com",
                "team_name": "1",
            }
            state["accounts_jsonl_offset"] = len((json.dumps(old_parent, ensure_ascii=False) + "\n").encode("utf-8"))
            state["accounts_jsonl_baseline_offset"] = state["accounts_jsonl_offset"]
            asyncio.run(self.service._save_state(state))

            cursor = FakeCursor(
                existing_accounts={
                    "parent@example.com": (
                        501,
                        "codex-parent@example.com",
                        {
                            "email": "parent@example.com",
                            "access_token": "access-new",
                            "refresh_token": "refresh-new",
                            "account_id": "acct-parent-new",
                            "id_token": "id-parent-new",
                            "expires_at": "2026-03-20T00:00:00Z",
                            "source": "gpt-team-new",
                            "plan_type": "team",
                            "organization_id": "org-parent",
                            "workspace_id": "ws-parent",
                            "codex_register_role": "parent",
                        },
                        {
                            "codex_auto_register": True,
                            "source": "gpt-team-new",
                            "team_name": "1",
                        },
                    )
                }
            )
            conn = FakeConnection(cursor)
            process = FakeProcess(returncode=0)
            context = {"mode": "resume", "name": "gpt_team_batch", "email": "Parent@Example.com"}
            self.service._active_process = process
            self.service._active_context = context

            with patch.object(self.service, "_create_db_connection", return_value=conn), \
                 patch.object(self.service, "_pg_json", side_effect=lambda value: value), \
                 patch.object(self.service, "_now_iso", return_value="2026-03-19T09:00:00Z"):
                asyncio.run(self.service._handle_process_exit(process, context, 0))

            parsed_lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            parent_lines = [line for line in parsed_lines if str(line.get("email") or "").strip().lower() == "parent@example.com"]
            self.assertEqual(len(parent_lines), 1)
            parent_line = parent_lines[0]
            self.assertEqual(parent_line["source"], "gpt-team-new")
            self.assertEqual(parent_line["codex_register_role"], "parent")
            self.assertEqual(parent_line["plan_type"], "team")
            self.assertEqual(parent_line["organization_id"], "org-parent")
            self.assertEqual(parent_line["workspace_id"], "ws-parent")
            self.assertEqual(parent_line["password"], "pw-parent")
            self.assertEqual(parent_line["access_token"], "access-new")
            self.assertEqual(parent_line["refresh_token"], "refresh-new")
            self.assertEqual(parent_line["account_id"], "acct-parent-new")
            self.assertEqual(parent_line["id_token"], "id-parent-new")
            self.assertEqual(parent_line["expires_at"], "2026-03-20T00:00:00Z")
            self.assertEqual(parent_line["created_at"], "2026-03-19T00:00:00Z")
            self.assertEqual(parent_line["updated_at"], "2026-03-19T09:00:00Z")

            latest_state = asyncio.run(self.service._load_state())
            self.assertEqual(latest_state["job_phase"], "completed")

    def test_resume_parent_record_replacement_preserves_existing_parent_password_without_get_tokens_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            existing_parent = {
                "email": "Parent@Example.com",
                "password": "pw-existing-parent",
                "access_token": "access-existing",
                "refresh_token": "refresh-existing",
                "account_id": "acct-parent-old",
                "source": "gpt-team-new",
                "plan_type": "free",
                "organization_id": "org-old",
                "workspace_id": "ws-old",
                "codex_register_role": "parent",
                "created_at": "2026-03-18T00:00:00Z",
                "updated_at": "2026-03-18T01:00:00Z",
            }
            child = {
                "email": "child@example.com",
                "password": "pw-child",
                "access_token": "access-child",
                "refresh_token": "refresh-child",
                "account_id": "acct-child",
                "source": "gpt-team-new",
                "plan_type": "team",
                "organization_id": "org-child",
                "workspace_id": "ws-child",
                "codex_register_role": "child",
            }
            path.write_text(
                json.dumps(existing_parent, ensure_ascii=False) + "\n" + json.dumps(child, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            state = self.service._default_state()
            state["job_phase"] = "running:gpt_team_batch"
            state["resume_context"] = {
                "email": "Parent@Example.com",
                "team_name": "1",
            }
            state["accounts_jsonl_offset"] = len((json.dumps(existing_parent, ensure_ascii=False) + "\n").encode("utf-8"))
            state["accounts_jsonl_baseline_offset"] = state["accounts_jsonl_offset"]
            asyncio.run(self.service._save_state(state))

            cursor = FakeCursor(
                existing_accounts={
                    "parent@example.com": (
                        501,
                        "codex-parent@example.com",
                        {
                            "email": "parent@example.com",
                            "access_token": "access-new",
                            "refresh_token": "refresh-new",
                            "account_id": "acct-parent-new",
                            "id_token": "id-parent-new",
                            "expires_at": "2026-03-20T00:00:00Z",
                            "source": "gpt-team-new",
                            "plan_type": "team",
                            "organization_id": "org-parent",
                            "workspace_id": "ws-parent",
                            "codex_register_role": "parent",
                        },
                        {
                            "codex_auto_register": True,
                            "source": "gpt-team-new",
                            "team_name": "1",
                            "created_at": "2026-03-18T00:00:00Z",
                        },
                    )
                }
            )
            conn = FakeConnection(cursor)
            process = FakeProcess(returncode=0)
            context = {"mode": "resume", "name": "gpt_team_batch", "email": "Parent@Example.com"}
            self.service._active_process = process
            self.service._active_context = context

            with patch.object(self.service, "_create_db_connection", return_value=conn), \
                 patch.object(self.service, "_pg_json", side_effect=lambda value: value), \
                 patch.object(self.service, "_now_iso", return_value="2026-03-19T09:00:00Z"):
                asyncio.run(self.service._handle_process_exit(process, context, 0))

            parsed_lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            parent_lines = [line for line in parsed_lines if str(line.get("email") or "").strip().lower() == "parent@example.com"]
            self.assertEqual(len(parent_lines), 1)
            parent_line = parent_lines[0]
            self.assertEqual(parent_line["password"], "pw-existing-parent")
            self.assertEqual(parent_line["created_at"], "2026-03-18T00:00:00Z")
            self.assertEqual(parent_line["source"], "gpt-team-new")
            self.assertEqual(parent_line["plan_type"], "team")
            self.assertEqual(parent_line["organization_id"], "org-parent")
            self.assertEqual(parent_line["workspace_id"], "ws-parent")

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

    def test_accounts_path_returns_persisted_codex_accounts_from_db_not_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                json.dumps({"email": "jsonl-only@example.com", "access_token": "jsonl-token", "source": "get_tokens"}) + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            cursor = FakeCursor(
                list_account_rows=[
                    (
                        91,
                        {
                            "email": "db@example.com",
                            "access_token": "db-token",
                            "refresh_token": "db-refresh",
                            "account_id": "acct-db",
                            "source": "gpt-team-new",
                            "codex_register_role": "child",
                        },
                        {
                            "codex_auto_register": True,
                            "source": "gpt-team-new",
                        },
                        "2026-03-19T03:00:00+00:00",
                        "2026-03-19T03:30:00+00:00",
                    )
                ]
            )
            conn = FakeConnection(cursor)

            async def _run():
                with patch.object(self.service, "_create_db_connection", return_value=conn):
                    return await self.service.handle_path("/accounts")

            result = asyncio.run(_run())

        self.assertTrue(result["success"])
        accounts = result["data"]
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["id"], 91)
        self.assertEqual(accounts[0]["email"], "db@example.com")
        self.assertEqual(accounts[0]["access_token"], "db-token")
        self.assertEqual(accounts[0]["refresh_token"], "db-refresh")
        self.assertEqual(accounts[0]["account_id"], "acct-db")
        self.assertEqual(accounts[0]["source"], "gpt-team-new")
        self.assertEqual(accounts[0]["codex_register_role"], "child")
        self.assertEqual(accounts[0]["created_at"], "2026-03-19T03:00:00+00:00")
        self.assertEqual(accounts[0]["updated_at"], "2026-03-19T03:30:00+00:00")


class LoopStateTests(ServiceTestCase):


    def test_status_includes_cumulative_codex_persisted_accounts(self):
        async def _run():
            return await self.service.handle_path("/status")

        result = asyncio.run(_run())

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["data"]["codex_total_persisted_accounts"], 0)

        result = asyncio.run(_run())

        self.assertTrue(result["success"], result.get("error"))
        self.assertFalse(result["data"]["loop_running"])


    def test_resume_child_created_count_increments_cumulative_persisted_total(self):
        state = self.service._default_state()
        state.update(
            {
                "job_phase": "running:gpt_team_batch",
                "enabled": True,
                "resume_context": {"email": "parent@example.com", "team_name": "1"},
                "codex_total_persisted_accounts": 2,
            }
        )
        asyncio.run(self.service._save_state(state))

        process = FakeProcess(returncode=0)
        self.service._active_process = process
        self.service._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"}

        async def fake_normalize(state_arg, *, email):
            self.assertEqual(email, "parent@example.com")
            latest = dict(state_arg)
            latest["last_parent_persist_action"] = "updated"
            return latest

        with patch.object(self.service, "_process_accounts_jsonl_records", return_value={"created": 5, "failed": 0}), \
             patch.object(self.service, "_normalize_parent_record_after_resume", side_effect=fake_normalize):
            asyncio.run(
                self.service._handle_process_exit(
                    process,
                    {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"},
                    0,
                )
            )

        latest = asyncio.run(self.service._load_state())
        self.assertEqual(latest["codex_total_persisted_accounts"], 7)

    def test_resume_parent_created_action_adds_one_to_cumulative_persisted_total(self):
        state = self.service._default_state()
        state.update(
            {
                "job_phase": "running:gpt_team_batch",
                "enabled": True,
                "resume_context": {"email": "parent@example.com", "team_name": "1"},
                "codex_total_persisted_accounts": 2,
            }
        )
        asyncio.run(self.service._save_state(state))

        process = FakeProcess(returncode=0)
        self.service._active_process = process
        self.service._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"}

        def fake_replace_parent(state_arg):
            state_arg["last_parent_persist_action"] = "created"

        with patch.object(self.service, "_process_accounts_jsonl_records", return_value={"created": 5, "failed": 0}), \
             patch.object(self.service, "_replace_parent_record_after_resume", side_effect=fake_replace_parent):
            asyncio.run(
                self.service._handle_process_exit(
                    process,
                    {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"},
                    0,
                )
            )

        latest = asyncio.run(self.service._load_state())
        self.assertEqual(latest["codex_total_persisted_accounts"], 8)

    def test_resume_stale_parent_created_marker_does_not_leak_into_non_created_run(self):
        state = self.service._default_state()
        state.update(
            {
                "job_phase": "running:gpt_team_batch",
                "enabled": True,
                "resume_context": {"email": "parent@example.com", "team_name": "1"},
                "codex_total_persisted_accounts": 2,
                "last_parent_persist_action": "created",
            }
        )
        asyncio.run(self.service._save_state(state))

        process = FakeProcess(returncode=0)
        self.service._active_process = process
        self.service._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"}

        async def fake_normalize(state_arg, *, email):
            self.assertEqual(email, "parent@example.com")
            latest = dict(state_arg)
            latest["last_parent_persist_action"] = "updated"
            return latest

        with patch.object(self.service, "_process_accounts_jsonl_records", return_value={"created": 0, "failed": 0}), \
             patch.object(self.service, "_normalize_parent_record_after_resume", side_effect=fake_normalize):
            asyncio.run(
                self.service._handle_process_exit(
                    process,
                    {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"},
                    0,
                )
            )

        latest = asyncio.run(self.service._load_state())
        self.assertEqual(latest["codex_total_persisted_accounts"], 2)

    def test_cumulative_persisted_count_integration_across_resume_loop_and_failure(self):
        state = self.service._default_state()
        self.assertEqual(state["codex_total_persisted_accounts"], 0)

        state.update(
            {
                "job_phase": "running:gpt_team_batch",
                "enabled": True,
                "resume_context": {"email": "parent@example.com", "team_name": "1"},
            }
        )
        asyncio.run(self.service._save_state(state))
        process = FakeProcess(returncode=0)
        self.service._active_process = process
        self.service._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"}

        async def fake_normalize_created(state_arg, *, email):
            latest = dict(state_arg)
            latest["last_parent_persist_action"] = "created"
            return latest

        with patch.object(self.service, "_process_accounts_jsonl_records", return_value={"created": 5, "failed": 0}), \
             patch.object(self.service, "_normalize_parent_record_after_resume", side_effect=fake_normalize_created):
            asyncio.run(
                self.service._handle_process_exit(
                    process,
                    {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"},
                    0,
                )
            )

        state = asyncio.run(self.service._load_state())
        self.assertEqual(state["codex_total_persisted_accounts"], 6)

        loop_state = dict(state)
        loop_state["loop_running"] = True
        loop_state["loop_committed_accounts_jsonl_offset"] = 0
        with patch.object(self.service, "_run_loop_process_once", new=AsyncMock(return_value=0)), \
             patch.object(self.service, "_process_loop_accounts_jsonl_round", return_value={
                 "start_offset": 0,
                 "end_offset": 10,
                 "records_seen": 2,
                 "created": 3,
                 "updated": 0,
                 "skipped": 0,
                 "failed": 0,
                 "errors": [],
             }):
            asyncio.run(self.service._run_loop_round(loop_state))

        self.assertEqual(loop_state["codex_total_persisted_accounts"], 9)

        with patch.object(self.service, "_run_loop_process_once", new=AsyncMock(return_value=1)):
            asyncio.run(self.service._run_loop_round(loop_state))

        self.assertEqual(loop_state["codex_total_persisted_accounts"], 9)

    def test_loop_start_rejects_when_already_running(self):
        state = self.service._default_state()
        state["loop_running"] = True
        self.service._loop_worker_thread = FakeWorker(alive=True)
        asyncio.run(self.service._save_state(state))

        result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "already_running")

    def test_loop_stop_repairs_stale_running_state(self):
        state = self.service._default_state()
        state["loop_running"] = True
        state["loop_started_at"] = "2026-03-19T00:00:00Z"
        asyncio.run(self.service._save_state(state))

        result = asyncio.run(self.service.handle_path("/loop/stop", payload={}))

        self.assertTrue(result["success"], result.get("error"))
        self.assertFalse(result["data"]["loop_running"])
        self.assertEqual(result["data"]["loop_last_error"], "loop_worker_missing_after_restart")


    def test_loop_start_rejects_while_previous_worker_is_still_stopping(self):
        state = self.service._default_state()
        state["loop_running"] = False
        state["loop_stopping"] = True
        self.service._loop_worker_thread = FakeWorker(alive=True)
        self.service._loop_worker_generation = 1
        self.service._loop_active_generation = 1
        asyncio.run(self.service._save_state(state))

        result = asyncio.run(self.service.handle_path("/loop/start", payload={}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "loop_stopping")
        self.assertTrue(result["data"]["loop_stopping"])

    def test_loop_start_after_stale_finalizer_keeps_new_generation_state(self):
        starter = ControllableStartLoopWorker(self.service)

        with patch.object(self.service, "_start_loop_worker", side_effect=starter, create=True):
            first_result = asyncio.run(self.service.handle_path("/loop/start", payload={}))
        self.assertTrue(first_result["success"], first_result.get("error"))
        first_generation = self.service._loop_active_generation
        self.assertEqual(first_generation, 1)

        first_worker = starter.created[0]
        first_worker._active = True
        stop_result = asyncio.run(self.service.handle_path("/loop/stop", payload={}))
        self.assertTrue(stop_result["success"], stop_result.get("error"))
        self.assertTrue(stop_result["data"]["loop_stopping"])
        self.assertFalse(stop_result["data"]["loop_running"])

        first_worker._active = False
        asyncio.run(self.service._finalize_loop_worker_shutdown(first_generation))
        state_after_finalize = asyncio.run(self.service._load_state())
        self.assertFalse(state_after_finalize["loop_stopping"])
        self.assertFalse(state_after_finalize["loop_running"])

        with patch.object(self.service, "_start_loop_worker", side_effect=starter, create=True):
            second_result = asyncio.run(self.service.handle_path("/loop/start", payload={}))
        self.assertTrue(second_result["success"], second_result.get("error"))
        second_generation = self.service._loop_active_generation
        self.assertEqual(second_generation, 2)
        self.assertTrue(second_result["data"]["loop_running"])
        self.assertFalse(second_result["data"]["loop_stopping"])

        asyncio.run(self.service._finalize_loop_worker_shutdown(first_generation))
        latest_state = asyncio.run(self.service._load_state())
        self.assertTrue(latest_state["loop_running"])
        self.assertFalse(latest_state["loop_stopping"])
        self.assertEqual(self.service._loop_active_generation, second_generation)
        self.assertEqual(self.service._loop_worker_generation, second_generation)
        self.assertIsNotNone(self.service._loop_worker_thread)

    def test_loop_stop_terminates_loop_owned_process(self):
        state = self.service._default_state()
        state["loop_running"] = True
        asyncio.run(self.service._save_state(state))
        process = FakeProcess(block=True)
        self.service._loop_owned_process = process

        result = asyncio.run(self.service.handle_path("/loop/stop", payload={}))

        self.assertTrue(result["success"], result.get("error"))
        self.assertTrue(process._terminated)
        self.assertFalse(result["data"]["loop_running"])

    def test_loop_stop_during_stopping_still_terminates_registered_process(self):
        state = self.service._default_state()
        state["loop_running"] = False
        state["loop_stopping"] = True
        self.service._loop_active_generation = 1
        self.service._loop_worker_generation = 1
        self.service._loop_worker_thread = FakeWorker(alive=True)
        process = FakeProcess(block=True)
        self.service._loop_owned_process = process
        self.service._loop_owned_process_generation = 1
        asyncio.run(self.service._save_state(state))

        result = asyncio.run(self.service.handle_path("/loop/stop", payload={}))

        self.assertTrue(result["success"], result.get("error"))
        self.assertTrue(process._terminated)
        self.assertTrue(result["data"]["loop_stopping"])
        self.assertFalse(result["data"]["loop_running"])

    def test_run_loop_process_once_terminates_when_stop_requested_before_registration(self):
        state = self.service._default_state()
        state["loop_running"] = True
        asyncio.run(self.service._save_state(state))
        self.service._loop_active_generation = 1
        self.service._loop_worker_generation = 1
        self.service._loop_worker_thread = FakeWorker(alive=True)
        process = FakeProcess(block=True)

        async def exercise():
            await self.service._state_lock.acquire()
            try:
                stop_task = asyncio.create_task(self.service.handle_path("/loop/stop", payload={}))
                await asyncio.sleep(0)
                run_once_task = asyncio.create_task(self.service._run_loop_process_once(1))
                await asyncio.sleep(0)
            finally:
                self.service._state_lock.release()

            stop_result = await asyncio.wait_for(stop_task, timeout=1)
            return_code = await asyncio.wait_for(run_once_task, timeout=1)
            latest_state = await self.service._load_state()
            return stop_result, return_code, latest_state

        with patch.object(self.service, "_spawn_process", return_value=(process, "")):
            stop_result, return_code, latest_state = asyncio.run(exercise())

        self.assertTrue(stop_result["success"], stop_result.get("error"))
        self.assertTrue(process._terminated)
        self.assertEqual(return_code, -15)
        self.assertTrue(stop_result["data"]["loop_stopping"])
        self.assertFalse(stop_result["data"]["loop_running"])
        self.assertIsNone(self.service._loop_owned_process)
        self.assertFalse(latest_state["loop_running"])

    def test_loop_worker_iteration_does_not_merge_stale_generation_round_state(self):
        state = self.service._default_state()
        state["loop_running"] = True
        state["loop_current_round"] = 2
        state["loop_history"] = [{"round": 2, "status": "success"}]
        self.service._loop_active_generation = 1
        self.service._loop_worker_generation = 1
        self.service._loop_worker_thread = GenerationAwareWorker(self.service, 1)
        asyncio.run(self.service._save_state(state))

        async def stale_round(round_state, generation=None):
            round_state["loop_current_round"] = 3
            round_state["loop_last_error"] = "stale-generation"
            round_state["loop_history"] = [{"round": 3, "status": "failed", "error": "stale-generation"}]
            self.service._loop_active_generation = 2
            self.service._loop_worker_generation = 2
            self.service._loop_worker_thread = GenerationAwareWorker(self.service, 2)
            latest = await self.service._load_state()
            latest["loop_running"] = True
            latest["loop_current_round"] = 9
            latest["loop_last_error"] = "new-generation"
            latest["loop_history"] = [{"round": 9, "status": "success"}]
            latest["loop_stopping"] = False
            await self.service._save_state(latest)
            return {"status": "success"}

        with patch.object(self.service, "_run_loop_round", side_effect=stale_round):
            asyncio.run(self.service._loop_worker_iteration(1))

        latest_state = asyncio.run(self.service._load_state())
        self.assertTrue(latest_state["loop_running"])
        self.assertEqual(latest_state["loop_current_round"], 9)
        self.assertEqual(latest_state["loop_last_error"], "new-generation")
        self.assertEqual(latest_state["loop_history"], [{"round": 9, "status": "success"}])


class LoopRoundTests(ServiceTestCase):
    def _base_round_state(self):
        state = self.service._default_state()
        state["loop_running"] = True
        state["accounts_jsonl_offset"] = 10
        state["loop_committed_accounts_jsonl_offset"] = 10
        return state

    def test_loop_round_updates_created_counts_and_committed_offset(self):
        state = self._base_round_state()
        summary = {
            "start_offset": 10,
            "end_offset": 25,
            "records_seen": 3,
            "created": 2,
            "updated": 1,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        with patch.object(
            self.service,
            "_process_loop_accounts_jsonl_round",
            return_value=summary,
            create=True,
        ) as process_mock, patch.object(
            self.service,
            "_run_loop_process_once",
            new=AsyncMock(return_value=0),
            create=True,
        ):
            asyncio.run(self.service._run_loop_round(state))

        process_mock.assert_called_once_with(state)
        self.assertEqual(state["loop_current_round"], 1)
        self.assertEqual(state["loop_last_round_created"], 2)
        self.assertEqual(state["loop_last_round_updated"], 1)
        self.assertEqual(state["loop_last_round_skipped"], 0)
        self.assertEqual(state["loop_last_round_failed"], 0)
        self.assertEqual(state["loop_total_created"], 2)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 25)
        self.assertEqual(state["loop_last_error"], "")
        self.assertEqual(state["loop_history"][-1]["status"], "success")

    def test_loop_round_failure_keeps_committed_offset(self):
        state = self._base_round_state()

        with patch.object(
            self.service,
            "_process_loop_accounts_jsonl_round",
            side_effect=RuntimeError("db boom"),
            create=True,
        ), patch.object(
            self.service,
            "_run_loop_process_once",
            new=AsyncMock(return_value=0),
            create=True,
        ):
            asyncio.run(self.service._run_loop_round(state))

        self.assertEqual(state["loop_current_round"], 1)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 10)
        self.assertEqual(state["loop_last_error"], "db boom")
        self.assertEqual(state["loop_history"][-1]["status"], "failed")

    def test_loop_round_stop_records_stopped_history_entry(self):
        state = self._base_round_state()

        stop_event = threading.Event()
        stop_event.set()

        with patch.object(self.service, "_loop_stop_event", stop_event, create=True), patch.object(
            self.service,
            "_run_loop_process_once",
            new=AsyncMock(return_value=-15),
            create=True,
        ) as run_once_mock, patch.object(
            self.service,
            "_process_loop_accounts_jsonl_round",
            create=True,
        ) as process_mock:
            asyncio.run(self.service._run_loop_round(state))

        run_once_mock.assert_called_once()
        process_mock.assert_not_called()
        self.assertEqual(state["loop_current_round"], 1)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 10)
        self.assertEqual(state["loop_history"][-1]["status"], "stopped")

    def test_process_loop_accounts_jsonl_round_restores_main_workflow_state(self):
        state = self._base_round_state()
        state["total_created"] = 9
        state["total_updated"] = 8
        state["total_skipped"] = 7
        state["total_failed"] = 6
        state["last_processed_records"] = 5
        state["last_processed_offset"] = 4
        state["last_processed_summary"] = {"created": 99}

        summary = {
            "start_offset": 10,
            "end_offset": 30,
            "records_seen": 1,
            "created": 1,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        with patch.object(self.service, "_process_accounts_jsonl_records", return_value=summary) as process_mock:
            result = self.service._process_loop_accounts_jsonl_round(state)

        process_mock.assert_called_once_with(state)
        self.assertEqual(result, summary)
        self.assertEqual(state["accounts_jsonl_offset"], 10)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 30)
        self.assertEqual(state["total_created"], 9)
        self.assertEqual(state["total_updated"], 8)
        self.assertEqual(state["total_skipped"], 7)
        self.assertEqual(state["total_failed"], 6)
        self.assertEqual(state["last_processed_records"], 5)
        self.assertEqual(state["last_processed_offset"], 4)
        self.assertEqual(state["last_processed_summary"], {"created": 99})

    def test_process_loop_accounts_jsonl_round_restores_main_workflow_state_on_exception(self):
        state = self._base_round_state()
        state["total_created"] = 9
        state["total_updated"] = 8
        state["total_skipped"] = 7
        state["total_failed"] = 6
        state["last_processed_records"] = 5
        state["last_processed_offset"] = 4
        state["last_processed_summary"] = {"created": 99}

        def raising_process(current_state):
            current_state["accounts_jsonl_offset"] = 22
            current_state["total_created"] = 12
            current_state["total_updated"] = 11
            current_state["total_skipped"] = 10
            current_state["total_failed"] = 9
            current_state["last_processed_records"] = 8
            current_state["last_processed_offset"] = 22
            current_state["last_processed_summary"] = {"failed": 1}
            raise RuntimeError("db boom")

        with patch.object(self.service, "_process_accounts_jsonl_records", side_effect=raising_process):
            with self.assertRaisesRegex(RuntimeError, "db boom"):
                self.service._process_loop_accounts_jsonl_round(state)

        self.assertEqual(state["accounts_jsonl_offset"], 10)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 10)
        self.assertEqual(state["total_created"], 9)
        self.assertEqual(state["total_updated"], 8)
        self.assertEqual(state["total_skipped"], 7)
        self.assertEqual(state["total_failed"], 6)
        self.assertEqual(state["last_processed_records"], 5)
        self.assertEqual(state["last_processed_offset"], 4)
        self.assertEqual(state["last_processed_summary"], {"created": 99})

    def test_loop_round_partial_processing_failure_preserves_summary_counts(self):
        state = self._base_round_state()
        summary = {
            "start_offset": 10,
            "end_offset": 22,
            "records_seen": 2,
            "created": 1,
            "updated": 0,
            "skipped": 1,
            "failed": 1,
            "errors": ["db boom"],
        }

        with patch.object(
            self.service,
            "_process_loop_accounts_jsonl_round",
            return_value=summary,
            create=True,
        ), patch.object(
            self.service,
            "_run_loop_process_once",
            new=AsyncMock(return_value=0),
            create=True,
        ):
            result = asyncio.run(self.service._run_loop_round(state))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "loop_accounts_processing_failed")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["summary"], summary)
        self.assertEqual(state["loop_committed_accounts_jsonl_offset"], 10)
        self.assertEqual(state["loop_last_error"], "loop_accounts_processing_failed")
        self.assertEqual(state["loop_last_round_created"], 1)
        self.assertEqual(state["loop_last_round_updated"], 0)
        self.assertEqual(state["loop_last_round_skipped"], 1)
        self.assertEqual(state["loop_last_round_failed"], 1)
        self.assertEqual(state["loop_history"][-1]["status"], "failed")
        self.assertEqual(state["loop_history"][-1]["summary"], summary)


    def test_loop_worker_iteration_releases_lock_during_active_round(self):
        state = self._base_round_state()
        state["loop_history"] = []
        self.service._loop_worker_thread = FakeWorker(alive=True)
        asyncio.run(self.service._save_state(state))

        entered_round = asyncio.Event()
        release_round = asyncio.Event()

        async def blocking_round(round_state):
            round_state["loop_last_error"] = ""
            entered_round.set()
            await release_round.wait()
            round_state["loop_history"] = [{"round": 1, "status": "success"}]
            round_state["loop_last_round_created"] = 0
            round_state["loop_last_round_updated"] = 0
            round_state["loop_last_round_skipped"] = 0
            round_state["loop_last_round_failed"] = 0
            round_state["loop_last_round_finished_at"] = "done"
            return {"status": "success"}

        async def exercise():
            with patch.object(self.service, "_run_loop_round", side_effect=blocking_round):
                iteration_task = asyncio.create_task(self.service._loop_worker_iteration())
                await asyncio.wait_for(entered_round.wait(), timeout=1)

                status_task = asyncio.create_task(self.service.handle_path("/loop/status"))
                status_result = await asyncio.wait_for(status_task, timeout=1)
                self.assertTrue(status_result["success"])
                self.assertTrue(status_result["data"]["loop_running"])

                stop_task = asyncio.create_task(self.service.handle_path("/loop/stop", payload={}))
                stop_result = await asyncio.wait_for(stop_task, timeout=1)
                self.assertTrue(stop_result["success"])
                self.assertFalse(stop_result["data"]["loop_running"])
                self.assertTrue(self.service._loop_stop_event.is_set())

                release_round.set()
                await asyncio.wait_for(iteration_task, timeout=1)

        asyncio.run(exercise())

    def test_run_loop_process_once_waits_without_blocking_event_loop(self):
        process = FakeProcess(block=True)

        async def exercise():
            wait_task = asyncio.create_task(self.service._run_loop_process_once())
            await asyncio.sleep(0)

            status_task = asyncio.create_task(self.service.handle_path("/loop/status"))
            status_result = await asyncio.wait_for(status_task, timeout=1)
            self.assertTrue(status_result["success"])
            self.assertIs(self.service._loop_owned_process, process)

            process.release()
            return_code = await asyncio.wait_for(wait_task, timeout=1)
            self.assertEqual(return_code, 0)
            self.assertIsNone(self.service._loop_owned_process)

        with patch.object(self.service, "_spawn_process", return_value=(process, "")):
            asyncio.run(exercise())


    def test_loop_round_success_increments_cumulative_persisted_total(self):
        state = self._base_round_state()
        state["codex_total_persisted_accounts"] = 4
        summary = {
            "start_offset": 10,
            "end_offset": 11,
            "records_seen": 2,
            "created": 3,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        with patch.object(self.service, "_run_loop_process_once", new=AsyncMock(return_value=0)), patch.object(
            self.service,
            "_process_loop_accounts_jsonl_round",
            return_value=summary,
        ):
            asyncio.run(self.service._run_loop_round(state))

        self.assertEqual(state["codex_total_persisted_accounts"], 7)

    def test_loop_round_failure_does_not_increment_cumulative_persisted_total(self):
        state = self._base_round_state()
        state["codex_total_persisted_accounts"] = 4

        with patch.object(self.service, "_run_loop_process_once", new=AsyncMock(return_value=1)):
            asyncio.run(self.service._run_loop_round(state))

        self.assertEqual(state["codex_total_persisted_accounts"], 4)


class LoopMutualExclusionTests(ServiceTestCase):
    def test_enable_rejects_while_loop_running(self):
        state = self.service._default_state()
        state["loop_running"] = True
        self.service._loop_worker_thread = FakeWorker(alive=True)
        asyncio.run(self.service._save_state(state))

        result = asyncio.run(self.service.handle_path("/enable", payload={}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "loop_running")

    def test_resume_rejects_while_loop_running(self):
        state = self.service._default_state()
        state["loop_running"] = True
        state["job_phase"] = "waiting_manual:subscribe_then_resume"
        state["resume_context"] = {"email": "loop@example.com"}
        self.service._loop_worker_thread = FakeWorker(alive=True)
        asyncio.run(self.service._save_state(state))

        result = asyncio.run(self.service.handle_path("/resume", payload={}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "loop_running")


class DataDirectoryContractTests(ServiceTestCase):
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
        cursor = FakeCursor(
            list_account_rows=[
                (
                    201,
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
                    },
                    {
                        "codex_auto_register": True,
                    },
                    "2026-03-19T00:00:00Z",
                    "2026-03-19T01:00:00Z",
                )
            ]
        )
        conn = FakeConnection(cursor)

        with patch.object(self.service, "_create_db_connection", return_value=conn):
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


