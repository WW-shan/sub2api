# Cumulative Codex Persisted-Account Count Design

## Goal
在 `codex_register_service.py` 的状态数据中新增一个“累计落库成功账号数”字段，用来表示当前服务会话内累计成功写入数据库的 Codex 账号数量，而不是仅显示当前一轮或当前批次的创建数量。

## Scope
- 修改 `tools/codex_register/codex_register_service.py`
- 必要时修改 `tools/codex_register/test_codex_register_service.py`
- 不修改前端文件（本设计先只补后端状态字段）
- 不改数据库 schema

## User-approved requirement
累计口径采用：
- **只统计最终成功落库到 DB 的 Codex 账号数**
- 不统计只是生成成功但尚未落库的账号

## Current behavior
当前状态里已有多个“created”相关字段：
- `total_created`
- `loop_total_created`
- `last_processed_summary.created`
- `loop_last_round_created`

这些字段都更偏向“某次处理 / 某轮 loop / 某次批次”的计数，不是一个稳定且明确的“累计落库成功数”。

因此当前看到的 `5`，实际上只是某个局部批次的 created 结果，不是完整业务语义上的累计落库总数。

## Counting semantics
本字段采用的精确定义是：

> **只要数据库已经确认发生了 `created`，就立即计入累计值。**

这意味着：
- 如果子号已经成功 `created` 到 DB，即使后续同一轮流程在别处失败，也仍然计入累计值
- 如果母号标准化的 DB upsert action 是 `created`，就计入累计值；如果是 `updated` 或 `skipped`，则不计入
- 本字段表示“当前 service 会话内，数据库真实创建过多少 Codex 账号”，而不是“有多少轮完整成功”

## Design
### 1. 新增状态字段
在 `CodexRegisterService._default_state()` 中新增：

- `codex_total_persisted_accounts: 0`

语义：
- 当前 service 进程生命周期内
- 累计成功创建到 DB 的 Codex 账号总数

### 2. 重置边界
该字段在以下边界重置为 0：
- service 进程启动后初始化 `_default_state()` 时
- 任何会完全重建 service 实例、重新初始化 state 的场景

该字段**不会**跨进程重启持久化。

### 3. 更新规则：主流程 `/resume`
当 `return_code == 0 and mode == "resume"` 执行过程中，累计值按数据库真实 `created` 数增长。

来源分两部分：
1. 子号批量处理：来自 `_process_accounts_jsonl_records(state)` 返回 summary 的 `created`
2. 母号标准化替换：如果母号单独 upsert action 为 `created`，则额外 +1；如果是 `updated` 或 `skipped`，则 +0

因此主流程的累加公式应为：

```python
state["codex_total_persisted_accounts"] += int(summary.get("created") or 0) + parent_created_delta
```

其中：
- `parent_created_delta = 1` 当且仅当母号 persistence action 为 `created`
- 否则为 `0`

### 4. 更新规则：loop 模式
当 loop round 成功执行 DB 处理后：
- 使用该轮 summary 的 `created`
- 累加到 `codex_total_persisted_accounts`

即：
- loop 只累计真正新建到 DB 的子号数量
- loop 模式不额外处理母号替换逻辑，因此不存在额外的 parent `+1`

### 5. 对 `summary["created"]` 的要求
`summary["created"]` 只有在数据库已经确认对应记录是 `created` 时，才能用于累计。

换句话说：
- 该值必须代表已完成 DB upsert 并得到 `created` 结果的数量
- 不能是预估值、预写入值、或仅基于 JSONL 解析出的候选数量

### 6. 失败路径规则
以下情况本身不会“回滚已计入的 created 数”：
- 同一轮流程后续步骤失败
- 母号标准化后续 JSONL rewrite 失败
- 其他非 DB-created 的后续阶段失败

核心原则：
> 本字段统计“数据库已经成功创建过多少账号”，不是“最终完整成功的 workflow 数”。

但以下情况不会新增累计值：
- `_process_accounts_jsonl_records()` 没有产生新的 `created`
- 母号 DB upsert 结果是 `updated` 或 `skipped`
- loop round 失败且没有新的 `created`

### 7. 与现有字段的关系
- `total_created`：保留，继续表示主流程 accounts.jsonl 批处理中的 created 数
- `loop_total_created`：保留，继续表示 loop 累计 created 数
- `codex_total_persisted_accounts`：新增，表示统一业务语义下的“累计落库成功账号数”

不要复用旧字段改语义，避免前端和现有逻辑混淆。

### 8. `/status` 输出
`/status` 当前直接返回 service state，因此只要 state 中新增该字段，接口就会自动带出：

- `codex_total_persisted_accounts`

## Non-goals
- 不回溯扫描数据库修正历史累计值
- 不做跨 service 重启持久化累计
- 不修改前端展示逻辑
- 不把 update/skipped 计入累计

## Acceptance criteria
- `/status` 响应包含 `codex_total_persisted_accounts`
- 主流程 `/resume` 处理后，该值会按本次真正 `created` 的 DB 账号数增加
- 母号若只是 `updated` 或 `skipped`，不会额外增加累计值
- loop round 成功时，该值会按该轮 summary 的 `created` 增加
- 若某账号已经被 DB 成功 `created`，即使后续同轮流程失败，也不会从累计值中扣除
- 任一没有发生新的 DB `created` 的路径下，该值不会错误增加
