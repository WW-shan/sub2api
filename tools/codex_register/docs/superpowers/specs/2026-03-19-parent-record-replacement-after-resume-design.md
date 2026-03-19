# Parent Record Replacement After Resume Design

## Goal
在 `codex_register_service.py` 的 `/resume` 流程成功后，为母号生成一条与后续 5 个账号相同结构的标准记录，并删除旧的 `get_tokens` 母号记录，保证母号最终既能落库，又不会在 `accounts.jsonl` 中保留旧格式重复行。

## Scope
- 修改 `tools/codex_register/codex_register_service.py`
- 修改 `tools/codex_register/test_codex_register_service.py`
- 不修改 `tools/codex_register/get_tokens.py`
- 不修改 `tools/codex_register/gpt-team-new.py`

## Current behavior
当前流程分两段：

1. `enable -> get_tokens.py`
   - 首号（母号）先写入 `accounts.jsonl`
   - 该记录来源是 `source = "get_tokens"`
2. `resume -> gpt-team-new.py`
   - 生成后续 5 个号
   - 它们写入的是 `gpt-team-new.py` 的标准导入记录格式

同时，`codex_register_service.py` 在 `enable` 成功后：
- 读取 baseline 之后最新一条记录作为 `resume_context`
- 把 `accounts_jsonl_offset` 和 `accounts_jsonl_baseline_offset` 推进到首号末尾

结果是：
- 首号被用于 `resume_context`
- resume 阶段批量落库只处理首号之后新增的记录
- 首号不会自动落库
- `accounts.jsonl` 里会长期保留旧的 `get_tokens` 母号记录

## User-approved decisions
- 母号需要落库
- 母号无论最终 `plan_type` 还是 `free` 还是 `team`，都要在 resume 后生成一条与后续 5 个号相同结构的标准记录
- 旧的 `get_tokens` 母号行需要删除
- 删除旧行的时机：**resume 成功后再删**
- 新母号标准记录的 `source`：**`gpt-team-new`**

## Record contract
resume 成功后，母号的新记录应与 `gpt-team-new.py` 的 `build_importable_account_record()` 输出结构保持一致，至少包含：
- `email`
- `password`
- `access_token`
- `refresh_token`
- `id_token`
- `account_id`
- `auth_file`
- `expires_at`
- `invited`
- `team_name`
- `plan_type`
- `organization_id`
- `workspace_id`
- `codex_register_role`
- `created_at`
- `updated_at`
- `source`

对母号的新记录，语义固定为：
- `source = "gpt-team-new"`
- `codex_register_role = "parent"`
- `invited = False`

## Design
### 1. 在 resume 成功后增加“母号记录规范化”步骤
在 `codex_register_service.py` 的 `return_code == 0 and mode == "resume"` 成功分支中，在最终完成状态落定前增加一个规范化阶段：

1. 读取 `resume_context.email`
2. 基于该 email 在当前 `accounts.jsonl` 中定位母号旧记录
3. 构造一条新的母号标准记录
4. 先对该母号标准记录执行 DB upsert
5. 只有 DB upsert 成功后，才允许重写 `accounts.jsonl`：
   - 删除旧的 `get_tokens` 母号行
   - 删除任何已有的同邮箱母号标准记录（避免重复 resume 时多条 parent 记录）
   - 插入唯一的一条最新母号标准记录
   - 保留其他已有记录（包括后续 5 个子号）

### 2. 用“重写整个 JSONL 文件”替代原地编辑或先追加后删除
JSONL 天然适合 append，不适合原地删除某一行。为了保证最终状态稳定、可测试且不依赖旧字节偏移，规范化过程采用：

1. 从 `accounts.jsonl` 读取并解析所有有效记录
2. 过滤掉：
   - `email == normalized_resume_email and source == "get_tokens"` 的旧母号记录
   - `email == normalized_resume_email and source == "gpt-team-new" and codex_register_role == "parent"` 的旧母号标准记录
3. 将新母号标准记录加入集合
4. 将最终记录集合完整重写回 `accounts.jsonl`

这样可以保证：
- 最终文件中只有一条母号记录
- 不会出现“先追加成功、删除失败”的双写中间态
- 重复 `/resume` 时文件不会越来越脏

### 3. 母号新记录的数据来源
新母号标准记录不应靠猜测拼接，而应优先利用当前可用的母号真实数据。

