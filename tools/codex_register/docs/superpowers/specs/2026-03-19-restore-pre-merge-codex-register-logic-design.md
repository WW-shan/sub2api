# Restore Pre-Merge Codex Register Logic Design

## Goal
以 `5c211aca^1` 为唯一基线，恢复 `5c211aca` 这个 merge 对 `codex_register_service.py` 原有逻辑造成的全部偏移。后续新增代码可以继续存在，但只能复用恢复后的原规则，不能改变原规则语义。

## Baseline
- 原逻辑基线：`5c211aca^1`
- 需要修复的错误来源：`5c211aca`
- 本次不追别的 commit，只处理这一个 merge 相对基线造成的原逻辑偏移

## Scope
- 修改 `tools/codex_register/codex_register_service.py`
- 修改 `tools/codex_register/test_codex_register_service.py`
- 默认不修改其他文件
- 若实现过程中发现其他文件也必须修改，必须先满足两个条件：
  1. 能给出明确调用链或失败证据，证明它直接依赖了 `5c211aca` 引入的错误语义
  2. 在实现说明里记录该文件为何属于“直接耦合调用点”

## User-approved constraints
- 必须以 `5c211aca^1` 为基准
- 后加代码可以复用原规则，但不能修改原先逻辑
- 不是只修 `name` / `mapping` / 母号这几处，而是恢复 `5c211aca` 对原逻辑造成的全部错误改动

## What counts as "original logic"
以下职责全部按 `5c211aca^1` 语义恢复：
- 注册结果解析规则
- account upsert / create / update 规则
- `name`、`email`、`credentials`、`extra` 的写入规则
- `model_mapping` 相关规则
- resume 成功后的母号处理链路
- 与这些规则直接绑定的测试预期

## Current problem
`5c211aca` 在合并 loop runner 时，不只是新增了 loop 能力，也同时改写了原先已经存在的落库逻辑，导致当前行为偏离 `5c211aca^1`。已确认的偏移包括但不限于：

1. 删除 email 校验，放宽了原先创建规则
2. 新账号命名从原先基线改成了 `account_id or email` 派生值
3. 删除 `model_mapping` 构造与创建时写入逻辑
4. 删除或改坏与上述行为绑定的测试
5. 删掉 resume 成功后母号规范化落库调用链中的原逻辑步骤

因此当前代码已经不是“在原逻辑上新增能力”，而是“新增能力顺带覆盖了原逻辑”。

## Design

### 1. Restoration checklist is mandatory
为了避免“恢复全部偏移”变成主观判断，本次实现必须先产出一份基于 `git diff 5c211aca^1 5c211aca -- codex_register_service.py test_codex_register_service.py` 的恢复清单，并在实现时逐项标注处理结果。

清单中的每个 diff hunk 都必须归入以下三类之一：
- `restore`: 该改动落在原职责内，必须恢复为 `5c211aca^1` 语义
- `keep`: 该改动属于独立新增能力，可原样保留
- `adapt`: 该改动属于新增能力，但当前实现依赖了错误 merge 语义，需要改成复用恢复后的基线逻辑

每一项都必须写明原因，避免遗漏或误回退。

### 2. 先恢复旧逻辑层，再让新增能力挂回去
本次修复分两层进行：

#### A. 旧逻辑层恢复
在 `codex_register_service.py` 中，把所有属于原职责范围、且被 `5c211aca` 改写的逻辑恢复为 `5c211aca^1` 的语义。

这一步不是“参考老代码重新实现一套差不多的逻辑”，而是：
- 以 `5c211aca^1` 的实际行为为准
- 当前代码只允许做结构适配，不允许改语义
- 如果当前文件为了支持新增功能做了重组，允许保留重组后的外壳，但内部规则必须回到基线

#### B. 新增能力重新依附
`5c211aca` 之后新增的能力（例如 loop runner、状态字段、统计字段、接口扩展）继续保留，但它们只能调用恢复后的旧逻辑。

原则是：
- 新增能力可以存在
- 新增能力不能重写基线行为
- 若新增能力当前依赖的是 merge 引入的错误语义，则改为依赖恢复后的基线语义

### 3. 恢复范围按职责整体恢复，不做零散打补丁
不采用“哪坏补哪”的外层兼容补丁方案。原因是这会在当前代码里留下两套规则：
- 一套是原本逻辑
- 一套是为了兼容 merge 错误再叠的一层逻辑

这违反用户要求，也会让后续行为继续漂移。

因此恢复方式采用“职责整体恢复”：
- 解析职责按基线恢复
- upsert 职责按基线恢复
- resume 母号后处理职责按基线恢复
- 相关测试职责按基线恢复

### 4. `codex_register_service.py` 的恢复边界
以下区域按 `5c211aca^1` 逐段恢复：

#### 4.1 输入记录解析
恢复 `5c211aca^1` 对账号记录的合法性判断、字段要求、字段规范化规则。

要求：
- 原先怎么判断一条记录可导入，就恢复成原先判断方式
- 原先哪些情况会 `skip`，就继续 `skip`
- 不保留 `5c211aca` 为了配合新逻辑而放宽或改变的原判断

#### 4.2 `_upsert_account`
这是本次恢复的核心。

