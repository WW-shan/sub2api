# ChatGPT register 当前流程补足与兼容设计（删除新流水线）

## 背景

用户明确要求：

1. `register` 以当前实现流程为准，不切换到新流水线。
2. 兼容过去（输入/返回/行为都要兼容）。
3. 删除“新”的注册流水线实现，避免双轨冲突。
4. 最关键验收：`register` 成功后应可立即继续执行 `D:\Code\sub2api\tools\codex_register\codex_register_service.py` 中后续 Team 管理流程（如 `get_members`/`send_invite`），且不要求重新登录。

## 目标

- 保留 `ChatGPTService.register(...)` 当前主流程与分支策略。
- 修复当前主流程中会影响稳定性的关键缺口。
- 删除未接入或重复的“新流水线”函数，收敛为单一真流程。
- 保证注册结果直接可用于 Team API，且与会话隔离模型不冲突。

## 非目标

- 不重写 `register` 为全新架构。
- 不修改 `codex_register_service.py` 的编排语义。
- 不新增与当前需求无关的抽象层。

## 兼容策略

### 1) 输入兼容

维持现有 `register(*, db_session=None, identifier="default")` 调用方式。

运行时配置继续从环境变量读取（`_build_runtime_context`），不引入新必填参数。

### 2) 输出兼容

维持统一返回壳：

- 成功：`success/status_code=200/data/error=None/error_code=None`
- 失败：`success=False/status_code/data=None/error/error_code`

并确保成功时 `data` 至少稳定包含 Team 流程衔接所需字段：

- `email`
- `identifier`
- `account_id`
- `access_token`
- `refresh_token`
- `id_token`
- `session_token`
- `expires_at`
- `plan_type`
- `organization_id`
- `workspace_id`

### 3) 行为兼容

保留当前分支判断骨架（`create-account/password`、`email-verification`、`about-you`、`callback`）。

对当前逻辑只做“补足与收敛”，不做策略翻新。

## 方案对比

### 方案 A（采用）

- 保留当前 `register` 主流程。
- 在现有流程内补足缺口（错误处理、OTP 实轮询、成功判定收紧）。
- 删除未使用的新流水线函数。

优点：风险最低、符合用户“当前流程优先”的要求；对调用方最友好。

### 方案 B（不采用）

让 `register` 调新流水线并做兼容适配。

缺点：违背“新的删除”；迁移风险更高。

### 方案 C（不采用）

大幅回滚并重建注册逻辑。

缺点：改动过大、回归成本高。

## 详细设计

### A. register 主流程补足（不改主形态）

1. **修复未知分支漏判返回值**
   - 在 fallback 分支中，`_register_user_with_password` 与 `_send_otp_email` 调用后必须检查 `success`。
   - 任一步骤失败立即返回错误，防止“假继续”。

2. **收紧完成态判断**
   - 调整 `"chatgpt.com" in final_url` 这类宽匹配条件。
   - 仅在明确回调完成或已到预期终态路径时判定 `completed`。

3. **OTP 真轮询**
   - `_poll_otp_from_mail_worker` 按 `mail_poll_seconds` 与 `mail_poll_max_attempts` 执行循环拉取。
   - 轮询期间允许 404/空码继续重试；达到上限后返回 `otp_validate_failed`。
   - 保留网络错误映射（`network_timeout/network_error`）。

### B. Team 流程衔接保障

1. **identifier 稳定规则**
   - 优先使用调用方显式 `identifier`（如 `workflow_id`）。
   - 否则回退 `acc_<account_id>`，再回退邮箱。
   - 将最终 `identifier` 回填到返回 `data`，供后续 Team API 复用。

2. **会话与代理一致性**
   - 保留 `_get_session(identifier, proxy)` 缓存策略。
   - 注册阶段解析出的代理在主流程内持续复用，避免后续 Team API 上下文漂移。

3. **注册即产出 Team 可用凭据**
   - `register` 成功返回中必须有可用于 `get_members`/`send_invite` 的 `access_token` 与 `account_id`。
   - 不要求调用方执行二次登录。

### C. 新流水线删除与收敛

删除以下函数及其仅内部依赖（以最终引用关系为准）：

- `_run_register_pipeline`
- `_finalize_registration_result`
- `_exchange_tokens`
- `_merge_pipeline_artifacts`
- `_check_network_and_region`

同时清理仅为这些函数服务的孤立辅助逻辑，确保 `chatgpt.py` 保留单一注册路径。

## 影响文件

- `chatgpt.py`（主改动）
- `test_chatgpt_register_service.py`（删除/改写针对新流水线的测试，保留并强化当前流程与 Team 衔接验证）

## 测试与验收

必须满足：

1. `register` 成功后，紧接 `get_members` 可执行。
2. `register` 成功后，紧接 `send_invite` 可执行。
3. 与 `codex_register_service.py` 现有调用链兼容（重点是 `register` 返回字段满足后续读取与持久化）。
4. OTP 邮件延迟场景下，轮询可在上限内成功拿码。
5. 未知分支中任一步骤失败可及时中止并返回错误，不出现“假成功”。

## 风险与缓解

- 风险：删除新函数时误删被其他路径引用的方法。
  - 缓解：删除前全仓 `Grep` 引用；删除后跑相关测试。

- 风险：收紧完成态导致个别边缘成功路径不再提前返回。
  - 缓解：保留当前核心路径并通过测试覆盖真实终态 URL 组合。

## 实施顺序

1. 在 `register` 当前主流程内完成补足修复。
2. 校准并验证 Team 衔接字段输出。
3. 删除新流水线与孤立依赖代码。
4. 更新并运行测试，确保 `codex_register_service.py` 流程连续性。

