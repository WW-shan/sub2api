import json
import os
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import traceback
from typing import List, Set, Tuple


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
status_lock = threading.Lock()


def append_log(level: str, message: str) -> None:
    with status_lock:
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
    import psycopg2

    host = get_env("POSTGRES_HOST", "postgres")
    port = int(get_env("POSTGRES_PORT", "5432"))
    connect_timeout = int(get_env("POSTGRES_CONNECT_TIMEOUT", "5"))
    user = get_env("POSTGRES_USER", required=True)
    password = get_env("POSTGRES_PASSWORD", required=True)
    dbname = get_env("POSTGRES_DB", required=True)

    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname,
        connect_timeout=connect_timeout,
    )
    conn.autocommit = True
    return conn


def pg_json(value):
    from psycopg2.extras import Json

    return Json(value)


def normalize_extra_for_compare(extra: dict) -> dict:
    normalized = ensure_dict(extra)
    normalized.pop("codex_auto_register_updated_at", None)
    return normalized


def should_update_account(
    current_credentials: dict,
    next_credentials: dict,
    current_extra: dict,
    next_extra: dict,
) -> bool:
    return (
        current_credentials != next_credentials
        or normalize_extra_for_compare(current_extra) != normalize_extra_for_compare(next_extra)
    )


def archive_processed_file(source: Path, processed_dir: Path) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"source token file not found: {source}")
    processed_dir.mkdir(parents=True, exist_ok=True)
    target = processed_dir / source.name
    while target.exists():
        target = processed_dir / f"{int(time.time() * 1000)}-{source.name}"
    shutil.move(str(source), str(target))
    return target


def compute_group_binding_changes(current_group_ids: Set[int], next_group_ids: Set[int]) -> Tuple[Set[int], Set[int]]:
    return next_group_ids - current_group_ids, current_group_ids - next_group_ids


