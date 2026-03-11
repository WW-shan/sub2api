import argparse
import base64
import hashlib
import importlib
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple



def get_requests_module():
    return importlib.import_module("curl_cffi.requests")


enabled = False
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
workflow_id = ""
job_phase = "idle"
waiting_reason = ""
last_transition: Dict[str, Any] = {}
last_resume_gate_reason = ""
active_workflow_thread = None
active_workflow_cancel_event = threading.Event()
status_lock = threading.Lock()
JSONDict = Dict[str, Any]
STATUS_LOG_TAIL_LIMIT = 50
LOGS_ENDPOINT_DEFAULT_LIMIT = 200
LOGS_ENDPOINT_MAX_LIMIT = 1000
VALID_LOG_LEVELS = {"info", "warn", "error"}
WAITING_MANUAL_PREFIX = "waiting_manual:"
PHASE_IDLE = "idle"
PHASE_RUNNING_CREATE_PARENT = "running:create_parent"
PHASE_WAITING_PARENT_UPGRADE = "waiting_manual:parent_upgrade"
PHASE_RUNNING_PRE_RESUME_CHECK = "running:pre_resume_check"
PHASE_RUNNING_INVITE_CHILDREN = "running:invite_children"
PHASE_RUNNING_ACCEPT_AND_SWITCH = "running:accept_and_switch"
PHASE_RUNNING_VERIFY_AND_BIND = "running:verify_and_bind"
PHASE_COMPLETED = "completed"
PHASE_ABANDONED = "abandoned"
PHASE_FAILED = "failed"
CANONICAL_JOB_PHASES = {
    PHASE_IDLE,
    PHASE_RUNNING_CREATE_PARENT,
    PHASE_WAITING_PARENT_UPGRADE,
    PHASE_RUNNING_PRE_RESUME_CHECK,
    PHASE_RUNNING_INVITE_CHILDREN,
    PHASE_RUNNING_ACCEPT_AND_SWITCH,
    PHASE_RUNNING_VERIFY_AND_BIND,
    PHASE_COMPLETED,
    PHASE_ABANDONED,
    PHASE_FAILED,
}
VALID_PARENT_PLAN_TYPES = {"team", "business"}
PARENT_RESUME_GATE_REASONS = {
    "parent_upgrade",
    "plan_type_missing",
    "plan_type_invalid",
    "organization_id_missing",
    "workspace_id_missing",
    "workspace_unreachable",
    "members_page_inaccessible",
    "parent_account_id_missing",
    "parent_access_token_missing",
}

DEFAULT_MODEL_MAPPING: Dict[str, str] = {
    "claude-haiku*": "gpt-5.3-codex",
    "claude-sonnet*": "gpt-5.3-codex",
    "claude-opus*": "gpt-5.3-codex",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-none": "gpt-5.4",
    "gpt-5.4-low": "gpt-5.4",
    "gpt-5.4-medium": "gpt-5.4",
    "gpt-5.4-high": "gpt-5.4",
    "gpt-5.4-xhigh": "gpt-5.4",
    "gpt-5.4-chat-latest": "gpt-5.4",
    "gpt-5.3": "gpt-5.3-codex",
    "gpt-5.3-none": "gpt-5.3-codex",
    "gpt-5.3-low": "gpt-5.3-codex",
    "gpt-5.3-medium": "gpt-5.3-codex",
    "gpt-5.3-high": "gpt-5.3-codex",
    "gpt-5.3-xhigh": "gpt-5.3-codex",
    "gpt-5.3-codex": "gpt-5.3-codex",
    "gpt-5.3-codex-spark": "gpt-5.3-codex-spark",
    "gpt-5.3-codex-spark-low": "gpt-5.3-codex-spark",
    "gpt-5.3-codex-spark-medium": "gpt-5.3-codex-spark",
    "gpt-5.3-codex-spark-high": "gpt-5.3-codex-spark",
    "gpt-5.3-codex-spark-xhigh": "gpt-5.3-codex-spark",
    "gpt-5.3-codex-low": "gpt-5.3-codex",
    "gpt-5.3-codex-medium": "gpt-5.3-codex",
    "gpt-5.3-codex-high": "gpt-5.3-codex",
    "gpt-5.3-codex-xhigh": "gpt-5.3-codex",
    "gpt-5.1-codex": "gpt-5.1-codex",
    "gpt-5.1-codex-low": "gpt-5.1-codex",
    "gpt-5.1-codex-medium": "gpt-5.1-codex",
    "gpt-5.1-codex-high": "gpt-5.1-codex",
    "gpt-5.1-codex-max": "gpt-5.1-codex-max",
    "gpt-5.1-codex-max-low": "gpt-5.1-codex-max",
    "gpt-5.1-codex-max-medium": "gpt-5.1-codex-max",
    "gpt-5.1-codex-max-high": "gpt-5.1-codex-max",
    "gpt-5.1-codex-max-xhigh": "gpt-5.1-codex-max",
    "gpt-5.2": "gpt-5.2",
    "gpt-5.2-none": "gpt-5.2",
    "gpt-5.2-low": "gpt-5.2",
    "gpt-5.2-medium": "gpt-5.2",
    "gpt-5.2-high": "gpt-5.2",
    "gpt-5.2-xhigh": "gpt-5.2",
    "gpt-5.2-codex": "gpt-5.2-codex",
    "gpt-5.2-codex-low": "gpt-5.2-codex",
    "gpt-5.2-codex-medium": "gpt-5.2-codex",
    "gpt-5.2-codex-high": "gpt-5.2-codex",
    "gpt-5.2-codex-xhigh": "gpt-5.2-codex",
    "gpt-5.1-codex-mini": "gpt-5.1-codex-mini",
    "gpt-5.1-codex-mini-medium": "gpt-5.1-codex-mini",
    "gpt-5.1-codex-mini-high": "gpt-5.1-codex-mini",
    "gpt-5.1": "gpt-5.1",
    "gpt-5.1-none": "gpt-5.1",
    "gpt-5.1-low": "gpt-5.1",
    "gpt-5.1-medium": "gpt-5.1",
    "gpt-5.1-high": "gpt-5.1",
    "gpt-5.1-chat-latest": "gpt-5.1",
    "gpt-5-codex": "gpt-5.1-codex",
    "codex-mini-latest": "gpt-5.1-codex-mini",
    "gpt-5-codex-mini": "gpt-5.1-codex-mini",
    "gpt-5-codex-mini-medium": "gpt-5.1-codex-mini",
    "gpt-5-codex-mini-high": "gpt-5.1-codex-mini",
    "gpt-5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
    "gpt-5-nano": "gpt-5-nano",
}


def _append_log_locked(level: str, message: str) -> None:
    recent_logs.append(
        {
            "time": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "message": message,
        }
    )
    if len(recent_logs) > 100:
        del recent_logs[0 : len(recent_logs) - 100]


def append_log(level: str, message: str) -> None:
    with status_lock:
        _append_log_locked(level, message)


def _safe_parent_record_summary(parent_record: JSONDict) -> JSONDict:
    return {
        "email": str(parent_record.get("email") or "").strip(),
        "account_id": str(parent_record.get("account_id") or "").strip(),
        "plan_type": str(parent_record.get("plan_type") or "").strip().lower(),
        "organization_id": str(parent_record.get("organization_id") or "").strip(),
        "workspace_id": str(parent_record.get("workspace_id") or "").strip(),
        "workspace_reachable": parent_record.get("workspace_reachable"),
        "members_page_accessible": parent_record.get("members_page_accessible"),
        "has_access_token": bool(str(parent_record.get("session_access_token") or parent_record.get("access_token") or "").strip()),
    }


def _log_resume_gate_decision(gate_reason: str, parent_record: JSONDict) -> None:
    global last_resume_gate_reason
    decision = {
        "gate_reason": gate_reason or "",
        "parent": _safe_parent_record_summary(parent_record),
    }
    with status_lock:
        last_resume_gate_reason = gate_reason or ""
        _append_log_locked("info", f"resume_gate_decision:{json.dumps(decision, ensure_ascii=False)}")


def ensure_dict(value: object) -> JSONDict:
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


def build_model_mapping() -> Dict[str, str]:
    raw = get_env("CODEX_MODEL_MAPPING_JSON", "")
    if not raw:
        return dict(DEFAULT_MODEL_MAPPING)

    parsed = ensure_dict(raw)
    mapping: Dict[str, str] = {}
    for key, value in parsed.items():
        pattern = str(key).strip()
        target = str(value).strip()
        if pattern and target:
            mapping[pattern] = target

    if mapping:
        return mapping

    return dict(DEFAULT_MODEL_MAPPING)


def get_env(name: str, default=None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"环境变量 {name} 未配置且为必需")
    return value or ""


