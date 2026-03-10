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
active_workflow_thread = None
status_lock = threading.Lock()
JSONDict = Dict[str, Any]
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

DEFAULT_MODEL_MAPPING: Dict[str, str] = {
    "claude-haiku*": "gpt-5.2-codex",
    "claude-sonnet*": "gpt-5.2-codex",
    "claude-opus*": "gpt-5.2-codex",
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


MAILTM_BASE = "https://api.mail.tm"
AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _mailtm_headers(*, token: str = "", use_json: bool = False) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if use_json:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mailtm_domains(proxies: Any = None) -> List[str]:
    requests = get_requests_module()
    resp = requests.get(
        f"{MAILTM_BASE}/domains",
        headers=_mailtm_headers(),
        proxies=proxies,
        impersonate="chrome",
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"获取 Mail.tm 域名失败，状态码: {resp.status_code}")

    data = resp.json()
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("hydra:member") or data.get("items") or []
    else:
        items = []

    domains: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        is_active = item.get("isActive", True)
        is_private = item.get("isPrivate", False)
        if domain and is_active and not is_private:
            domains.append(domain)

    return domains


def get_email_and_token(proxies: Any = None) -> tuple[str, str, str]:
    requests = get_requests_module()
    try:
        domains = _mailtm_domains(proxies)
        if not domains:
            print("[Error] Mail.tm 没有可用域名")
            return "", "", ""
        domain = random.choice(domains)

        for _ in range(5):
            local = f"oc{secrets.token_hex(5)}"
            email = f"{local}@{domain}"
            password = secrets.token_urlsafe(18)

            create_resp = requests.post(
                f"{MAILTM_BASE}/accounts",
                headers=_mailtm_headers(use_json=True),
                json={"address": email, "password": password},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if create_resp.status_code not in (200, 201):
                continue

            token_resp = requests.post(
                f"{MAILTM_BASE}/token",
                headers=_mailtm_headers(use_json=True),
                json={"address": email, "password": password},
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if token_resp.status_code == 200:
                token = str(token_resp.json().get("token") or "").strip()
                if token:
                    return email, token, password

        print("[Error] Mail.tm 邮箱创建成功但获取 Token 失败")
        return "", "", ""
    except Exception as exc:
        print(f"[Error] 请求 Mail.tm API 出错: {exc}")
        return "", "", ""


def get_oai_code(token: str, email: str, proxies: Any = None) -> str:
    requests = get_requests_module()
    url_list = f"{MAILTM_BASE}/messages"
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set[str] = set()

    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)
    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = requests.get(
                url_list,
                headers=_mailtm_headers(token=token),
                proxies=proxies,
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("hydra:member") or data.get("messages") or []
            else:
                messages = []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                read_resp = requests.get(
                    f"{MAILTM_BASE}/messages/{msg_id}",
                    headers=_mailtm_headers(token=token),
                    proxies=proxies,
                    impersonate="chrome",
                    timeout=15,
                )
                if read_resp.status_code != 200:
                    continue

                mail_data = read_resp.json()
                sender = str(((mail_data.get("from") or {}).get("address") or "")).lower()
                subject = str(mail_data.get("subject") or "")
                intro = str(mail_data.get("intro") or "")
                text = str(mail_data.get("text") or "")
                html = mail_data.get("html") or ""
                if isinstance(html, list):
                    html = "\n".join(str(x) for x in html)
                content = "\n".join([subject, intro, text, str(html)])

                if "openai" not in sender and "openai" not in content.lower():
                    continue

                match = re.search(regex, content)
                if match:
                    print(" 抓到啦! 验证码:", match.group(1))
                    return match.group(1)
        except Exception:
            pass

        time.sleep(3)

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
    print(f"[*] 成功获取 Mail.tm 邮箱与授权: {email}")

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
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        if not workspace_id:
            print("[Error] 无法解析 workspace_id")
            return None

        select_body = f'{{"workspace_id":"{workspace_id}"}}'
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
                    token_payload["password"] = password
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
            "SELECT id, email, password, refresh_token, access_token, account_id, source, created_at, updated_at "
            "FROM codex_register_accounts WHERE source = 'codex-register' ORDER BY created_at DESC"
        )
        rows = cur.fetchall()
        records: List[JSONDict] = []
        for row in rows:
            records.append(
                {
                    "id": row[0],
                    "email": row[1],
                    "password": row[2],
                    "refresh_token": row[3],
                    "access_token": row[4],
                    "account_id": row[5],
                    "source": row[6],
                    "created_at": row[7].isoformat() + "Z" if row[7] is not None else None,
                    "updated_at": row[8].isoformat() + "Z" if row[8] is not None else None,
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


def run_codex_once(tokens_dir: Path) -> List[Tuple[Path, List[JSONDict]]]:
    service_file = Path(__file__).resolve()
    tokens_dir.mkdir(parents=True, exist_ok=True)

    proxy = get_env("CODEX_PROXY", "")
    cmd = [sys.executable, str(service_file), "--register-only", "--once", "--tokens-dir", str(tokens_dir)]
    if proxy:
        cmd.extend(["--proxy", proxy])

    print("[codex-register] 启动注册脚本:", " ".join(cmd), flush=True)

    result = subprocess.run(
        cmd,
        cwd=str(service_file.parent),
        capture_output=True,
        text=True,
    )

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
    credentials["source"] = "codex-auto-register"
    credentials["model_mapping"] = build_model_mapping()
    if token_info.get("auth_file"):
        credentials["codex_auth_file"] = token_info.get("auth_file")
    return credentials


def build_extra(existing: JSONDict, token_info: JSONDict) -> JSONDict:
    extra = dict(existing)
    extra["codex_auto_register"] = True
    extra["codex_auto_register_model_mapping"] = build_model_mapping()
    if token_info.get("auth_file"):
        extra["codex_auth_file"] = token_info.get("auth_file")
    return extra


def upsert_codex_register_account(cur, token_info: JSONDict) -> None:
    email = str(token_info.get("email") or "").strip()
    if not email:
        append_log("warn", "codex_register_account_missing_email")
        return

    password = str(token_info.get("password") or "").strip()
    refresh_token = str(token_info.get("refresh_token") or "").strip()
    access_token = str(token_info.get("session_access_token") or token_info.get("access_token") or "").strip()
    account_id = str(token_info.get("account_id") or "").strip() or None

    cur.execute(
        "INSERT INTO codex_register_accounts (email, password, refresh_token, access_token, account_id, source, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, 'codex-register', NOW(), NOW()) "
        "ON CONFLICT (email, source) DO UPDATE "
        "SET password = EXCLUDED.password, refresh_token = EXCLUDED.refresh_token, access_token = EXCLUDED.access_token, "
        "account_id = EXCLUDED.account_id, updated_at = NOW()",
        (email, password, refresh_token, access_token, account_id),
    )


def upsert_account(cur, token_info: JSONDict) -> str:
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


def normalize_reason_code(reason: str) -> str:
    return str(reason or "unknown").strip().replace(" ", "_")


def build_waiting_phase(reason: str) -> str:
    return f"{WAITING_MANUAL_PREFIX}{normalize_reason_code(reason)}"


def is_waiting_phase(phase: str) -> bool:
    return str(phase or "").startswith(WAITING_MANUAL_PREFIX)


def set_waiting_manual_locked(reason: str) -> None:
    global job_phase, waiting_reason
    reason_code = normalize_reason_code(reason)
    job_phase = build_waiting_phase(reason_code)
    waiting_reason = reason_code


def _set_phase_locked(phase: str) -> None:
    global job_phase
    if phase in CANONICAL_JOB_PHASES:
        job_phase = phase


def _refresh_workflow_thread_locked() -> None:
    global active_workflow_thread
    if active_workflow_thread is not None and not active_workflow_thread.is_alive():
        active_workflow_thread = None


def _build_workflow_id() -> str:
    return f"wf-{int(time.time() * 1000)}-{secrets.token_hex(4)}"


def run_one_cycle(tokens_dir: Path) -> Tuple[bool, str]:
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
        trace = traceback.format_exc()
        with status_lock:
            last_error = trace
        append_log("error", f"db_connect_failed:{exc}")
        print(f"[codex-register] 数据库连接失败: {trace}", flush=True)
        return False, "db_connect_failed"

    stage_failed = False
    stage_reason = ""

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
                        upsert_codex_register_account(cur, token_info)
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
        if reason.startswith("script_exit_nonzero:"):
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
    global workflow_id, waiting_reason, enabled, active_workflow_thread

    _refresh_workflow_thread_locked()
    if active_workflow_thread is not None and active_workflow_thread.is_alive():
        return None

    if job_phase == PHASE_ABANDONED:
        return None

    if allow_resume:
        if not is_waiting_phase(job_phase):
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
            return None
        next_phase = PHASE_RUNNING_CREATE_PARENT

    workflow_id = _build_workflow_id()
    _set_phase_locked(next_phase)
    waiting_reason = ""
    enabled = True
    workflow_thread = threading.Thread(target=_run_workflow_once, args=(workflow_id, mode), daemon=True)
    active_workflow_thread = workflow_thread
    return workflow_thread


def start_workflow_once(*, allow_resume: bool = False) -> bool:
    workflow_thread = None
    with status_lock:
        workflow_thread = _begin_workflow_locked(allow_resume=allow_resume)

    if workflow_thread is None:
        return False

    try:
        workflow_thread.start()
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
            return

        if success:
            _set_phase_locked(PHASE_COMPLETED)
            waiting_reason = ""
        else:
            set_waiting_manual_locked(reason)

        enabled = False
        active_workflow_thread = None


def _transition_workflow_phase(workflow_token: str, phase: str) -> bool:
    with status_lock:
        if workflow_id != workflow_token:
            _refresh_workflow_thread_locked()
            return False
        if job_phase == PHASE_ABANDONED:
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


def _run_workflow_once(workflow_token: str, mode: str) -> None:
    with status_lock:
        tokens_dir = tokens_dir_global

    if tokens_dir is None:
        _finalize_workflow_once(workflow_token, success=False, reason="tokens_dir_unavailable")
        return

    if mode == "start":
        if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_CREATE_PARENT):
            return
        success, reason = run_one_cycle(tokens_dir)
        if success:
            _mark_parent_upgrade_waiting(workflow_token)
        else:
            _finalize_workflow_once(workflow_token, success=False, reason=reason)
        return

    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_PRE_RESUME_CHECK):
        return
    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_INVITE_CHILDREN):
        return
    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_ACCEPT_AND_SWITCH):
        return
    if not _transition_workflow_phase(workflow_token, PHASE_RUNNING_VERIFY_AND_BIND):
        return

    success, reason = run_one_cycle(tokens_dir)
    _finalize_workflow_once(workflow_token, success=success, reason=reason)


