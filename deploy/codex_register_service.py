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

import psycopg2
from psycopg2.extras import Json


enabled = True
last_run = None
last_success = None
last_error = ""
total_created = 0
sleep_min_global = 0
sleep_max_global = 0
tokens_dir_global = None
recent_logs = []


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
        return None

    json_files = sorted(tokens_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        print("[codex-register] 未找到新的 token JSON 文件", flush=True)
        return None

    latest = json_files[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[codex-register] 解析 token JSON 失败: {exc}", flush=True)
        return None

    print(f"[codex-register] 读取 token 文件: {latest}", flush=True)
    return data


def account_exists(cur, email: str) -> bool:
    cur.execute(
        "SELECT id FROM accounts WHERE platform = 'openai' AND type = 'oauth' "
        "AND credentials ->> 'email' = %s LIMIT 1",
        (email,),
    )
    return cur.fetchone() is not None


def insert_account(cur, token_info: dict) -> None:
    email = token_info.get("email") or ""
    if not email:
        print("[codex-register] token 中缺少 email，跳过", flush=True)
        return

    if account_exists(cur, email):
        print(f"[codex-register] 账号已存在于数据库中，跳过: {email}", flush=True)
        return

    name = f"codex-{email}"

    creds = {
        "access_token": token_info.get("access_token"),
        "refresh_token": token_info.get("refresh_token"),
        "id_token": token_info.get("id_token"),
        "email": email,
        "account_id": token_info.get("account_id"),
        "expires_at": token_info.get("expired"),
        "source": "codex-auto-register",
    }

    sql = (
        "INSERT INTO accounts (name, platform, type, credentials, extra, "
        "concurrency, priority, rate_multiplier, status, schedulable, auto_pause_on_expired) "
        "VALUES (%s, 'openai', 'oauth', %s, '{}'::jsonb, 3, 50, 1.0, 'active', true, true)"
    )

    cur.execute(sql, (name, Json(creds)))
    print(f"[codex-register] 已插入新账号: {email}", flush=True)


def run_one_cycle(tokens_dir: Path) -> None:
    global last_run, last_success, last_error, total_created
    last_run = datetime.utcnow()
    try:
        conn = create_db_connection()
        cur = conn.cursor()
        print("[codex-register] 数据库连接成功", flush=True)
    except Exception as exc:  # noqa: BLE001
        last_error = traceback.format_exc()
        recent_logs.append(
            {
                "time": datetime.utcnow().isoformat() + "Z",
                "level": "error",
                "message": f"db_connect_failed: {exc}",
            }
        )
        if len(recent_logs) > 50:
            del recent_logs[0 : len(recent_logs) - 50]
        print(f"[codex-register] 数据库连接失败，将在 10 秒后重试: {last_error}", flush=True)
        time.sleep(10)
        return

    try:
        token_info = run_codex_once(tokens_dir)
        if token_info:
            insert_account(cur, token_info)
            total_created += 1
            last_success = datetime.utcnow()
            last_error = ""
            recent_logs.append(
                {
                    "time": last_success.isoformat() + "Z",
                    "level": "info",
                    "message": "created account",
                }
            )
            if len(recent_logs) > 50:
                del recent_logs[0 : len(recent_logs) - 50]
    except Exception:  # noqa: BLE001
        last_error = traceback.format_exc()
        recent_logs.append(
            {
                "time": datetime.utcnow().isoformat() + "Z",
                "level": "error",
                "message": "process_error",
            }
        )
        if len(recent_logs) > 50:
            del recent_logs[0 : len(recent_logs) - 50]
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
        "last_run": last_run.isoformat() + "Z" if last_run else None,
        "last_success": last_success.isoformat() + "Z" if last_success else None,
        "last_error": last_error,
        "proxy": bool(proxy),
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
