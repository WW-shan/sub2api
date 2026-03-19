import asyncio
import base64
import importlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, mock_open

THIS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codex_register_service import CodexRegisterService, InMemoryStateStore


class CodexRegisterServiceContractTests(unittest.TestCase):
    def setUp(self):
        self.service = CodexRegisterService(
            state_store=InMemoryStateStore(),
            chatgpt_service=SimpleNamespace(),
            workflow_id="wf-test",
            sleep_min=1,
            sleep_max=1,
            auto_run=False,
        )

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

    def test_logs_path_returns_logs_without_500(self):
        self.service.state_store.logs = [{"message": "hello", "time": "2026-03-19T00:00:00Z"}]

        async def _run():
            return await self.service.handle_path("/logs")

        result = asyncio.run(_run())

        self.assertTrue(result["success"])
        self.assertEqual(result["data"][0]["message"], "hello")

    def test_service_uses_configured_data_dir_for_accounts_jsonl(self):
        module_name = "codex_register_service"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CODEX_REGISTER_DATA_DIR": tmpdir}, clear=False):
                if module_name in sys.modules:
                    del sys.modules[module_name]
                module = importlib.import_module(module_name)
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


    def test_resume_success_normalizes_parent_record_before_completed_state(self):
        state = self.service._default_state()
        state.update(
            {
                "job_phase": "running:gpt_team_batch",
                "enabled": True,
                "resume_context": {"email": "parent@example.com", "team_name": "1"},
            }
        )
        asyncio.run(self.service._save_state(state))

        process = SimpleNamespace()
        self.service._active_process = process
        self.service._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"}

        calls = []

        async def fake_normalize(state_arg, *, email):
            calls.append((dict(state_arg), email))
            latest = dict(state_arg)
            latest["normalized_parent"] = True
            return latest

        with patch.object(self.service, "_process_accounts_jsonl_records", return_value={"failed": 0}), \
             patch.object(self.service, "_normalize_parent_record_after_resume", side_effect=fake_normalize):
            asyncio.run(
                self.service._handle_process_exit(
                    process,
                    {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"},
                    0,
                )
            )

        latest = asyncio.run(self.service._load_state())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "parent@example.com")
        self.assertTrue(latest.get("normalized_parent"))

    def test_build_parent_record_after_resume_applies_spec_field_precedence(self):
        old_parent = {
            "email": " Parent@Example.com ",
            "password": "pw-old",
            "access_token": "old-at",
            "refresh_token": "old-rt",
            "id_token": "old-id",
            "account_id": "old-acct",
            "auth_file": "",
            "expires_at": "old-exp",
            "created_at": "2026-03-19T00:00:00Z",
        }
        latest_parent = {
            "access_token": "new-at",
            "refresh_token": "new-rt",
            "id_token": "new-id",
            "account_id": "new-acct",
            "auth_file": "auth.json",
            "expires_at": "new-exp",
            "plan_type": "team",
            "organization_id": "org-1",
        }
        resume_context = {"email": "Parent@Example.com", "team_name": "1"}

        record = self.service._build_parent_record_after_resume(
            old_parent_record=old_parent,
            latest_parent_record=latest_parent,
            resume_context=resume_context,
        )

        self.assertEqual(record["email"], "parent@example.com")
        self.assertEqual(record["password"], "pw-old")
        self.assertEqual(record["access_token"], "new-at")
        self.assertEqual(record["refresh_token"], "new-rt")
        self.assertEqual(record["id_token"], "new-id")
        self.assertEqual(record["account_id"], "new-acct")
        self.assertEqual(record["auth_file"], "auth.json")
        self.assertEqual(record["expires_at"], "new-exp")
        self.assertEqual(record["plan_type"], "team")
        self.assertEqual(record["organization_id"], "org-1")
        self.assertEqual(record["workspace_id"], "")
        self.assertEqual(record["team_name"], "1")
        self.assertEqual(record["source"], "gpt-team-new")
        self.assertEqual(record["codex_register_role"], "parent")
        self.assertFalse(record["invited"])
        self.assertEqual(record["created_at"], "2026-03-19T00:00:00Z")

    def test_normalize_parent_record_persists_parent_before_rewrite(self):
        state = self.service._default_state()
        state["resume_context"] = {"email": "parent@example.com", "team_name": "1"}

        calls = []
        parent_record = {
            "email": "parent@example.com",
            "access_token": "new-at",
            "source": "gpt-team-new",
            "codex_register_role": "parent",
        }

        with patch.object(self.service, "_read_accounts_jsonl_records", return_value=(
            [
                {"email": "parent@example.com", "source": "get_tokens", "password": "pw", "created_at": "2026-03-19T00:00:00Z"},
                {"email": "parent@example.com", "source": "gpt-team-new", "access_token": "new-at", "plan_type": "team"},
            ],
            999,
        )), \
             patch.object(self.service, "_build_parent_record_after_resume", return_value=parent_record), \
             patch.object(self.service, "_persist_single_parent_record", side_effect=lambda record: calls.append(("persist", dict(record))) or "updated"), \
             patch.object(self.service, "_rewrite_accounts_jsonl_with_parent_record", side_effect=lambda **kwargs: calls.append(("rewrite", dict(kwargs["parent_record"]))) or {"end_offset": 555}), \
             patch.object(self.service, "_recalculate_offsets_after_parent_rewrite", side_effect=lambda state_arg, rewrite_summary: calls.append(("offsets", dict(rewrite_summary)))):
            latest = asyncio.run(self.service._normalize_parent_record_after_resume(state, email="parent@example.com"))

        self.assertEqual([item[0] for item in calls], ["persist", "rewrite", "offsets"])
        self.assertEqual(latest["accounts_jsonl_offset"], 555)
        self.assertEqual(latest["last_processed_offset"], 555)

    def test_normalize_parent_record_keeps_old_row_when_persist_fails(self):
        state = self.service._default_state()
        state["resume_context"] = {"email": "parent@example.com", "team_name": "1"}

        with patch.object(self.service, "_read_accounts_jsonl_records", return_value=(
            [
                {"email": "parent@example.com", "source": "get_tokens", "password": "pw", "created_at": "2026-03-19T00:00:00Z"},
                {"email": "parent@example.com", "source": "gpt-team-new", "access_token": "new-at", "plan_type": "team"},
            ],
            999,
        )), \
             patch.object(self.service, "_build_parent_record_after_resume", return_value={"email": "parent@example.com", "access_token": "new-at"}), \
             patch.object(self.service, "_persist_single_parent_record", side_effect=RuntimeError("parent_record_rewrite_failed:db fail")), \
             patch.object(self.service, "_rewrite_accounts_jsonl_with_parent_record") as rewrite_mock:
            with self.assertRaises(RuntimeError):
                asyncio.run(self.service._normalize_parent_record_after_resume(state, email="parent@example.com"))

        rewrite_mock.assert_not_called()

    def test_rewrite_accounts_jsonl_with_parent_record_preserves_invalid_lines_and_dedupes_parent_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"email": "parent@example.com", "access_token": "old-at", "source": "get_tokens"}),
                        "{bad-json",
                        json.dumps({"email": "parent@example.com", "access_token": "older-parent", "source": "gpt-team-new", "codex_register_role": "parent"}),
                        json.dumps({"email": "child@example.com", "access_token": "child-at", "source": "gpt-team-new", "codex_register_role": "child"}),
                    ]
                ) + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            summary = self.service._rewrite_accounts_jsonl_with_parent_record(
                normalized_email="parent@example.com",
                parent_record={
                    "email": "parent@example.com",
                    "access_token": "new-at",
                    "source": "gpt-team-new",
                    "codex_register_role": "parent",
                },
            )

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "{bad-json")
            parsed = [json.loads(line) for line in lines[1:]]
            self.assertEqual(len([row for row in parsed if row.get("email") == "parent@example.com"]), 1)
            self.assertFalse(any(row.get("source") == "get_tokens" and row.get("email") == "parent@example.com" for row in parsed))
            self.assertTrue(any(row.get("email") == "child@example.com" for row in parsed))
            self.assertTrue(summary["end_offset"] > 0)

    def test_recalculate_offsets_after_parent_rewrite_uses_rewritten_file_positions(self):
        state = self.service._default_state()
        self.service._recalculate_offsets_after_parent_rewrite(state, {"end_offset": 123})
        self.assertEqual(state["accounts_jsonl_offset"], 123)
        self.assertEqual(state["accounts_jsonl_baseline_offset"], 123)
        self.assertEqual(state["last_processed_offset"], 123)

    def test_resume_success_parent_normalization_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "accounts.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "email": "parent@example.com",
                            "password": "pw",
                            "access_token": "old-at",
                            "source": "get_tokens",
                            "created_at": "2026-03-19T00:00:00Z",
                        }),
                        json.dumps({
                            "email": "parent@example.com",
                            "access_token": "new-at",
                            "refresh_token": "new-rt",
                            "plan_type": "team",
                            "organization_id": "org-1",
                            "source": "gpt-team-new",
                            "codex_register_role": "parent",
                        }),
                        json.dumps({
                            "email": "child@example.com",
                            "access_token": "child-at",
                            "source": "gpt-team-new",
                            "codex_register_role": "child",
                        }),
                    ]
                ) + "\n",
                encoding="utf-8",
            )
            self.service._accounts_jsonl_path = path

            state = self.service._default_state()
            state.update(
                {
                    "job_phase": "running:gpt_team_batch",
                    "enabled": True,
                    "resume_context": {"email": "parent@example.com", "team_name": "1"},
                }
            )
            asyncio.run(self.service._save_state(state))

            process = SimpleNamespace()
            self.service._active_process = process
            self.service._active_context = {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"}

            calls = []

            with patch.object(self.service, "_process_accounts_jsonl_records", return_value={"failed": 0}), \
                 patch.object(self.service, "_persist_single_parent_record", side_effect=lambda record: calls.append(("persist", record.get("email"))) or "updated"):
                asyncio.run(
                    self.service._handle_process_exit(
                        process,
                        {"mode": "resume", "name": "gpt_team_batch", "email": "parent@example.com"},
                        0,
                    )
                )

            latest = asyncio.run(self.service._load_state())
            parsed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(calls[0][0], "persist")
            self.assertEqual(len([row for row in parsed if row.get("email") == "parent@example.com" and row.get("codex_register_role") == "parent"]), 1)
            self.assertFalse(any(row.get("email") == "parent@example.com" and row.get("source") == "get_tokens" for row in parsed))
            self.assertTrue(any(row.get("email") == "child@example.com" for row in parsed))
            self.assertEqual(latest["job_phase"], "completed")


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


class GetTokensHelperLoadingContractTests(unittest.TestCase):
    def test_get_gpt_team_helpers_exposes_expected_keys(self):
        module_name = "tools.codex_register.get_tokens"
        module = importlib.import_module(module_name)

        with patch.object(module, "_load_gpt_team_new_module", return_value=SimpleNamespace(
            build_token_dict=lambda email, tokens: {"email": email, **tokens},
            build_importable_account_record=lambda **kwargs: kwargs,
            chatgpt_http_login=lambda **kwargs: ("chatgpt-token", "org-1", "team"),
        )):
            helpers = module._get_gpt_team_helpers()

        self.assertEqual(
            set(helpers.keys()),
            {"build_token_dict", "build_importable_account_record", "chatgpt_http_login"},
        )
        self.assertTrue(callable(helpers["build_token_dict"]))
        self.assertTrue(callable(helpers["build_importable_account_record"]))
        self.assertTrue(callable(helpers["chatgpt_http_login"]))

    def test_get_gpt_team_helpers_returns_none_values_when_module_unavailable(self):
        module_name = "tools.codex_register.get_tokens"
        module = importlib.import_module(module_name)

        with patch.object(module, "_load_gpt_team_new_module", return_value=None):
            helpers = module._get_gpt_team_helpers()

        self.assertEqual(
            helpers,
            {
                "build_token_dict": None,
                "build_importable_account_record": None,
                "chatgpt_http_login": None,
            },
        )

    def test_save_result_to_results_txt_writes_only_results_file(self):
        module_name = "tools.codex_register.get_tokens"
        module = importlib.import_module(module_name)

        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = pathlib.Path(tmpdir) / "results.txt"
            accounts_path = pathlib.Path(tmpdir) / "accounts.jsonl"
            module.RESULTS_FILE = str(results_path)
            module.ACCOUNTS_JSONL_FILE = str(accounts_path)

            module.save_result_to_results_txt("one@example.com", "pw", "at", "rt")

            self.assertEqual(results_path.read_text(encoding="utf-8"), "one@example.com|pw|at|rt\n")
            self.assertFalse(accounts_path.exists())

    def test_process_one_wraps_oauth_tuple_into_token_dict(self):
        module_name = "tools.codex_register.get_tokens"
        module = importlib.import_module(module_name)

        captured = {}

        def fake_build_token_dict(email, tokens):
            captured["email"] = email
            captured["tokens"] = dict(tokens)
            return {
                "type": "codex",
                "email": email,
                "access_token": tokens.get("access_token", ""),
                "refresh_token": tokens.get("refresh_token", ""),
                "id_token": tokens.get("id_token", ""),
                "account_id": "acct-1",
                "expired": "",
                "last_refresh": "",
            }

        with patch.object(module, "_generate_worker_email", return_value="one@example.com"), \
             patch.object(module, "generate_random_password", return_value="pw"), \
             patch.object(module.Registrar, "register", return_value=True), \
             patch.object(module, "oauth_login", return_value=("at", "rt")), \
             patch.object(module, "save_result_to_results_txt"), \
             patch.object(module, "_get_gpt_team_helpers", return_value={
                 "build_token_dict": fake_build_token_dict,
                 "build_importable_account_record": lambda **kwargs: {**kwargs, "source": "gpt-team-new"},
                 "chatgpt_http_login": None,
             }), \
             patch("builtins.open", mock_open()):
            ok = module.process_one()

        self.assertTrue(ok)
        self.assertEqual(captured["email"], "one@example.com")
        self.assertEqual(
            captured["tokens"],
            {"access_token": "at", "refresh_token": "rt", "id_token": ""},
        )

    def test_process_one_emits_parity_jsonl_record(self):
        module_name = "tools.codex_register.get_tokens"
        module = importlib.import_module(module_name)

        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = pathlib.Path(tmpdir) / "results.txt"
            accounts_path = pathlib.Path(tmpdir) / "accounts.jsonl"
            module.RESULTS_FILE = str(results_path)
            module.ACCOUNTS_JSONL_FILE = str(accounts_path)

            def fake_build_token_dict(email, tokens):
                return {
                    "type": "codex",
                    "email": email,
                    "access_token": tokens.get("access_token", ""),
                    "refresh_token": tokens.get("refresh_token", ""),
                    "id_token": "id-1",
                    "account_id": "acct-1",
                    "expired": "2026-03-19T10:00:00+08:00",
                    "last_refresh": "2026-03-19T09:00:00+08:00",
                }

            def fake_build_importable_account_record(**kwargs):
                token_dict = kwargs["token_dict"]
                return {
                    "email": kwargs["email"],
                    "password": kwargs["password"],
                    "access_token": token_dict.get("access_token", ""),
                    "refresh_token": token_dict.get("refresh_token", ""),
                    "id_token": token_dict.get("id_token", ""),
                    "account_id": token_dict.get("account_id", ""),
                    "auth_file": kwargs.get("auth_file", ""),
                    "expires_at": token_dict.get("expired", ""),
                    "invited": kwargs.get("invited", False),
                    "team_name": kwargs.get("team_name", ""),
                    "plan_type": token_dict.get("plan_type", ""),
                    "organization_id": token_dict.get("organization_id", ""),
                    "workspace_id": token_dict.get("workspace_id", ""),
                    "codex_register_role": token_dict.get("codex_register_role", ""),
                    "created_at": "2026-03-19T00:00:00Z",
                    "updated_at": "2026-03-19T00:00:00Z",
                    "source": "gpt-team-new",
                }

            with patch.object(module, "_generate_worker_email", return_value="one@example.com"), \
                 patch.object(module, "generate_random_password", return_value="pw"), \
                 patch.object(module.Registrar, "register", return_value=True), \
                 patch.object(module, "oauth_login", return_value=("at", "rt")), \
                 patch.object(module, "_get_gpt_team_helpers", return_value={
                     "build_token_dict": fake_build_token_dict,
                     "build_importable_account_record": fake_build_importable_account_record,
                     "chatgpt_http_login": lambda **kwargs: ("chatgpt-at", "org-1", "team"),
                 }):
                ok = module.process_one()

            self.assertTrue(ok)
            self.assertEqual(results_path.read_text(encoding="utf-8"), "one@example.com|pw|at|rt\n")
            record = json.loads(accounts_path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["source"], "get_tokens")
            self.assertFalse(record["invited"])
            self.assertEqual(record["team_name"], "")
            self.assertEqual(record["codex_register_role"], "parent")
            self.assertEqual(record["plan_type"], "team")
            self.assertEqual(record["organization_id"], "org-1")
            for key in {
                "email", "password", "access_token", "refresh_token", "id_token", "account_id",
                "auth_file", "expires_at", "invited", "team_name", "plan_type", "organization_id",
                "workspace_id", "codex_register_role", "created_at", "updated_at", "source",
            }:
                self.assertIn(key, record)

    def test_process_one_degrades_when_importable_record_helper_unavailable(self):
        module_name = "tools.codex_register.get_tokens"
        module = importlib.import_module(module_name)

        with tempfile.TemporaryDirectory() as tmpdir:
            results_path = pathlib.Path(tmpdir) / "results.txt"
            accounts_path = pathlib.Path(tmpdir) / "accounts.jsonl"
            module.RESULTS_FILE = str(results_path)
            module.ACCOUNTS_JSONL_FILE = str(accounts_path)

            with patch.object(module, "_generate_worker_email", return_value="one@example.com"), \
                 patch.object(module, "generate_random_password", return_value="pw"), \
                 patch.object(module.Registrar, "register", return_value=True), \
                 patch.object(module, "oauth_login", return_value=("at", "rt")), \
                 patch.object(module, "_get_gpt_team_helpers", return_value={
                     "build_token_dict": None,
                     "build_importable_account_record": None,
                     "chatgpt_http_login": None,
                 }):
                ok = module.process_one()

            self.assertFalse(ok)
            self.assertEqual(results_path.read_text(encoding="utf-8"), "one@example.com|pw|at|rt\n")
            self.assertFalse(accounts_path.exists())




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