def _masked_secret(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "***"
    return f"{raw[:4]}...{raw[-4:]}"


def _redact_account_record(record: JSONDict) -> JSONDict:
    redacted = dict(record or {})
    redacted["refresh_token"] = _masked_secret(redacted.get("refresh_token"))
    redacted["access_token"] = _masked_secret(redacted.get("access_token"))
    return redacted


def _is_request_authorized(handler: BaseHTTPRequestHandler) -> bool:
    expected_api_key = str(get_env("CODEX_HTTP_API_KEY", "") or "").strip()
    if not expected_api_key:
        return True
    provided_api_key = str(getattr(handler, "headers", {}).get("X-API-Key") or "").strip()
    return bool(provided_api_key) and secrets.compare_digest(provided_api_key, expected_api_key)


def _workflow_cancelled(workflow_token: str) -> bool:
    with status_lock:
        if workflow_id != workflow_token:
            return True
        return active_workflow_cancel_event.is_set() or job_phase == PHASE_ABANDONED


def workspace_plan_type(workspace: JSONDict) -> str:
    candidates = [
        workspace.get("plan_type"),
        workspace.get("planType"),
        workspace.get("workspace_plan_type"),
        workspace.get("subscription_plan"),
        workspace.get("plan"),
    ]
    for item in candidates:
        value = str(item or "").strip().lower()
        if value:
            return value
    return ""


def workspace_organization_id(workspace: JSONDict) -> str:
    candidates = [
        workspace.get("organization_id"),
        workspace.get("organizationId"),
        workspace.get("org_id"),
        workspace.get("id"),
    ]
    for item in candidates:
        value = str(item or "").strip()
        if value:
            return value
    return ""


def workspace_identifier(workspace: JSONDict) -> str:
    candidates = [
        workspace.get("id"),
        workspace.get("workspace_id"),
        workspace.get("workspaceId"),
    ]
    for item in candidates:
        value = str(item or "").strip()
        if value:
            return value
    return ""


def select_parent_workspace(workspaces: List[JSONDict], preferred_workspace_id: str) -> JSONDict:
    preferred_id = str(preferred_workspace_id or "").strip()
    if preferred_id:
        for workspace in workspaces:
            workspace_id = str((workspace or {}).get("id") or "").strip()
            if workspace_id == preferred_id:
                return workspace

    for workspace in workspaces:
        plan_type = workspace_plan_type(workspace)
        if plan_type in VALID_PARENT_PLAN_TYPES:
            return workspace

    return workspaces[0] if workspaces else {}


AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _worker_headers(worker_token: str) -> Dict[str, Any]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {worker_token}",
    }


def get_email_and_token(proxies: Any = None) -> tuple[str, str, str]:
    del proxies
    try:
        domain = get_env("CODEX_MAIL_DOMAIN", required=True).strip().lower()
        local = f"oc{secrets.token_hex(5)}"
        email = f"{local}@{domain}"
        password = secrets.token_urlsafe(18)
        return email, "worker", password
    except Exception as exc:
        print(f"[Error] 生成自定义域名邮箱失败: {exc}")
        return "", "", ""


def get_oai_code(token: str, email: str, proxies: Any = None) -> str:
    del token
    requests = get_requests_module()

    worker_base = get_env("CODEX_MAIL_WORKER_BASE_URL", required=True).rstrip("/")
    worker_token = get_env("CODEX_MAIL_WORKER_TOKEN", required=True).strip()
    poll_seconds = max(1, int(get_env("CODEX_MAIL_POLL_SECONDS", "3")))
    max_attempts = max(1, int(get_env("CODEX_MAIL_POLL_MAX_ATTEMPTS", "40")))

    query_url = f"{worker_base}/v1/code?email={urllib.parse.quote(email)}"

    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)
    for attempt in range(max_attempts):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                url=query_url,
                headers=_worker_headers(worker_token),
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            print(f" [poll#{attempt + 1}] Worker 轮询状态: {resp.status_code}")

            if resp.status_code == 200:
                data = ensure_dict(resp.json())
                code = str(data.get("code") or "").strip()
                if code:
                    print(" 抓到啦! 验证码:", code)
                    return code
                time.sleep(poll_seconds)
                continue

            if resp.status_code == 404:
                time.sleep(poll_seconds)
                continue

            if resp.status_code == 401:
                print(" [Error] Worker 鉴权失败，请检查 CODEX_MAIL_WORKER_TOKEN")
                return ""
        except Exception as exc:
            print(f" [poll#{attempt + 1}] Worker 轮询异常: {exc}")

        time.sleep(poll_seconds)

    print(" 超时，未收到验证码")
    return ""


def _sanitize_filename_component(value: str, fallback: str = "unknown") -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    sanitized = sanitized.strip("._-")
    if not sanitized:
        return fallback
    return sanitized[:128]


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(value: str) -> str:
    return _b64url_no_pad(hashlib.sha256(value.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _parse_callback_url(callback_url: str) -> Dict[str, Any]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)
    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(key: str) -> str:
        values = query.get(key, [""])
        return (values[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")
    if code and not state and "#" in code:
        code, state = code.split("#", 1)
    if not error and error_description:
        error, error_description = error_description, ""
    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _decode_jwt_segment(segment: str) -> Dict[str, Any]:
    raw = (segment or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _post_form(url: str, data: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}") from exc


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(*, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(auth_url=auth_url, state=state, code_verifier=code_verifier, redirect_uri=redirect_uri)


def submit_callback_url(*, callback_url: str, expected_state: str, code_verifier: str, redirect_uri: str = DEFAULT_REDIRECT_URI) -> str:
    callback = _parse_callback_url(callback_url)
    if callback["error"]:
        desc = callback["error_description"]
        raise RuntimeError(f"oauth error: {callback['error']}: {desc}".strip())
    if not callback["code"]:
        raise ValueError("callback url missing ?code=")
    if not callback["state"]:
        raise ValueError("callback url missing ?state=")
    if callback["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": callback["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))
    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0)))
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }
    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


def extract_session_access_token(session_payload: JSONDict) -> str:
    if not isinstance(session_payload, dict):
        return ""
    return str(session_payload.get("accessToken") or "").strip()


def fetch_session_access_token(session: Any) -> str:
    try:
        response = session.get("https://chatgpt.com/api/auth/session", timeout=15)
    except Exception as exc:  # noqa: BLE001
        append_log("warn", f"session_access_token_request_failed:{exc}")
        return ""

    if getattr(response, "status_code", 0) != 200:
        append_log("warn", f"session_access_token_status:{getattr(response, 'status_code', 0)}")
        return ""

    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        append_log("warn", f"session_access_token_parse_failed:{exc}")
        return ""

    token = extract_session_access_token(payload)
    if not token:
        append_log("warn", "session_access_token_missing")
    return token


def run(proxy: Optional[str]) -> Optional[str]:
    requests = get_requests_module()
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    session = requests.Session(proxies=proxies, impersonate="chrome")
    try:
        trace = session.get("https://cloudflare.com/cdn-cgi/trace", timeout=10).text
        loc_match = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_match.group(1) if loc_match else None
        print(f"[*] 当前 IP 所在地: {loc}")
        if loc == "CN":
            raise RuntimeError("检查代理哦w - 所在地不支持")
    except Exception as exc:
        print(f"[Error] 网络连接检查失败: {exc}")
        return None

    email, dev_token, password = get_email_and_token(proxies)
    if not email or not dev_token:
        return None
    print(f"[*] 成功获取自定义邮箱与授权: {email}")

    oauth = generate_oauth_url()
    try:
        session.get(oauth.auth_url, timeout=15)
        did = session.cookies.get("oai-did")
        print(f"[*] Device ID: {did}")

        signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'

        sen_resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )
        if sen_resp.status_code != 200:
            print(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
            return None

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        signup_resp = session.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
            },
            data=signup_body,
        )
        print(f"[*] 提交注册表单状态: {signup_resp.status_code}")

        otp_resp = session.post(
            "https://auth.openai.com/api/accounts/passwordless/send-otp",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
        print(f"[*] 验证码发送状态: {otp_resp.status_code}")

        code = get_oai_code(dev_token, email, proxies)
        if not code:
            return None

        code_body = f'{{"code":"{code}"}}'
        code_resp = session.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
        )
        print(f"[*] 验证码校验状态: {code_resp.status_code}")

        create_account_body = '{"name":"Neo","birthdate":"2000-02-20"}'
        create_account_resp = session.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_account_body,
        )
        create_account_status = create_account_resp.status_code
        print(f"[*] 账户创建状态: {create_account_status}")
        if create_account_status != 200:
            print(create_account_resp.text)
            return None

        auth_cookie = session.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            print("[Error] 未能获取到授权 Cookie")
            return None

        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        workspaces = auth_json.get("workspaces") or []
        if not workspaces:
            print("[Error] 授权 Cookie 里没有 workspace 信息")
            return None
        preferred_workspace_id = get_env("CODEX_PARENT_WORKSPACE_ID", "").strip()
        selected_workspace = select_parent_workspace(workspaces, preferred_workspace_id)
        selected_workspace_id = workspace_identifier(selected_workspace)
        if not selected_workspace_id:
            print("[Error] 无法解析 workspace_id")
            return None

        select_body = f'{{"workspace_id":"{selected_workspace_id}"}}'
        select_resp = session.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=select_body,
        )
        if select_resp.status_code != 200:
            print(f"[Error] 选择 workspace 失败，状态码: {select_resp.status_code}")
            print(select_resp.text)
            return None

        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            print("[Error] workspace/select 响应里缺少 continue_url")
            return None

        current_url = continue_url
        for _ in range(6):
            final_resp = session.get(current_url, allow_redirects=False, timeout=15)
            location = final_resp.headers.get("Location") or ""
            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                token_json = submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                )
                try:
                    token_payload = ensure_dict(token_json)
                    selected_plan_type = workspace_plan_type(selected_workspace)
                    selected_organization_id = workspace_organization_id(selected_workspace)
                    if selected_plan_type:
                        token_payload["plan_type"] = selected_plan_type
                        token_payload["codex_parent_plan_type"] = selected_plan_type
                    selected_workspace_id = workspace_identifier(selected_workspace)
                    if selected_organization_id:
                        token_payload["organization_id"] = selected_organization_id
                        token_payload["codex_parent_organization_id"] = selected_organization_id
                    if selected_workspace_id:
                        token_payload["workspace_id"] = selected_workspace_id
                        token_payload["codex_parent_workspace_id"] = selected_workspace_id
                    token_payload["codex_register_role"] = "parent"
                    session_access_token = fetch_session_access_token(session)
                    if session_access_token:
                        token_payload["session_access_token"] = session_access_token
                        token_payload["access_token"] = session_access_token
                    return json.dumps(token_payload, ensure_ascii=False, separators=(",", ":"))
                except Exception as exc:  # noqa: BLE001
                    append_log("warn", f"token_payload_augment_failed:{exc}")
                    return token_json
            current_url = next_url

        print("[Error] 未能在重定向链中捕获到最终 Callback URL")
        return None
    except Exception as exc:
        print(f"[Error] 运行时发生错误: {exc}")
        return None


