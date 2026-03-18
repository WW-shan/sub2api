# get_tokens Data Parity Design

## Goal
让 `tools/codex_register/get_tokens.py` 产出的 `accounts.jsonl` 记录字段集合与 `tools/codex_register/gpt-team-new.py` 的 `build_importable_account_record()` 输出保持一致，同时保留 `results.txt` 的现有文本格式。

## User-approved approach
采用方案 1：`get_tokens.py` 直接复用 `gpt-team-new.py` 内已有的辅助函数，而不是复制一套 ChatGPT 会话探测逻辑，也不抽公共模块。

## Scope
- 修改 `tools/codex_register/get_tokens.py`
- 修改 `tools/codex_register/test_codex_register_service.py`
- 不修改 `tools/codex_register/codex_register_service.py`
- 不抽取新共享模块
- 不重写 `gpt-team-new.py` 的 ChatGPT 登录实现

## Existing behavior
`get_tokens.py` 当前写入的 `accounts.jsonl` 记录只有：
- `email`
- `password`
- `access_token`
- `refresh_token`
- `invited`
- `team_name`
- `source`
- `created_at`

`gpt-team-new.py` 的导入记录还包含：
- `id_token`
- `account_id`
- `auth_file`
- `expires_at`
- `plan_type`
- `organization_id`
- `workspace_id`
- `codex_register_role`
- `updated_at`

## Design
### 1. 保持 `oauth_login()` 主流程不大改
`get_tokens.py` 现有 `oauth_login()` 已能稳定返回 `(access_token, refresh_token)`。为了降低改动风险，不在本次中重写这段长流程。`process_one()` 负责把这个二元组包装成 `tokens` 字典，供共享 helper 使用。

### 2. 通过动态导入复用 `gpt-team-new.py` helper
`get_tokens.py` 新增动态导入逻辑，从同目录的 `gpt-team-new.py` 获取：
- `build_token_dict`
- `build_importable_account_record`
- `chatgpt_http_login`

如果导入失败或函数不存在，记录 warning，并走降级路径。

### 3. 通过 `build_token_dict()` 统一 token 派生字段
`process_one()` 在拿到 `(access_token, refresh_token)` 后，构造：

```python
{
  "access_token": access_token,
  "refresh_token": refresh_token,
  "id_token": "",
}
```

然后优先调用 `build_token_dict(email, tokens)` 来得到：
- `account_id`
- `expired`（后续映射到 `expires_at`）
- `last_refresh`
- `id_token`

若 helper 不可用，则使用最小 fallback token dict，但仍保持字段完整。

### 4. 通过 `chatgpt_http_login()` 补充 ChatGPT 侧计划信息
`process_one()` 额外调用 `chatgpt_http_login(email, password, proxy, tag)`，best-effort 获取：
- `plan_type`
- `organization_id`

失败只记日志，不影响注册成功或 `results.txt` 输出。

### 5. 通过 `build_importable_account_record()` 统一生成 JSONL 记录
JSONL 记录不再由 `get_tokens.py` 自己拼最小结构，而是调用：

```python
build_importable_account_record(
    email=email,
    password=password,
    token_dict=token_dict,
    invited=False,
    team_name="",
    auth_file="",
)
```

并在返回后覆盖：

```python
record["source"] = "get_tokens"
record["codex_register_role"] = "parent"
```

这样可保持记录结构与 `gpt-team-new.py` 一致，同时保留来源区分。

## Output contract
最终 `get_tokens.py` 写入的 `accounts.jsonl` 每条记录至少包含：
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

并满足：
- `source == "get_tokens"`
- `invited is False`
- `team_name == ""`
- `codex_register_role == "parent"`

## Non-goals
- 不让 `get_tokens.py` 直接复制 `chatgpt_http_login()` 实现
- 不抽公共模块
- 不修改服务端路由逻辑
- 不改变 `results.txt` 文本格式
- 不引入新的 planType 推断启发式

## Acceptance criteria
- `get_tokens.py` 继续写 `results.txt`，格式不变
- `get_tokens.py` 写入的 `accounts.jsonl` 字段集合与 `gpt-team-new.py` 导入记录一致
- `plan_type` 与 `organization_id` 通过 `chatgpt_http_login()` best-effort 补充
- `source` 被正确写为 `get_tokens`
- 现有 `codex_register_service.py` 无需改动即可读取这些字段
- 新增测试覆盖 richer JSONL contract 与 helper 不可用时的降级行为
