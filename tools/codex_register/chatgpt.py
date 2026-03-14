"""
ChatGPT API 服务
用于调用 ChatGPT 后端 API,实现 Team 成员管理功能
"""
import asyncio
import logging
import random
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
                return {"success": False, "status_code": 0, "error": str(e)}

        return {"success": False, "status_code": 0, "error": "未知错误"}

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
        """注册流程请求分发器。special_session_step 仅用于步骤标注，session 仅用于结果回传。"""
        result = await self._make_request(
            method,
            url,
            headers,
            json_data,
            db_session,
            identifier,
        )

        if special_session_step and session is not None:
            enriched = dict(result)
            enriched.setdefault("session", session)
            return enriched

        return result

    async def register(
        self,
        register_input: Dict[str, Any],
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """注册新账号（占位实现）"""
        runtime_context_result = self._build_runtime_context(register_input, identifier)
        if not runtime_context_result.get("success"):
            return runtime_context_result

        runtime_context = runtime_context_result.get("data", {})
        runtime_identifier = runtime_context.get("identifier", identifier)

        pipeline_result = await self._run_register_pipeline(
            {
                "register_input": runtime_context.get("register_input", {}),
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

        data = dict(pipeline_result.get("data", {}))
        if "identifier" not in data:
            data["identifier"] = runtime_identifier

        return self._success_result(data)

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
        email = str(register_input.get("fixed_email") or "").strip()

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
                "auth_flow_failed",
            )

        return self._success_result(result.get("data", {}))

    async def _submit_signup(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """提交注册信息"""
        register_input = ctx.get("register_input", {})
        body = {
            "username": str(register_input.get("fixed_email") or "").strip(),
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
                "signup_failed",
            )

        return self._success_result(result.get("data", {}))

    async def _send_otp_with_fallback(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """发送 OTP，密码免注册禁用时走 fallback"""
        register_input = ctx.get("register_input", {})
        email = str(register_input.get("fixed_email") or "").strip()

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
                "otp_send_failed",
            )

        signup_result = await self._submit_signup(ctx)
        if not signup_result.get("success"):
            return signup_result

        fallback_data = dict(signup_result.get("data", {}))
        fallback_data["used_fallback"] = True
        return self._success_result(fallback_data)

    async def _poll_and_validate_otp(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """轮询并校验 OTP"""
        register_input = ctx.get("register_input", {})
        email = str(register_input.get("fixed_email") or "").strip()

        result = await self._make_register_request(
            "POST",
            "https://auth.openai.com/api/otp/validate",
            self._build_auth_headers(),
            {
                "username": email,
                "otp_code": str(ctx.get("otp_code") or ""),
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
                "otp_validate_failed",
            )

        return self._success_result(result.get("data", {}))

    async def _create_account(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """创建账号"""
        register_input = ctx.get("register_input", {})
        email = str(register_input.get("fixed_email") or "").strip()

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
                "create_account_failed",
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
                "auth_flow_failed",
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

        return self._success_result({"identifier": ctx.get("identifier", "default")})

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