def run_auto_register_cli(*, proxy: Optional[str], once: bool, sleep_min: int, sleep_max: int, tokens_dir: Path) -> None:
    sleep_min = max(1, sleep_min)
    sleep_max = max(sleep_min, sleep_max)
    count = 0
    print("[Info] Seamless OpenAI Auto-Registrar Started")
    while True:
        count += 1
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] >>> 开始第 {count} 次注册流程 <<<")
        try:
            token_json = run(proxy)
            if token_json:
                try:
                    token_data = json.loads(token_json)
                    filename_email = _sanitize_filename_component(str(token_data.get("email", "unknown")))
                    refresh_token = token_data.get("refresh_token", "")
                except Exception:
                    filename_email = "unknown"
                    refresh_token = ""

                tokens_dir.mkdir(parents=True, exist_ok=True)
                file_name = tokens_dir / f"token_{filename_email}_{int(time.time())}.json"
                with file_name.open("w", encoding="utf-8") as file_obj:
                    file_obj.write(token_json)
                print(f"[*] 成功! Token 已保存至: {file_name}")

                if refresh_token:
                    rt_file = tokens_dir / "RT.txt"
                    with rt_file.open("a", encoding="utf-8") as file_obj:
                        file_obj.write(refresh_token + "\n")
                    print(f"[*] Refresh Token 已追加至：{rt_file}")
            else:
                print("[-] 本次注册失败。")
        except Exception as exc:
            print(f"[Error] 发生未捕获异常: {exc}")

        if once:
            break
        wait_time = random.randint(sleep_min, sleep_max)
        print(f"[*] 休息 {wait_time} 秒...")
        time.sleep(wait_time)


def create_db_connection():
    psycopg2 = importlib.import_module("psycopg2")

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


def list_codex_register_accounts() -> List[JSONDict]:
    conn = create_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, email, refresh_token, access_token, account_id, source, created_at, updated_at "
            "FROM codex_register_accounts WHERE source = 'codex-register' ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
        records: List[JSONDict] = []
        for row in rows:
            records.append(
                {
                    "id": row[0],
                    "email": row[1],
                    "refresh_token": row[2],
                    "access_token": row[3],
                    "account_id": row[4],
                    "source": row[5],
                    "created_at": row[6].isoformat() + "Z" if row[6] is not None else None,
                    "updated_at": row[7].isoformat() + "Z" if row[7] is not None else None,
                }
            )
        return records
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def pg_json(value):
    Json = importlib.import_module("psycopg2.extras").Json

    return Json(value)


def normalize_extra_for_compare(extra: JSONDict) -> JSONDict:
    normalized = ensure_dict(extra)
    normalized.pop("codex_auto_register_updated_at", None)
    return normalized


