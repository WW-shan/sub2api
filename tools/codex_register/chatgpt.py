"""
ChatGPT API 服务
用于调用 ChatGPT 后端 API,实现 Team 成员管理功能
"""
import asyncio
import base64
import importlib
import json
import logging
import os
import random
import urllib.parse
from urllib.parse import urlparse
from typing import Optional, Dict, Any
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
            register_input["fixed_password"] = f"Cg#{random.randint(1000000, 9999999)}Aa"

        register_input["resolved_email"] = resolved_email

        prepared_ctx = dict(ctx or {})
        prepared_ctx["register_input"] = register_input
        return self._success_result(prepared_ctx)

    def _resolve_step_error_code(self, result: Dict[str, Any], default_error_code: str) -> str:
        """步骤错误码映射：保留网络层错误码，不重写"""
        error_code = str((result or {}).get("error_code") or "").strip()
        if error_code in {"network_timeout", "network_error"}:
            return error_code
        return default_error_code

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
        """通过 mail worker 轮询拉取 OTP"""
        register_input = dict((ctx or {}).get("register_input") or {})
        email = self._resolve_register_email(register_input)
        mail_worker_base_url = str(register_input.get("mail_worker_base_url") or "").strip().rstrip("/")
        mail_worker_token = str(register_input.get("mail_worker_token") or "").strip()

        if not mail_worker_base_url or not mail_worker_token:
            return self._error_result(400, "mail worker config missing", "input_invalid")

        poll_seconds_raw = register_input.get("mail_poll_seconds", 3)
        poll_attempts_raw = register_input.get("mail_poll_max_attempts", 40)
        try:
            poll_seconds = float(poll_seconds_raw)
        except (TypeError, ValueError):
            poll_seconds = 3.0
        try:
            poll_max_attempts = int(poll_attempts_raw)
        except (TypeError, ValueError):
            poll_max_attempts = 40

        poll_seconds = max(0.0, poll_seconds)
        poll_max_attempts = max(1, poll_max_attempts)

        request_url = f"{mail_worker_base_url}/v1/code?email={urllib.parse.quote(email)}"
        request_headers = {
            "Authorization": f"Bearer {mail_worker_token}",
            "Accept": "application/json",
        }

        last_status_code = 404
        last_error = "otp code not found"

        for attempt in range(poll_max_attempts):
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
            resolved_error_code = self._resolve_step_error_code(result, "otp_validate_failed")

            if not result.get("success") or status_code >= 300:
                if resolved_error_code in {"network_timeout", "network_error"}:
                    return self._error_result(
                        status_code,
                        result.get("error", "mail worker otp fetch failed"),
                        resolved_error_code,
                    )

                last_status_code = status_code or 404
                last_error = result.get("error", "mail worker otp fetch failed")
            else:
                otp_code = self._extract_otp_code_from_payload(result.get("data", {}))
                if otp_code:
                    return self._success_result({"otp_code": otp_code})
                last_status_code = 404
                last_error = "otp code not found"

            if attempt < poll_max_attempts - 1 and poll_seconds > 0:
                await asyncio.sleep(poll_seconds)

        return self._error_result(last_status_code, last_error, "otp_validate_failed")

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

    async def _visit_homepage(
        self,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """访问主页并获取初始 cookies"""
        url = "https://chatgpt.com/"
        headers = self._build_browser_base_headers(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        
        try:
            result = await self._make_request(
                "GET", url, headers, db_session=db_session, identifier=identifier, proxy=proxy
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if not result.get("success"):
                error_msg = result.get("error", "unable to fetch homepage")
                logger.warning(f"[{identifier}] 主页访问失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, "homepage_visit_failed")
            
            logger.info(f"[{identifier}] 主页访问成功")
            return self._success_result({})
        except Exception as e:
            logger.error(f"[{identifier}] 主页访问异常: {e}")
            return self._error_result(0, f"homepage visit exception: {str(e)}", "homepage_visit_exception")

    async def _get_csrf_token(
        self,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取 CSRF token"""
        url = "https://chatgpt.com/api/auth/csrf"
        headers = self._build_browser_base_headers(
            {"Accept": "application/json", "Referer": "https://chatgpt.com/"}
        )
        
        try:
            result = await self._make_request(
                "GET", url, headers, db_session=db_session, identifier=identifier, proxy=proxy
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if not result.get("success"):
                error_msg = result.get("error", "csrf token fetch failed")
                logger.warning(f"[{identifier}] CSRF token 获取失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, "csrf_token_failed")
            
            data = result.get("data", {})
            if not isinstance(data, dict):
                logger.warning(f"[{identifier}] CSRF响应数据格式异常: {type(data)}")
                return self._error_result(400, "csrf response format invalid", "csrf_token_format_invalid")
            
            # 容错处理：尝试多种可能的字段名
            csrf_token = str(data.get("csrfToken") or data.get("csrf_token") or "").strip()
            if not csrf_token:
                logger.warning(f"[{identifier}] CSRF token 在响应中未找到")
                return self._error_result(400, "csrf token not found in response", "csrf_token_not_found")
            
            logger.info(f"[{identifier}] CSRF token 已获取")
            return self._success_result({"csrf_token": csrf_token})
        except Exception as e:
            logger.error(f"[{identifier}] CSRF token 获取异常: {e}")
            return self._error_result(0, f"csrf token exception: {str(e)}", "csrf_token_exception")

    async def _signin_with_email(
        self,
        email: str,
        csrf_token: str,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """登录/签名，获取授权 URL"""
        url = "https://chatgpt.com/api/auth/signin/openai"
        # 按照参考文件的方式生成更大的随机数
        device_id = str(random.randint(10**15, 10**16 - 1))
        auth_session_logging_id = str(random.randint(10**15, 10**16 - 1))
        
        params = {
            "prompt": "login",
            "ext-oai-did": device_id,
            "auth_session_logging_id": auth_session_logging_id,
            "screen_hint": "login_or_signup",
            "login_hint": email,
        }
        
        form_data = {
            "callbackUrl": "https://chatgpt.com/",
            "csrfToken": csrf_token,
            "json": "true",
        }
        
        headers = self._build_browser_base_headers(
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "Referer": "https://chatgpt.com/",
                "Origin": "https://chatgpt.com",
            }
        )
        
        try:
            result = await self._make_request(
                "POST",
                url + "?" + urllib.parse.urlencode(params),
                headers,
                db_session=db_session,
                identifier=identifier,
                proxy=proxy,
                form_data=form_data,
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if not result.get("success"):
                error_msg = result.get("error", "signin failed")
                logger.warning(f"[{identifier}] 登录失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, "signin_failed")
            
            data = result.get("data", {})
            if not isinstance(data, dict):
                logger.warning(f"[{identifier}] 登录响应格式异常: {type(data)}")
                return self._error_result(400, "signin response format invalid", "signin_format_invalid")
            
            # 容错处理：尝试多种可能的字段名
            authorize_url = str(data.get("url") or data.get("authorize_url") or data.get("auth_url") or "").strip()
            if not authorize_url:
                logger.warning(f"[{identifier}] 授权URL未在登录响应中找到")
                return self._error_result(400, "authorize url not found in signin response", "authorize_url_not_found")
            
            logger.info(f"[{identifier}] 登录成功，已获取授权 URL")
            return self._success_result({"authorize_url": authorize_url, "device_id": device_id})
        except Exception as e:
            logger.error(f"[{identifier}] 登录异常: {e}")
            return self._error_result(0, f"signin exception: {str(e)}", "signin_exception")

    async def _authorize_and_redirect(
        self,
        authorize_url: str,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行授权并跟踪重定向"""
        headers = self._build_browser_base_headers(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://chatgpt.com/",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        
        try:
            result = await self._make_request(
                "GET", authorize_url, headers, db_session=db_session, identifier=identifier, proxy=proxy
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if not result.get("success"):
                error_msg = result.get("error", "authorize failed")
                logger.warning(f"[{identifier}] 授权失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, "authorize_failed")
            
            # 容错处理：尝试从响应中提取最终URL
            final_url = authorize_url
            data = result.get("data", {})
            if isinstance(data, dict):
                final_url = str(data.get("final_url") or data.get("url") or authorize_url).strip()
            
            final_path = urlparse(final_url).path if final_url else "/"
            logger.info(f"[{identifier}] 授权完成，最终URL: {final_url}, 路径: {final_path}")
            return self._success_result({"final_url": final_url})
        except Exception as e:
            logger.error(f"[{identifier}] 授权异常: {e}")
            return self._error_result(0, f"authorize exception: {str(e)}", "authorize_exception")

    async def _register_user_with_password(
        self,
        email: str,
        password: str,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """使用邮箱和密码进行用户注册"""
        url = "https://auth.openai.com/api/accounts/user/register"
        
        headers = self._build_auth_headers(
            extra_headers={
                "Referer": "https://auth.openai.com/create-account/password",
                "Origin": "https://auth.openai.com",
            }
        )
        
        json_data = {"username": email, "password": password}
        
        try:
            result = await self._make_register_request(
                "POST",
                url,
                headers,
                json_data,
                db_session=db_session,
                identifier=identifier,
                special_session_step=True,
                proxy=proxy,
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if status_code >= 400:
                error_msg = result.get("error", "register user failed")
                error_code = self._resolve_step_error_code(result, "register_user_failed")
                logger.warning(f"[{identifier}] 用户注册失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, error_code)
            elif status_code >= 300:
                logger.debug(f"[{identifier}] 用户注册返回: {status_code}")
            
            logger.info(f"[{identifier}] 用户注册成功")
            return self._success_result({})
        except Exception as e:
            logger.error(f"[{identifier}] 用户注册异常: {e}")
            return self._error_result(0, f"register user exception: {str(e)}", "register_user_exception")

    async def _send_otp_email(
        self,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """发送 OTP 邮件"""
        url = "https://auth.openai.com/api/accounts/email-otp/send"
        
        headers = self._build_browser_base_headers(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://auth.openai.com/create-account/password",
                "Upgrade-Insecure-Requests": "1",
            },
            origin="https://auth.openai.com",
            referer="https://auth.openai.com/create-account/password",
        )
        
        try:
            result = await self._make_register_request(
                "GET",
                url,
                headers,
                db_session=db_session,
                identifier=identifier,
                special_session_step=True,
                proxy=proxy,
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if status_code >= 300:
                error_msg = result.get("error", "send otp email failed")
                error_code = self._resolve_step_error_code(result, "otp_send_failed")
                logger.warning(f"[{identifier}] 发送OTP邮件失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, error_code)
            
            logger.info(f"[{identifier}] OTP 邮件已发送")
            return self._success_result({})
        except Exception as e:
            logger.error(f"[{identifier}] 发送OTP邮件异常: {e}")
            return self._error_result(0, f"send otp email exception: {str(e)}", "send_otp_email_exception")

    async def _poll_and_validate_otp(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """轮询并校验 OTP"""
        register_input = dict((ctx or {}).get("register_input") or {})
        email = self._resolve_register_email(register_input)

        otp_code = str((ctx or {}).get("otp_code") or "").strip()
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

        return await self._validate_otp_code(
            email,
            otp_code,
            ctx.get("db_session"),
            ctx.get("identifier", "default"),
            proxy=ctx.get("proxy"),
        )

    async def _validate_otp_code(
        self,
        email: str,
        otp_code: str,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """验证 OTP 代码（保留原有的邮箱验证逻辑）"""
        url = "https://auth.openai.com/api/accounts/email-otp/validate"
        
        headers = self._build_auth_headers()
        
        json_data = {"code": otp_code}
        
        try:
            result = await self._make_register_request(
                "POST",
                url,
                headers,
                json_data,
                db_session=db_session,
                identifier=identifier,
                special_session_step=True,
                proxy=proxy,
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if status_code >= 300:
                error_msg = result.get("error", "validate otp failed")
                error_code = self._resolve_step_error_code(result, "otp_validate_failed")
                logger.warning(f"[{identifier}] OTP 验证失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, error_code)
            
            logger.info(f"[{identifier}] OTP 验证成功")
            return self._success_result({})
        except Exception as e:
            logger.error(f"[{identifier}] OTP 验证异常: {e}")
            return self._error_result(0, f"validate otp exception: {str(e)}", "otp_validate_exception")

    async def _create_account_with_info(
        self,
        name: str,
        birthdate: str,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建账号并填写个人信息"""
        url = "https://auth.openai.com/api/accounts/create_account"
        
        headers = self._build_auth_headers(
            extra_headers={
                "Referer": "https://auth.openai.com/about-you",
                "Origin": "https://auth.openai.com",
            }
        )
        
        json_data = {"name": name, "birthdate": birthdate}
        
        try:
            result = await self._make_register_request(
                "POST",
                url,
                headers,
                json_data,
                db_session=db_session,
                identifier=identifier,
                special_session_step=True,
                proxy=proxy,
            )
            
            status_code = int(result.get("status_code", 0) or 0)
            if status_code >= 300:
                error_msg = result.get("error", "create account failed")
                error_code = self._resolve_step_error_code(result, "create_account_failed")
                logger.warning(f"[{identifier}] 账号创建失败 ({status_code}): {error_msg}")
                return self._error_result(status_code, error_msg, error_code)
            
            data = result.get("data", {})
            callback_url = str(data.get("continue_url") or data.get("url") or data.get("redirect_url") or "").strip()
            
            logger.info(f"[{identifier}] 账号创建成功，回调URL: {callback_url}")
            return self._success_result({"callback_url": callback_url})
        except Exception as e:
            logger.error(f"[{identifier}] 创建账号异常: {e}")
            return self._error_result(0, f"create account exception: {str(e)}", "create_account_exception")

    async def _execute_callback(
        self,
        callback_url: str,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行回调 URL"""
        if not callback_url:
            logger.debug(f"[{identifier}] 无回调 URL，跳过")
            return self._success_result({})

        headers = self._build_browser_base_headers(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
            }
        )

        try:
            result = await self._make_request(
                "GET", callback_url, headers, db_session=db_session, identifier=identifier, proxy=proxy
            )

            status_code = int(result.get("status_code", 0) or 0)
            # 即使状态码不是200，回调仍可能成功
            logger.info(f"[{identifier}] 回调已执行 (状态: {status_code})")
            return self._success_result({})
        except Exception as e:
            logger.error(f"[{identifier}] 执行回调异常: {e}")
            # 回调失败不影响主流程
            return self._error_result(0, f"callback exception: {str(e)}", "callback_exception")

    def _decode_oai_client_auth_session_cookie(self, session: AsyncSession) -> Dict[str, Any]:
        cookies = getattr(session, "cookies", None)
        if cookies is None:
            return {}

        for cookie in cookies:
            if getattr(cookie, "name", "") != "oai-client-auth-session":
                continue

            raw_value = str(getattr(cookie, "value", "") or "")
            if not raw_value:
                continue

            first_part = raw_value.split(".")[0] if "." in raw_value else raw_value
            padding = 4 - (len(first_part) % 4)
            if padding != 4:
                first_part += "=" * padding

            try:
                decoded = base64.urlsafe_b64decode(first_part)
                parsed = json.loads(decoded.decode("utf-8"))
            except Exception:
                continue

            if isinstance(parsed, dict):
                return parsed

        return {}

    async def _collect_register_session_tokens(
        self,
        db_session: Optional[DBAsyncSession],
        identifier: str,
        proxy: Optional[str] = None,
        callback_url: str = "",
        oauth_client_id: str = "",
    ) -> Dict[str, Any]:
        """从注册会话中提取 account/token 字段用于持久化"""
        headers = self._build_browser_base_headers(
            {
                "Accept": "application/json",
                "Referer": "https://chatgpt.com/",
            }
        )

        result = await self._make_request(
            "GET",
            "https://chatgpt.com/api/auth/session",
            headers,
            db_session=db_session,
            identifier=identifier,
            proxy=proxy,
        )
        if not result.get("success"):
            return {}

        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        access_token = str(data.get("accessToken") or "").strip()
        refresh_token = str(data.get("refreshToken") or "").strip()
        session_token = str(data.get("sessionToken") or "").strip()

        account_id = str(data.get("currentAccountId") or "").strip()
        if not account_id:
            accounts = data.get("accounts")
            if isinstance(accounts, dict) and accounts:
                account_id = str(next(iter(accounts.keys())) or "").strip()

        id_token = ""

        def _extract_code_from_url(raw_url: str) -> str:
            parsed_url = str(raw_url or "").strip()
            if not parsed_url or "code=" not in parsed_url:
                return ""
            try:
                query = str(urlparse(parsed_url).query or "")
                return str(urllib.parse.parse_qs(query).get("code", [""])[0] or "").strip()
            except Exception:
                return ""

        callback_code = _extract_code_from_url(callback_url)

        session: Optional[AsyncSession] = None
        auth_session_payload: Dict[str, Any] = {}

        if callback_code or not refresh_token:
            session = await self._get_session(db_session, identifier, proxy=proxy)
            decoded_payload = self._decode_oai_client_auth_session_cookie(session)
            if isinstance(decoded_payload, dict):
                auth_session_payload = decoded_payload

        if not callback_code and not refresh_token and session is not None:
            workspaces = auth_session_payload.get("workspaces") if isinstance(auth_session_payload, dict) else []
            workspace = workspaces[0] if isinstance(workspaces, list) and workspaces else {}
            workspace_id = str((workspace or {}).get("id") or "").strip() if isinstance(workspace, dict) else ""

            if workspace_id:
                workspace_select_result = await self._make_register_request(
                    "POST",
                    "https://auth.openai.com/api/accounts/workspace/select",
                    self._build_auth_headers(),
                    json_data={"workspace_id": workspace_id},
                    db_session=db_session,
                    identifier=identifier,
                    special_session_step=True,
                    session=session,
                    proxy=proxy,
                )
                if workspace_select_result.get("success"):
                    workspace_data = workspace_select_result.get("data")
                    if isinstance(workspace_data, dict):
                        callback_code = _extract_code_from_url(
                            str(workspace_data.get("continue_url") or workspace_data.get("url") or "")
                        )

        if callback_code:
            if session is None:
                session = await self._get_session(db_session, identifier, proxy=proxy)
                decoded_payload = self._decode_oai_client_auth_session_cookie(session)
                if isinstance(decoded_payload, dict):
                    auth_session_payload = decoded_payload

            code_verifier = ""
            if isinstance(auth_session_payload, dict):
                code_verifier = str(auth_session_payload.get("code_verifier") or "").strip()

                if not code_verifier:
                    workspaces = auth_session_payload.get("workspaces")
                    workspace = workspaces[0] if isinstance(workspaces, list) and workspaces else {}
                    if isinstance(workspace, dict):
                        code_verifier = str(workspace.get("code_verifier") or "").strip()

            token_form_data: Dict[str, Any] = {
                "grant_type": "authorization_code",
                "code": callback_code,
                "redirect_uri": "https://chatgpt.com/api/auth/callback/openai",
                "client_id": oauth_client_id or "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",
            }
            if code_verifier:
                token_form_data["code_verifier"] = code_verifier

            token_exchange_result = await self._make_register_request(
                "POST",
                "https://auth.openai.com/oauth/token",
                {"Content-Type": "application/x-www-form-urlencoded"},
                db_session=db_session,
                identifier=identifier,
                special_session_step=True,
                session=session,
                proxy=proxy,
                form_data=token_form_data,
            )
            if token_exchange_result.get("success"):
                token_data = token_exchange_result.get("data") or {}
                oauth_access_token = str(token_data.get("access_token") or token_data.get("accessToken") or "").strip()
                oauth_refresh_token = str(token_data.get("refresh_token") or token_data.get("refreshToken") or "").strip()
                oauth_id_token = str(token_data.get("id_token") or token_data.get("idToken") or "").strip()
                if oauth_access_token:
                    access_token = oauth_access_token
                if oauth_refresh_token:
                    refresh_token = oauth_refresh_token
                if oauth_id_token:
                    id_token = oauth_id_token

        if access_token:
            decoded = self.jwt_parser.decode_token(access_token) or {}
            auth_payload = decoded.get("https://api.openai.com/auth") if isinstance(decoded, dict) else {}
            if isinstance(auth_payload, dict):
                jwt_account_id = str(auth_payload.get("chatgpt_account_id") or auth_payload.get("organization_id") or "").strip()
                if jwt_account_id:
                    account_id = jwt_account_id

        payload: Dict[str, Any] = {}
        if account_id:
            payload["account_id"] = account_id
        if access_token:
            payload["access_token"] = access_token
        if refresh_token:
            payload["refresh_token"] = refresh_token
        if session_token:
            payload["session_token"] = session_token
        if id_token:
            payload["id_token"] = id_token
        return payload

    def _build_register_compat_payload(
        self,
        *,
        email: str,
        identifier: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建兼容 codex_register_service / Team API 的注册成功载荷"""
        payload = {
            "email": str(email or "").strip(),
            "identifier": str(identifier or "default").strip() or "default",
            "account_id": "",
            "access_token": "",
            "refresh_token": "",
            "id_token": "",
            "session_token": "",
            "expires_at": "",
            "plan_type": "",
            "organization_id": "",
            "workspace_id": "",
            "status": "completed",
        }

        if isinstance(extra, dict):
            for key in (
                "account_id",
                "access_token",
                "refresh_token",
                "id_token",
                "session_token",
                "expires_at",
                "plan_type",
                "organization_id",
                "workspace_id",
                "status",
            ):
                if key not in extra:
                    continue
                value = extra.get(key)
                payload[key] = str(value or "").strip() if isinstance(value, str) else value

        return payload

    def _random_profile_name(self) -> str:
        first_names = [
            "James", "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia",
            "Lucas", "Mia", "Mason", "Isabella", "Logan", "Charlotte", "Alexander",
            "Amelia", "Benjamin", "Harper", "William", "Evelyn", "Henry", "Abigail",
            "Sebastian", "Emily", "Jack", "Elizabeth",
        ]
        last_names = [
            "Smith", "Johnson", "Brown", "Davis", "Wilson", "Moore", "Taylor",
            "Clark", "Hall", "Young", "Anderson", "Thomas", "Jackson", "White",
            "Harris", "Martin", "Thompson", "Garcia", "Robinson", "Lewis",
            "Walker", "Allen", "King", "Wright", "Scott", "Green",
        ]
        return f"{random.choice(first_names)} {random.choice(last_names)}"

    async def register(
        self,
        *,
        db_session: Optional[DBAsyncSession] = None,
        identifier: str = "default"
    ) -> Dict[str, Any]:
        """
        完整注册流程 - 采用参考文件逻辑，保留邮箱和验证码原有处理
        
        步骤:
        1. 初始化运行时上下文
        2. 访问主页
        3. 获取 CSRF token
        4. 登录/签名
        5. 授权和重定向
        6. 根据最终URL路径确定流程分支
        7. 执行对应的注册分支
        8. 验证并完成注册
        """
        try:
            # 步骤 0: 初始化运行时上下文 (验证必填配置、解析邮箱和验证码配置)
            runtime_context_result = self._build_runtime_context(identifier)
            if not runtime_context_result.get("success"):
                logger.warning(f"[{identifier}] 上下文初始化失败: {runtime_context_result.get('error')}")
                return runtime_context_result

            runtime_context = runtime_context_result.get("data", {})
            runtime_identifier = runtime_context.get("identifier", identifier)
            register_input = runtime_context.get("register_input", {})
            
            logger.info(f"[{runtime_identifier}] 注册流程启动")

            # 解析代理
            resolved_proxy = await self._resolve_register_proxy(register_input, db_session)
            if resolved_proxy:
                register_input["resolved_proxy"] = resolved_proxy
                logger.debug(f"[{runtime_identifier}] 代理已配置")

            # 步骤 1: 访问主页
            visit_result = await self._visit_homepage(db_session, runtime_identifier, resolved_proxy)
            if not visit_result.get("success"):
                return visit_result

            await asyncio.sleep(random.uniform(0.3, 0.8))

            # 步骤 2: 获取 CSRF token
            csrf_result = await self._get_csrf_token(db_session, runtime_identifier, resolved_proxy)
            if not csrf_result.get("success"):
                return csrf_result

            csrf_token = csrf_result.get("data", {}).get("csrf_token", "")
            
            await asyncio.sleep(random.uniform(0.2, 0.5))

            # 准备邮箱和密码 (保留原有逻辑)
            identity_result = self._prepare_identity(
                {
                    "register_input": register_input,
                    "db_session": db_session,
                    "identifier": runtime_identifier,
                }
            )
            if not identity_result.get("success"):
                return identity_result

            identity_ctx = identity_result.get("data", {})
            register_input = identity_ctx.get("register_input", register_input)
            email = self._resolve_register_email(register_input)
            password = str(register_input.get("fixed_password") or "").strip()

            logger.info(f"[{runtime_identifier}] 邮箱已准备: {email}")

            # 步骤 3: 登录/签名
            signin_result = await self._signin_with_email(
                email, csrf_token, db_session, runtime_identifier, resolved_proxy
            )
            if not signin_result.get("success"):
                return signin_result

            authorize_url = signin_result.get("data", {}).get("authorize_url", "")
            authorize_client_id = ""
            if authorize_url:
                try:
                    parsed_qs = urllib.parse.parse_qs(urlparse(authorize_url).query)
                    authorize_client_id = str((parsed_qs.get("client_id") or [""])[0] or "").strip()
                except Exception:
                    authorize_client_id = ""
            
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # 步骤 4: 授权和重定向
            authorize_result = await self._authorize_and_redirect(
                authorize_url, db_session, runtime_identifier, resolved_proxy
            )
            if not authorize_result.get("success"):
                return authorize_result

            final_url = authorize_result.get("data", {}).get("final_url", "")
            final_path = urlparse(final_url).path
            
            await asyncio.sleep(random.uniform(0.3, 0.8))

            logger.info(f"[{runtime_identifier}] 授权完成，路径: {final_path}")

            # 步骤 5: 根据最终URL路径确定流程分支
            need_otp = False
            
            if "create-account/password" in final_path:
                logger.info(f"[{runtime_identifier}] 全新注册流程")
                
                # 执行用户注册
                await asyncio.sleep(random.uniform(0.5, 1.0))
                register_user_result = await self._register_user_with_password(
                    email, password, db_session, runtime_identifier, resolved_proxy
                )
                if not register_user_result.get("success"):
                    return register_user_result
                
                await asyncio.sleep(random.uniform(0.3, 0.8))
                
                # 发送 OTP
                send_otp_result = await self._send_otp_email(
                    db_session, runtime_identifier, resolved_proxy
                )
                if not send_otp_result.get("success"):
                    return send_otp_result
                
                need_otp = True
                
            elif "email-verification" in final_path or "email-otp" in final_path:
                logger.info(f"[{runtime_identifier}] 跳到 OTP 验证阶段")
                need_otp = True
                
            elif "about-you" in final_path:
                logger.info(f"[{runtime_identifier}] 跳到填写信息阶段")

                name = self._random_profile_name()
                birthdate = f"{random.randint(1990, 2000)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"

                await asyncio.sleep(random.uniform(0.5, 1.0))
                create_result = await self._create_account_with_info(
                    name, birthdate, db_session, runtime_identifier, resolved_proxy
                )
                if not create_result.get("success"):
                    return create_result

                callback_url = create_result.get("data", {}).get("callback_url", "")

                await asyncio.sleep(random.uniform(0.3, 0.5))
                await self._execute_callback(callback_url, db_session, runtime_identifier, resolved_proxy)
                session_tokens = await self._collect_register_session_tokens(
                    db_session,
                    runtime_identifier,
                    resolved_proxy,
                    callback_url,
                    authorize_client_id,
                )

                return self._success_result(
                    self._build_register_compat_payload(
                        email=email,
                        identifier=runtime_identifier,
                        extra=session_tokens,
                    )
                )

            elif "callback-complete" in final_path:
                logger.info(f"[{runtime_identifier}] 回调完成信号已确认，注册短路完成")

                callback_url = final_url
                session_tokens = await self._collect_register_session_tokens(
                    db_session,
                    runtime_identifier,
                    resolved_proxy,
                    callback_url,
                    authorize_client_id,
                )

                return self._success_result(
                    self._build_register_compat_payload(
                        email=email,
                        identifier=runtime_identifier,
                        extra=session_tokens,
                    )
                )
            else:
                logger.warning(f"[{runtime_identifier}] 未知路径: {final_url}，执行完整流程")

                # 执行完整流程
                await asyncio.sleep(random.uniform(0.5, 1.0))
                register_user_result = await self._register_user_with_password(
                    email, password, db_session, runtime_identifier, resolved_proxy
                )
                if not register_user_result.get("success"):
                    return register_user_result

                await asyncio.sleep(random.uniform(0.3, 0.8))
                send_otp_result = await self._send_otp_email(db_session, runtime_identifier, resolved_proxy)
                if not send_otp_result.get("success"):
                    return send_otp_result
                need_otp = True

            # 步骤 6: 验证 OTP (保留原有邮箱和验证码逻辑)
            if need_otp:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                
                otp_result = await self._poll_and_validate_otp(
                    {
                        "register_input": register_input,
                        "db_session": db_session,
                        "identifier": runtime_identifier,
                    }
                )
                if not otp_result.get("success"):
                    return otp_result

            # 步骤 7: 创建账号
            name = self._random_profile_name()
            birthdate = f"{random.randint(1990, 2000)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            create_result = await self._create_account_with_info(
                name, birthdate, db_session, runtime_identifier, resolved_proxy
            )
            if not create_result.get("success"):
                return create_result
            
            callback_url = create_result.get("data", {}).get("callback_url", "")

            # 步骤 8: 执行回调
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await self._execute_callback(callback_url, db_session, runtime_identifier, resolved_proxy)
            session_tokens = await self._collect_register_session_tokens(
                db_session,
                runtime_identifier,
                resolved_proxy,
                callback_url,
                authorize_client_id,
            )

            logger.info(f"[{runtime_identifier}] 注册流程完成")
            return self._success_result(
                self._build_register_compat_payload(
                    email=email,
                    identifier=runtime_identifier,
                    extra=session_tokens,
                )
            )

        except Exception as exc:
            logger.exception(f"[{identifier}] 注册流程异常: {exc}")
            return self._error_result(
                500,
                f"registration exception: {str(exc)}",
                "registration_exception",
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
