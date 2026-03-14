import argparse
import base64
import hashlib
import importlib
import json
import logging
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
status_lock = threading.RLock()
JSONDict = Dict[str, Any]

logger = logging.getLogger("codex-register")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

_child_round_state: Dict[str, JSONDict] = {}
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
    normalized_level = str(level or "").strip().lower()
    if normalized_level not in VALID_LOG_LEVELS:
        normalized_level = "info"

    text = str(message)
    with status_lock:
        _append_log_locked(normalized_level, text)

    if normalized_level == "error":
        logger.error(text)
    elif normalized_level == "warn":
        logger.warning(text)
    else:
        logger.info(text)


def info_log(*args: Any, **kwargs: Any) -> None:
    sep = str(kwargs.get("sep", " "))
    end = str(kwargs.get("end", ""))
    message = sep.join(str(arg) for arg in args)
    if end:
        message = f"{message}{end}"
    logger.info(message)


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


def _get_child_round_state(workflow_token: str, round_index: int) -> JSONDict:
    with status_lock:
        return _child_round_state.get(f"{workflow_token}:{round_index}", {})


def _set_child_round_state(workflow_token: str, round_index: int, payload: JSONDict) -> None:
    with status_lock:
        _child_round_state[f"{workflow_token}:{round_index}"] = dict(payload)


def _clear_child_round_state(workflow_token: Optional[str] = None) -> None:
    with status_lock:
        if not workflow_token:
            _child_round_state.clear()
            return
        prefix = f"{workflow_token}:"
        for key in list(_child_round_state.keys()):
            if key.startswith(prefix):
                del _child_round_state[key]


def _get_or_create_child_identity(workflow_token: str, round_index: int) -> JSONDict:
    state = ensure_dict(_get_child_round_state(workflow_token, round_index))
    if state.get("email") and state.get("password"):
        return state

    email, _dev_token, password = get_email_and_token()
    email = str(email or "").strip().lower()
    password = str(password or "").strip()
    if not email:
        email = str(last_token_email or "").strip().lower()
    if not email:
        email = f"child-{secrets.token_hex(4)}@example.com"
    if not password:
        password = secrets.token_urlsafe(18)

    identity = {
        "email": email,
        "password": password,
    }
    _set_child_round_state(workflow_token, round_index, identity)
    return identity


def _worker_headers(worker_token: str) -> Dict[str, Any]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {worker_token}",
    }


def get_email_and_token(proxies: Any = None) -> tuple[str, str, str]:
    del proxies
    fixed_email = get_env("CODEX_FIXED_EMAIL", "").strip()
    fixed_password = get_env("CODEX_FIXED_PASSWORD", "").strip()
    if fixed_email:
        password = fixed_password or secrets.token_urlsafe(18)
        return fixed_email, "worker", password
    try:
        domain = get_env("CODEX_MAIL_DOMAIN", required=True).strip().lower()
        local = f"oc{secrets.token_hex(5)}"
        email = f"{local}@{domain}"
        password = fixed_password or secrets.token_urlsafe(18)
        return email, "worker", password
    except Exception as exc:
        info_log(f"[Error] 生成自定义域名邮箱失败: {exc}")
        return "", "", ""


def get_oai_code(token: str, email: str, proxies: Any = None) -> str:
    del token
    requests = get_requests_module()

    worker_base = get_env("CODEX_MAIL_WORKER_BASE_URL", required=True).rstrip("/")
    worker_token = get_env("CODEX_MAIL_WORKER_TOKEN", required=True).strip()
    poll_seconds = max(1, int(get_env("CODEX_MAIL_POLL_SECONDS", "3")))
    max_attempts = max(1, int(get_env("CODEX_MAIL_POLL_MAX_ATTEMPTS", "40")))

    query_url = f"{worker_base}/v1/code?email={urllib.parse.quote(email)}"

    info_log(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)
    for attempt in range(max_attempts):
        info_log(".", end="", flush=True)
        try:
            resp = requests.get(
                url=query_url,
                headers=_worker_headers(worker_token),
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            info_log(f" [poll#{attempt + 1}] Worker 轮询状态: {resp.status_code}")

            if resp.status_code == 200:
                data = ensure_dict(resp.json())
                code = str(data.get("code") or "").strip()
                if code:
                    info_log(" 抓到啦! 验证码:", code)
                    return code
                time.sleep(poll_seconds)
                continue

            if resp.status_code == 404:
                time.sleep(poll_seconds)
                continue

            if resp.status_code == 401:
                info_log(" [Error] Worker 鉴权失败，请检查 CODEX_MAIL_WORKER_TOKEN")
                return ""
        except Exception as exc:
            info_log(f" [poll#{attempt + 1}] Worker 轮询异常: {exc}")

        time.sleep(poll_seconds)

    info_log(" 超时，未收到验证码")
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


def run(proxy: Optional[str]) -> Optional[str]:
    requests = get_requests_module()
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    session = requests.Session(proxies=proxies, impersonate="chrome")
    register_http_timeout = max(1, _to_int(get_env("CODEX_REGISTER_HTTP_TIMEOUT", "15")))
    try:
        trace = session.get("https://cloudflare.com/cdn-cgi/trace", timeout=10).text
        loc_match = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_match.group(1) if loc_match else None
        info_log(f"[*] 当前 IP 所在地: {loc}")
        if loc == "CN":
            raise RuntimeError("检查代理哦w - 所在地不支持")
    except Exception as exc:
        info_log(f"[Error] 网络连接检查失败: {exc}")
        return None

    email, dev_token, password = get_email_and_token(proxies)
    if not email or not dev_token:
        return None
    info_log(f"[*] 成功获取自定义邮箱与授权: {email}")

    oauth = generate_oauth_url()
    try:
        session.get(oauth.auth_url, timeout=15)
        did = session.cookies.get("oai-did")
        info_log(f"[*] Device ID: {did}")

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
            info_log(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
            return None

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'


        register_resp = session.post(
            "https://auth.openai.com/api/accounts/user/register",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
                "origin": "https://auth.openai.com",
            },
            data=json.dumps({"username": email, "password": password}, ensure_ascii=False, separators=(",", ":")),
            timeout=register_http_timeout,
        )
        info_log(f"[*] 用户注册状态: {register_resp.status_code}")
        if register_resp.status_code != 200:
            info_log(f"[Error] 用户注册失败，状态码: {register_resp.status_code}")
            info_log(register_resp.text)
            return None

        otp_send_resp = session.get(
            "https://auth.openai.com/api/accounts/email-otp/send",
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "referer": "https://auth.openai.com/create-account/password",
            },
            timeout=register_http_timeout,
        )
        info_log(f"[*] 验证码发送状态: {otp_send_resp.status_code}")
        if otp_send_resp.status_code != 200:
            info_log(f"[Error] 验证码发送失败，状态码: {otp_send_resp.status_code}")
            info_log(getattr(otp_send_resp, "text", ""))
            return None

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
            timeout=register_http_timeout,
        )
        info_log(f"[*] 验证码校验状态: {code_resp.status_code}")
        if code_resp.status_code != 200:
            info_log(f"[Error] 验证码校验失败，状态码: {code_resp.status_code}")
            info_log(code_resp.text)
            return None

        create_account_body = f'{{"name":"{email}","birthdate":"2000-02-20"}}'
        create_account_resp = session.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_account_body,
            timeout=register_http_timeout,
        )
        create_account_status = create_account_resp.status_code
        info_log(f"[*] 账户创建状态: {create_account_status}")
        if create_account_status != 200:
            info_log(create_account_resp.text)
            return None


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

