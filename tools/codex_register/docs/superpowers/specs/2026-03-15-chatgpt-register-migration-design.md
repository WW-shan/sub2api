# ChatGPTService 注册迁移设计（弃用 codex_register_service）

## 背景与目标

当前仓库中注册流程主要位于 `codex_register_service.py`，Team/账户 API 封装主要位于 `chatgpt.py` 的 `ChatGPTService`。目标是将“中间注册部分”完全迁移到 `ChatGPTService` 风格中，并彻底弃用/删除 `codex_register_service.py`。

本设计仅覆盖**注册能力迁移**，不包含 Team 动作编排。

## 已确认约束

1. 硬弃用：`codex_register_service.py` 最终删除，不保留兼容壳。
2. 只保留注册入口，不做 `register_and_setup_team` 编排。
3. 返回格式遵循现有 `ChatGPTService` 统一返回风格（`success/status_code/data/error`），旧字符串 JSON 返回格式彻底废弃。
5. 注册完成后必须继续复用同一 `ChatGPTService` 会话体系调用 Team 能力，符合现有 `chatgpt.py` 使用方式。

## 现状（关键参考）

- 现有 HTTP 统一封装：`chatgpt.py:64-165`
- 现有 Team API 方法风格：`chatgpt.py:167-332`
- 现有注册主流程（待迁移来源）：`codex_register_service.py:697-862`
- OAuth/回调辅助函数（可复用语义）：`codex_register_service.py:623-688`

## 目标架构

在 `chatgpt.py` 的 `ChatGPTService` 内新增注册域方法，形成“单服务、统一风格”的注册实现：

- 公共入口：`register(register_input, db_session=None, identifier="default")`
- 注册后兼容要求：注册成功后必须可在同一 `ChatGPTService` 实例内无缝调用现有 Team 管理方法（`send_invite/get_members/get_invites/delete_invite/delete_member/...`），不允许额外登录流程。
- 私有步骤：
  - `_build_runtime_context`
  - `_check_network_and_region`
  - `_prepare_identity`
  - `_start_auth_flow`
  - `_submit_signup`
  - `_send_otp_with_fallback`
  - `_poll_and_validate_otp`
  - `_create_account`
  - `_exchange_tokens`（注册完成后获取 token）
  - `_enrich_account_context`
  - `_finalize_registration_result`

新增“结构化复用层”验收标准（MUST）：
- 注册链路请求头必须由 `_build_browser_base_headers` / `_build_auth_headers` / `_build_sentinel_headers` 组合产出；
- 默认请求出口必须是 `_make_request`；
- 仅 sentinel/signup/otp/create_account 这类必须保持同 session 的步骤允许最小扩展，且仍需保持统一返回结构。



## 接口契约

### 输入：`register_input`

最小字段（逻辑上必需）:
- `mail_worker_base_url`
- `mail_worker_token`

条件必填：
- 当 `fixed_email` 为空时，`mail_domain` 必填。

可选字段:
- `proxy`
- `fixed_email`
- `fixed_password`
- `register_http_timeout`（默认 15）
- `mail_poll_seconds`（默认 3）
- `mail_poll_max_attempts`（默认 40）

非法值处理：
- `register_http_timeout <= 0`、`mail_poll_seconds <= 0`、`mail_poll_max_attempts <= 0` 统一视为 `input_invalid`。

### 输出（统一固定顶层字段）

成功：

```python
{
  "success": True,
  "status_code": 200,
  "data": {
    "email": str,
    "identifier": str,
    "account_id": str,
    "access_token": str,
    "refresh_token": str,
    "id_token": str,
    "session_token": str | "",
    "expires_at": str,
    "plan_type": str | "",
    "organization_id": str | "",
    "workspace_id": str | ""
  },
  "error": None,
  "error_code": None
}
```

失败：

```python
{
  "success": False,
  "status_code": int,
  "data": None,
  "error": str,
  "error_code": str
}
```

`error_code` 在失败时必填，成功时固定为 `None`。

`identifier` 规则：
- 调用方提供有效 `identifier` 时优先使用该值；
- 否则按现有 `chatgpt.py` 约定自动推导（优先 `acc_<account_id>`，其次邮箱）；
- 后续 Team 方法建议显式传回该 `identifier`，确保会话稳定复用。

## Token 产出路径（必须明确）

旧 `run()` 可见主链路只到 `create_account`（`codex_register_service.py:847-862`），因此迁移后必须显式补齐 token 获取步骤：

1. 使用现有 OAuth 相关能力完成 code→token exchange（迁移 `submit_callback_url` 语义，来源 `codex_register_service.py:643-688`）。
2. 产出 `access_token/refresh_token/id_token/expires_at`。
3. 若可用，补充 `session_token`（没有则置空字符串）。
4. 若 token 解析失败，返回 `token_finalize_failed`。

## 需迁移能力清单（删除旧文件前）

在删除 `codex_register_service.py` 前，需将以下能力迁移到 `chatgpt.py` 私有方法或同文件工具函数：

