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
        self.assertEqual(accounts[1]["email"], "two@example.com")

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
