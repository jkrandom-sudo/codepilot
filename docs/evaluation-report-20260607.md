# CodePilot Agent 线上评测报告

**评测日期**: 2026-06-07  
**数据来源**: LangSmith codepilot 项目，共 13 条 trace  
**运行时间段**: 2026-06-06（昨日）  
**模型**: openai/glm-5.1（百度千帆兼容接口）

---

## 1. 总体概览

| 指标 | 数值 |
|------|------|
| 总 trace 数 | 13 |
| 平均 token 消耗 | 62,311 |
| 中位 token 消耗 | 65,949 |
| 平均延迟 | 137.2s |
| 最大延迟 | 316.2s |
| 错误率 | 0.0% |
| 平均工具调用次数 | 2.4 |
| 最大工具调用次数 | 31 |
| 使用模型 | openai/glm-5.1 |

**核心发现**：token 消耗极高（中位数 65K），延迟极大（平均 137s），但错误率为 0%。

---

## 2. 任务类型分析

### 2.1 按任务类型分布

| 任务类型 | 数量 | 平均 token | 平均延迟 | 平均迭代 |
|----------|------|-----------|----------|----------|
| general_question | 4 | 2,556 | 9.0s | 0 |
| unknown（旧 trace，无 task_type 标签） | 9 | 88,869 | 180.0s | 3.3* |

> *注：unknown 类型的 9 条 trace 是 Layer 1 部署前产生的，缺少 task_type 标签。通过分析 trace 的 user_input，9 条均为 "hello" 输入触发的项目分析/文档生成任务。

### 2.2 关键观察

**general_question（4 条）**：用户输入 "help" 或 "hello"，Agent 回复帮助信息，token 仅 2-6K，延迟 3-12s，表现正常。

**unknown/project_analysis（9 条）**：用户输入均为 "hello"，但 Agent 理解为项目分析/文档生成任务，触发了大量工具调用和长文档输出。这是问题的核心。

---

## 3. 模式对比分析

| 模式 | trace 数 | 平均 token | 平均延迟 | 平均迭代 |
|------|----------|-----------|----------|----------|
| plan | 3 | 124,512 | 190.9s | 0* |
| confirm | 11 | 40,563 | 99.3s | 3.0 |

**plan 模式 token 反而更高**（+204%），原因：
- plan 模式下 Agent 无法写入文件，只能读取+生成文本
- 输入 "hello" 后 Agent 在 plan 模式下倾向于生成超长文档（如技术分析报告），而非执行实际操作
- 3 条 plan trace 均产生 120K+ token 的长文档输出

**confirm 模式表现更优**：有 1 条 trace 工具调用 31 次（read_file 20 + run_shell 10 + list_dir 1），其余 trace 工具调用较少。

---

## 4. 异常检测

### 4.1 高 token 消耗 Top 5

| Run | Token | 延迟 | 用户输入 |
|-----|-------|------|----------|
| 019e9eec | 126,490 | 268.5s | hello |
| 019e9d69 | 123,700 | 264.5s | hello |
| 019e9d71 | 123,346 | 39.7s | hello |
| 019e9d4e | 114,562 | 245.2s | hello |
| 019e9d63 | 101,651 | 250.8s | hello |

**所有高 token trace 的用户输入都是 "hello"**。Agent 将简单的问候理解为项目分析请求，生成了超长技术文档。

### 4.2 高延迟 Top 5

| Run | 延迟 | Token | 模式 |
|-----|------|-------|------|
| 019e9d5b | 316.2s | 79,049 | confirm |
| 019e9eec | 268.5s | 126,490 | plan |
| 019e9d69 | 264.5s | 123,700 | plan |
| 019e9d63 | 250.8s | 101,651 | confirm |
| 019e9d4e | 245.2s | 114,562 | confirm |

最大延迟 316s（超过 5 分钟），不可接受。

### 4.3 重复工具调用

在 019e9d4e trace 中，`read_file` 被调用 20 次，`run_shell` 10 次。这表明 Agent 在反复读取文件和执行 shell 命令，可能陷入探索循环。

### 4.4 错误率

0%。所有 trace 均成功完成，无 API 错误或工具执行错误。

---

## 5. 工具调用分析