def should_update_account(
    current_credentials: JSONDict,
    next_credentials: JSONDict,
    current_extra: JSONDict,
    next_extra: JSONDict,
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


def run_codex_once(
    tokens_dir: Path,
    *,
    preferred_workspace_id: str = "",
    fixed_email: str = "",
    fixed_password: str = "",
) -> List[Tuple[Path, List[JSONDict]]]:
    service_file = Path(__file__).resolve()
    tokens_dir.mkdir(parents=True, exist_ok=True)

    proxy = get_env("CODEX_PROXY", "")
    timeout_seconds = max(1, int(get_env("CODEX_REGISTER_SUBPROCESS_TIMEOUT", "120")))
    cmd = [sys.executable, str(service_file), "--register-only", "--once", "--tokens-dir", str(tokens_dir)]
    if proxy:
        cmd.extend(["--proxy", proxy])

    env = dict(os.environ)
    workspace_override = str(preferred_workspace_id or "").strip()
    if workspace_override:
        env["CODEX_PARENT_WORKSPACE_ID"] = workspace_override

    fixed_email_value = str(fixed_email or "").strip()
    if fixed_email_value:
        env["CODEX_FIXED_EMAIL"] = fixed_email_value
    fixed_password_value = str(fixed_password or "").strip()
    if fixed_password_value:
        env["CODEX_FIXED_PASSWORD"] = fixed_password_value

    print("[codex-register] 启动注册脚本:", " ".join(cmd), flush=True)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(service_file.parent),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired:
        reason = "script_timeout"
        append_log("error", f"script_timeout:{timeout_seconds}")
        print(f"[codex-register] 注册脚本执行超时: {timeout_seconds}s", flush=True)
        raise RuntimeError(reason)

    print("[codex-register] stdout:\n" + (result.stdout or ""), flush=True)
    if result.stderr:
        print("[codex-register] stderr:\n" + result.stderr, flush=True)

    if result.returncode != 0:
        reason = f"script_exit_nonzero:{result.returncode}"
        print(f"[codex-register] 注册脚本退出码非 0: {result.returncode}", flush=True)
        append_log("error", reason)
        raise RuntimeError(reason)

    json_files = sorted(tokens_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        print("[codex-register] 未找到新的 token JSON 文件", flush=True)
        append_log("warn", "no_token_json_found")
        return []

    batches: List[Tuple[Path, List[JSONDict]]] = []
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[codex-register] 解析 token JSON 失败: {exc}", flush=True)
            append_log("error", f"token_json_parse_failed:{json_file.name}")
            continue

        token_infos: List[JSONDict] = []
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


def build_credentials(existing: JSONDict, token_info: JSONDict) -> JSONDict:
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

    plan_type = str(token_info.get("plan_type") or token_info.get("codex_parent_plan_type") or "").strip().lower()
    organization_id = str(token_info.get("organization_id") or token_info.get("codex_parent_organization_id") or "").strip()
    if plan_type:
        credentials["plan_type"] = plan_type
        credentials["codex_parent_plan_type"] = plan_type
    if organization_id:
        credentials["organization_id"] = organization_id
        credentials["codex_parent_organization_id"] = organization_id

    credentials["source"] = "codex-auto-register"
    credentials["model_mapping"] = build_model_mapping()
    if token_info.get("auth_file"):
        credentials["codex_auth_file"] = token_info.get("auth_file")
    return credentials


def build_extra(existing: JSONDict, token_info: JSONDict) -> JSONDict:
    extra = dict(existing)
    extra["codex_auto_register"] = True
    extra["codex_auto_register_model_mapping"] = build_model_mapping()

    plan_type = str(token_info.get("plan_type") or token_info.get("codex_parent_plan_type") or "").strip().lower()
    organization_id = str(token_info.get("organization_id") or token_info.get("codex_parent_organization_id") or "").strip()
    if plan_type:
        extra["plan_type"] = plan_type
        extra["codex_parent_plan_type"] = plan_type
    if organization_id:
        extra["organization_id"] = organization_id
        extra["codex_parent_organization_id"] = organization_id

    if token_info.get("auth_file"):
        extra["codex_auth_file"] = token_info.get("auth_file")
    return extra


def upsert_codex_register_account(cur, token_info: JSONDict) -> None:
    email = str(token_info.get("email") or "").strip()
    if not email:
        append_log("warn", "codex_register_account_missing_email")
        return

    refresh_token = str(token_info.get("refresh_token") or "").strip()
    access_token = str(token_info.get("session_access_token") or token_info.get("access_token") or "").strip()
    account_id = str(token_info.get("account_id") or "").strip() or None
    plan_type = str(token_info.get("plan_type") or token_info.get("codex_parent_plan_type") or "").strip().lower() or None
    organization_id = (
        str(token_info.get("organization_id") or token_info.get("codex_parent_organization_id") or "").strip() or None
    )
    workspace_id_value = str(token_info.get("workspace_id") or token_info.get("codex_parent_workspace_id") or "").strip() or None
    workspace_reachable = token_info.get("workspace_reachable")
    members_page_accessible = token_info.get("members_page_accessible")
    codex_register_role = str(token_info.get("codex_register_role") or "").strip().lower() or None

    cur.execute(
        "INSERT INTO codex_register_accounts "
        "(email, refresh_token, access_token, account_id, plan_type, organization_id, workspace_id, workspace_reachable, members_page_accessible, codex_register_role, source, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'codex-register', NOW(), NOW()) "
        "ON CONFLICT (email, source) DO UPDATE "
        "SET refresh_token = EXCLUDED.refresh_token, access_token = EXCLUDED.access_token, "
        "account_id = EXCLUDED.account_id, plan_type = COALESCE(EXCLUDED.plan_type, codex_register_accounts.plan_type), "
        "organization_id = COALESCE(EXCLUDED.organization_id, codex_register_accounts.organization_id), "
        "workspace_id = COALESCE(EXCLUDED.workspace_id, codex_register_accounts.workspace_id), "
        "workspace_reachable = COALESCE(EXCLUDED.workspace_reachable, codex_register_accounts.workspace_reachable), "
        "members_page_accessible = COALESCE(EXCLUDED.members_page_accessible, codex_register_accounts.members_page_accessible), "
        "codex_register_role = COALESCE(EXCLUDED.codex_register_role, codex_register_accounts.codex_register_role), "
        "updated_at = NOW()",
        (
            email,
            refresh_token,
            access_token,
            account_id,
            plan_type,
            organization_id,
            workspace_id_value,
            workspace_reachable,
            members_page_accessible,
            codex_register_role,
        ),
    )


def upsert_account(cur, token_info: JSONDict, *, account_role: str = "child") -> str:
    email = token_info.get("email") or ""
    account_id = token_info.get("account_id") or ""
    if not email and not account_id:
        print("[codex-register] token 中缺少 email/account_id，跳过", flush=True)
        append_log("warn", "skip_missing_email_and_account_id")
        return "skipped"

    role = "parent" if str(account_role or "").strip().lower() == "parent" else "child"
    notes = "codex-register 母号" if role == "parent" else "codex-register 子号"

    existing = get_existing_account(cur, email, account_id)
    group_ids = parse_group_ids()
    if existing is not None:
        existing_id, _existing_name, existing_credentials, existing_extra = existing
        credentials = build_credentials(ensure_dict(existing_credentials), token_info)
        extra = build_extra(ensure_dict(existing_extra), token_info)
        extra["codex_register_role"] = role
        current_credentials = ensure_dict(existing_credentials)
        current_extra = ensure_dict(existing_extra)
        if not should_update_account(current_credentials, credentials, current_extra, extra):
            bind_groups(cur, existing_id, group_ids)
            print(f"[codex-register] 账号无需更新，跳过: {email or account_id}", flush=True)
            append_log("info", f"skip_unchanged:{email or account_id}")
            return "skipped"

        extra["codex_auto_register_updated_at"] = datetime.utcnow().isoformat() + "Z"
        cur.execute(
            "UPDATE accounts SET notes = %s, credentials = %s, extra = %s, status = 'active', schedulable = true, updated_at = NOW() WHERE id = %s",
            (notes, pg_json(credentials), pg_json(extra), existing_id),
        )
        bind_groups(cur, existing_id, group_ids)
        print(f"[codex-register] 已更新账号: {email or account_id}", flush=True)
        append_log("info", f"updated:{email or account_id}")
        return "updated"

    identifier = email or account_id
    name = identifier
    credentials = build_credentials({}, token_info)
    extra = build_extra({}, token_info)
    extra["codex_register_role"] = role
    extra["codex_auto_register_updated_at"] = datetime.utcnow().isoformat() + "Z"

    cur.execute(
        "INSERT INTO accounts (name, notes, platform, type, credentials, extra, concurrency, priority, rate_multiplier, status, schedulable, auto_pause_on_expired) "
        "VALUES (%s, %s, 'openai', 'oauth', %s, %s, 3, 50, 1.0, 'active', true, true) RETURNING id",
        (name, notes, pg_json(credentials), pg_json(extra)),
    )
    created_id = cur.fetchone()[0]
    bind_groups(cur, created_id, group_ids)
    print(f"[codex-register] 已插入新账号: {identifier}", flush=True)
    append_log("info", f"created:{identifier}")
    return "created"


def normalize_reason_code(reason: str) -> str:
    return str(reason or "unknown").strip().replace(" ", "_")


def build_waiting_phase(reason: str) -> str:
    return f"{WAITING_MANUAL_PREFIX}{normalize_reason_code(reason)}"


def is_waiting_phase(phase: str) -> bool:
    return str(phase or "").startswith(WAITING_MANUAL_PREFIX)


def set_waiting_manual_locked(reason: str) -> None:
    global job_phase, waiting_reason, last_transition
    reason_code = normalize_reason_code(reason)
    previous_phase = job_phase
    next_phase = build_waiting_phase(reason_code)
    job_phase = next_phase
    waiting_reason = reason_code
    last_transition = {
        "time": datetime.utcnow().isoformat() + "Z",
        "from": previous_phase,
        "to": next_phase,
        "reason": reason_code,
    }
    _append_log_locked("warn", f"phase_transition:{previous_phase}->{next_phase}:reason={reason_code}")


def _set_phase_locked(phase: str) -> None:
    global job_phase, last_transition
    if phase in CANONICAL_JOB_PHASES:
        previous_phase = job_phase
        job_phase = phase
        last_transition = {
            "time": datetime.utcnow().isoformat() + "Z",
            "from": previous_phase,
            "to": phase,
            "reason": "",
        }
        _append_log_locked("info", f"phase_transition:{previous_phase}->{phase}")


def _refresh_workflow_thread_locked() -> None:
    global active_workflow_thread
    if active_workflow_thread is not None and not active_workflow_thread.is_alive():
        active_workflow_thread = None


def _build_workflow_id() -> str:
    return f"wf-{int(time.time() * 1000)}-{secrets.token_hex(4)}"


def register_child_once(
    tokens_dir: Path,
    *,
    email: str,
    password: str,
    preferred_workspace_id: str,
) -> Tuple[bool, JSONDict]:
    batches = run_codex_once(
        tokens_dir,
        preferred_workspace_id=preferred_workspace_id,
        fixed_email=email,
        fixed_password=password,
    )
    if not batches:
        return False, {}
    _source_file, token_infos = batches[0]
    return True, ensure_dict(token_infos[0] if token_infos else {})


def run_one_cycle(
    tokens_dir: Path,
    *,
    write_to_accounts: bool = True,
    register_role: str = "child",
    preferred_workspace_id: str = "",
) -> Tuple[bool, str]:
    global last_run, last_success, last_error, total_created, total_updated, total_skipped
    global last_token_email, last_created_email, last_created_account_id, last_updated_email, last_updated_account_id
    global last_processed_records

    with status_lock:
        last_run = datetime.utcnow()
    append_log(
        "info",
        f"run_one_cycle_started:write_to_accounts={write_to_accounts}:register_role={register_role}:preferred_workspace_id={preferred_workspace_id}:tokens_dir={tokens_dir}",
    )

    try:
        conn = create_db_connection()
        cur = conn.cursor()
        print("[codex-register] 数据库连接成功", flush=True)
    except Exception as exc:  # noqa: BLE001
        trace = traceback.format_exc()
        with status_lock:
            last_error = trace
        append_log("error", f"db_connect_failed:{exc}")
        print(f"[codex-register] 数据库连接失败: {trace}", flush=True)
        return False, "db_connect_failed"

    stage_failed = False
    stage_reason = ""

    try:
        batches = run_codex_once(tokens_dir, preferred_workspace_id=preferred_workspace_id)
        append_log("info", f"run_codex_once_batches:{len(batches)}")
        with status_lock:
            last_processed_records = sum(len(items) for _, items in batches)
        append_log("info", f"run_one_cycle_processed_records:{last_processed_records}")

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
                        append_log(
                            "info",
                            f"token_process_started:file={source_file.name}:identifier={identifier}:register_role={register_role}:write_to_accounts={write_to_accounts}",
                        )
                        action = "skipped"
                        cycle_role = str(register_role or "").strip().lower()
                        if cycle_role not in {"parent", "child"}:
                            cycle_role = "child"
                        token_role = str(token_info.get("codex_register_role") or "").strip().lower()
                        if cycle_role == "child":
                            effective_role = "child"
                        else:
                            effective_role = token_role if token_role in {"parent", "child"} else cycle_role
                        token_info["codex_register_role"] = effective_role
                        if write_to_accounts:
                            action = upsert_account(cur, token_info, account_role=effective_role)
                        upsert_codex_register_account(cur, token_info)
                        append_log(
                            "info",
                            f"token_process_completed:file={source_file.name}:identifier={identifier}:action={action}:effective_role={effective_role}",
                        )
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
                        if not stage_reason:
                            stage_reason = f"token_process_failed:{source_file.name}"
                        stage_failed = True
                        append_log("error", f"token_process_failed:{source_file.name}:{exc}")
                        print(f"[codex-register] 处理 token 失败（保留重试）: {source_file} {exc}", flush=True)
                        break

                if file_success:
                    try:
                        archived = archive_processed_file(source_file, processed_dir)
                        append_log("info", f"archived:{archived.name}")
                    except Exception as exc:  # noqa: BLE001
                        if not stage_reason:
                            stage_reason = f"archive_failed:{source_file.name}"
                        stage_failed = True
                        append_log("error", f"archive_failed:{source_file.name}:{exc}")
                        print(f"[codex-register] 归档 token 文件失败（保留重试）: {source_file} {exc}", flush=True)

            if stage_failed:
                append_log("warn", f"cycle_waiting_manual:{stage_reason}")
                with status_lock:
                    last_error = stage_reason
                return False, stage_reason or "process_error"

            with status_lock:
                last_success = datetime.utcnow()
                last_error = ""
            append_log("info", f"cycle_completed:{last_processed_records}")
            return True, ""

        append_log("info", "cycle_completed:0")
        with status_lock:
            last_success = datetime.utcnow()
            last_error = ""
        return True, ""
    except Exception as exc:  # noqa: BLE001
        trace = traceback.format_exc()
        reason = str(exc or "").strip()
        if reason.startswith("script_exit_nonzero:") or reason == "script_timeout":
            with status_lock:
                last_error = reason
            append_log("error", reason)
            print(f"[codex-register] 处理流程异常: {reason}", flush=True)
            return False, reason
        with status_lock:
            last_error = trace
        append_log("error", "process_error")
        print(f"[codex-register] 处理流程异常: {trace}", flush=True)
        return False, "process_error"
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _begin_workflow_locked(*, allow_resume: bool) -> Optional[threading.Thread]:
    global workflow_id, waiting_reason, enabled, active_workflow_thread, last_resume_gate_reason

    _refresh_workflow_thread_locked()
    if active_workflow_thread is not None and active_workflow_thread.is_alive():
        _append_log_locked("warn", f"workflow_begin_rejected:already_running:job_phase={job_phase}")
        return None

    if job_phase == PHASE_ABANDONED:
        _append_log_locked("warn", "workflow_begin_rejected:abandoned")
        return None

    if allow_resume:
        if not is_waiting_phase(job_phase):
            _append_log_locked("warn", f"workflow_begin_rejected:not_waiting:job_phase={job_phase}")
            return None

        if job_phase == PHASE_WAITING_PARENT_UPGRADE or waiting_reason == "parent_upgrade":
            mode = "resume"
            next_phase = PHASE_RUNNING_PRE_RESUME_CHECK
        else:
            mode = "start"
            next_phase = PHASE_RUNNING_CREATE_PARENT
    else:
        mode = "start"
        if job_phase not in (PHASE_IDLE, PHASE_COMPLETED):
            _append_log_locked("warn", f"workflow_begin_rejected:invalid_phase_for_start:job_phase={job_phase}")
            return None
        next_phase = PHASE_RUNNING_CREATE_PARENT

    workflow_id = _build_workflow_id()
    _set_phase_locked(next_phase)
    waiting_reason = ""
    last_resume_gate_reason = ""
    active_workflow_cancel_event.clear()
    enabled = True
    workflow_thread = threading.Thread(target=_run_workflow_once, args=(workflow_id, mode), daemon=True)
    active_workflow_thread = workflow_thread
    _append_log_locked("info", f"workflow_begin_accepted:workflow_id={workflow_id}:mode={mode}:next_phase={next_phase}")
    return workflow_thread
def start_workflow_once(*, allow_resume: bool = False) -> bool:
    append_log("info", f"start_workflow_once_requested:allow_resume={allow_resume}")
    workflow_thread = None
    with status_lock:
        workflow_thread = _begin_workflow_locked(allow_resume=allow_resume)

    if workflow_thread is None:
        append_log(
            "warn",
            f"start_workflow_once_rejected:allow_resume={allow_resume}:job_phase={job_phase}:waiting_reason={waiting_reason}",
        )
        return False

    try:
        workflow_thread.start()
        append_log("info", f"workflow_thread_started:allow_resume={allow_resume}:workflow_id={workflow_id}")
        return True
    except Exception as exc:  # noqa: BLE001
        with status_lock:
            global enabled, active_workflow_thread
            enabled = False
            set_waiting_manual_locked(f"thread_start_failed:{type(exc).__name__}")
            active_workflow_thread = None
        append_log("error", f"thread_start_failed:{exc}")
        return False



def _finalize_workflow_once(workflow_token: str, *, success: bool, reason: str = "") -> None:
    global waiting_reason, enabled, active_workflow_thread

    with status_lock:
        if workflow_id != workflow_token:
            _refresh_workflow_thread_locked()
            return

        if job_phase == PHASE_ABANDONED:
            enabled = False
            active_workflow_thread = None
            active_workflow_cancel_event.clear()
            return

        if success:
            _set_phase_locked(PHASE_COMPLETED)
            waiting_reason = ""
        else:
            set_waiting_manual_locked(reason)

        enabled = False
        active_workflow_thread = None
        active_workflow_cancel_event.clear()


def _transition_workflow_phase(workflow_token: str, phase: str) -> bool:
    with status_lock:
        if workflow_id != workflow_token:
            _refresh_workflow_thread_locked()
            return False
        if job_phase == PHASE_ABANDONED:
            return False
        if active_workflow_cancel_event.is_set():
            return False
        _set_phase_locked(phase)
        return True


def _mark_parent_upgrade_waiting(workflow_token: str) -> None:
    global enabled, active_workflow_thread
    with status_lock:
        if workflow_id != workflow_token:
            _refresh_workflow_thread_locked()
            return
        if job_phase == PHASE_ABANDONED:
            enabled = False
            active_workflow_thread = None
            return
        set_waiting_manual_locked("parent_upgrade")
        enabled = False
        active_workflow_thread = None


def invite_recent_children(
    parent_record: JSONDict,
    *,
    expected_count: int,
    target_email: str = "",
) -> Tuple[bool, str]:
    parent_account_id = str(parent_record.get("account_id") or "").strip()
    if not parent_account_id:
        return False, "parent_account_id_missing"

    parent_access_token = str(parent_record.get("session_access_token") or parent_record.get("access_token") or "").strip()
    if not parent_access_token:
        return False, "parent_access_token_missing"

    workspace_id_value = str(parent_record.get("workspace_id") or "").strip()
    organization_id = str(parent_record.get("organization_id") or "").strip()
    plan_type = str(parent_record.get("plan_type") or "").strip().lower()
    if not workspace_id_value or not organization_id or not plan_type:
        return False, "parent_metadata_incomplete"

    append_log(
        "info",
        f"invite_recent_children_started:expected_count={expected_count}:workspace_id={workspace_id_value}:organization_id={organization_id}:plan_type={plan_type}",
    )

    normalized_target_email = str(target_email or "").strip().lower()
    conn = None
    cur = None
    invited = 0
    try:
        if normalized_target_email:
            rows = [(normalized_target_email,)]
        else:
            conn = create_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT email FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'child' "
                "AND workspace_id = %s AND organization_id = %s AND plan_type = %s "
                "AND COALESCE(email, '') <> '' "
                "AND created_at >= NOW() - INTERVAL '30 minutes' "
                "ORDER BY created_at DESC LIMIT %s",
                (workspace_id_value, organization_id, plan_type, max(1, int(expected_count or 1))),
            )
            rows = cur.fetchall() or []
        append_log("info", f"invite_recent_children_targets:{len(rows)}")
        if not rows:
            return False, "child_invite_targets_missing"

        base_url = str(get_env("CODEX_CHATGPT_BASE_URL", "https://chatgpt.com") or "https://chatgpt.com").rstrip("/")
        invite_url = f"{base_url}/backend-api/accounts/{parent_account_id}/invites"

        def _invite_once(child_email: str) -> bool:
            payload = json.dumps({"email": child_email}).encode("utf-8")
            req = urllib.request.Request(
                invite_url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {parent_access_token}",
                    "chatgpt-account-id": parent_account_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                    status = int(getattr(resp, "status", 0) or 0)
                append_log("info", f"invite_child:{child_email}:{status}")
                return status in {200, 201, 202, 204, 409}
            except urllib.error.HTTPError as exc:
                append_log("warn", f"invite_child_http_error:{child_email}:{exc.code}")
                if int(getattr(exc, "code", 0) or 0) == 409:
                    try:
                        body = exc.read().decode("utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        body = ""
                    if "already" in body.lower():
                        return True
                return False
            except Exception as exc:  # noqa: BLE001
                append_log("warn", f"invite_child_request_failed:{child_email}:{exc}")
                return False

        for row in rows:
            child_email = str((row or [""])[0] or "").strip()
            if not child_email:
                continue
            ok = _invite_once(child_email)
            if not ok:
                ok = _invite_once(child_email)
            if ok:
                invited += 1

        append_log("info", f"invite_recent_children_completed:invited={invited}:expected={max(1, int(expected_count or 1))}")
        if invited < max(1, int(expected_count or 1)):
            return False, "child_invite_incomplete"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        append_log("error", f"invite_recent_children_failed:{exc}")
        return False, "child_invite_failed"
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:  # noqa: BLE001
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def verify_child_business_plan_via_session_exchange(
    token_info: JSONDict,
    *,
    workspace_id: str,
    parent_account_id: str = "",
) -> Tuple[bool, str]:
    child_access_token = str(token_info.get("session_access_token") or token_info.get("access_token") or "").strip()
    if not child_access_token:
        return False, "child_access_token_missing"

    target_workspace_id = str(workspace_id or "").strip()
    if not target_workspace_id:
        return False, "workspace_id_missing"

    base_url = str(get_env("CODEX_CHATGPT_BASE_URL", "https://chatgpt.com") or "https://chatgpt.com").rstrip("/")
    workspace_candidates: List[str] = [target_workspace_id]
    fallback_workspace_id = str(parent_account_id or "").strip()
    if fallback_workspace_id and fallback_workspace_id not in workspace_candidates:
        workspace_candidates.append(fallback_workspace_id)

    raw = ""
    last_error: Exception | None = None
    for candidate_workspace_id in workspace_candidates:
        query = urllib.parse.urlencode(
            {
                "exchange_workspace_token": "true",
                "workspace_id": candidate_workspace_id,
                "reason": "setCurrentAccount",
            }
        )
        url = f"{base_url}/api/auth/session?{query}"
        req = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {child_access_token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            append_log("warn", f"child_session_exchange_failed:{candidate_workspace_id}:{exc}")
            continue

    if not raw:
        if last_error is not None:
            append_log("warn", f"child_session_exchange_failed_final:{last_error}")
        return False, "child_session_exchange_failed"

    try:
        payload = ensure_dict(raw)
    except Exception:  # noqa: BLE001
        payload = {}

    user = ensure_dict(payload.get("user"))
    account = ensure_dict(user.get("account"))
    current_account = ensure_dict(account.get("current_account") or account.get("currentAccount"))
    workspace = ensure_dict(current_account.get("workspace"))
    subscription = ensure_dict(workspace.get("subscription"))

    current_workspace_id = str(
        workspace.get("id")
        or workspace.get("workspace_id")
        or workspace.get("workspaceId")
        or current_account.get("workspace_id")
        or ""
    ).strip()
    if current_workspace_id and current_workspace_id not in workspace_candidates:
        return False, "child_workspace_mismatch"

    plan_type = str(
        subscription.get("plan_type")
        or subscription.get("planType")
        or workspace.get("plan_type")
        or workspace.get("planType")
        or current_account.get("plan_type")
        or ""
    ).strip().lower()

    if not plan_type:
        account_root = ensure_dict(payload.get("account"))
        plan_type = str(
            account_root.get("plan_type")
            or account_root.get("planType")
            or account_root.get("workspace_plan_type")
            or ""
        ).strip().lower()

    if not plan_type:
        accounts_map = ensure_dict(payload.get("accounts"))
        selected_account = ensure_dict(accounts_map.get(target_workspace_id))
        selected_account_payload = ensure_dict(selected_account.get("account"))
        if not selected_account_payload and fallback_workspace_id:
            fallback_account = ensure_dict(accounts_map.get(fallback_workspace_id))
            selected_account_payload = ensure_dict(fallback_account.get("account"))
        plan_type = str(
            selected_account_payload.get("plan_type")
            or selected_account_payload.get("workspace_plan_type")
            or ""
        ).strip().lower()

    if plan_type not in VALID_PARENT_PLAN_TYPES:
        return False, "child_plan_not_business"

    return True, ""


def promote_parent_record_to_pool(parent_record: JSONDict) -> Tuple[bool, str]:
    account_id = str(parent_record.get("account_id") or "").strip()
    if not account_id:
        return False, "parent_account_id_missing"

    email = str(parent_record.get("email") or "").strip()
    refresh_token = str(parent_record.get("refresh_token") or "").strip()
    access_token = str(parent_record.get("session_access_token") or parent_record.get("access_token") or "").strip()
    workspace_id_value = str(parent_record.get("workspace_id") or "").strip()
    organization_id = str(parent_record.get("organization_id") or "").strip()
    plan_type = str(parent_record.get("plan_type") or "").strip().lower()

    token_info: JSONDict = {
        "email": email,
        "refresh_token": refresh_token,
        "access_token": access_token,
        "account_id": account_id,
        "workspace_id": workspace_id_value,
        "organization_id": organization_id,
        "plan_type": plan_type,
        "codex_register_role": "parent",
    }

    try:
        conn = create_db_connection()
        cur = conn.cursor()
    except Exception as exc:  # noqa: BLE001
        append_log("error", f"promote_parent_record_to_pool_db_connect_failed:{exc}")
        return False, "parent_pool_promote_failed"

    try:
        action = upsert_account(cur, token_info, account_role="parent")
        append_log("info", f"promote_parent_record_to_pool_result:action={action}:account_id={account_id}:email={email}")
        if action in {"created", "updated", "skipped"}:
            return True, ""
        return False, "parent_pool_promote_failed"
    except Exception as exc:  # noqa: BLE001
        append_log("error", f"promote_parent_record_to_pool_failed:{exc}")
        return False, "parent_pool_promote_failed"
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def verify_parent_business_context_after_resume(parent_record: JSONDict) -> Tuple[bool, str]:
    parent_workspace_id = str(parent_record.get("workspace_id") or "").strip()
    parent_account_id = str(parent_record.get("account_id") or "").strip()
    parent_access_token = str(parent_record.get("session_access_token") or parent_record.get("access_token") or "").strip()
    if not parent_workspace_id:
        return False, "workspace_id_missing"
    if not parent_account_id:
        return False, "parent_account_id_missing"
    if not parent_access_token:
        return False, "parent_access_token_missing"

    verified, reason = verify_child_business_plan_via_session_exchange(
        {
            "account_id": parent_account_id,
            "access_token": parent_access_token,
            "session_access_token": parent_access_token,
        },
        workspace_id=parent_workspace_id,
        parent_account_id=parent_account_id,
    )
    if verified:
        return True, ""

    if reason == "child_workspace_mismatch":
        return False, "parent_switch_workspace_mismatch"
    if reason == "child_plan_not_business":
        return False, "parent_switch_plan_not_business"
    if reason == "child_session_exchange_failed":
        return False, "parent_switch_failed"
    return False, "parent_switch_failed"


def validate_recent_child_records(
    parent_record: JSONDict,
    *,
    expected_count: int,
    target_email: str = "",
) -> Tuple[bool, str]:
    workspace_id_value = str(parent_record.get("workspace_id") or "").strip()
    organization_id = str(parent_record.get("organization_id") or "").strip()
    plan_type = str(parent_record.get("plan_type") or "").strip().lower()
    if not workspace_id_value or not organization_id or not plan_type:
        return False, "parent_metadata_incomplete"

    append_log(
        "info",
        f"validate_recent_child_records_started:expected_count={expected_count}:workspace_id={workspace_id_value}:organization_id={organization_id}:plan_type={plan_type}",
    )

    conn = create_db_connection()
    cur = conn.cursor()
    try:
        normalized_target_email = str(target_email or "").strip().lower()
        if normalized_target_email:
            cur.execute(
                "SELECT email, refresh_token, access_token, account_id "
                "FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'child' "
                "AND workspace_id = %s AND organization_id = %s AND plan_type = %s "
                "AND LOWER(email) = %s "
                "AND COALESCE(refresh_token, '') <> '' AND COALESCE(access_token, '') <> '' AND COALESCE(account_id, '') <> '' "
                "AND created_at >= NOW() - INTERVAL '30 minutes' "
                "ORDER BY created_at DESC LIMIT 1",
                (workspace_id_value, organization_id, plan_type, normalized_target_email),
            )
        else:
            cur.execute(
                "SELECT email, refresh_token, access_token, account_id "
                "FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'child' "
                "AND workspace_id = %s AND organization_id = %s AND plan_type = %s "
                "AND COALESCE(refresh_token, '') <> '' AND COALESCE(access_token, '') <> '' AND COALESCE(account_id, '') <> '' "
                "AND created_at >= NOW() - INTERVAL '30 minutes' "
                "ORDER BY created_at DESC LIMIT %s",
                (workspace_id_value, organization_id, plan_type, max(1, int(expected_count or 1))),
            )
        rows = cur.fetchall() or []
        append_log("info", f"validate_recent_child_records_candidates:{len(rows)}")
        if len(rows) < max(1, int(expected_count or 1)):
            return False, "child_invite_acceptance_incomplete"

        for row in rows:
            token_info: JSONDict = {
                "email": str(row[0] or "").strip(),
                "refresh_token": str(row[1] or "").strip(),
                "access_token": str(row[2] or "").strip(),
                "account_id": str(row[3] or "").strip(),
            }
            verified, verify_reason = verify_child_business_plan_via_session_exchange(
                token_info,
                workspace_id=workspace_id_value,
                parent_account_id=str(parent_record.get("account_id") or "").strip(),
            )
            append_log(
                "info",
                f"validate_child_session_exchange_result:email={token_info.get('email')}:account_id={token_info.get('account_id')}:verified={verified}:reason={verify_reason}",
            )
            if not verified:
                return False, verify_reason

        append_log("info", "validate_recent_child_records_completed")
        return True, ""
    except Exception as exc:  # noqa: BLE001
        append_log("error", f"validate_recent_child_records_failed:{exc}")
        return False, "child_validation_failed"
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def promote_recent_child_records_to_pool(
    parent_record: JSONDict,
    *,
    expected_count: int,
    target_email: str = "",
) -> Tuple[bool, str]:
    workspace_id_value = str(parent_record.get("workspace_id") or "").strip()
    organization_id = str(parent_record.get("organization_id") or "").strip()
    plan_type = str(parent_record.get("plan_type") or "").strip().lower()
    if not workspace_id_value or not organization_id or not plan_type:
        return False, "parent_metadata_incomplete"

    append_log(
        "info",
        f"promote_recent_child_records_started:expected_count={expected_count}:workspace_id={workspace_id_value}:organization_id={organization_id}:plan_type={plan_type}",
    )

    conn = create_db_connection()
    cur = conn.cursor()
    promoted = 0
    try:
        normalized_target_email = str(target_email or "").strip().lower()
        if normalized_target_email:
            cur.execute(
                "SELECT email, refresh_token, access_token, account_id, plan_type, organization_id, workspace_id "
                "FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'child' "
                "AND workspace_id = %s AND organization_id = %s AND plan_type = %s "
                "AND LOWER(email) = %s "
                "AND COALESCE(refresh_token, '') <> '' AND COALESCE(access_token, '') <> '' AND COALESCE(account_id, '') <> '' "
                "AND created_at >= NOW() - INTERVAL '30 minutes' "
                "ORDER BY created_at DESC LIMIT 1",
                (workspace_id_value, organization_id, plan_type, normalized_target_email),
            )
        else:
            cur.execute(
                "SELECT email, refresh_token, access_token, account_id, plan_type, organization_id, workspace_id "
                "FROM codex_register_accounts "
                "WHERE source = 'codex-register' AND codex_register_role = 'child' "
                "AND workspace_id = %s AND organization_id = %s AND plan_type = %s "
                "AND COALESCE(refresh_token, '') <> '' AND COALESCE(access_token, '') <> '' AND COALESCE(account_id, '') <> '' "
                "AND created_at >= NOW() - INTERVAL '30 minutes' "
                "ORDER BY created_at DESC LIMIT %s",
                (workspace_id_value, organization_id, plan_type, max(1, int(expected_count or 1))),
            )
        rows = cur.fetchall() or []
        append_log("info", f"promote_recent_child_records_candidates:{len(rows)}")
        if not rows:
            return False, "no_child_records_to_promote"

        for row in rows:
            token_info: JSONDict = {
                "email": str(row[0] or "").strip(),
                "refresh_token": str(row[1] or "").strip(),
                "access_token": str(row[2] or "").strip(),
                "account_id": str(row[3] or "").strip(),
                "plan_type": str(row[4] or "").strip().lower(),
                "organization_id": str(row[5] or "").strip(),
                "workspace_id": str(row[6] or "").strip(),
                "codex_register_role": "child",
            }
            action = upsert_account(cur, token_info, account_role="child")
            append_log(
                "info",
                f"promote_child_result:email={token_info.get('email')}:account_id={token_info.get('account_id')}:action={action}",
            )
            if action in {"created", "updated", "skipped"}:
                promoted += 1

        append_log("info", f"promote_recent_child_records_completed:promoted={promoted}:expected={max(1, int(expected_count or 1))}")
        if promoted < max(1, int(expected_count or 1)):
            return False, "child_promotion_incomplete"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        append_log("error", f"promote_recent_child_records_to_pool_failed:{exc}")
        return False, "child_promotion_failed"
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def run_single_child_round(
    workflow_token: str,
    parent_record: JSONDict,
    *,
    tokens_dir: Path,
    round_index: int,
    total_rounds: int,
) -> Tuple[bool, str]:
    append_log("info", f"workflow_round_started:workflow_id={workflow_token}:round={round_index}/{total_rounds}")
    if _workflow_cancelled(workflow_token):
        append_log("warn", f"workflow_round_cancelled:workflow_id={workflow_token}:round={round_index}/{total_rounds}")
        return False, "cancelled"

    preferred_workspace_id = str(parent_record.get("workspace_id") or "").strip()

    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_INVITE_CHILDREN):
        reason = f"transition_rejected:{PHASE_RUNNING_INVITE_CHILDREN}:round={round_index}"
        append_log("warn", f"workflow_round_stopped:workflow_id={workflow_token}:reason={reason}")
        return False, reason

    success, reason = run_one_cycle(
        tokens_dir,
        write_to_accounts=False,
        register_role="child",
        preferred_workspace_id=preferred_workspace_id,
    )
    append_log(
        "info",
        f"workflow_round_child_cycle_result:workflow_id={workflow_token}:round={round_index}/{total_rounds}:success={success}:reason={reason}",
    )
    if not success:
        return False, reason

    with status_lock:
        processed_records = int(last_processed_records or 0)
    if processed_records < 1:
        return False, "child_round_no_records"

    target_email = str(last_token_email or "").strip().lower()
    if not target_email:
        return False, "child_round_target_email_missing"

    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_ACCEPT_AND_SWITCH):
        reason = f"transition_rejected:{PHASE_RUNNING_ACCEPT_AND_SWITCH}:round={round_index}"
        append_log("warn", f"workflow_round_stopped:workflow_id={workflow_token}:reason={reason}")
        return False, reason

    invited, invite_reason = invite_recent_children(parent_record, expected_count=1, target_email=target_email)
    append_log(
        "info",
        f"workflow_round_invite_result:workflow_id={workflow_token}:round={round_index}/{total_rounds}:invited={invited}:reason={invite_reason}",
    )
    if not invited:
        return False, invite_reason

    accepted, accept_reason = validate_recent_child_records(parent_record, expected_count=1, target_email=target_email)
    append_log(
        "info",
        f"workflow_round_acceptance_result:workflow_id={workflow_token}:round={round_index}/{total_rounds}:accepted={accepted}:reason={accept_reason}",
    )
    if not accepted:
        return False, accept_reason

    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_VERIFY_AND_BIND):
        reason = f"transition_rejected:{PHASE_RUNNING_VERIFY_AND_BIND}:round={round_index}"
        append_log("warn", f"workflow_round_stopped:workflow_id={workflow_token}:reason={reason}")
        return False, reason

    promoted, promote_reason = promote_recent_child_records_to_pool(parent_record, expected_count=1, target_email=target_email)
    append_log(
        "info",
        f"workflow_round_promote_result:workflow_id={workflow_token}:round={round_index}/{total_rounds}:promoted={promoted}:reason={promote_reason}",
    )
    if not promoted:
        return False, promote_reason

    append_log("info", f"workflow_round_completed:workflow_id={workflow_token}:round={round_index}/{total_rounds}")
    return True, ""



def _run_workflow_once(workflow_token: str, mode: str) -> None:
    append_log("info", f"workflow_run_started:workflow_id={workflow_token}:mode={mode}")
    if _workflow_cancelled(workflow_token):
        append_log("warn", f"workflow_run_cancelled_before_start:workflow_id={workflow_token}")
        _finalize_workflow_once(workflow_token, success=False, reason="cancelled")
        return

    with status_lock:
        tokens_dir = tokens_dir_global

    if tokens_dir is None:
        append_log("error", f"workflow_run_failed:workflow_id={workflow_token}:reason=tokens_dir_unavailable")
        _finalize_workflow_once(workflow_token, success=False, reason="tokens_dir_unavailable")
        return

    if mode == "start":
        if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_CREATE_PARENT):
            append_log("warn", f"workflow_run_stopped:workflow_id={workflow_token}:reason=transition_rejected:{PHASE_RUNNING_CREATE_PARENT}")
            return
        success, reason = run_one_cycle(
            tokens_dir,
            write_to_accounts=False,
            register_role="parent",
            preferred_workspace_id="",
        )
        append_log("info", f"workflow_parent_cycle_result:workflow_id={workflow_token}:success={success}:reason={reason}")
        if success:
            _mark_parent_upgrade_waiting(workflow_token)
        else:
            _finalize_workflow_once(workflow_token, success=False, reason=reason)
        return

    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_PRE_RESUME_CHECK):
        append_log("warn", f"workflow_run_stopped:workflow_id={workflow_token}:reason=transition_rejected:{PHASE_RUNNING_PRE_RESUME_CHECK}")
        return

    parent_record = get_latest_parent_record()
    append_log("info", f"workflow_resume_parent_record:{json.dumps(_safe_parent_record_summary(parent_record), ensure_ascii=False)}")
    gate_reason = evaluate_resume_gate(parent_record)
    _log_resume_gate_decision(gate_reason, parent_record)
    if gate_reason:
        _finalize_workflow_once(workflow_token, success=False, reason=gate_reason)
        return

    append_log("info", f"workflow_parent_switch_verification_started:workflow_id={workflow_token}")
    parent_switched, parent_switch_reason = verify_parent_business_context_after_resume(parent_record)
    append_log(
        "info",
        f"workflow_parent_switch_verification_result:workflow_id={workflow_token}:ok={parent_switched}:reason={parent_switch_reason}",
    )
    if not parent_switched:
        _finalize_workflow_once(workflow_token, success=False, reason=parent_switch_reason)
        return

    parent_promoted, parent_promote_reason = promote_parent_record_to_pool(parent_record)
    append_log(
        "info",
        f"workflow_parent_pool_promotion_result:workflow_id={workflow_token}:ok={parent_promoted}:reason={parent_promote_reason}",
    )
    if not parent_promoted:
        _finalize_workflow_once(workflow_token, success=False, reason=parent_promote_reason)
        return

    total_rounds = 5
    for round_index in range(1, total_rounds + 1):
        round_ok, round_reason = run_single_child_round(
            workflow_token,
            parent_record,
            tokens_dir=tokens_dir,
            round_index=round_index,
            total_rounds=total_rounds,
        )
        if not round_ok:
            _finalize_workflow_once(
                workflow_token,
                success=False,
                reason=f"child_round_failed:round={round_index}:{round_reason}",
            )
            return

    append_log("info", f"workflow_run_completed:workflow_id={workflow_token}")
    _finalize_workflow_once(workflow_token, success=True, reason="")