def run_codex_once(tokens_dir: Path) -> List[Tuple[Path, List[dict]]]:
    codex_dir = Path("/app/codex-auto-register-main")
    script_name = get_env("CODEX_REGISTER_SCRIPT", "codex-autp-register.py")
    script_path = codex_dir / script_name
    if not script_path.exists():
        fallback_script_path = codex_dir / "codex-auto-register.py"
        if fallback_script_path.exists():
            script_path = fallback_script_path

    tokens_dir.mkdir(parents=True, exist_ok=True)

    proxy = get_env("CODEX_PROXY", "")
    cmd = [sys.executable, str(script_path), "--once"]
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

    batches: List[Tuple[Path, List[dict]]] = []
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[codex-register] 解析 token JSON 失败: {exc}", flush=True)
            append_log("error", f"token_json_parse_failed:{json_file.name}")
            continue

        token_infos: List[dict] = []
        if isinstance(data, list):
            token_infos.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            token_infos.append(data)
        print(f"[codex-register] 读取 token 文件: {json_file}", flush=True)
        batches.append((json_file, token_infos))

    return batches


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

    desired_priority = {group_id: index for index, group_id in enumerate(group_ids, start=1)}
    desired_ids = set(desired_priority.keys())

    cur.execute("SELECT group_id, priority FROM account_groups WHERE account_id = %s", (account_id,))
    current_rows = cur.fetchall()
    current_priority = {int(row[0]): int(row[1]) for row in current_rows}
    current_ids = set(current_priority.keys())

    to_add, to_remove = compute_group_binding_changes(current_ids, desired_ids)

    for group_id in to_remove:
        cur.execute("DELETE FROM account_groups WHERE account_id = %s AND group_id = %s", (account_id, group_id))

    for group_id in to_add:
        cur.execute(
            "INSERT INTO account_groups (account_id, group_id, priority, created_at) VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (account_id, group_id) DO UPDATE SET priority = EXCLUDED.priority",
            (account_id, group_id, desired_priority[group_id]),
        )

    retained_ids = desired_ids.intersection(current_ids)
    for group_id in retained_ids:
        next_priority = desired_priority[group_id]
        if current_priority[group_id] != next_priority:
            cur.execute(
                "UPDATE account_groups SET priority = %s WHERE account_id = %s AND group_id = %s",
                (next_priority, account_id, group_id),
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
        if not should_update_account(current_credentials, credentials, current_extra, extra):
            bind_groups(cur, existing_id, group_ids)
            print(f"[codex-register] 账号无需更新，跳过: {email or account_id}", flush=True)
            append_log("info", f"skip_unchanged:{email or account_id}")
            return "skipped"

        extra["codex_auto_register_updated_at"] = datetime.utcnow().isoformat() + "Z"
        cur.execute(
            "UPDATE accounts SET credentials = %s, extra = %s, status = 'active', schedulable = true, updated_at = NOW() WHERE id = %s",
            (pg_json(credentials), pg_json(extra), existing_id),
        )
        bind_groups(cur, existing_id, group_ids)
        print(f"[codex-register] 已更新账号: {email or account_id}", flush=True)
        append_log("info", f"updated:{email or account_id}")
        return "updated"

    identifier = email or account_id
    name = f"codex-{identifier}"
    credentials = build_credentials({}, token_info)
    extra = build_extra({}, token_info)
    extra["codex_auto_register_updated_at"] = datetime.utcnow().isoformat() + "Z"

    cur.execute(
        "INSERT INTO accounts (name, platform, type, credentials, extra, concurrency, priority, rate_multiplier, status, schedulable, auto_pause_on_expired) "
        "VALUES (%s, 'openai', 'oauth', %s, %s, 3, 50, 1.0, 'active', true, true) RETURNING id",
        (name, pg_json(credentials), pg_json(extra)),
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
    with status_lock:
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
        batches = run_codex_once(tokens_dir)
        with status_lock:
            last_processed_records = sum(len(items) for _, items in batches)
        if batches:
            processed_dir = tokens_dir / "processed"
            for source_file, token_infos in batches:
                file_success = True
                for token_info in token_infos:
                    try:
                        identifier = token_info.get("email") or token_info.get("account_id") or token_info.get("name") or ""
                        if identifier:
                            with status_lock:
                                last_token_email = identifier
                        action = upsert_account(cur, token_info)
                        if action == "created":
                            with status_lock:
                                total_created += 1
                                last_created_email = token_info.get("email") or ""
                                last_created_account_id = token_info.get("account_id") or ""
                        elif action == "updated":
                            with status_lock:
                                total_updated += 1
                                last_updated_email = token_info.get("email") or ""
                                last_updated_account_id = token_info.get("account_id") or ""
                        else:
                            with status_lock:
                                total_skipped += 1
                    except Exception as exc:  # noqa: BLE001
                        file_success = False
                        append_log("error", f"token_process_failed:{source_file.name}:{exc}")
                        print(f"[codex-register] 处理 token 失败（保留重试）: {source_file} {exc}", flush=True)
                        break

                if file_success:
                    try:
                        archived = archive_processed_file(source_file, processed_dir)
                        append_log("info", f"archived:{archived.name}")
                    except Exception as exc:  # noqa: BLE001
                        append_log("error", f"archive_failed:{source_file.name}:{exc}")
                        print(f"[codex-register] 归档 token 文件失败（保留重试）: {source_file} {exc}", flush=True)
            with status_lock:
                last_success = datetime.utcnow()
                last_error = ""
            append_log("info", f"cycle_completed:{last_processed_records}")
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
    while True:
        with status_lock:
            worker_enabled = enabled
        if not worker_enabled:
            time.sleep(5)
            continue
        run_one_cycle(tokens_dir)
        sleep_seconds = random.randint(sleep_min, sleep_max)
        print(f"[codex-register] 休眠 {sleep_seconds} 秒后继续下一轮", flush=True)
        time.sleep(sleep_seconds)


def get_status_payload() -> dict:
    proxy = get_env("CODEX_PROXY", "")
    with status_lock:
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
            with status_lock:
                logs = list(recent_logs)
            body = json.dumps({"logs": logs}).encode("utf-8")
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
            with status_lock:
                enabled = True
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/disable":
            with status_lock:
                enabled = False
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/run-once":
            with status_lock:
                run_once_tokens_dir = tokens_dir_global
            if run_once_tokens_dir is not None:
                run_one_cycle(run_once_tokens_dir)
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

    with status_lock:
        sleep_min_global = sleep_min
        sleep_max_global = sleep_max

    tokens_dir = Path("/app/codex-auto-register-main/tokens")
    with status_lock:
        tokens_dir_global = tokens_dir

    worker = threading.Thread(target=worker_loop, args=(tokens_dir, sleep_min, sleep_max), daemon=True)
    worker.start()

    port = int(get_env("CODEX_HTTP_PORT", "5000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), CodexRequestHandler)
    print(f"[codex-register] HTTP 服务启动于 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
