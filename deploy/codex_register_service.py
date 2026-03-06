import json
import os
import random
import subprocess
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import threading
import traceback
from typing import List

import psycopg2
from psycopg2.extras import Json


enabled = True
last_run = None
last_success = None
last_error = ""
total_created = 0
total_updated = 0
total_skipped = 0
sleep_min_global = 0
sleep_max_global = 0
tokens_dir_global = None
last_token_email = ""
last_created_email = ""
last_created_account_id = ""
last_updated_email = ""
last_updated_account_id = ""
last_processed_records = 0
recent_logs = []


def append_log(level: str, message: str) -> None:
    recent_logs.append(
        {
            "time": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "message": message,
        }
    )
    if len(recent_logs) > 100:
        del recent_logs[0 : len(recent_logs) - 100]


def ensure_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def parse_group_ids() -> List[int]:
    raw = get_env("CODEX_GROUP_IDS", "")
    if not raw:
        return [1]
    group_ids: List[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0:
            group_ids.append(value)
    if not group_ids:
        return [1]
    return group_ids


def build_model_mapping() -> dict:
    return {
        "claude-*-sonnet*": "gpt-5.4",
        "claude-*-opus*": "gpt-5.4",
    }


def get_env(name: str, default=None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"环境变量 {name} 未配置且为必需")
    return value or ""


def create_db_connection():
    host = get_env("POSTGRES_HOST", "postgres")
    port = int(get_env("POSTGRES_PORT", "5432"))
    user = get_env("POSTGRES_USER", required=True)
    password = get_env("POSTGRES_PASSWORD", required=True)
    dbname = get_env("POSTGRES_DB", required=True)

    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname,
    )
    conn.autocommit = True
    return conn