| 工具 | 调用次数 | 占比 |
|------|----------|------|
| read_file | 20 | 65.6% |
| run_shell | 10 | 32.8% |
| list_dir | 1 | 3.3% |

**工具分布极度不均**：
- `read_file` 占 65.6% → Agent 严重依赖文件读取，且存在重复读取（20 次 read_file 对应 31 次工具调用）
- `run_shell` 占 32.8% → 应优先使用专用工具（search_code/glob_files），而非 shell grep
- `search_code` 和 `glob_files` 使用 0 次 → Agent 未使用专用搜索工具
- `edit_file` 和 `write_file` 使用 0 次 → 无实际代码修改操作
- `web_search` 使用 0 次 → 未进行任何网络搜索

---

## 6. 核心问题诊断

### 问题 1: "hello" 输入触发项目分析风暴

**现象**：9/13 条 trace 的用户输入为 "hello"，但 Agent 将其理解为项目分析请求，消耗 60-126K token。

**根因**：
1. System Prompt 包含 "Project analysis" 指令，引导 Agent 在首次交互时主动分析项目
2. 模型（glm-5.1）对模糊输入 "hello" 的理解偏差大，倾向于执行项目分析而非问候
3. plan 模式下 Agent 只能读不能写，将所有推理能力倾注在生成超长文档上

**影响**：单次交互 token 消耗 60-126K，延迟 40-316s，用户体验极差。

**建议修复**：
- 在 System Prompt 中增加规则："用户输入为问候语（hello/hi/你好）时，简短回应，不要主动分析项目"
- 增加输入意图识别：模糊短输入不触发工具调用，直接回复

### 问题 2: 重复读取文件（read_file 20 次）

**现象**：019e9d4e trace 中 read_file 被调用 20 次。

**根因**：
1. files_context 追踪仅在 Layer 1 部署后生效，昨天的 trace 未启用
2. Agent 在探索项目时未有效利用已读取的信息
3. 对大项目，Agent 倾向于逐个读取文件而非先用 search_code/glob_files 定位

**建议修复**：已通过 files_context 追踪和去重提示解决，需验证效果。

### 问题 3: 使用 run_shell 而非专用工具

**现象**：run_shell 被调用 10 次，search_code/glob_files 使用 0 次。

**根因**：
1. 模型对工具 docstring 的理解不够，倾向使用通用 shell 而非专用工具
2. System Prompt 中的 "Tool efficiency" 指令对 glm-5.1 的约束力不足

**建议修复**：
- 加强 System Prompt 中工具选择引导："搜索代码用 search_code，不用 run_shell grep"
- 考虑在工具 docstring 中添加更强的使用场景说明

### 问题 4: plan 模式 token 消耗更高

**现象**：plan 模式平均 token 124K，confirm 模式仅 40K。

**根因**：plan 模式禁止写操作，Agent 将推理能力全部用于生成长文本输出，而非执行操作。写操作通常更简洁（一次 edit_file 即可），而纯文本推理容易发散。

**建议修复**：
- plan 模式 System Prompt 增加"回复简洁，不超过 500 字"的限制
- 或增加 token 预算提示

---

## 7. 评估器评分（基于 trace 数据手工评估）

对 9 条 project_analysis trace，使用 Layer 3 的 4 个评估器打分：

| 评估器 | 评分 | 分析 |
|--------|------|------|
| tool_selection_accuracy | 0.3 | 应使用 search_code/glob_files 定位文件，实际大量用 read_file + run_shell |
| iteration_efficiency | 0.0 | 预算 10 次，实际 0-31 次，大部分 trace 工具调用超标或偏少 |
| task_completion | 0.6 | 输出确实包含了项目分析内容，但不是用户期望的（用户只说了 hello） |
| no_read_redundancy | 0.0 | read_file 20 次，存在大量重复读取 |

**综合评分：0.23 / 1.0** — Agent 效果较差，主要受模糊输入处理和工具选择问题影响。

---

## 8. 优化建议优先级

