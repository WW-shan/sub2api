"""
ChatGPT API 服务
用于调用 ChatGPT 后端 API,实现 Team 成员管理功能
"""
import asyncio
import logging
import random
from urllib.parse import parse_qs, urlparse
from typing import Optional, Dict, Any, List
from curl_cffi.requests import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession as DBAsyncSession
from app.utils.jwt_parser import JWTParser

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

    async def _create_session(self, db_session: DBAsyncSession) -> AsyncSession:
        """
        创建 HTTP 会话
        """
        # 使用 chrome110 指纹，这是 curl_cffi 中绕过 CF 最稳定的版本之一
        session = AsyncSession(
            impersonate="chrome110",
            timeout=30,
            verify=False # 某些代理环境下需要，或根据需求开启
        )
        return session

    async def _get_session(self, db_session: DBAsyncSession, identifier: str) -> AsyncSession:
        """
        根据标识符获取或创建持久会话
        """
        if identifier not in self._sessions:
            logger.info(f"为标识符 {identifier} 创建新会话")
            self._sessions[identifier] = await self._create_session(db_session)
        return self._sessions[identifier]


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
    ):
        """在给定会话上发送 HTTP 请求"""
        if method == "GET":
            return await session.get(url, headers=headers)
        if method == "POST":
            return await session.post(url, headers=headers, json=json_data)
        if method == "DELETE":
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
                response = await self._dispatch_http_call(session, method, url, headers, json_data)
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

    async def _check_network_and_region(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """注册前网络与区域检查（最小实现）"""
        register_input = dict((ctx or {}).get("register_input") or {})

        blocked_regions = {
            str(region).strip().upper()
            for region in (register_input.get("blocked_regions") or [])
            if str(region).strip()
        }
        if not blocked_regions:
            blocked_regions = {"IR", "KP", "SY", "CU"}

        region = str(register_input.get("region") or "").strip().upper()
        if region and region in blocked_regions:
            return self._error_result(451, f"region blocked: {region}", "region_blocked")

        return self._success_result(dict(ctx or {}))

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

        request_url = f"{mail_worker_base_url}/api/otp/latest"
        request_headers = {
            "Authorization": f"Bearer {mail_worker_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request_payload = {
            "email": email,
        }

        result = await self._make_register_request(
            "POST",
            request_url,
            request_headers,
            request_payload,
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
                self._resolve_step_error_code(result, "otp_fetch_failed"),
            )

        otp_code = self._extract_otp_code_from_payload(result.get("data", {}))
        if not otp_code:
            return self._error_result(404, "otp code not found", "otp_not_found")

        return self._success_result({"otp_code": otp_code})

    async def _send_signup_fallback_otp(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """fallback 后显式触发 OTP 发送"""
        register_input = ctx.get("register_input", {})
        email = self._resolve_register_email(register_input)

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/otp/send",
            self._build_auth_headers(),
            {"username": email, "reason": "signup_fallback"},
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        status_code = int(result.get("status_code", 0) or 0)
        if not result.get("success") or status_code >= 300:
            return self._error_result(
                status_code,
                result.get("error", "fallback otp send failed"),
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
        identifier: str = "default"
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

        session = await self._get_session(db_session, identifier)
        
        # 补全基础浏览器请求头
        base_headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://chatgpt.com/",
            "Origin": "https://chatgpt.com",
            "Connection": "keep-alive"
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
                    response = await session.post(url, headers=headers, json=json_data)
                elif method == "DELETE":
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
            )

        active_session = session
        if active_session is None:
            active_session = await self._get_session(db_session, identifier)

        result = await self._make_special_session_request(
            method,
            url,
            headers,
            json_data,
            active_session,
            identifier,
        )
        enriched = dict(result)
        enriched.setdefault("session", active_session)
        return enriched

    async def register(
        self,
        register_input: Dict[str, Any],
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """注册新账号"""
        runtime_context_result = self._build_runtime_context(register_input, identifier)
        if not runtime_context_result.get("success"):
            return runtime_context_result

        runtime_context = runtime_context_result.get("data", {})
        runtime_identifier = runtime_context.get("identifier", identifier)

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

    def _build_runtime_context(self, register_input: Dict[str, Any], identifier: str) -> Dict[str, Any]:
        """构建注册运行时上下文并执行输入校验"""
        if not isinstance(register_input, dict):
            return self._error_result(400, "register_input must be an object", "input_invalid")

        normalized_input = dict(register_input)

        mail_worker_base_url = str(normalized_input.get("mail_worker_base_url") or "").strip()
        if not mail_worker_base_url:
            return self._error_result(400, "mail_worker_base_url is required", "input_invalid")
        normalized_input["mail_worker_base_url"] = mail_worker_base_url.rstrip("/")

        mail_worker_token = str(normalized_input.get("mail_worker_token") or "").strip()
        if not mail_worker_token:
            return self._error_result(400, "mail_worker_token is required", "input_invalid")
        normalized_input["mail_worker_token"] = mail_worker_token

        fixed_email = str(normalized_input.get("fixed_email") or "").strip()
        normalized_input["fixed_email"] = fixed_email
        if not fixed_email:
            mail_domain = str(normalized_input.get("mail_domain") or "").strip().lower()
            if not mail_domain:
                return self._error_result(
                    400,
                    "mail_domain is required when fixed_email is absent",
                    "input_invalid",
                )
            normalized_input["mail_domain"] = mail_domain

        for field_name, default_value in (
            ("register_http_timeout", 15),
            ("mail_poll_seconds", 3),
            ("mail_poll_max_attempts", 40),
        ):
            raw_value = normalized_input.get(field_name, default_value)
            try:
                int_value = int(raw_value)
            except (TypeError, ValueError):
                return self._error_result(400, f"{field_name} must be a positive integer", "input_invalid")

            if int_value <= 0:
                return self._error_result(400, f"{field_name} must be > 0", "input_invalid")

            normalized_input[field_name] = int_value

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

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/accounts/check/v4",
            self._build_auth_headers(),
            {
                "username": email,
                "state": "register",
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

        return self._success_result(result.get("data", {}))

    async def _submit_signup(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """提交注册信息"""
        register_input = ctx.get("register_input", {})
        body = {
            "username": self._resolve_register_email(register_input),
            "password": str(register_input.get("fixed_password") or ""),
        }

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/accounts/user/register",
            self._build_auth_headers(),
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
        """发送 OTP，密码免注册禁用时走 fallback"""
        register_input = ctx.get("register_input", {})
        email = self._resolve_register_email(register_input)

        passwordless_result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/passwordless/start",
            self._build_auth_headers(),
            {"username": email},
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        passwordless_status = int(passwordless_result.get("status_code", 0) or 0)
        if passwordless_result.get("success") and passwordless_status < 300:
            data = dict(passwordless_result.get("data", {}))
            data["used_fallback"] = False
            return self._success_result(data)

        if passwordless_result.get("error_code") != "passwordless_signup_disabled":
            return self._error_result(
                passwordless_status,
                passwordless_result.get("error", "send otp failed"),
                self._resolve_step_error_code(passwordless_result, "otp_send_failed"),
            )

        signup_result = await self._submit_signup(ctx)
        if not signup_result.get("success"):
            return signup_result

        otp_send_result = await self._send_signup_fallback_otp(ctx)
        if not otp_send_result.get("success"):
            return otp_send_result

        fallback_data = dict(signup_result.get("data", {}))
        fallback_data.update(otp_send_result.get("data", {}))
        fallback_data["used_fallback"] = True
        return self._success_result(fallback_data)

    async def _poll_and_validate_otp(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """轮询并校验 OTP"""
        register_input = ctx.get("register_input", {})
        email = self._resolve_register_email(register_input)

        otp_code = str(ctx.get("otp_code") or "").strip()
        if not otp_code:
            otp_result = await self._poll_otp_from_mail_worker(ctx)
            if otp_result.get("success"):
                otp_code = str((otp_result.get("data") or {}).get("otp_code") or "").strip()
            else:
                otp_error_code = str(otp_result.get("error_code") or "").strip()
                if otp_error_code in {"network_timeout", "network_error"}:
                    return otp_result

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

    async def _run_register_pipeline(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """执行注册流水线"""
        sentinel_result = await self._make_register_request(
            "POST",
            "https://chatgpt.com/backend-api/sentinel/chat-requirements",
            self._build_sentinel_headers(),
            {},
            db_session=ctx.get("db_session"),
            identifier=ctx.get("identifier", "default"),
            special_session_step=True,
            session=ctx.get("session"),
        )

        sentinel_status = int(sentinel_result.get("status_code", 0) or 0)
        if not sentinel_result.get("success") or sentinel_status >= 300:
            return self._error_result(
                sentinel_status,
                sentinel_result.get("error", "sentinel failed"),
                self._resolve_step_error_code(sentinel_result, "auth_flow_failed"),
            )

        step_ctx = dict(ctx)
        step_ctx["session"] = sentinel_result.get("session", ctx.get("session"))
        step_ctx["signup_completed"] = False

        start_result = await self._start_auth_flow(step_ctx)
        if not start_result.get("success"):
            return start_result

        otp_send_result = await self._send_otp_with_fallback(step_ctx)
        if not otp_send_result.get("success"):
            return otp_send_result

        if otp_send_result.get("data", {}).get("used_fallback"):
            step_ctx["signup_completed"] = True

        if not step_ctx.get("signup_completed"):
            signup_result = await self._submit_signup(step_ctx)
            if not signup_result.get("success"):
                return signup_result
            step_ctx["signup_completed"] = True

        otp_validate_result = await self._poll_and_validate_otp(step_ctx)
        if not otp_validate_result.get("success"):
            return otp_validate_result

        create_result = await self._create_account(step_ctx)
        if not create_result.get("success"):
            return create_result

        pipeline_data = {"identifier": ctx.get("identifier", "default")}
        create_data = create_result.get("data")
        if isinstance(create_data, dict):
            pipeline_data.update(create_data)

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
                {"Content-Type": "application/json"},
                token_exchange_payload,
                db_session=db_session,
                identifier=identifier,
            )
            if exchange_result.get("success"):
                source.update(exchange_result.get("data", {}))
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
            if identifier in self._sessions:
                try:
                    await self._sessions[identifier].close()
                except:
                    pass
                del self._sessions[identifier]
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


# 创建全局实例
chatgpt_service = ChatGPTService()