- OAuth URL 构造（`generate_oauth_url` 语义）
- callback URL 解析（`_parse_callback_url` 语义）
- code→token 交换（`_post_form` + `submit_callback_url` 语义）
- token claims 解析（`_jwt_claims_no_verify` 语义）
- 会话 access token 提取（`extract_session_access_token` 语义）
- 注册辅助能力（邮箱/验证码轮询、回退分支判断）

不要求函数名保持一致，但要求语义保持一致。

## 数据流

1. 校验 `register_input`；构建上下文与默认值。
2. 网络连通性与地域检查（延续旧语义）。
3. 生成/获取邮箱、dev token、密码。
4. 启动授权流程并获取必要 challenge/sentinel 上下文。
5. 提交 signup。
6. 发送 OTP；若 `passwordless_signup_disabled`，走备用注册+OTP 发送。
7. 拉取并校验 OTP。
8. 执行 `create_account`。
9. 执行 token 交换并形成结构化凭据。
10. 生成并固化 `identifier` 到返回体，确保后续 Team 调用可直接复用。
11. best-effort 补充 `plan_type/organization_id/workspace_id`，失败不影响注册成功。
12. 输出统一结果。

## 反爬与会话不可省略条件

- Sentinel 请求与后续 signup/otp/create_account 必须在同一会话上下文（同 cookie jar）完成。
- `oai-did` 与 sentinel token 的绑定关系必须保持，不能跨 session 拼接。
- 注册成功后不清理当前 `identifier` 会话，必须可立即用于 Team API 调用。


## 错误模型与映射规则

标准 error_code 集合（首版）：
- `input_invalid`
- `network_error`
- `network_timeout`
- `identity_prepare_failed`
- `auth_flow_failed`
- `signup_failed`
- `otp_send_failed`
- `otp_validate_failed`
- `create_account_failed`
- `token_finalize_failed`
- `unknown_error`

映射规则：
- 超时异常 → `network_timeout`，`status_code=0`
- 网络/连接异常 → `network_error`，`status_code=0`
- signup 接口非 200 → `signup_failed`，`status_code=<http>`
- otp 发送非 200 且不属于 fallback 条件 → `otp_send_failed`，`status_code=<http>`
- otp 校验非 200 → `otp_validate_failed`，`status_code=<http>`
- create_account 非 200 → `create_account_failed`，`status_code=<http>`
- token 交换/解析失败 → `token_finalize_failed`，`status_code=0 或 <http>`
- 未命中以上分类 → `unknown_error`

说明：`passwordless_signup_disabled` 作为分支原因记录，不直接作为最终失败码。

## proxy 与 async 约定

- 方法保持 `async`，与现有 `ChatGPTService` 模型一致。
- proxy 优先级：`register_input.proxy` > settings_service（若有）> 无代理。

## 字段补充策略（仅注册边界）

- `plan_type/organization_id/workspace_id` 属于增强信息，采用 best-effort 填充。
- 若无法获取这三个字段，不影响 `success=True`，对应字段返回空字符串。

## 文件变更计划

1. 修改 `chatgpt.py`
   - 新增 `register` 公共方法。
   - 新增注册相关私有方法。
   - 保持原 Team API 能力不变。

2. 删除 `codex_register_service.py`
   - 不保留业务逻辑和兼容调用。

3. 更新测试文件（新增或替换现有测试）
   - 注册成功主路径
   - passwordless fallback 路径
   - OTP 发送失败
   - OTP 校验失败
   - create_account 失败
   - token 交换失败映射
   - 统一返回结构检查（成功/失败字段集合固定）
   - 删除旧文件后导入与调用路径检查
   - 结构化复用约束测试：关键步骤必须调用 `_build_browser_base_headers` / `_build_auth_headers` / `_build_sentinel_headers` 产出 headers
   - 默认请求出口约束测试：非同会话特例步骤必须走 `_make_request`
   - 同会话约束测试：sentinel → signup → otp → create_account 全链路复用同一 session/cookie jar

## 兼容性与影响

- **破坏性变更**：旧 `run(proxy) -> Optional[str]` 风格彻底移除。
- 所有调用方必须切换到 `ChatGPTService.register(register_input)` 并按统一返回 dict 处理。

## 验证策略


- 单元测试：步骤级异常映射与分支覆盖。
- 集成测试（mock 网络）：全链路成功与关键失败场景。
- 语法检查：`python -m py_compile` 覆盖变更文件。
- 结构化复用守卫检查：新增静态检查/审查规则，禁止在注册实现中内联复制旧文件的静态 headers 大字典。

## 不在范围内

- Team 编排（`register_and_setup_team`）
- 数据库模型迁移
- 非注册相关 API 重构

## 风险与缓解

1. 旧流程迁移时语义漂移
   - 缓解：按步骤一一映射，并用旧流程关键分支写回归测试。
2. 外部接口波动导致注册失败率上升
   - 缓解：统一错误码与日志字段，便于快速定位。
3. 删除旧文件后的调用方遗漏
   - 缓解：全仓 grep 检查 + 导入测试。