必须恢复为基线语义，包括但不限于：
- 创建前校验条件
- create 与 update 的分支条件
- 新账号 `name` 的取值逻辑
- `credentials` 的构造逻辑
- `extra` 的构造逻辑
- `model_mapping` 的写入逻辑
- 原本不会在 update 中被修改的字段，仍然不能被当前实现额外修改

目标不是只让测试过，而是让 `_upsert_account` 再次成为“旧规则的唯一实现点”。

#### 4.3 resume 成功后的母号链路
恢复 `5c211aca^1` 中原本存在、但被 `5c211aca` 删除或绕开的母号后处理路径。

要求：
- resume 成功后的母号逻辑重新回到基线路径
- 任何后加流程如需处理母号，也必须建立在这条恢复后的链路上
- 不允许为了兼容当前状态再额外分叉出一套母号补丁逻辑

### 5. `test_codex_register_service.py` 的恢复边界
测试不是“顺手修一下”，而是这次修复的一部分。

要求：
- 恢复 `5c211aca` 改掉的旧测试预期
- 恢复 `5c211aca` 删除的原保护性测试
- 保留后续真正独立的新增测试，但前提是它们不能要求错误的 merge 语义继续存在

测试分两层：

#### 5.1 原逻辑回归测试
证明当前行为重新与 `5c211aca^1` 对齐，例如：
- 创建规则回到基线
- 命名规则回到基线
- `model_mapping` 回到基线
- 原先禁止的创建路径仍被禁止
- 母号链路回到基线

#### 5.2 新增能力兼容测试
证明 loop runner 等后加能力仍能工作，但它们现在依赖的是恢复后的旧规则，而不是 `5c211aca` 的错误语义。

### 6. 冲突处理原则
如果某个后加能力与 `5c211aca^1` 基线冲突，处理原则固定为：

> 基线优先，但只针对 `5c211aca` 改坏的那部分原语义。

这条原则不允许扩张成“回退所有后续提交”。只有当某个当前行为能被证明是 `5c211aca` 相对 `5c211aca^1` 引入的偏移时，才回到基线。若后续提交对同一语义做了明确、独立且有意的调整，则该调整需要在恢复清单中显式标注为 `keep` 或 `adapt`，不能被隐式抹掉。

这条原则适用于：
- 命名
- 校验
- mapping
- 母号处理
- update/create 判定
- 测试预期

## Implementation shape
实现上推荐遵守以下形状：

1. 优先恢复原 helper / 原判断顺序 / 原字段写入规则
2. 尽量避免增加新的兼容分支
3. 如果为了接回 loop runner 必须写桥接代码，桥接代码只能调用恢复后的原逻辑，不能复制旧逻辑
4. 不做无关重构

## Verification plan

### 1. Restoration checklist verification
实现前必须先生成 `5c211aca^1..5c211aca` 在以下两个文件上的恢复清单，并在实现完成后逐项核对处理结果：
- `codex_register_service.py`
- `test_codex_register_service.py`

只有当每个 hunk 都被标记为 `restore` / `keep` / `adapt` 且有理由说明时，才算完成范围验证。

### 2. Executable verification gates
至少需要运行并通过以下命令：

```bash
python -m unittest tools.codex_register.test_codex_register_service.UpsertHelperTests -v
python -m unittest tools.codex_register.test_codex_register_service.ProcessingFlowTests -v
python -m unittest tools.codex_register.test_codex_register_service -v
```

其中必须明确覆盖并验证：
- 输入记录解析恢复到 `5c211aca^1` 语义
- `_upsert_account` 的 create/update 行为恢复到 `5c211aca^1`
- 新建账号命名规则恢复到基线
- `model_mapping` 恢复到基线
- email 缺失/非法路径恢复到基线
- resume 母号处理链路恢复到基线
- loop runner 相关测试继续通过，证明新增能力仍可用

### 3. Behavior-level verification
除自动化测试外，必须对以下行为进行结果核对：
- 记录解析
- upsert create/update
- 命名规则
- `model_mapping`
- 母号 resume 链路

### 4. Compatibility verification
验证以下功能仍然可用：
- loop runner 相关接口与状态字段
- accounts 列表能力
- 统计/offset/round history 等新增状态能力

但验证重点不是“它们还在”，而是“它们没有继续覆盖旧逻辑”。

## Non-goals
- 不重新设计 codex register 架构
- 不重写 loop runner
- 不借机清理无关代码
- 不追查与 `5c211aca` 无关的历史偏移
- 不把本次修复扩展成大规模重构

## Acceptance criteria
- `codex_register_service.py` 中所有被 `5c211aca` 改写的原职责逻辑，行为恢复到 `5c211aca^1`
- 后加代码可以继续存在，但只能复用恢复后的原规则
- `test_codex_register_service.py` 中被 `5c211aca` 改坏或删除的基线测试得到恢复
- 当前测试能够证明：修复的是原逻辑恢复，而不是新的兼容补丁
- loop runner 等新增能力不会再要求错误的 merge 语义继续存在
- 若确实需要修改第三个文件，必须能给出直接耦合证据并在实现说明中记录原因
- 实现完成后必须产出并核对恢复清单，确保 `5c211aca^1..5c211aca` 的目标 hunk 没有遗漏