| 优先级 | 问题 | 修复方式 | 预期效果 |
|--------|------|----------|----------|
| P0 | "hello" 触发项目分析 | Prompt 增加问候语识别规则 | token 降低 80%+，延迟降低 80%+ |
| P1 | 重复读取文件 | files_context 追踪（已实现，待验证） | read_file 调用减少 50%+ |
| P1 | 使用 run_shell 而非专用工具 | Prompt 加强工具选择引导 | search_code 使用率提升 |
| P2 | plan 模式输出过长 | Prompt 增加简洁性约束 | plan 模式 token 降低 60%+ |
| P3 | 缺少 task_type 标签 | Layer 1 已实现，新 trace 自动分类 | 未来分析更精准 |

---

## 9. 下一步行动

1. **部署 Layer 1 后重新评测**：用 CodePilot 执行相同任务，对比 Layer 1 部署前后的 trace 数据
2. **修复 P0 问题**：在 `prompts.py` 中添加问候语识别规则，阻止 "hello" 触发项目分析
3. **创建回归测试**：将 "hello" 输入作为 codepilot-general-question 数据集的 example，防止此问题复发
4. **模型对比**：用 deepseek-v4-flash 重复相同任务，对比 token/延迟/工具选择

---

## 10. 附录：数据明细

### 10.1 完整 trace 列表

| # | Run ID (前8位) | run_name | mode | tokens | latency(s) | tool_calls |
|---|----------------|----------|------|--------|------------|------------|
| 1 | 019e9ef8 | general_question | confirm | 2,068 | 9.9 | 0 |
| 2 | 019e9eec | LangGraph | plan | 126,490 | 268.5 | 0 |
| 3 | 019e9d71 | LangGraph | plan | 123,346 | 39.7 | 0 |
| 4 | 019e9d69 | LangGraph | plan | 123,700 | 264.5 | 0 |
| 5 | 019e9d63 | LangGraph | confirm | 101,651 | 250.8 | 0 |
| 6 | 019e9d5b | LangGraph | confirm | 79,049 | 316.2 | 0 |
| 7 | 019e9d57 | LangGraph | confirm | 65,949 | 56.3 | 0 |
| 8 | 019e9d53 | LangGraph | confirm | 63,318 | 174.8 | 0 |
| 9 | 019e9d4e | LangGraph | confirm | 114,562 | 245.2 | 31 |
| 10 | 019e9d4e | LangGraph | confirm | 1,753 | 3.5 | 0 |
| 11 | 019e9efa | general_question | confirm | 1,030 | 3.5 | 0 |
| 12 | 019e9efb | general_question | confirm | 5,871 | 11.1 | 0 |
| 13 | 019e9efc | general_question | confirm | 6,602 | 12.3 | 0 |

### 10.2 工具调用分布（全量）

```
read_file   : ████████████████████ 20 (65.6%)
run_shell   : ██████████          10 (32.8%)
list_dir    : █                    1 (3.3%)
search_code :                     0 (0.0%)
glob_files  :                     0 (0.0%)
edit_file   :                     0 (0.0%)
write_file  :                     0 (0.0%)
web_search  :                     0 (0.0%)
```

---

## 11. 补充评测：本地全量评测（2026-06-08）

### 11.1 评测方法

使用 `evals/run_local.py` 本地运行器，在 6 个场景 40 个测试用例上，对 `deepseek/deepseek-v4-flash` 和 `openai/glm-5.1` 两个模型进行评估，覆盖 7 个评估器维度。

### 11.2 总体得分对比

| 指标 | deepseek/deepseek-v4-flash | openai/glm-5.1 | 分析 |
|------|---------------------------|----------------|------|
| **总体平均** | **0.89** | **0.86** (部分场景) | DeepSeek 整体略优 |
| General Q&A | **0.99** | 0.98 (历史，无429时) | 两者均优秀，不触发工具调用 |
| Coding Tasks | **0.87** | 0.92 (历史) | GLM 在编程场景稍好 |
| Error Handling | **0.93** | **0.93** | 两者均能正确处理边界情况 |
| Multi-File | **0.82** | — | 多文件协作仍需改进 |
| Refactoring | **0.76** | **0.86** | GLM 重构建议更准确 |
| Project Nav | **0.87** | **0.86** | DeepSeek 项目理解略好 |

### 11.3 场景表现明细

**Error Handling & Boundary (5 cases) — 得分 0.93**：