def get_latest_parent_record() -> JSONDict:
    conn = create_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT email, account_id, refresh_token, access_token, plan_type, organization_id, workspace_id, "
            "workspace_reachable, members_page_accessible, codex_register_role "
            "FROM codex_register_accounts WHERE source = 'codex-register' "
            "AND (codex_register_role = 'parent' OR codex_register_role IS NULL) "
            "ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return {}

        email = str(row[0] or "").strip()
        account_id = str(row[1] or "").strip()
        register_plan_type = str(row[4] or "").strip().lower() or None
        register_org_id = str(row[5] or "").strip() or None
        register_workspace_id = str(row[6] or "").strip() or None
        register_refresh_token = str(row[2] or "").strip()
        register_access_token = str(row[3] or "").strip()
        parent_record: JSONDict = {
            "email": email,
            "account_id": account_id,
            "refresh_token": register_refresh_token,
            "access_token": register_access_token,
            "session_access_token": register_access_token,
            "has_refresh_token": bool(register_refresh_token),
            "has_access_token": bool(register_access_token),
            "plan_type": register_plan_type,
            "organization_id": register_org_id,
            "workspace_id": register_workspace_id,
            "codex_register_role": str(row[9] or "").strip().lower() or None,
        }
        if row[7] is not None:
            parent_record["workspace_reachable"] = bool(row[7])
        if row[8] is not None:
            parent_record["members_page_accessible"] = bool(row[8])

        if not email and not account_id:
            return parent_record

        cur.execute(
            "SELECT credentials, extra FROM accounts WHERE platform = 'openai' AND type = 'oauth' "
            "AND ((%s <> '' AND credentials ->> 'email' = %s) "
            "OR (%s <> '' AND credentials ->> 'account_id' = %s)) "
            "ORDER BY updated_at DESC NULLS LAST, id DESC LIMIT 1",
            (email, email, account_id, account_id),
        )
        account_row = cur.fetchone()
        if account_row is None:
            return parent_record

        credentials = ensure_dict(account_row[0])
        extra = ensure_dict(account_row[1])

        plan_type = (
            extra.get("plan_type")
            or extra.get("codex_parent_plan_type")
            or credentials.get("plan_type")
            or credentials.get("codex_parent_plan_type")
            or parent_record.get("plan_type")
            or ""
        )
        organization_id = (
            extra.get("organization_id")
            or extra.get("org_id")
            or extra.get("codex_parent_organization_id")
            or credentials.get("organization_id")
            or credentials.get("org_id")
            or credentials.get("codex_parent_organization_id")
            or parent_record.get("organization_id")
            or ""
        )

        parent_record["plan_type"] = str(plan_type or "").strip().lower() or None
        parent_record["organization_id"] = str(organization_id or "").strip() or None

        if "workspace_reachable" in extra:
            parent_record["workspace_reachable"] = bool(extra.get("workspace_reachable"))
        if "members_page_accessible" in extra:
            parent_record["members_page_accessible"] = bool(extra.get("members_page_accessible"))

        append_log("info", f"latest_parent_record_loaded:{json.dumps(_safe_parent_record_summary(parent_record), ensure_ascii=False)}")
        return parent_record
    except Exception as exc:  # noqa: BLE001
        append_log("error", f"parent_record_read_failed:{exc}")
        return {}
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def evaluate_resume_gate(parent_record: JSONDict) -> str:
    with status_lock:
        _refresh_workflow_thread_locked()
        if active_workflow_thread is not None and active_workflow_thread.is_alive():
            return "already_running"
        if tokens_dir_global is None:
            return "tokens_dir_unavailable"
        if job_phase == PHASE_ABANDONED:
            return "abandoned"

    plan_type = str(parent_record.get("plan_type") or "").strip().lower()
    if not plan_type:
        return "plan_type_missing"
    if plan_type not in VALID_PARENT_PLAN_TYPES:
        return "plan_type_invalid"

    organization_id = str(parent_record.get("organization_id") or "").strip()
    if not organization_id:
        return "organization_id_missing"

    workspace_id_value = str(parent_record.get("workspace_id") or "").strip()
    if not workspace_id_value:
        return "workspace_id_missing"

    if parent_record.get("workspace_reachable") is False:
        return "workspace_unreachable"

    if parent_record.get("members_page_accessible") is False:
        return "members_page_inaccessible"

    parent_account_id = str(parent_record.get("account_id") or "").strip()
    if not parent_account_id:
        return "parent_account_id_missing"

    parent_access_token = str(parent_record.get("session_access_token") or parent_record.get("access_token") or "").strip()
    if not parent_access_token:
        return "parent_access_token_missing"

    return ""