字段来源与优先级明确如下：
- `email`: `resume_context.email`，写入前需要 `strip().lower()` 规范化
- `password`: 优先旧的 `get_tokens` 母号记录中的 `password`；若缺失则空字符串
- `access_token`: 优先最新母号记录中的值；若无则回退到旧母号记录
- `refresh_token`: 优先最新母号记录中的值；若无则回退到旧母号记录；再无则空字符串
- `id_token`: 优先最新母号记录中的值；若无则回退到旧母号记录；再无则空字符串
- `account_id`: 优先最新母号记录中的值；若无则回退到旧母号记录；再无则空字符串
- `auth_file`: 优先最新母号记录中的值；若无则回退到旧母号记录；再无则空字符串
- `expires_at`: 优先最新母号记录中的值；若无则回退到旧母号记录；再无则空字符串
- `invited`: 固定 `False`
- `team_name`: 沿用 `resume_context.team_name`
- `plan_type`: 来自母号当前最新状态；无论最终是 `free` 还是 `team`，都写入该最新值
- `organization_id`: 来自母号当前最新状态，缺失时写空字符串
- `workspace_id`: 来自母号当前最新状态，缺失时写空字符串
- `codex_register_role`: 固定 `parent`
- `created_at`: 优先保留旧母号记录中的 `created_at`，没有则退回当前时间
- `updated_at`: 写为当前时间
- `source`: 固定 `gpt-team-new`

如果当前实现中没有一个现成 helper 能直接给出“母号标准记录”，则应在 `codex_register_service.py` 内新增一个小范围 helper，职责仅是：
- 根据旧母号记录、最新母号记录、resume_context 组装 parity-format parent record

### 4. 坏行与无效 JSONL 行策略
规范化重写 `accounts.jsonl` 时，不允许因为重写而静默丢掉历史坏行。

要求：
- 读取文件时应保留原始行顺序
- 对于可解析且有效的账号记录，参与“过滤旧母号 + 插入新母号记录”的重写逻辑
- 对于不可解析或无效的原始行，必须原样保留，不得因为本次重写而删除

这样可以避免“母号替换成功，但顺手把历史坏行吃掉”的数据损失。

### 5. 原子重写要求
重写 `accounts.jsonl` 不能直接覆盖目标文件。

要求：
- 先把最终内容写入同目录下的临时文件
- flush/fsync（如果平台实现允许）后再执行原子替换
- 只有替换成功才视为 rewrite 成功

这样可避免在进程中断或写入失败时把 `accounts.jsonl` 写坏，从而违背“不要丢旧行”的设计目标。

### 6. Offset 处理要求
由于母号替换采用“全文件重写”策略，文件字节布局会变化，因此不能继续直接信任旧 offset 值。

要求：
- rewrite 完成后，必须基于新文件重新计算并更新与后续状态一致的 offset 字段
- 至少要确保：
  - `accounts_jsonl_offset`
  - `accounts_jsonl_baseline_offset`
  - `last_processed_offset`
  在 rewrite 后不会指向旧文件中的失效字节位置

推荐做法：
- rewrite 完成后重新扫描文件，根据最终母号标准记录与后续子号记录的实际 `line_end_offset` 重建后续 state
- 如果实现上更稳，也可以在 rewrite 完成后把后续处理所需 offset 直接重置为新文件的末尾或明确的重新计算值，但必须保证不会导致后续重复处理或跳过新记录

## Failure handling
### 1. 如果母号新标准记录生成失败
- 不删除旧 `get_tokens` 行
- 整个 resume 流程视为失败或至少不能宣称成功
- 必须记录明确错误，例如 `parent_record_rewrite_failed`

### 2. 如果母号 DB upsert 失败
- 不删除旧 `get_tokens` 行
- 不进入最终 completed 成功状态

### 3. 如果 JSONL 重写失败
- 不删除旧 `get_tokens` 行
- 不进入最终 completed 成功状态

核心原则：
> 只有当“新母号记录已生成且 DB upsert 成功”之后，才允许删除旧 `get_tokens` 记录。

## Deduplication rules
对母号 email，最终 `accounts.jsonl` 中应满足：
- 匹配时必须使用规范化 email（`strip().lower()`）
- 不存在 `source == "get_tokens"` 的旧母号记录
- 不存在多个 `source == "gpt-team-new" and codex_register_role == "parent"` 的母号标准记录
- 只保留唯一一条最新母号标准记录

## Non-goals
- 不修改 `get_tokens.py` 的产出逻辑
- 不修改 `gpt-team-new.py` 的子号生成逻辑
- 不重构整体状态机
- 不改变后续 5 个子号的现有落库流程

## Acceptance criteria
- `/resume` 成功后，母号在 `accounts.jsonl` 中变为标准记录格式
- 新母号记录的 `source == "gpt-team-new"`
- 旧的 `get_tokens` 母号行被删除
- 重复 `/resume` 不会产生多个母号标准记录
- 母号最终会落库到 DB
- rewrite 完成后 offset 不会指向旧文件字节位置
- rewrite 使用临时文件 + 原子替换
- 如果母号标准记录生成 / 落库 / 替换失败，旧 `get_tokens` 行不会被删除
