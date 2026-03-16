# Codex Register 六账号 Team 邀请链路设计（前端契约精简版）

## 1. 目标
在不改变现有前端交互入口的前提下，实现以下业务链路：
1. 自动注册 6 个账号（1 父 + 5 子）；
2. 注册成功即写入 `codex_register_accounts`；
3. 进入人工等待，用户完成父账号订阅后点击 Resume；
4. Resume 后先切换到父账号（setCurrentAccount），再检查订阅并继续邀请 5 个子账号；
5. 严格校验 6 个账号都已进入 Team 成员列表后返回成功。

## 2. 约束与边界

### 2.1 固定约束
- `codex_register_role` 固定使用：`parent` / `child`。
- 成员校验标准固定为严格成员态：`get_members` 中必须包含 6 个账号。
- Resume 顺序固定为：
  - 前置记录检查（父账号必需上下文）；
  - `setCurrentAccount` / token 刷新；
  - 订阅 gate 校验（`plan_type=team && has_active_subscription=true`）；
  - 通过后才允许 invite。

### 2.2 非目标（本次不做）
- 不新增前端页面与交互入口。
- 不引入新的主流程 API（保留现有 `/admin/codex/*`）。
- 不引入额外数据库表。

## 3. 前后端调用契约（保持不变）

### 3.1 API 入口
- `POST /admin/codex/enable`：启动流程
- `POST /admin/codex/resume`：人工订阅后继续流程
- `POST /admin/codex/disable`：中止/放弃
- `GET /admin/codex/status`：轮询状态
- `GET /admin/codex/accounts`：展示账号列表
- `GET /admin/codex/logs`：日志面板

仅保证前端依赖字段持续可用：
- `enabled`
- `sleep_min`, `sleep_max`
- `total_created`
- `last_success`, `last_error`
- `proxy`
- `job_phase`
- `workflow_id`
- `waiting_reason`
- `can_start`, `can_resume`, `can_abandon`
- `last_transition`
- `last_resume_gate_reason`
- `recent_logs_tail`

## 4. Phase 设计（精简版）
仅保留必要 phase：
- `running:create_parent`
- `waiting_manual:parent_upgrade`
- `running:accept_and_switch`
- `running:invite_children`
- `running:verify_and_bind`
- `completed`
- `failed`
- `abandoned`

> 说明：删除独立 `running:pre_resume_check`，其检查逻辑并入 `running:accept_and_switch`，减少状态复杂度。

## 5. 主流程设计

### 5.1 启动阶段（enable）
1. 运行注册流程，连续创建 6 个账号；
2. 第 1 个账号标记为父账号，其余 5 个标记为子账号；
3. 每个账号注册成功即写库 `codex_register_accounts`；
4. 写入 `codex_register_role`（`parent`/`child`）；
5. 进入 `waiting_manual:parent_upgrade`，等待人工订阅。

### 5.2 恢复阶段（resume）
在 `running:accept_and_switch` 中按顺序执行：
1. 校验父账号上下文是否完整（至少包含 `account_id` 与 `session_token`）；
2. 调用 `refresh_access_token_with_session_token(..., account_id=parent_account_id)` 做 setCurrentAccount；
3. 使用刷新后的上下文调用账户检查，执行订阅 gate：
   - `plan_type == "team"`
   - `has_active_subscription == true`
4. 任一不满足则返回 waiting 并设置 `last_resume_gate_reason`；
5. 通过后进入邀请阶段。

### 5.3 邀请与校验阶段
1. `running:invite_children`：父账号依次邀请 5 个子账号；
2. `running:verify_and_bind`：轮询 `get_members`，直到父+5子全部在成员列表；
3. 全量命中后置 `completed`，否则在可重试条件下维持失败信息。

## 6. 数据落库策略

表：`codex_register_accounts`

注册成功即写入（upsert 或唯一键冲突可控处理）：
- `email`
- `refresh_token`
- `access_token`
- `account_id`
- `source`
- `plan_type`
- `organization_id`
- `workspace_id`
- `codex_register_role`（`parent`/`child`）
- `updated_at`

## 7. 失败与可恢复策略
- 父账号上下文缺失：停留 waiting，提示补齐。
- setCurrentAccount 失败：进入 failed 或可恢复 waiting（按错误类型）。
- 订阅 gate 未通过：保持 waiting，提示继续完成订阅。
- invite 部分失败：保留已执行结果，记录日志并支持后续 resume/retry。
- verify 超时：返回 failed，并保留当前成员快照用于排查。

## 8. 验收标准
1. 启动后可稳定创建并落库 6 条记录，角色正确（1 parent + 5 child）。
2. 未订阅前 resume 不会进入邀请，且有明确 gate 原因。
3. 已订阅后 resume 必须先完成 setCurrentAccount，再进入邀请。
4. 邀请完成后，`get_members` 严格包含 6 个账号才判定成功。
5. 前端不需改入口即可完整驱动流程与查看结果。