def get_status_payload() -> JSONDict:
    proxy = get_env("CODEX_PROXY", "")
    with status_lock:
        _refresh_workflow_thread_locked()
        can_resume = is_waiting_phase(job_phase)
        can_start = job_phase in (PHASE_IDLE, PHASE_COMPLETED)
        can_abandon = job_phase != PHASE_ABANDONED
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
            "job_phase": job_phase,
            "workflow_id": workflow_id or None,
            "waiting_reason": waiting_reason or None,
            "can_start": can_start,
            "can_resume": can_resume,
            "can_abandon": can_abandon,
            "last_transition": dict(last_transition) if isinstance(last_transition, dict) else None,
            "last_resume_gate_reason": last_resume_gate_reason or None,
            "recent_logs_tail": list(recent_logs[-STATUS_LOG_TAIL_LIMIT:]),
        }


def _parse_logs_query(path: str) -> Tuple[str, int]:
    parsed = urllib.parse.urlparse(path)
    query = urllib.parse.parse_qs(parsed.query or "")
    level = str((query.get("level") or [""])[0] or "").strip().lower()
    if level and level not in VALID_LOG_LEVELS:
        level = ""

    default_limit = max(1, int(LOGS_ENDPOINT_DEFAULT_LIMIT))
    max_limit = max(default_limit, int(LOGS_ENDPOINT_MAX_LIMIT))
    limit_raw = str((query.get("limit") or [default_limit])[0] or default_limit).strip()
    try:
        limit = int(limit_raw)
    except Exception:  # noqa: BLE001
        limit = default_limit
    limit = max(1, min(max_limit, limit))
    return level, limit


