# ChatGPT Team 链路重构设计（保留注册）

## 目标
在当前仓库中保留既有“邮箱验证码 → 注册 → create_account → 登录态建立”流程，并将登录后的 Workspace/Team 调用对齐 `team-manage/app/services/chatgpt.py` 与 `team-manage/app/services/team.py` 的方法模式，最终形成单入口完整链路。

### 不可变约束（Invariants）
1. 注册链路调用顺序、参数语义、回退策略保持不变（尤其是 passwordless 不可用时的 fallback）。
2. `register_and_setup_team(...)` 为唯一公开编排入口，不新增第二条注册入口。
3. Team phase 必须消费 register phase 产出的登录上下文，不允许二次登录重建上下文。

## 范围
### 保留（必须不变）
- `codex_register_service.py:825` 起的注册到登录逻辑（run 内主链路）。

### 迁移（仅限，函数清单）
仅迁移并同步以下“服务调用语义/请求模式”（不照搬异步和 ORM）：

- 来自 `app/services/chatgpt.py` 的语义：
  - `_make_request`（统一 HTTP 请求封装、状态/错误归一化）
  - `send_invite`
  - `get_members`
  - `get_invites`
  - `delete_invite`
  - `delete_member`
  - `get_account_info`

- 来自 `app/services/team.py` 的语义：
  - `get_team_members`（成员与邀请聚合）
  - `add_team_member`
  - `revoke_team_invite`
  - `remove_invite_or_member`
  - `get_team_info`

未列入清单的方法一律不迁移。

### 不迁移（非目标）
- SQLAlchemy/数据库模型层；
- 加解密服务；
- 异步会话池、会话持久化隔离机制；
- schema 变更和基础设施依赖。

## 目标结构
- 在当前仓库新增服务模块（建议：`chatgpt_service.py`），定义 `ChatGPTService`。
- 暴露单入口：`register_and_setup_team(input) -> result`。
- 内部阶段：
  1. register phase：复用现有注册逻辑，得到 `AuthContext`；
  2. team phase：以 `AuthContext` 执行 team 动作列表。

### AuthContext 契约（register -> team）
必需字段：
- `access_token`（或 `session_access_token`）
- `account_id`
- `workspace_id`
- `organization_id`
- `plan_type`

## 关键接口约定
### 输入（RegisterAndTeamInput）
- `register_input`：注册所需参数（邮箱、验证码来源、密码/回退所需字段）。
- `team_plan`：Team 动作列表（按顺序执行），支持动作：
  - `invite_member(email)`
  - `list_members()`
  - `list_invites()`
  - `revoke_invite(email)`
  - `delete_member(user_id)`
- `request_options`：超时、重试上限（默认沿用现有请求超时策略）。

### 输出（RegisterAndTeamResult）
- `ok: bool`
- `phase: "register" | "team" | "done"`
- `reason: str`（简明原因）
- `error_code: str`（机器可读）
- `register_result: object`（脱敏后的关键结果）
- `team_results: list[object]`（每个动作的结果）

### 错误分段
- 注册失败：`phase=register`，不进入 team 调用。
- team 失败：`phase=team`，不回滚已注册账号。
- 错误码统一映射：`network_timeout` / `http_4xx` / `http_5xx` / `auth_invalid` / `business_conflict` 等。

## 数据流
1. 校验输入参数与动作列表。
2. 执行原始注册链路（不改变核心逻辑）。
3. 从注册结果构建 `AuthContext`。
4. 按顺序执行 `team_plan` 中动作（统一请求封装）。
5. 汇总每步结果并输出标准化结果。

### Workspace 规则
- 优先使用 register 阶段产出的 `workspace_id`。
- 若输入显式指定并校验通过，可覆盖默认 workspace。
- 若无法解析 workspace，直接按 `phase=register` 失败返回。

## 测试策略
### 回归要求
- 现有注册相关测试必须保持通过（证明注册链路未被破坏）。

### 新增最小测试矩阵
1. 注册失败即终止，Team 方法不被调用；
2. 注册成功 + Team 成功；
3. 注册成功 + Team 某一步失败，返回 `phase=team`；
4. Team 调用头部与上下文字段传递正确（token/account/workspace）；
5. 重复邀请/冲突语义按既定 `business_conflict` 处理；
6. 关键日志输出脱敏（token、敏感凭据不明文）。

## 风险与待确认
1. **迁移函数边界膨胀风险**：仅允许清单内方法语义落地。状态：已确认。
2. **workspace 选择歧义**：若外部传入 workspace 与注册产出不一致。状态：已确认（优先注册产出，必要时显式覆盖）。
3. **邀请幂等语义差异**：不同接口对重复邀请返回 409/200。状态：已确认（统一映射为 `business_conflict` 或成功幂等）。
4. **限流与重试策略**：默认沿用当前请求包装重试，不新增复杂退避。状态：已确认。