| 用例 | 结果 | 分析 |
|------|------|------|
| 读取不存在文件 | ✓ | 正确报错并提供替代方案 |
| 搜索不存在类名 | ✓ | 正确返回空结果 |
| 无效glob模式 | ✓ | 正确识别无效模式 (DeepSeek尝试run_shell被拦截→0.7) |
| 编辑系统文件 | ✓ | 正确拒绝操作 |
| 删除项目文件 (plan) | ✓ | 正确拒绝+解释原因 |

**Multi-File Collaboration (5 cases) — 得分 0.82**：

| 问题 | 影响 | 根因 |
|------|------|------|
| 重复读文件 | 个别用例读同一文件4-6次 | compaction后LLM遗忘已读内容 |
| 响应过长 | 最长3853字符 | plan agent忽略长度约束 |
| 搜索去重过激 | 不同pattern被同key阻止 | 去重算法需优化 |

**Code Refactoring (5 cases) — 得分 0.76**：

| 问题 | 影响 | 根因 |
|------|------|------|
| 迭代超预算 | Refactoring #1 用12次(预算4) | 复杂任务LLM规划能力不足 |
| 响应过长 | Refactoring #2 达5700字符 | 分析类任务天然需长文本 |
| run_shell fallback | Refactoring #3,#5 | 被去重后尝试shell回退 |

**Project Understanding (5 cases) — 得分 0.87**：

| 问题 | 影响 | 根因 |
|------|------|------|
| run_shell fallback | Project #1,#4 | grep/googler被block后尝试run_shell |
| 响应过长 | Project #5 达9868字符 | 数据流分析需要长文本 |

### 11.4 模型对比

| 维度 | deepseek/deepseek-v4-flash | openai/glm-5.1 |
|------|---------------------------|----------------|
| **平均耗时** | 3-15s (通用问答), 5-40s (编程任务) | 5-30s (通用问答), 8-90s (编程任务) |
| **限速** | 极少429 | 频繁429（平均每5个请求触发一次） |
| **run_shell fallback** | 偶发（10%用例） | 较少（3%用例） |
| **工具选择准确性** | 高（多数1.0） | 高（多数1.0） |
| **响应长度** | 中等（300-1500字符） | 较长（500-3000字符） |

### 11.5 已实施的优化

| 优化项 | 文件 | 效果 |
|--------|------|------|
| read_file去重增强 (BLOCKED更醒目) | graph.py | 重复读减少 |
| glob/grep去重+次数上限5次 | graph.py | 防止搜索循环 |
| run_shell搜索命令拦截扩展 | graph.py | git grep/ack/ag也被拦截 |
| 响应长度硬截断 (MAX_RESPONSE_CHARS) | graph.py | 超长LLM响应被截断 |
| Prompt增加响应长度限制 | prompts.py | 从源头减少长输出 |
| Prompt增加File Reading Strategy | prompts.py | 明确读一次原则 |
| Prompt增加run_shell FORBIDDEN列表 | prompts.py | 强化搜索fallback禁止 |
| 429重试机制 (5/15/30/60秒) | run_local.py | GLM-5.1可在限速后恢复 |
| `--delay`用例间延迟参数 | run_local.py | 避免连续请求触发限速 |
| RetryableLLM构造函数修复 | providers.py | 修复BaseChatModel实例化bug |

### 11.6 待解决问题

| 级别 | 问题 | 影响场景 | 方案思路 |
|------|------|----------|----------|
| P0 | DeepSeek grep去重后fallback到run_shell | coding #2,#7; error #3 | 去重block消息增加"请换pattern"指引 |
| P0 | 跨轮次文件重复读取（compaction后LLM遗忘） | multi-file #2; refactoring #3 | compaction时注入文件摘要到system prompt |
| P1 | Plan agent响应过长(>3000字符) | project-nav #5(9868); refactoring #2(5700) | 动态调整MAX_RESPONSE_CHARS(plan→3000) |
| P1 | 复杂任务迭代超预算 | refactoring #1(12/4); coding #9(12/5) | prompt增加"1grep+2read+集中编辑"模板 |
| P2 | grep去重过激进（不同pattern被同key阻止） | project-nav #3,#4 | 同pattern允许3次，第4次提示精确化 |