class CodexRequestHandler(BaseHTTPRequestHandler):
    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed_path = urllib.parse.urlparse(self.path).path

        if parsed_path != "/health" and not _is_request_authorized(self):
            self.send_response(401)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return

        if parsed_path == "/status":
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path == "/logs":
            level, limit = _parse_logs_query(self.path)
            with status_lock:
                logs = list(recent_logs)
            if level:
                logs = [item for item in logs if str(item.get("level") or "").strip().lower() == level]
            logs = logs[-limit:]
            body = json.dumps({"logs": logs, "level": level or None, "limit": limit}).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path == "/accounts":
            try:
                accounts = list_codex_register_accounts()
            except Exception as exc:  # noqa: BLE001
                append_log("error", f"list_codex_register_accounts_failed:{exc}")
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self._cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            redacted_accounts = [_redact_account_record(item) for item in accounts]
            body = json.dumps({"accounts": redacted_accounts}).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed_path == "/health":
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
        global enabled, waiting_reason

        if not _is_request_authorized(self):
            self.send_response(401)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return

        append_log("info", f"http_post_received:path={self.path}")

        if self.path == "/enable":
            started = start_workflow_once(allow_resume=False)
            append_log("info", f"http_post_enable_result:started={started}")
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
                active_workflow_cancel_event.set()
                if active_workflow_thread is not None and active_workflow_thread.is_alive():
                    set_waiting_manual_locked("cancelled")
                else:
                    _set_phase_locked(PHASE_IDLE)
                    waiting_reason = ""
            append_log("info", "http_post_disable_result:cancel_requested")
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/run-once":
            started = start_workflow_once(allow_resume=False)
            append_log("info", f"http_post_run_once_result:started={started}")
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/retry":
            current_status = get_status_payload()
            retry_phase = str(current_status.get("job_phase") or "")
            retry_reason = str(current_status.get("waiting_reason") or "")
            append_log("info", f"retry_request_received:phase={retry_phase}:waiting_reason={retry_reason}")

            if not is_waiting_phase(retry_phase):
                append_log("warn", f"retry_request_ignored:not_waiting:phase={retry_phase}:waiting_reason={retry_reason}")
            else:
                started = start_workflow_once(allow_resume=True)
                append_log("info", f"retry_request_started:started={started}:phase={retry_phase}:waiting_reason={retry_reason}")

            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/resume":
            current_status = get_status_payload()
            resume_phase = str(current_status.get("job_phase") or "")
            resume_reason = str(current_status.get("waiting_reason") or "")
            append_log("info", f"resume_request_received:phase={resume_phase}:waiting_reason={resume_reason}")

            if not is_waiting_phase(resume_phase):
                append_log("warn", f"resume_request_ignored:not_waiting:phase={resume_phase}:waiting_reason={resume_reason}")
                body = json.dumps(current_status).encode("utf-8")
            else:
                needs_parent_gate = resume_phase == PHASE_WAITING_PARENT_UPGRADE or resume_reason in PARENT_RESUME_GATE_REASONS
                append_log(
                    "info",
                    f"resume_request_gate_check:needs_parent_gate={needs_parent_gate}:phase={resume_phase}:waiting_reason={resume_reason}",
                )

                if needs_parent_gate:
                    latest_parent = get_latest_parent_record()
                    append_log(
                        "info",
                        f"resume_parent_record:{json.dumps(_safe_parent_record_summary(latest_parent), ensure_ascii=False)}",
                    )
                    gate_reason = evaluate_resume_gate(latest_parent)
                    _log_resume_gate_decision(gate_reason, latest_parent)
                    if gate_reason:
                        with status_lock:
                            if job_phase != PHASE_ABANDONED:
                                enabled = False
                                set_waiting_manual_locked(gate_reason)
                        append_log("warn", f"resume_gate_blocked:{gate_reason}")
                    else:
                        started = start_workflow_once(allow_resume=True)
                        append_log("info", f"resume_started_after_gate:started={started}")
                else:
                    started = start_workflow_once(allow_resume=True)
                    append_log("info", f"resume_started_without_gate:started={started}")
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
    parser = argparse.ArgumentParser(description="Codex register service")
    parser.add_argument("--register-only", action="store_true", help="run the embedded OpenAI register flow only")
    parser.add_argument("--proxy", default=None, help="代理地址，如 http://127.0.0.1:7890")
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--sleep-min", type=int, default=5, help="循环模式最短等待秒数")
    parser.add_argument("--sleep-max", type=int, default=30, help="循环模式最长等待秒数")
    parser.add_argument("--tokens-dir", default="", help="token 输出目录")
    args = parser.parse_args()

    if args.register_only:
        tokens_dir = Path(args.tokens_dir).expanduser() if args.tokens_dir else Path(__file__).resolve().parent / "tokens"
        run_auto_register_cli(
            proxy=args.proxy,
            once=args.once,
            sleep_min=args.sleep_min,
            sleep_max=args.sleep_max,
            tokens_dir=tokens_dir,
        )
        return

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

    tokens_dir = Path(__file__).resolve().parent / "tokens"
    with status_lock:
        tokens_dir_global = tokens_dir

    port = int(get_env("CODEX_HTTP_PORT", "5000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), CodexRequestHandler)
    print(f"[codex-register] HTTP 服务启动于 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

