"""
ChatGPT API 服务
用于调用 ChatGPT 后端 API,实现 Team 成员管理功能
"""
import asyncio
import base64
import hashlib
import importlib
import json
import logging
import os
import random
import urllib.parse
from urllib.parse import parse_qs, urlparse, parse_qsl, urlencode
from typing import Optional, Dict, Any, List
from curl_cffi.requests import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession as DBAsyncSession
try:
    from .utils.jwt_parser import JWTParser
except ImportError:  # pragma: no cover - script mode fallback
    from utils.jwt_parser import JWTParser

logger = logging.getLogger(__name__)


class ChatGPTService:
    """ChatGPT API 服务类"""

    BASE_URL = "https://chatgpt.com/backend-api"

    # 重试配置
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]  # 指数退避: 1s, 2s, 4s

    def __init__(self):
        """初始化 ChatGPT API 服务"""
        self.jwt_parser = JWTParser()
        # 会话池：按标识符（如 Email 或 TeamID）隔离，防止身份泄漏并提高 CF 稳定性
        self._sessions: Dict[str, AsyncSession] = {}
        # 记录标识符对应代理，确保注册流程内后续请求复用同一代理会话
        self._identifier_proxies: Dict[str, str] = {}

    async def _create_session(
        self,
        db_session: DBAsyncSession,
        proxy: Optional[str] = None,
    ) -> AsyncSession:
        """
        创建 HTTP 会话
        """
        del db_session
        session_kwargs: Dict[str, Any] = {
            "impersonate": "chrome110",
            "timeout": 30,
            "verify": False,  # 某些代理环境下需要，或根据需求开启
        }
        normalized_proxy = str(proxy or "").strip()
        if normalized_proxy:
            session_kwargs["proxy"] = normalized_proxy

        # 使用 chrome110 指纹，这是 curl_cffi 中绕过 CF 最稳定的版本之一
        session = AsyncSession(**session_kwargs)
        return session

    async def _get_session(
        self,
        db_session: DBAsyncSession,
        identifier: str,
        proxy: Optional[str] = None,
    ) -> AsyncSession:
        """
        根据标识符获取或创建持久会话
        """
        normalized_identifier = str(identifier or "").strip() or "default"
        normalized_proxy = str(proxy or "").strip()
        if not normalized_proxy:
            normalized_proxy = str(self._identifier_proxies.get(normalized_identifier) or "").strip()

        if normalized_proxy:
            self._identifier_proxies[normalized_identifier] = normalized_proxy

        session_cache_key = normalized_identifier
        if normalized_proxy:
            session_cache_key = f"{normalized_identifier}::proxy::{normalized_proxy}"

        if session_cache_key not in self._sessions:
            logger.info(f"为标识符 {session_cache_key} 创建新会话")
            self._sessions[session_cache_key] = await self._create_session(
                db_session,
                normalized_proxy,
            )
        return self._sessions[session_cache_key]


    def _build_browser_base_headers(
        self,
        extra_headers: Optional[Dict[str, str]] = None,
        *,
        origin: str = "https://chatgpt.com",
        referer: str = "https://chatgpt.com/",
    ) -> Dict[str, str]:
        """构建浏览器基础请求头"""
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
            "Origin": origin,
            "Connection": "keep-alive",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _build_auth_headers(
        self,
        access_token: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """构建 auth.openai.com 请求头"""
        headers = self._build_browser_base_headers(
            origin="https://auth.openai.com",
            referer="https://auth.openai.com/",
        )
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/json"
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _build_sentinel_headers(
        self,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """构建 Sentinel 请求头"""
        headers = self._build_browser_base_headers(
            origin="https://sentinel.openai.com",
            referer="https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
        )
        headers["Content-Type"] = "text/plain;charset=UTF-8"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _resolve_register_email(self, register_input: Dict[str, Any]) -> str:
        """解析注册邮箱：优先 resolved_email，其次 fixed_email"""
        resolved_email = str(register_input.get("resolved_email") or "").strip()
        if resolved_email:
            return resolved_email
        return str(register_input.get("fixed_email") or "").strip()

    def _resolve_register_proxy_from_input(self, register_input: Dict[str, Any]) -> str:
        """解析注册代理：优先 resolved_proxy，再回退 proxy"""
        if not isinstance(register_input, dict):
            return ""

        for key in ("resolved_proxy", "proxy"):
            value = str(register_input.get(key) or "").strip()
            if value:
                return value
        return ""

    async def _resolve_settings_service_proxy(
        self,
        db_session: Optional[DBAsyncSession],
    ) -> str:
        """从 settings service best-effort 获取代理"""
        candidate_modules = (
            "settings_service",
            "app.services.settings_service",
            "services.settings_service",
        )

        for module_name in candidate_modules:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                continue

            for service_ref in (
                getattr(module, "settings_service", None),
                getattr(module, "SettingsService", None),
            ):
                if service_ref is None:
                    continue

                try:
                    service_obj = service_ref() if isinstance(service_ref, type) else service_ref
                except Exception:
                    continue

                for method_name in (
                    "get_register_proxy",
                    "resolve_register_proxy",
                    "get_proxy",
                    "resolve_proxy",
                ):
                    method = getattr(service_obj, method_name, None)
                    if not callable(method):
                        continue

                    try:
                        if db_session is None:
                            maybe_proxy = method()
                        else:
                            maybe_proxy = method(db_session)
                    except TypeError:
                        try:
                            maybe_proxy = method(db_session)
                        except Exception:
                            continue
                    except Exception:
                        continue

                    if asyncio.iscoroutine(maybe_proxy):
                        try:
                            maybe_proxy = await maybe_proxy
                        except Exception:
                            continue

                    normalized_proxy = str(maybe_proxy or "").strip()
                    if normalized_proxy:
                        return normalized_proxy

                for attr_name in ("proxy", "proxy_url"):
                    normalized_proxy = str(getattr(service_obj, attr_name, "") or "").strip()
                    if normalized_proxy:
                        return normalized_proxy

        return ""

    async def _resolve_register_proxy(
        self,
        register_input: Dict[str, Any],
        db_session: Optional[DBAsyncSession],
    ) -> str:
        """解析注册代理优先级: 输入代理 > settings service > 空"""
        input_proxy = self._resolve_register_proxy_from_input(register_input)
        if input_proxy:
            return input_proxy

        try:
            return await self._resolve_settings_service_proxy(db_session)
        except Exception:
            return ""

    def _resolve_register_proxy_from_ctx(self, ctx: Dict[str, Any]) -> str:
        """从上下文中解析注册代理"""
        register_input = dict((ctx or {}).get("register_input") or {})
        return self._resolve_register_proxy_from_input(register_input)

    def _build_deterministic_oauth_state(self, ctx: Dict[str, Any]) -> str:
        """构建确定性的 oauth_state，保证同一输入状态稳定"""
        source_ctx = ctx if isinstance(ctx, dict) else {}
        register_input = source_ctx.get("register_input") or {}
        if not isinstance(register_input, dict):
            register_input = {}

        seed_parts = [
            str(source_ctx.get("identifier") or "default").strip() or "default",
            self._resolve_register_email(register_input),
            str(register_input.get("mail_domain") or "").strip().lower(),
            str(register_input.get("token_endpoint") or "").strip(),
        ]
        seed = "|".join(seed_parts)
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return f"state-{digest[:24]}"

    def _ensure_oauth_bootstrap(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """注册流水线 oauth bootstrap：在缺失时补全并固化 oauth_state"""
        normalized_ctx = dict(ctx or {})
        register_input = dict(normalized_ctx.get("register_input") or {})

        oauth_state = str(
            normalized_ctx.get("oauth_state")
            or register_input.get("oauth_state")
            or register_input.get("state")
            or ""
        ).strip()

        if not oauth_state:
            oauth_state = self._build_deterministic_oauth_state(
                {
                    "identifier": normalized_ctx.get("identifier", "default"),
                    "register_input": register_input,
                }
            )

        normalized_ctx["oauth_state"] = oauth_state
        register_input["oauth_state"] = oauth_state
        normalized_ctx["register_input"] = register_input
        return normalized_ctx

    def _build_register_oauth_url(
        self,
        register_input: Dict[str, Any],
        oauth_state: str,
    ) -> str:
        """构建注册域 OAuth authorize URL，兼容 legacy 语义"""
        source = register_input if isinstance(register_input, dict) else {}
        base_url = str(
            source.get("authorize_endpoint")
            or source.get("authorization_endpoint")
            or "https://auth.openai.com/oauth/authorize"
        ).strip()
        if not base_url:
            return ""

        existing_params = dict(parse_qsl(urlparse(base_url).query, keep_blank_values=True))
        query: Dict[str, str] = dict(existing_params)

        query["response_type"] = str(source.get("response_type") or query.get("response_type") or "code").strip() or "code"

        def _maybe_set(field: str, fallback: str = ""):
            value = str(source.get(field) or "").strip()
            if value:
                query[field] = value
            elif fallback and fallback not in query:
                query[fallback] = query.get(fallback, "")

        for field in (
            "client_id",
            "redirect_uri",
            "scope",
            "audience",
            "prompt",
            "code_challenge",
            "code_challenge_method",
        ):
            _maybe_set(field)

        if str(oauth_state or "").strip():
            query["state"] = str(oauth_state).strip()

        parsed = urlparse(base_url)
        return parsed._replace(query=urlencode(query, doseq=True)).geturl()

    def _extract_token_claims_without_verification(self, token: str) -> Dict[str, Any]:
        """无签名校验解析 JWT claims，等价 legacy 非验证读取"""
        raw_token = str(token or "").strip()
        if not raw_token:
            return {}

        parts = raw_token.split(".")
        if len(parts) < 2:
            return {}

        payload = parts[1].strip()
        if not payload:
            return {}

        padding = "=" * ((4 - len(payload) % 4) % 4)
        try:
            decoded = base64.urlsafe_b64decode((payload + padding).encode("utf-8"))
            parsed = json.loads(decoded.decode("utf-8"))
        except Exception:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    def _extract_session_access_token(self, payload: Dict[str, Any]) -> str:
        """从 session 响应结构中提取 access token"""
        if not isinstance(payload, dict):
            return ""

        candidates: List[Any] = [payload]
        nested_session = payload.get("session")
        if isinstance(nested_session, dict):
            candidates.append(nested_session)

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for key in ("access_token", "accessToken", "token", "idp_access_token"):
                token_value = str(candidate.get(key) or "").strip()
                if token_value:
                    return token_value

        return ""

    def _verify_callback_state(
        self,
        pipeline_data: Dict[str, Any],
        register_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """校验 callback_url 中 state 与预期 oauth_state 一致性"""
        merged_source: Dict[str, Any] = {}
        if isinstance(register_input, dict):
            merged_source.update(register_input)
        if isinstance(pipeline_data, dict):
            merged_source.update(pipeline_data)

        callback_url = str(merged_source.get("callback_url") or "").strip()
        if not callback_url:
            return self._success_result({})

        parsed = self._parse_callback_url(callback_url)
        callback_state = str(parsed.get("state") or "").strip()
        expected_state = str(
            merged_source.get("oauth_state")
            or merged_source.get("state")
            or ""
        ).strip()

        if callback_state and expected_state and callback_state != expected_state:
            return self._error_result(
                400,
                f"oauth callback state mismatch: expected {expected_state}, got {callback_state}",
                "token_finalize_failed",
            )

        return self._success_result(
            {
                "oauth_state": expected_state or callback_state,
                "callback_state": callback_state,
            }
        )

    def _map_network_exception(self, exc: Exception) -> str:
        """网络异常映射"""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return "network_timeout"
        if isinstance(exc, (ConnectionError, OSError)):
            return "network_error"
        return "network_error"

    async def _dispatch_http_call(
        self,
        session: AsyncSession,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_data: Optional[Dict[str, Any]] = None,
        form_data: Optional[Dict[str, Any]] = None,
    ):
        """在给定会话上发送 HTTP 请求"""
        if method == "GET":
            return await session.get(url, headers=headers)
        if method == "POST":
            if form_data is not None:
                return await session.post(url, headers=headers, data=form_data)
            return await session.post(url, headers=headers, json=json_data)
        if method == "DELETE":
            if form_data is not None:
                return await session.delete(url, headers=headers, data=form_data)
            return await session.delete(url, headers=headers, json=json_data)
        raise ValueError(f"不支持的 HTTP 方法: {method}")

    async def _make_special_session_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_data: Optional[Dict[str, Any]],
        session: AsyncSession,
        identifier: str,
        form_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """特殊注册步骤：强制使用传入会话"""
        base_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://chatgpt.com/",
            "Origin": "https://chatgpt.com",
            "Connection": "keep-alive",
        }
        for key, value in base_headers.items():
            if key not in headers:
                headers[key] = value

        for attempt in range(self.MAX_RETRIES):
            try:
                if attempt > 0:
                    delay = self.RETRY_DELAYS[attempt - 1] + random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay)

                logger.info(f"[{identifier}] 特殊步骤请求: {method} {url} (尝试 {attempt + 1})")
                response = await self._dispatch_http_call(
                    session,
                    method,
                    url,
                    headers,
                    json_data,
                    form_data=form_data,
                )
                status_code = response.status_code

                if 200 <= status_code < 300:
                    try:
                        data = response.json()
                    except Exception:
                        data = {}
                    return {
                        "success": True,
                        "status_code": status_code,
                        "data": data,
                        "error": None,
                        "error_code": None,
                    }

                if 400 <= status_code < 500:
                    error_msg = response.text
                    error_code = None
                    try:
                        error_data = response.json()
                        detail = error_data.get("detail", error_msg)
                        error_msg = str(detail) if not isinstance(detail, str) else detail
                        if isinstance(error_data, dict):
                            error_info = error_data.get("error")
                            error_code = error_info.get("code") if isinstance(error_info, dict) else error_data.get("code")
                    except Exception:
                        pass
                    return {
                        "success": False,
                        "status_code": status_code,
                        "error": error_msg,
                        "error_code": error_code,
                    }

                if status_code >= 500:
                    if attempt < self.MAX_RETRIES - 1:
                        continue
                    return {
                        "success": False,
                        "status_code": status_code,
                        "error": f"服务器错误 {status_code}",
                        "error_code": "server_error",
                    }

            except Exception as e:
                logger.error(f"特殊步骤请求异常: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    continue
                return {
                    "success": False,
                    "status_code": 0,
                    "error": str(e),
                    "error_code": self._map_network_exception(e),
                }

        return {"success": False, "status_code": 0, "error": "未知错误", "error_code": "network_error"}

    def _prepare_identity(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """准备注册身份：补全邮箱与密码"""
        register_input = dict((ctx or {}).get("register_input") or {})
        fixed_email = str(register_input.get("fixed_email") or "").strip()

        if fixed_email:
            resolved_email = fixed_email
        else:
            mail_domain = str(register_input.get("mail_domain") or "").strip().lower()
            if not mail_domain:
                return self._error_result(
                    400,
                    "mail_domain is required when fixed_email is absent",
                    "input_invalid",
                )
            local_part = f"cg{random.randint(100000, 999999)}"
            resolved_email = f"{local_part}@{mail_domain}"
            register_input["fixed_email"] = resolved_email

        fixed_password = str(register_input.get("fixed_password") or "")
        if not fixed_password:
            register_input["fixed_password"] = f"Cg#{random.randint(100000, 999999)}Aa"

        register_input["resolved_email"] = resolved_email

        prepared_ctx = dict(ctx or {})
        prepared_ctx["register_input"] = register_input
        return self._success_result(prepared_ctx)

    def _parse_cloudflare_trace_location(self, trace_body: str) -> str:
        """解析 Cloudflare trace 返回中的 loc 字段"""
        raw_trace = str(trace_body or "")
        if not raw_trace:
            return ""

        for line in raw_trace.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().lower() == "loc":
                return str(value or "").strip().upper()
        return ""

    async def _check_network_and_region(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """注册前网络与区域检查：预检连通性并校验区域策略"""
        register_input = dict((ctx or {}).get("register_input") or {})

        blocked_regions = {
            str(region).strip().upper()
            for region in (register_input.get("blocked_regions") or [])
            if str(region).strip()
        }
        if not blocked_regions:
            blocked_regions = {"IR", "KP", "SY", "CU"}

        resolved_region = str(register_input.get("region") or "").strip().upper()

        resolved_proxy = self._resolve_register_proxy_from_input(register_input)

        if not resolved_region:
            try:
                active_session = await self._get_session(
                    ctx.get("db_session"),
                    ctx.get("identifier", "default"),
                    proxy=resolved_proxy,
                )
                trace_response = await active_session.get(
                    "https://www.cloudflare.com/cdn-cgi/trace",
                    headers=self._build_browser_base_headers(
                        {"Accept": "text/plain"},
                        origin="https://www.cloudflare.com",
                        referer="https://www.cloudflare.com/",
                    ),
                )
                trace_status = int(getattr(trace_response, "status_code", 0) or 0)
                if trace_status and trace_status >= 400:
                    return self._error_result(
                        trace_status,
                        f"network precheck failed: http {trace_status}",
                        "network_error",
                    )

                resolved_region = self._parse_cloudflare_trace_location(
                    str(getattr(trace_response, "text", "") or "")
                )
            except Exception as exc:
                mapped_code = self._map_network_exception(exc)
                return self._error_result(
                    0,
                    f"network precheck failed: {exc}",
                    mapped_code,
                )

        if resolved_region and resolved_region in blocked_regions:
            return self._error_result(451, f"region blocked: {resolved_region}", "network_error")

        checked_ctx = dict(ctx or {})
        checked_ctx["detected_region"] = resolved_region
        return self._success_result(checked_ctx)


    def _resolve_step_error_code(self, result: Dict[str, Any], default_error_code: str) -> str:
        """步骤错误码映射：保留网络层错误码，不重写"""
        error_code = str((result or {}).get("error_code") or "").strip()
        if error_code in {"network_timeout", "network_error"}:
            return error_code
        return default_error_code

    def _parse_callback_url(self, callback_url: str) -> Dict[str, str]:
        """解析 OAuth 回调地址中的 code/state"""
        raw_url = str(callback_url or "").strip()
        if not raw_url:
            return {"auth_code": "", "state": ""}

        parsed = urlparse(raw_url)
        query_params = parse_qs(parsed.query or "", keep_blank_values=False)
        fragment_params = parse_qs(parsed.fragment or "", keep_blank_values=False)

        def _pick_first(params: Dict[str, List[str]], key: str) -> str:
            values = params.get(key) or []
            if not values:
                return ""
            return str(values[0] or "").strip()

        auth_code = (
            _pick_first(query_params, "code")
            or _pick_first(query_params, "auth_code")
            or _pick_first(fragment_params, "code")
            or _pick_first(fragment_params, "auth_code")
        )
        state = _pick_first(query_params, "state") or _pick_first(fragment_params, "state")

        return {
            "auth_code": auth_code,
            "state": state,
        }

    def _extract_otp_code_from_payload(self, payload: Dict[str, Any]) -> str:
        """从 mail worker 返回体中提取 OTP"""
        if not isinstance(payload, dict):
            return ""

        for key in ("otp_code", "code", "otp", "verification_code"):
            value = payload.get(key)
            code = str(value or "").strip()
            if code:
                return code

        nested = payload.get("data")
        if isinstance(nested, dict):
            for key in ("otp_code", "code", "otp", "verification_code"):
                value = nested.get(key)
                code = str(value or "").strip()
                if code:
                    return code

        return ""

    async def _poll_otp_from_mail_worker(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """通过 mail worker 拉取 OTP"""
        register_input = dict((ctx or {}).get("register_input") or {})
        email = self._resolve_register_email(register_input)
        mail_worker_base_url = str(register_input.get("mail_worker_base_url") or "").strip().rstrip("/")
        mail_worker_token = str(register_input.get("mail_worker_token") or "").strip()

        if not mail_worker_base_url or not mail_worker_token:
            return self._error_result(400, "mail worker config missing", "input_invalid")

        request_url = f"{mail_worker_base_url}/v1/code?email={urllib.parse.quote(email)}"
        request_headers = {
            "Authorization": f"Bearer {mail_worker_token}",
            "Accept": "application/json",
        }

        result = await self._make_register_request(
            "GET",
            request_url,
            request_headers,
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=False,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "mail worker otp fetch failed"),
                self._resolve_step_error_code(result, "otp_validate_failed"),
            )

        otp_code = self._extract_otp_code_from_payload(result.get("data", {}))
        if not otp_code:
            return self._error_result(404, "otp code not found", "otp_validate_failed")

        return self._success_result({"otp_code": otp_code})

    async def _send_signup_fallback_otp(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """兼容辅助方法：统一使用 email-otp/send，无 passwordless fallback"""
        result = await self._make_register_request(
            "GET",
            "https://auth.openai.com/api/accounts/email-otp/send",
            self._build_browser_base_headers(
                {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                origin="https://auth.openai.com",
                referer="https://auth.openai.com/create-account/password",
            ),
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "send otp failed"),
                self._resolve_step_error_code(result, "otp_send_failed"),
            )

        return self._success_result(result.get("data", {}))

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_data: Optional[Dict[str, Any]] = None,
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default",
        proxy: Optional[str] = None,
        form_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求 (使用持久化隔离会话，提高 CF 通过率并防止污染)
        """
        # 尝试从 Header 或 Token 自动提取标识符，确保身份绝对隔离
        if identifier == "default":
            # 优先从账号 ID 识别，这对 Team 邀请等操作最重要
            acc_id = headers.get("chatgpt-account-id")
            if acc_id:
                identifier = f"acc_{acc_id}"
            # 其次从 Token 解析邮箱
            elif "Authorization" in headers:
                token = headers["Authorization"].replace("Bearer ", "")
                email = self.jwt_parser.extract_email(token)
                if email:
                    identifier = email

        proxy = str(proxy or "").strip()
        session = await self._get_session(db_session, identifier, proxy=proxy)

        # 补全基础浏览器请求头
        base_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://chatgpt.com/",
            "Origin": "https://chatgpt.com",
            "Connection": "keep-alive",
        }
        # 合并请求头，不要轻易覆盖 User-Agent 以免破坏 impersonate 的指纹
        for k, v in base_headers.items():
            if k not in headers:
                headers[k] = v

        for attempt in range(self.MAX_RETRIES):
            try:
                # 随机微小延迟，模拟真实用户行为
                if attempt > 0:
                    delay = self.RETRY_DELAYS[attempt-1] + random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay)

                logger.info(f"[{identifier}] 发送请求: {method} {url} (尝试 {attempt + 1})")

                if method == "GET":
                    response = await session.get(url, headers=headers)
                elif method == "POST":
                    if form_data is not None:
                        response = await session.post(url, headers=headers, data=form_data)
                    else:
                        response = await session.post(url, headers=headers, json=json_data)
                elif method == "DELETE":
                    if form_data is not None:
                        response = await session.delete(url, headers=headers, data=form_data)
                    else:
                        response = await session.delete(url, headers=headers, json=json_data)
                else:
                    raise ValueError(f"不支持的 HTTP 方法: {method}")

                status_code = response.status_code
                logger.info(f"响应状态码: {status_code}")

                if 200 <= status_code < 300:
                    try:
                        data = response.json()
                    except Exception:
                        data = {}
                    return {"success": True, "status_code": status_code, "data": data, "error": None}

                if 400 <= status_code < 500:
                    error_msg = response.text
                    error_code = None
                    try:
                        error_data = response.json()
                        detail = error_data.get("detail", error_msg)
                        # 确保 error_msg 是字符串，避免前端显示 [object Object]
                        error_msg = str(detail) if not isinstance(detail, str) else detail
                        if isinstance(error_data, dict):
                            error_info = error_data.get("error")
                            error_code = error_info.get("code") if isinstance(error_info, dict) else error_data.get("code")
                    except Exception:
                        pass

                    if error_code == "token_invalidated" or "token_invalidated" in str(error_msg).lower():
                        logger.warning(f"检测到 Token 失效，清理会话缓存: {identifier}")
                        await self.clear_session(identifier)

                    logger.warning(f"客户端错误 {status_code}: {error_msg}")
                    return {"success": False, "status_code": status_code, "error": error_msg, "error_code": error_code}

                if status_code >= 500:
                    if attempt < self.MAX_RETRIES - 1:
                        continue
                    return {"success": False, "status_code": status_code, "error": f"服务器错误 {status_code}"}

            except Exception as e:
                logger.error(f"请求异常: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    continue
                return {
                    "success": False,
                    "status_code": 0,
                    "error": str(e),
                    "error_code": self._map_network_exception(e),
                }

        return {"success": False, "status_code": 0, "error": "未知错误", "error_code": "network_error"}

    async def _make_register_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json_data: Optional[Dict[str, Any]] = None,
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default",
        special_session_step: bool = False,
        session: Optional[AsyncSession] = None,
        proxy: Optional[str] = None,
        form_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """注册流程请求分发器。special_session_step 会强制同一会话执行。"""
        if not special_session_step:
            return await self._make_request(
                method,
                url,
                headers,
                json_data,
                db_session,
                identifier,
                proxy=proxy,
                form_data=form_data,
            )

        active_session = session
        if active_session is None:
            active_session = await self._get_session(db_session, identifier, proxy=proxy)

        result = await self._make_special_session_request(
            method,
            url,
            headers,
            json_data,
            active_session,
            identifier,
            form_data=form_data,
        )
        enriched = dict(result)
        enriched.setdefault("session", active_session)
        return enriched

    async def register(
        self,
        *,
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """注册新账号"""
        runtime_context_result = self._build_runtime_context(identifier)
        if not runtime_context_result.get("success"):
            return runtime_context_result

        runtime_context = runtime_context_result.get("data", {})
        runtime_identifier = runtime_context.get("identifier", identifier)
        runtime_register_input = dict(runtime_context.get("register_input", {}))

        resolved_proxy = await self._resolve_register_proxy(runtime_register_input, db_session)
        if resolved_proxy:
            runtime_register_input["resolved_proxy"] = resolved_proxy
            runtime_context["register_input"] = runtime_register_input

        network_check_result = await self._check_network_and_region(
            {
                "register_input": runtime_context.get("register_input", {}),
                "db_session": db_session,
                "identifier": runtime_identifier,
            }
        )
        if not network_check_result.get("success"):
            return network_check_result

        identity_context_result = self._prepare_identity(
            {
                "register_input": runtime_context.get("register_input", {}),
                "db_session": db_session,
                "identifier": runtime_identifier,
            }
        )
        if not identity_context_result.get("success"):
            return identity_context_result

        pipeline_ctx = identity_context_result.get("data", {})

        pipeline_result = await self._run_register_pipeline(
            {
                "register_input": pipeline_ctx.get("register_input", {}),
                "runtime_context": runtime_context,
                "db_session": db_session,
                "identifier": runtime_identifier,
            }
        )

        if not pipeline_result.get("success"):
            return self._error_result(
                pipeline_result.get("status_code", 0),
                pipeline_result.get("error", "not implemented"),
                pipeline_result.get("error_code", "unknown_error"),
            )

        return await self._finalize_registration_result(
            pipeline_result.get("data", {}),
            register_input=pipeline_ctx.get("register_input", {}),
            db_session=db_session,
            identifier=runtime_identifier,
        )

    def _build_runtime_context(self, identifier: str) -> Dict[str, Any]:
        """构建注册运行时上下文并执行输入校验"""
        mail_domain = str(os.getenv("REGISTER_MAIL_DOMAIN") or "").strip().lower()
        if not mail_domain:
            return self._error_result(400, "REGISTER_MAIL_DOMAIN is required", "input_invalid")

        mail_worker_base_url = str(os.getenv("REGISTER_MAIL_WORKER_BASE_URL") or "").strip()
        if not mail_worker_base_url:
            return self._error_result(400, "REGISTER_MAIL_WORKER_BASE_URL is required", "input_invalid")

        mail_worker_token = str(os.getenv("REGISTER_MAIL_WORKER_TOKEN") or "").strip()
        if not mail_worker_token:
            return self._error_result(400, "REGISTER_MAIL_WORKER_TOKEN is required", "input_invalid")

        normalized_input: Dict[str, Any] = {
            "mail_domain": mail_domain,
            "mail_worker_base_url": mail_worker_base_url.rstrip("/"),
            "mail_worker_token": mail_worker_token,
            "register_http_timeout": 15,
            "mail_poll_seconds": 3,
            "mail_poll_max_attempts": 40,
            "fixed_email": "",
            "fixed_password": "",
        }

        runtime_identifier = str(identifier or "").strip() or "default"

        return self._success_result(
            {
                "identifier": runtime_identifier,
                "register_input": normalized_input,
            }
        )

    async def _start_auth_flow(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """启动注册鉴权前置步骤"""
        register_input = ctx.get("register_input", {})
        email = self._resolve_register_email(register_input)
        oauth_state = str(
            ctx.get("oauth_state")
            or register_input.get("oauth_state")
            or register_input.get("state")
            or ""
        ).strip()

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/accounts/check/v4",
            self._build_auth_headers(),
            {
                "username": email,
                "state": oauth_state or "register",
            },
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "start auth flow failed"),
                self._resolve_step_error_code(result, "auth_flow_failed"),
            )

        response_data = dict(result.get("data", {}))
        response_data["oauth_state"] = oauth_state or str(response_data.get("oauth_state") or "").strip()

        authorize_url = self._build_register_oauth_url(register_input, response_data.get("oauth_state", ""))
        if authorize_url:
            response_data["authorize_url"] = authorize_url

        return self._success_result(response_data)

    async def _submit_signup(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """提交注册信息（必须密码注册）"""
        register_input = ctx.get("register_input", {})
        password = str(register_input.get("fixed_password") or "").strip()
        if not password:
            return self._error_result(400, "password is required", "signup_failed")

        body = {
            "username": self._resolve_register_email(register_input),
            "password": password,
        }

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/accounts/user/register",
            self._build_auth_headers(
                extra_headers={
                    "Referer": "https://auth.openai.com/create-account/password",
                    "Origin": "https://auth.openai.com",
                }
            ),
            body,
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "signup failed"),
                self._resolve_step_error_code(result, "signup_failed"),
            )

        return self._success_result(result.get("data", {}))

    async def _send_otp_with_fallback(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """发送 OTP（禁用 passwordless，固定使用 email-otp/send）"""
        result = await self._make_register_request(
            "GET",
            "https://auth.openai.com/api/accounts/email-otp/send",
            self._build_browser_base_headers(
                {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
                origin="https://auth.openai.com",
                referer="https://auth.openai.com/create-account/password",
            ),
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "send otp failed"),
                self._resolve_step_error_code(result, "otp_send_failed"),
            )

        data = dict(result.get("data", {}))
        data["used_fallback"] = False
        return self._success_result(data)

    async def _poll_and_validate_otp(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """轮询并校验 OTP"""
        register_input = ctx.get("register_input", {})
        email = self._resolve_register_email(register_input)

        otp_code = str(ctx.get("otp_code") or "").strip()
        if not otp_code:
            otp_result = await self._poll_otp_from_mail_worker(ctx)
            if not otp_result.get("success"):
                otp_error_code = self._resolve_step_error_code(
                    otp_result,
                    "otp_validate_failed",
                )
                if otp_error_code not in {"network_timeout", "network_error"}:
                    otp_error_code = "otp_validate_failed"
                return self._error_result(
                    int(otp_result.get("status_code", 0) or 0),
                    otp_result.get("error", "otp validate failed"),
                    otp_error_code,
                )
            otp_code = str((otp_result.get("data") or {}).get("otp_code") or "").strip()
            if not otp_code:
                return self._error_result(404, "otp code not found", "otp_validate_failed")

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/otp/validate",
            self._build_auth_headers(),
            {
                "username": email,
                "otp_code": otp_code,
            },
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "otp validate failed"),
                self._resolve_step_error_code(result, "otp_validate_failed"),
            )

        return self._success_result(result.get("data", {}))

    async def _create_account(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """创建账号"""
        register_input = ctx.get("register_input", {})
        email = self._resolve_register_email(register_input)

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/accounts/create",
            self._build_auth_headers(),
            {"email": email},
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "create account failed"),
                self._resolve_step_error_code(result, "create_account_failed"),
            )

        return self._success_result(result.get("data", {}))

    def _merge_pipeline_artifacts(
        self,
        pipeline_data: Dict[str, Any],
        *artifact_sources: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """将关键鉴权产物从多步输出合并到 pipeline_data"""
        merged = dict(pipeline_data or {})
        artifact_keys = {
            "auth_code",
            "callback_url",
            "token_endpoint",
            "oauth_state",
            "state",
            "code",
            "access_token",
            "refresh_token",
            "id_token",
            "session_token",
            "expires_at",
            "account_id",
            "email",
        }

        for source in artifact_sources:
            if not isinstance(source, dict):
                continue

            candidates = [source]
            nested_data = source.get("data")
            if isinstance(nested_data, dict):
                candidates.append(nested_data)

            for candidate in candidates:
                for key, value in candidate.items():
                    if key not in artifact_keys:
                        continue
                    if value is None:
                        continue
                    normalized = str(value).strip() if isinstance(value, str) else value
                    if isinstance(normalized, str) and not normalized:
                        continue
                    merged[key] = value

        callback_url = str(merged.get("callback_url") or "").strip()
        if callback_url:
            parsed_callback = self._parse_callback_url(callback_url)
            parsed_auth_code = str(parsed_callback.get("auth_code") or "").strip()
            if parsed_auth_code and not str(merged.get("auth_code") or "").strip():
                merged["auth_code"] = parsed_auth_code
            parsed_state = str(parsed_callback.get("state") or "").strip()
            if parsed_state and not str(merged.get("oauth_state") or "").strip():
                merged["oauth_state"] = parsed_state

        if not str(merged.get("auth_code") or "").strip():
            code_alias = str(merged.get("code") or "").strip()
            if code_alias:
                merged["auth_code"] = code_alias

        if not str(merged.get("oauth_state") or "").strip():
            state_alias = str(merged.get("state") or "").strip()
            if state_alias:
                merged["oauth_state"] = state_alias

        return merged

    async def _run_register_pipeline(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """执行注册流水线"""
        bootstrap_ctx = self._ensure_oauth_bootstrap(ctx)

        sentinel_result = await self._make_register_request(
            "POST",
            "https://chatgpt.com/backend-api/sentinel/chat-requirements",
            self._build_sentinel_headers(),
            {},
            db_session=bootstrap_ctx.get("db_session"),
            identifier=bootstrap_ctx.get("identifier", "default"),
            special_session_step=True,
            session=bootstrap_ctx.get("session"),
            proxy=self._resolve_register_proxy_from_ctx(bootstrap_ctx),
        )

        sentinel_status = int(sentinel_result.get("status_code", 0) or 0)
        if not sentinel_result.get("success") or sentinel_status >= 300:
            return self._error_result(
                sentinel_status,
                sentinel_result.get("error", "sentinel failed"),
                self._resolve_step_error_code(sentinel_result, "auth_flow_failed"),
            )

        step_ctx = dict(bootstrap_ctx)
        step_ctx["session"] = sentinel_result.get("session", bootstrap_ctx.get("session"))
        step_ctx["signup_completed"] = False

        pipeline_data = self._merge_pipeline_artifacts(
            {
                "identifier": bootstrap_ctx.get("identifier", "default"),
                "oauth_state": bootstrap_ctx.get("oauth_state"),
            },
            bootstrap_ctx,
            sentinel_result,
        )

        start_result = await self._start_auth_flow(step_ctx)
        if not start_result.get("success"):
            return start_result
        pipeline_data = self._merge_pipeline_artifacts(pipeline_data, start_result)

        otp_send_result = await self._send_otp_with_fallback(step_ctx)
        if not otp_send_result.get("success"):
            return otp_send_result
        pipeline_data = self._merge_pipeline_artifacts(pipeline_data, otp_send_result)

        if otp_send_result.get("data", {}).get("used_fallback"):
            step_ctx["signup_completed"] = True

        if not step_ctx.get("signup_completed"):
            signup_result = await self._submit_signup(step_ctx)
            if not signup_result.get("success"):
                return signup_result
            step_ctx["signup_completed"] = True
            pipeline_data = self._merge_pipeline_artifacts(pipeline_data, signup_result)

        otp_validate_result = await self._poll_and_validate_otp(step_ctx)
        if not otp_validate_result.get("success"):
            return otp_validate_result
        pipeline_data = self._merge_pipeline_artifacts(pipeline_data, otp_validate_result)

        create_result = await self._create_account(step_ctx)
        if not create_result.get("success"):
            return create_result

        pipeline_data = self._merge_pipeline_artifacts(
            pipeline_data,
            create_result,
        )

        return self._success_result(pipeline_data)

    async def _exchange_tokens(
        self,
        pipeline_data: Dict[str, Any],
        register_input: Dict[str, Any],
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default",
    ) -> Dict[str, Any]:
        """最小 token 交换实现：优先 token endpoint，其次复用已有字段"""
        source: Dict[str, Any] = {}
        if isinstance(pipeline_data, dict):
            source.update(pipeline_data)

        source = self._merge_pipeline_artifacts(source)
        normalized_register_input = register_input if isinstance(register_input, dict) else {}

        auth_code = str(
            source.get("auth_code")
            or normalized_register_input.get("auth_code")
            or ""
        ).strip()

        if not auth_code:
            callback_url = str(
                source.get("callback_url")
                or normalized_register_input.get("callback_url")
                or ""
            ).strip()
            parsed_callback = self._parse_callback_url(callback_url)
            auth_code = str(parsed_callback.get("auth_code") or "").strip()
            callback_state = str(parsed_callback.get("state") or "").strip()
            if callback_state and not source.get("oauth_state"):
                source["oauth_state"] = callback_state

        token_endpoint = str(
            normalized_register_input.get("token_endpoint")
            or source.get("token_endpoint")
            or ""
        ).strip()

        if auth_code and token_endpoint:
            token_exchange_payload = {
                "grant_type": str(normalized_register_input.get("grant_type") or "authorization_code"),
                "code": auth_code,
            }
            client_id = str(normalized_register_input.get("client_id") or "").strip()
            redirect_uri = str(normalized_register_input.get("redirect_uri") or "").strip()
            code_verifier = str(normalized_register_input.get("code_verifier") or "").strip()
            if client_id:
                token_exchange_payload["client_id"] = client_id
            if redirect_uri:
                token_exchange_payload["redirect_uri"] = redirect_uri
            if code_verifier:
                token_exchange_payload["code_verifier"] = code_verifier

            exchange_result = await self._make_request(
                "POST",
                token_endpoint,
                {"Content-Type": "application/x-www-form-urlencoded"},
                db_session=db_session,
                identifier=identifier,
                form_data=token_exchange_payload,
            )
            if exchange_result.get("success"):
                exchange_data = exchange_result.get("data", {}) if isinstance(exchange_result.get("data"), dict) else {}
                source.update(exchange_data)

                session_access_token = self._extract_session_access_token(exchange_data)
                if session_access_token and not str(source.get("access_token") or "").strip():
                    source["access_token"] = session_access_token

                if not str(source.get("session_token") or "").strip():
                    for key in ("session_token", "sessionToken"):
                        maybe_session_token = str(exchange_data.get(key) or "").strip()
                        if maybe_session_token:
                            source["session_token"] = maybe_session_token
                            break

                if not str(source.get("id_token") or "").strip():
                    for key in ("id_token", "idToken"):
                        maybe_id_token = str(exchange_data.get(key) or "").strip()
                        if maybe_id_token:
                            source["id_token"] = maybe_id_token
                            break
            else:
                return self._error_result(
                    int(exchange_result.get("status_code", 0) or 0),
                    exchange_result.get("error", "token exchange failed"),
                    self._resolve_step_error_code(exchange_result, "token_exchange_failed"),
                )

        token_payload = normalized_register_input.get("token_payload")
        if isinstance(token_payload, dict):
            for key in ("access_token", "refresh_token", "id_token", "session_token", "expires_at"):
                if key not in token_payload:
                    continue
                current_value = str(source.get(key) or "").strip()
                fallback_value = token_payload.get(key)
                if not current_value and fallback_value is not None:
                    source[key] = fallback_value

        if not str(source.get("access_token") or "").strip():
            session_access_token = self._extract_session_access_token(source)
            if session_access_token:
                source["access_token"] = session_access_token

        id_token_claims = self._extract_token_claims_without_verification(str(source.get("id_token") or ""))
        if id_token_claims:
            if not str(source.get("email") or "").strip():
                source["email"] = str(id_token_claims.get("email") or "").strip() or source.get("email")
            if not str(source.get("account_id") or "").strip():
                source["account_id"] = (
                    str(id_token_claims.get("account_id") or "").strip()
                    or str(id_token_claims.get("sub") or "").strip()
                    or source.get("account_id")
                )

        access_token = str(source.get("access_token") or "").strip()
        refresh_token = str(source.get("refresh_token") or "").strip()
        id_token = str(source.get("id_token") or "").strip()
        session_token = str(source.get("session_token") or "").strip()
        expires_at = str(source.get("expires_at") or "").strip()

        if not any((access_token, refresh_token, id_token, session_token)):
            return self._error_result(0, "token exchange failed", "token_exchange_failed")

        return self._success_result(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id_token": id_token,
                "session_token": session_token,
                "expires_at": expires_at,
            }
        )

    async def _enrich_account_context(
        self,
        base_payload: Dict[str, Any],
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default",
    ) -> Dict[str, Any]:
        """best-effort 补充 plan/org/workspace 字段"""
        enriched = {
            "plan_type": str(base_payload.get("plan_type") or "").strip(),
            "organization_id": str(base_payload.get("organization_id") or "").strip(),
            "workspace_id": str(base_payload.get("workspace_id") or "").strip(),
        }

        if all(enriched.values()):
            return self._success_result(enriched)

        access_token = str(base_payload.get("access_token") or "").strip()
        if not access_token:
            return self._success_result(enriched)

        try:
            info_result = await self.get_account_info(access_token, db_session, identifier=identifier)
        except Exception:
            return self._success_result(enriched)

        accounts = info_result.get("accounts") or []
        account_id = str(base_payload.get("account_id") or "").strip()
        selected = None
        for account in accounts:
            if str((account or {}).get("account_id") or "").strip() == account_id and account_id:
                selected = account
                break
        if selected is None and accounts:
            selected = accounts[0]

        if isinstance(selected, dict):
            if not enriched["plan_type"]:
                enriched["plan_type"] = str(selected.get("plan_type") or "").strip()
            if not enriched["organization_id"]:
                enriched["organization_id"] = str(selected.get("organization_id") or "").strip()
            if not enriched["workspace_id"]:
                enriched["workspace_id"] = str(
                    selected.get("workspace_id")
                    or selected.get("account_id")
                    or ""
                ).strip()

        return self._success_result(enriched)

    async def _finalize_registration_result(
        self,
        pipeline_data: Dict[str, Any],
        register_input: Dict[str, Any],
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default",
    ) -> Dict[str, Any]:
        """聚合注册流水线结果并完成 token 与上下文补充"""
        payload = dict(pipeline_data or {})
        payload.setdefault("email", self._resolve_register_email(register_input))

        state_verification_result = self._verify_callback_state(payload, register_input)
        if not state_verification_result.get("success"):
            return state_verification_result

        if state_verification_result.get("data"):
            payload.update(state_verification_result.get("data", {}))

        if any(
            str(payload.get(field) or "").strip()
            for field in ("access_token", "refresh_token", "id_token", "session_token")
        ):
            token_result = self._success_result(
                {
                    "access_token": str(payload.get("access_token") or "").strip(),
                    "refresh_token": str(payload.get("refresh_token") or "").strip(),
                    "id_token": str(payload.get("id_token") or "").strip(),
                    "session_token": str(payload.get("session_token") or "").strip(),
                    "expires_at": str(payload.get("expires_at") or "").strip(),
                }
            )
        else:
            token_result = await self._exchange_tokens(
                payload,
                register_input,
                db_session=db_session,
                identifier=identifier,
            )

        if not token_result.get("success"):
            return self._error_result(
                int(token_result.get("status_code", 0) or 0),
                token_result.get("error", "token finalize failed"),
                self._resolve_step_error_code(token_result, "token_finalize_failed"),
            )

        payload.update(token_result.get("data", {}))

        account_id = str(payload.get("account_id") or "").strip()
        provided_identifier = str(identifier or "").strip()
        pipeline_identifier = str(payload.get("identifier") or "").strip()
        email = str(payload.get("email") or "").strip()

        if provided_identifier and provided_identifier != "default":
            final_identifier = provided_identifier
        elif pipeline_identifier:
            final_identifier = pipeline_identifier
        elif account_id:
            final_identifier = f"acc_{account_id}"
        elif email:
            final_identifier = email
        else:
            final_identifier = "default"

        payload["identifier"] = final_identifier

        enrich_result = await self._enrich_account_context(
            payload,
            db_session=db_session,
            identifier=final_identifier,
        )
        if enrich_result.get("success"):
            payload.update(enrich_result.get("data", {}))

        final_payload = {
            "email": str(payload.get("email") or "").strip(),
            "identifier": final_identifier,
            "account_id": account_id,
            "access_token": str(payload.get("access_token") or "").strip(),
            "refresh_token": str(payload.get("refresh_token") or "").strip(),
            "id_token": str(payload.get("id_token") or "").strip(),
            "session_token": str(payload.get("session_token") or "").strip(),
            "expires_at": str(payload.get("expires_at") or "").strip(),
            "plan_type": str(payload.get("plan_type") or "").strip(),
            "organization_id": str(payload.get("organization_id") or "").strip(),
            "workspace_id": str(payload.get("workspace_id") or "").strip(),
        }
        return self._success_result(final_payload)

    def _success_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """构建统一成功响应"""
        return {
            "success": True,
            "status_code": 200,
            "data": data,
            "error": None,
            "error_code": None,
        }

    def _error_result(self, status_code: int, error: str, error_code: str) -> Dict[str, Any]:
        """构建统一错误响应"""
        return {
            "success": False,
            "status_code": status_code,
            "data": None,
            "error": error,
            "error_code": error_code,
        }

    async def send_invite(
        self,
        access_token: str,
        account_id: str,
        email: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """发送 Team 邀请"""
        url = f"{self.BASE_URL}/accounts/{account_id}/invites"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id
        }
        json_data = {"email_addresses": [email], "role": "standard-user", "resend_emails": True}
        return await self._make_request("POST", url, headers, json_data, db_session, identifier)

    async def get_members(
        self,
        access_token: str,
        account_id: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """获取 Team 成员列表"""
        all_members = []
        offset = 0
        limit = 50
        while True:
            url = f"{self.BASE_URL}/accounts/{account_id}/users?limit={limit}&offset={offset}"
            headers = {"Authorization": f"Bearer {access_token}"}
            result = await self._make_request("GET", url, headers, db_session=db_session, identifier=identifier)
            if not result["success"]:
                return {"success": False, "members": [], "total": 0, "error": result["error"]}
            data = result["data"]
            items = data.get("items", [])
            total = data.get("total", 0)
            all_members.extend(items)
            if len(all_members) >= total:
                break
            offset += limit
        return {"success": True, "members": all_members, "total": len(all_members), "error": None}

    async def get_invites(
        self,
        access_token: str,
        account_id: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """获取 Team 邀请列表"""
        url = f"{self.BASE_URL}/accounts/{account_id}/invites"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id
        }
        result = await self._make_request("GET", url, headers, db_session=db_session, identifier=identifier)
        if not result["success"]:
            return {"success": False, "items": [], "total": 0, "error": result["error"]}
        data = result["data"]
        items = data.get("items", [])
        return {"success": True, "items": items, "total": len(items), "error": None}

    async def delete_invite(
        self,
        access_token: str,
        account_id: str,
        email: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """撤回邀请"""
        url = f"{self.BASE_URL}/accounts/{account_id}/invites"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id
        }
        json_data = {"email_address": email}
        return await self._make_request("DELETE", url, headers, json_data, db_session, identifier)

    async def delete_member(
        self,
        access_token: str,
        account_id: str,
        user_id: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """删除成员"""
        url = f"{self.BASE_URL}/accounts/{account_id}/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id
        }
        result = await self._make_request("DELETE", url, headers, db_session=db_session, identifier=identifier)
        return result

    async def toggle_beta_feature(
        self,
        access_token: str,
        account_id: str,
        feature: str,
        value: bool,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """开启或关闭 Beta 功能"""
        url = f"{self.BASE_URL}/accounts/{account_id}/beta_features"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "oai-language": "zh-CN",
            "sec-ch-ua-platform": '"Windows"'
        }
        json_data = {"feature": feature, "value": value}
        return await self._make_request("POST", url, headers, json_data, db_session, identifier)

    async def get_account_info(
        self,
        access_token: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """获取账户和订阅信息"""
        url = f"{self.BASE_URL}/accounts/check/v4-2023-04-27"
        headers = {"Authorization": f"Bearer {access_token}"}
        result = await self._make_request("GET", url, headers, db_session=db_session, identifier=identifier)
        if not result["success"]:
            return {"success": False, "accounts": [], "error": result["error"]}

        data = result["data"]
        accounts_data = data.get("accounts", {})
        team_accounts = []
        for aid, info in accounts_data.items():
            account = info.get("account", {})
            entitlement = info.get("entitlement", {})
            if account.get("plan_type") == "team":
                team_accounts.append({
                    "account_id": aid,
                    "name": account.get("name", ""),
                    "plan_type": "team",
                    "account_user_role": account.get("account_user_role", ""),
                    "subscription_plan": entitlement.get("subscription_plan", ""),
                    "expires_at": entitlement.get("expires_at", ""),
                    "has_active_subscription": entitlement.get("has_active_subscription", False)
                })
        return {"success": True, "accounts": team_accounts, "error": None}

    async def get_account_settings(
        self,
        access_token: str,
        account_id: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """获取账户设置信息 (包含 beta_settings)"""
        url = f"{self.BASE_URL}/accounts/{account_id}/settings"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id
        }
        return await self._make_request("GET", url, headers, db_session=db_session, identifier=identifier)

    async def refresh_access_token_with_session_token(
        self,
        session_token: str,
        db_session: DBAsyncSession,
        account_id: Optional[str] = None,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """使用 session_token 刷新 AT (使用标识符隔离会话)"""
        url = "https://chatgpt.com/api/auth/session"
        if account_id:
            url += f"?exchange_workspace_token=true&workspace_id={account_id}&reason=setCurrentAccount"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Cookie": f"__Secure-next-auth.session-token={session_token}"
        }

        # 对于刷新请求，如果未提供 identifier，我们使用 session_token 的前 8 位作为临时隔离
        if identifier == "default":
            identifier = f"st_{session_token[:8]}"

        session = await self._get_session(db_session, identifier)
        try:
            # 手动合并基础头
            headers["Referer"] = "https://chatgpt.com/"
            headers["Connection"] = "keep-alive"

            response = await session.get(url, headers=headers)
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    return {"success": False, "error": "无法解析会话 JSON 响应"}

                at = data.get("accessToken")
                st = data.get("sessionToken")
                if at:
                    return {"success": True, "access_token": at, "session_token": st}

                # 如果 200 但没有 token，可能是被拦截或格式变了
                error_msg = str(data.get("detail") or data.get("error") or "响应中未包含 accessToken")
                return {"success": False, "error": error_msg}
            else:
                error_text = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail") or error_data.get("error") or error_text
                    if not isinstance(error_msg, str):
                        error_msg = str(error_msg)
                except:
                    error_msg = error_text
                return {"success": False, "status_code": response.status_code, "error": error_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def refresh_access_token_with_refresh_token(
        self,
        refresh_token: str,
        client_id: str,
        db_session: DBAsyncSession,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """使用 refresh_token 刷新 AT"""
        url = "https://auth.openai.com/oauth/token"
        json_data = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "redirect_uri": "com.openai.sora://auth.openai.com/android/com.openai.sora/callback",
            "refresh_token": refresh_token
        }
        headers = {"Content-Type": "application/json"}

        if identifier == "default":
            identifier = f"rt_{refresh_token[:8]}"

        result = await self._make_request("POST", url, headers, json_data, db_session, identifier)
        if result["success"]:
            data = result.get("data", {})
            return {
                "success": True,
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "data": data
            }
        return result

    async def clear_session(self, identifier: Optional[str] = None):
        """清理指定身份的会话，若不提供则清理所有"""
        if identifier:
            normalized_identifier = str(identifier or "").strip()
            session_keys = [
                key
                for key in self._sessions.keys()
                if key == normalized_identifier or key.startswith(f"{normalized_identifier}::proxy::")
            ]
            for session_key in session_keys:
                try:
                    await self._sessions[session_key].close()
                except:
                    pass
                del self._sessions[session_key]
            self._identifier_proxies.pop(normalized_identifier, None)
        else:
            await self.close()

    async def close(self):
        """关闭所有会话"""
        for session in self._sessions.values():
            try:
                await session.close()
            except:
                pass
        self._sessions.clear()
        self._identifier_proxies.clear()


# 创建全局实例
chatgpt_service = ChatGPTService()