def run_codex_once(tokens_dir: Path):
    codex_dir = Path("/app/codex-auto-register-main")
    script_path = codex_dir / "codex-autp-register.py"

    tokens_dir.mkdir(parents=True, exist_ok=True)

    proxy = get_env("CODEX_PROXY", "")
    cmd = ["python", str(script_path), "--once"]
    if proxy:
        cmd.extend(["--proxy", proxy])

    print("[codex-register] 启动注册脚本:", " ".join(cmd), flush=True)

    result = subprocess.run(
        cmd,
        cwd=str(codex_dir),
        capture_output=True,
        text=True,
    )

    print("[codex-register] stdout:\n" + (result.stdout or ""), flush=True)
    if result.stderr:
        print("[codex-register] stderr:\n" + result.stderr, flush=True)

    if result.returncode != 0:
        print(f"[codex-register] 注册脚本退出码非 0: {result.returncode}", flush=True)
        append_log("error", f"script_exit_nonzero:{result.returncode}")
        return []

    json_files = sorted(tokens_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        print("[codex-register] 未找到新的 token JSON 文件", flush=True)
        append_log("warn", "no_token_json_found")
        return []

    token_infos = []
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[codex-register] 解析 token JSON 失败: {exc}", flush=True)
            append_log("error", f"token_json_parse_failed:{json_file.name}")
            continue

        if isinstance(data, list):
            token_infos.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            token_infos.append(data)
        print(f"[codex-register] 读取 token 文件: {json_file}", flush=True)

    return token_infos


def get_existing_account(cur, email: str, account_id: str):
    conditions = []
    params = []
    if email:
        conditions.append("credentials ->> 'email' = %s")
        params.append(email)
    if account_id:
        conditions.append("credentials ->> 'account_id' = %s")
        params.append(account_id)
    if not conditions:
        return None
    cur.execute(
        "SELECT id, name, credentials, extra FROM accounts WHERE platform = 'openai' AND type = 'oauth' "
        f"AND ({' OR '.join(conditions)}) ORDER BY id LIMIT 1",
        tuple(params),
    )
    return cur.fetchone()


def bind_groups(cur, account_id: int, group_ids: List[int]) -> None:
    if not group_ids:
        return
    cur.execute("DELETE FROM account_groups WHERE account_id = %s", (account_id,))
    for index, group_id in enumerate(group_ids, start=1):
        cur.execute(
            "INSERT INTO account_groups (account_id, group_id, priority, created_at) VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id, group_id) DO UPDATE SET priority = EXCLUDED.priority",
            (account_id, group_id, index),
        )


def build_credentials(existing: dict, token_info: dict) -> dict:
    credentials = dict(existing)
    credentials["access_token"] = token_info.get("access_token") or credentials.get("access_token") or ""
    credentials["refresh_token"] = token_info.get("refresh_token") or credentials.get("refresh_token") or ""
    credentials["id_token"] = token_info.get("id_token") or credentials.get("id_token") or ""
    if token_info.get("email"):
        credentials["email"] = token_info.get("email")
    if token_info.get("account_id"):
        credentials["account_id"] = token_info.get("account_id")
        credentials["chatgpt_account_id"] = token_info.get("account_id")
    if token_info.get("expired") is not None:
        credentials["expires_at"] = token_info.get("expired")
    credentials["source"] = "codex-auto-register"
    credentials["model_mapping"] = build_model_mapping()
    if token_info.get("auth_file"):
        credentials["codex_auth_file"] = token_info.get("auth_file")
    return credentials


def build_extra(existing: dict, token_info: dict) -> dict:
    extra = dict(existing)
    extra["codex_auto_register"] = True
    extra["codex_auto_register_model_target"] = "gpt-5.4"
    extra["codex_auto_register_updated_at"] = datetime.utcnow().isoformat() + "Z"
    if token_info.get("auth_file"):
        extra["codex_auth_file"] = token_info.get("auth_file")
    return extra


def upsert_account(cur, token_info: dict) -> str:
    email = token_info.get("email") or ""
    account_id = token_info.get("account_id") or ""
    if not email and not account_id:
        print("[codex-register] token 中缺少 email/account_id，跳过", flush=True)
        append_log("warn", "skip_missing_email_and_account_id")
        return "skipped"

    existing = get_existing_account(cur, email, account_id)
    group_ids = parse_group_ids()
    if existing is not None:
        existing_id, _existing_name, existing_credentials, existing_extra = existing
        credentials = build_credentials(ensure_dict(existing_credentials), token_info)
        extra = build_extra(ensure_dict(existing_extra), token_info)
        current_credentials = ensure_dict(existing_credentials)
        current_extra = ensure_dict(existing_extra)
        if credentials == current_credentials and extra == current_extra:
            bind_groups(cur, existing_id, group_ids)
            print(f"[codex-register] 账号无需更新，跳过: {email or account_id}", flush=True)
            append_log("info", f"skip_unchanged:{email or account_id}")
            return "skipped"
        cur.execute(
            "UPDATE accounts SET credentials = %s, extra = %s, status = 'active', schedulable = true, updated_at = NOW() WHERE id = %s",
            (Json(credentials), Json(extra), existing_id),
        )
        bind_groups(cur, existing_id, group_ids)
        print(f"[codex-register] 已更新账号: {email or account_id}", flush=True)
        append_log("info", f"updated:{email or account_id}")
        return "updated"

    identifier = email or account_id
    name = f"codex-{identifier}"
    credentials = build_credentials({}, token_info)
    extra = build_extra({}, token_info)

    cur.execute(
        "INSERT INTO accounts (name, platform, type, credentials, extra, concurrency, priority, rate_multiplier, status, schedulable, auto_pause_on_expired) "
        "VALUES (%s, 'openai', 'oauth', %s, %s, 3, 50, 1.0, 'active', true, true) RETURNING id",
        (name, Json(credentials), Json(extra)),
    )
    created_id = cur.fetchone()[0]
    bind_groups(cur, created_id, group_ids)
    print(f"[codex-register] 已插入新账号: {identifier}", flush=True)
    append_log("info", f"created:{identifier}")
    return "created"


def run_one_cycle(tokens_dir: Path) -> None:
    global last_run, last_success, last_error, total_created, total_updated, total_skipped
    global last_token_email, last_created_email, last_created_account_id, last_updated_email, last_updated_account_id
    global last_processed_records
    last_run = datetime.utcnow()
    try:
        conn = create_db_connection()
        cur = conn.cursor()
        print("[codex-register] 数据库连接成功", flush=True)
    except Exception as exc:  # noqa: BLE001
        last_error = traceback.format_exc()
        append_log("error", f"db_connect_failed:{exc}")
        print(f"[codex-register] 数据库连接失败，将在 10 秒后重试: {last_error}", flush=True)
        time.sleep(10)
        return

    try:
        token_infos = run_codex_once(tokens_dir)
        last_processed_records = len(token_infos)
        if token_infos:
            for token_info in token_infos:
                identifier = token_info.get("email") or token_info.get("account_id") or token_info.get("name") or ""
                if identifier:
                    last_token_email = identifier
                action = upsert_account(cur, token_info)
                if action == "created":
                    total_created += 1
                    last_created_email = token_info.get("email") or ""
                    last_created_account_id = token_info.get("account_id") or ""
                elif action == "updated":
                    total_updated += 1
                    last_updated_email = token_info.get("email") or ""
                    last_updated_account_id = token_info.get("account_id") or ""
                else:
                    total_skipped += 1
            last_success = datetime.utcnow()
            last_error = ""
            append_log("info", f"cycle_completed:{len(token_infos)}")
        else:
            append_log("info", "cycle_completed:0")
    except Exception:  # noqa: BLE001
        last_error = traceback.format_exc()
        append_log("error", "process_error")
        print(f"[codex-register] 处理流程异常: {last_error}", flush=True)
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def worker_loop(tokens_dir: Path, sleep_min: int, sleep_max: int) -> None:
    global enabled
    while True:
        if not enabled:
            time.sleep(5)
            continue
        run_one_cycle(tokens_dir)
        sleep_seconds = random.randint(sleep_min, sleep_max)
        print(f"[codex-register] 休眠 {sleep_seconds} 秒后继续下一轮", flush=True)
        time.sleep(sleep_seconds)


def get_status_payload() -> dict:
    proxy = get_env("CODEX_PROXY", "")
    return {
        "enabled": enabled,
        "sleep_min": sleep_min_global,
        "sleep_max": sleep_max_global,
        "total_created": total_created,
        "total_updated": total_updated,
        "total_skipped": total_skipped,
        "last_run": last_run.isoformat() + "Z" if last_run else None,
        "last_success": last_success.isoformat() + "Z" if last_success else None,
        "last_error": last_error,
        "proxy": bool(proxy),
        "last_token_email": last_token_email or None,
        "last_created_email": last_created_email or None,
        "last_created_account_id": last_created_account_id or None,
        "last_updated_email": last_updated_email or None,
        "last_updated_account_id": last_updated_account_id or None,
        "last_processed_records": last_processed_records,
    }


class CodexRequestHandler(BaseHTTPRequestHandler):
    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/status":
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/logs":
            body = json.dumps({"logs": recent_logs}).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/health":
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not_found"}')

    def do_POST(self) -> None:  # noqa: N802
        global enabled, tokens_dir_global
        if self.path == "/enable":
            enabled = True
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/disable":
            enabled = False
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/run-once":
            if tokens_dir_global is not None:
                run_one_cycle(tokens_dir_global)
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not_found"}')


def main() -> None:
    global sleep_min_global, sleep_max_global, tokens_dir_global
    sleep_min = int(get_env("CODEX_SLEEP_MIN", "5"))
    sleep_max = int(get_env("CODEX_SLEEP_MAX", "30"))
    if sleep_min < 1:
        sleep_min = 1
    if sleep_max < sleep_min:
        sleep_max = sleep_min

    sleep_min_global = sleep_min
    sleep_max_global = sleep_max

    tokens_dir = Path("/app/codex-auto-register-main/tokens")
    tokens_dir_global = tokens_dir

    worker = threading.Thread(target=worker_loop, args=(tokens_dir, sleep_min, sleep_max), daemon=True)
    worker.start()

    port = int(get_env("CODEX_HTTP_PORT", "5000"))
    server = HTTPServer(("0.0.0.0", port), CodexRequestHandler)
    print(f"[codex-register] HTTP 服务启动于 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