def get_latest_parent_record() -> JSONDict:
    conn = create_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT email, account_id, refresh_token, access_token "
            "FROM codex_register_accounts WHERE source = 'codex-register' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return {}

        email = str(row[0] or "").strip()
        account_id = str(row[1] or "").strip()
        parent_record: JSONDict = {
            "email": email,
            "account_id": account_id,
            "has_refresh_token": bool(str(row[2] or "").strip()),
            "has_access_token": bool(str(row[3] or "").strip()),
        }

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
            or ""
        )
        organization_id = (
            extra.get("organization_id")
            or extra.get("org_id")
            or extra.get("codex_parent_organization_id")
            or credentials.get("organization_id")
            or credentials.get("org_id")
            or credentials.get("codex_parent_organization_id")
            or ""
        )

        parent_record["plan_type"] = str(plan_type or "").strip().lower() or None
        parent_record["organization_id"] = str(organization_id or "").strip() or None

        if "workspace_reachable" in extra:
            parent_record["workspace_reachable"] = bool(extra.get("workspace_reachable"))
        if "members_page_accessible" in extra:
            parent_record["members_page_accessible"] = bool(extra.get("members_page_accessible"))

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

    if parent_record.get("workspace_reachable") is False:
        return "workspace_unreachable"

    if parent_record.get("members_page_accessible") is False:
        return "members_page_inaccessible"

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
        if self.path == "/accounts":
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
            body = json.dumps({"accounts": accounts}).encode("utf-8")
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
        global enabled, waiting_reason

        if self.path == "/enable":
            start_workflow_once(allow_resume=False)
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
                _set_phase_locked(PHASE_ABANDONED)
                waiting_reason = "disabled"
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/run-once":
            start_workflow_once(allow_resume=False)
            body = json.dumps(get_status_payload()).encode("utf-8")
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/resume":
            current_status = get_status_payload()
            if not is_waiting_phase(current_status.get("job_phase")):
                body = json.dumps(current_status).encode("utf-8")
            else:
                resume_phase = str(current_status.get("job_phase") or "")
                resume_reason = str(current_status.get("waiting_reason") or "")
                needs_parent_gate = resume_phase == PHASE_WAITING_PARENT_UPGRADE or resume_reason == "parent_upgrade"

                if needs_parent_gate:
                    latest_parent = get_latest_parent_record()
                    gate_reason = evaluate_resume_gate(latest_parent)
                    if gate_reason:
                        with status_lock:
                            if job_phase != PHASE_ABANDONED:
                                enabled = False
                                set_waiting_manual_locked(gate_reason)
                    else:
                        start_workflow_once(allow_resume=True)
                else:
                    start_workflow_once(allow_resume=True)
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

