# CodePilot Agent 评测方法文档

## 1. 概述

CodePilot 的评测体系分为四层，形成从数据采集到质量评估到持续改进的完整闭环：

```
Layer 1: 增强可观测性  →  丰富每次 trace 的指标数据
Layer 2: 线上分析脚本  →  聚合、对比、异常检测
Layer 3: 评估框架      →  自动化质量评分
Layer 4: 持续改进闭环  →  问题 trace 固化为回归测试
```

每一层独立可用，合在一起支撑"观察→假设→改动→验证→固化"的迭代循环。

---

## 2. 评测体系架构

```
                    ┌──────────────────────────────┐
                    │       LangSmith 平台          │
                    │  ┌─────────────────────────┐  │
                    │  │  Traces (带 task_metrics) │  │
                    │  │  Feedback (task_outcome)  │  │
                    │  │  Datasets (评估数据集)     │  │
                    │  │  Experiments (评估实验)    │  │
                    │  └─────────────────────────┘  │
                    └──────────┬───────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
     analyze_traces     compare_runs     detect_anomalies
     (聚合分析)         (对比分析)       (异常检测)
              │                │                │
              └────────────────┼────────────────┘
                               │
                               ▼
                        run_eval (评估执行)
                        evaluators (4个评估器)
                               │
                               ▼
                     trace_to_eval (问题→回归测试)
```

---

## 3. Layer 1: 增强可观测性

### 3.1 追踪数据结构

每次 Agent 执行任务后，LangSmith trace 携带以下数据：

**metadata（元数据）**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `model` | str | 当前模型 (如 deepseek/deepseek-v4-flash) | repl.py |
| `session_id` | str | REPL 会话 ID | repl.py |
| `agent_name` | str | 当前 Agent 名称 (build/plan/...) | repl.py |
| `confirm` | str | 权限确认模式 (readonly/confirm/auto) | repl.py |
| `task_type` | str | 任务分类 | `classify_task()` |
| `user_input_preview` | str | 用户输入前 200 字符 | repl.py |

**tags（标签）**：

| 标签 | 格式 | 用途 |
|------|------|------|
| agent 标签 | `agent:build` | 按 Agent 过滤 |
| confirm 标签 | `confirm:confirm` | 按确认模式过滤 |
| model 标签 | `model:deepseek/deepseek-v4-flash` | 按模型过滤 |
| task_type 标签 | `task_type:file_edit` | 按任务类型过滤 |
| prompt 版本标签 | `prompt:v7` | 按 prompt 版本对比 |

**run_name**：设为 `task_type` 值（如 "file_edit"），在 LangSmith UI 中直接显示任务类别而非默认 graph 名。

**extra.task_metrics（任务指标）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `iteration_count` | int | AIMessage(tool_calls) 出现次数 |
| `tool_call_count` | int | 工具调用总次数 |
| `tool_distribution` | dict | 各工具调用次数分布 |
| `denied_count` | int | 权限拒绝次数 |
| `total_tokens` | int | 消耗 token 总数 |
| `elapsed_seconds` | float | 任务耗时（秒） |
| `outcome` | str | 任务结果：success / partial / error |
| `did_edit` | bool | 本次任务是否成功执行写入/编辑 |
| `did_test` | bool | 本次任务是否执行测试/校验命令 |
| `tests_passed` | bool \| null | 测试是否通过，未执行测试时为 null |
| `permission_wait_count` | int | confirm 模式下等待用户确认的次数 |
| `time_to_first_tool` | float \| null | 从任务开始到首次工具调用的秒数 |
| `time_to_first_visible_update` | float \| null | 从任务开始到首次用户可见更新的秒数 |
| `final_user_visible_status` | str | UI 最终可见状态，同 outcome |

**feedback（评分）**：

| key | score | 说明 |
|-----|-------|------|
| `task_outcome` | 1.0 | success（正常完成） |
| `task_outcome` | 0.5 | partial（达到迭代上限） |
| `task_outcome` | 0.0 | error（异常终止） |

### 3.2 任务分类规则

`classify_task()` 根据用户输入关键词分类：

| 分类 | 关键词 | 典型任务 |
|------|--------|----------|
| `file_edit` | edit, 修改, 改, fix, bug, 修复, 进行优化 | "修复 state.py 的 bug" |
| `code_search` | search, find, 查找, 搜索, grep | "找到所有 BaseMessage 的文件" |
| `project_analysis` | analyze, 分析, review, 审查, explain, 解释 | "分析项目架构" |
| `file_write` | write, create, 新建, 创建, implement, 实现 | "实现 OAuth2 登录" |
| `command_run` | run, execute, 执行, test, 测试 | "运行测试" |
| `general_question` | （默认） | "Python 的 GIL 是什么" |

### 3.3 数据采集时机

```
用户输入 → 保存 _task_user_input + 分类 task_type
    │
    ▼
graph.stream(config=增强 config) → 追踪 iteration_count / tool_names / denied_count
    │
    ▼
任务结束（正常/异常）→ try/finally 调用 _report_task_to_langsmith()
    │
    ├── 上报 task_metrics 到 run.extra
    ├── 上报 task_outcome feedback score
    └── 异常时上报 outcome=error
```

### 3.4 LangSmith UI 验证方法

1. 打开 LangSmith 项目页面，确认 trace 列表显示 `run_name`（如 file_edit）而非默认名
2. 点击一个 trace，检查 Tags 区域包含 `task_type:file_edit`、`prompt:v7`
3. 检查 Feedback 区域有 `task_outcome` 评分
4. 检查 Run Extra 区域有 `task_metrics` 对象

---

## 4. Layer 2: 线上分析脚本

### 4.1 analyze_traces.py — 聚合分析

从 LangSmith 拉取近期 trace，按 task_type/model 分组计算指标。

**用法**：

```bash
# 最近 7 天全量分析
python -m evals.analyze_traces --days 7

# 只看 file_edit 类型
python -m evals.analyze_traces --days 30 --task-type file_edit

# 只看特定模型
python -m evals.analyze_traces --model deepseek/deepseek-v4-flash
```

**输出指标**：

| 指标 | 说明 |
|------|------|
| `avg_tokens` | 平均 token 消耗 |
| `median_tokens` | 中位 token 消耗 |
| `avg_latency_s` | 平均延迟（秒） |
| `error_rate` | 错误率 |
| `avg_iterations` | 平均迭代次数 |
| `max_iterations` | 最大迭代次数 |
| `tool_distribution` | 工具调用分布 |

**输出示例**：

```
============================================================
CodePilot Trace Analysis Report
============================================================
Total runs: 42

Overall:
  Avg tokens:     12,345
  Median tokens:  8,900
  Avg latency:    15.3s
  Error rate:     4.8%
  Avg iterations: 6.2
  Max iterations: 23

By Task Type:
  file_edit          : n= 15  avg_tokens=18,200  avg_latency=22.1s  error_rate=6.7%
  code_search        : n= 10  avg_tokens= 5,400  avg_latency= 8.3s  error_rate=0.0%
  project_analysis   : n=  8  avg_tokens=25,600  avg_latency=35.7s  error_rate=12.5%

By Model:
  deepseek/deepseek-v4-flash: n=25  avg_tokens=10,200  avg_latency=12.1s  error_rate=4.0%
  anthropic/claude-sonnet-4  : n=17  avg_tokens=15,800  avg_latency=21.4s  error_rate=5.9%

Tool Distribution:
  read_file      : 85
  list_dir       : 32
  edit_file      : 18
  search_code    : 15
============================================================
```

### 4.2 compare_runs.py — 对比分析

对比两个维度（时间段/模型/模式）的指标差异，输出 delta 百分比。

**用法**：

```bash
# 两个时间段对比
python -m evals.compare_runs --period1 7 --period2 30

# 两个模型对比
python -m evals.compare_runs --model1 "anthropic/claude-sonnet-4-20250514" --model2 "deepseek/deepseek-v4-flash"

# 两个模式对比
python -m evals.compare_runs --mode1 plan --mode2 auto
```

**输出示例**：

```
============================================================
Comparison: anthropic/claude-sonnet-4-20250514 vs deepseek/deepseek-v4-flash
============================================================

--- anthropic/claude-sonnet-4-20250514 ---
  Runs:           17
  Avg tokens:     15,800
  Avg latency:    21.4s
  Error rate:     5.9%
  Avg iterations: 7.1

--- deepseek/deepseek-v4-flash ---
  Runs:           25
  Avg tokens:     10,200
  Avg latency:    12.1s
  Error rate:     4.0%
  Avg iterations: 5.8

--- Deltas (anthropic/claude-sonnet-4-20250514 -> deepseek/deepseek-v4-flash) ---
  Avg tokens:  -35.4%
  Avg latency: -43.5%
  Error rate:  -32.2%
  Avg iters:   -18.3%
============================================================
```

### 4.3 detect_anomalies.py — 异常检测

自动识别 5 类异常 trace：

| 异常类型 | 阈值 | 说明 |
|----------|------|------|
| 高 token 消耗 | Top N | token 消耗最高的 trace |
| 高延迟 | Top N | 耗时最长的 trace |
| 错误 | `r.error != None` | 执行出错的 trace |
| 高迭代 | ≥15 次 | 接近或超过迭代上限的 trace |
| 重复工具调用 | 同一工具 ≥5 次 | 可能陷入循环的 trace |

**用法**：

```bash
python -m evals.detect_anomalies --days 7 --top 10
```

**输出示例**：

```
============================================================
Top 10 Highest Token Usage
============================================================
  file_edit           | tokens= 109,248 | model=deepseek/deepseek-v4-flash | task_type=file_edit       | id=abc123
  project_analysis    | tokens=  87,654 | model=deepseek/deepseek-v4-flash | task_type=project_analysis | id=def456

High Iteration Runs (>=15 iterations)
============================================================
  project_analysis    | iters=23 | tools=61 | tokens= 109,248 | model=deepseek/deepseek-v4-flash

Repeated Tool Calls (same tool >=5 times)
============================================================
  read_file       x8   | project_analysis    | model=deepseek/deepseek-v4-flash
============================================================
```

### 4.4 使用场景

| 场景 | 使用哪个脚本 |
|------|-------------|
| "最近一周 Agent 表现如何？" | `analyze_traces --days 7` |
| "deepseek 比 claude 快多少？" | `compare_runs --model1 X --model2 Y` |
| "哪些 trace 有问题？" | `detect_anomalies --days 7` |
| "改了 prompt 后效果变了吗？" | `compare_runs --period1 3 --period2 7` |

---

## 5. Layer 3: 评估框架

### 5.1 评估数据集

三个核心数据集，覆盖 CodePilot 的主要任务类型：

| 数据集 | 任务类型 | 核心评估点 | Example 数量 |
|--------|----------|-----------|-------------|
| `codepilot-file-edit` | 文件编辑 | 应使用 read_file + edit_file，不用 write_file | 2 |
| `codepilot-code-search` | 代码搜索 | 应使用 search_code/glob_files，不用 run_shell | 1 |
| `codepilot-project-analysis` | 项目分析 | 应 list_dir→read_file→synthesize，控制在 10 次内 | 1 |

**数据集 Example 结构**：

```python
{
    "inputs": {
        "messages": [{"role": "user", "content": "在 state.py 中添加 iteration_count 字段"}],
        "mode": "auto",                  # 权限模式
    },
    "outputs": {
        "expected_tools": ["read_file", "edit_file"],  # 期望使用的工具
        "forbidden_tools": ["write_file"],             # 禁止使用的工具
        "max_iterations": 5,                           # 迭代预算
        "expected_outcome": "AgentState now has iteration_count: int field",  # 期望结果描述
    },
}
```

**创建数据集**：

```bash
python -m evals.datasets.create_datasets
```

数据集创建后可在 LangSmith UI 的 Datasets 页面查看和编辑。

### 5.2 评估器详解

7 个自定义评估器从不同维度量化 Agent 质量：

#### 5.2.1 tool_selection_accuracy — 工具选择准确度

**评估逻辑**：检查 Agent 是否使用了期望工具、是否避免了禁止工具。

**评分规则**：

| 场景 | 分数 | 说明 |
|------|------|------|
| 所有期望工具都使用 + 没有使用禁止工具 | 1.0 | 完美 |
| 部分期望工具使用 + 没有使用禁止工具 | 0.5 | 部分正确 |
| 使用了禁止工具 | 0.0 | 严重错误 |
| 没有使用任何期望工具（但未用禁止工具） | 0.3 | 方向错误 |

**示例**：

```
期望: [read_file, edit_file]  禁止: [write_file]
实际: [read_file, edit_file]  → 1.0 "All expected tools used"
实际: [read_file]             → 0.5 "Partial match"
实际: [write_file]            → 0.0 "Used forbidden tools: {write_file}"
实际: [list_dir]              → 0.3 "No expected tools used. Used: {list_dir}"
```

#### 5.2.2 iteration_efficiency — 迭代效率

**评估逻辑**：检查 Agent 是否在迭代预算内完成任务。

**评分规则**：

| 迭代次数占预算比例 | 分数 | 说明 |
|-------------------|------|------|
| ≤ 50% | 1.0 | 非常高效 |
| ≤ 100% | 0.7 | 预算内 |
| ≤ 150% | 0.4 | 超预算 |
| > 150% | 0.0 | 严重超预算 |

**示例**：

```
预算: 5 次迭代
实际: 2 次 → 1.0 "Very efficient: 2 iterations (budget: 5)"
实际: 5 次 → 0.7 "Within budget: 5 iterations (budget: 5)"
实际: 7 次 → 0.4 "Over budget: 7 iterations (budget: 5)"
实际: 9 次 → 0.0 "Far over budget: 9 iterations (budget: 5)"
```

#### 5.2.3 task_completion — 任务完成度

**评估逻辑**：检查 Agent 最终回复是否覆盖 `expected_outcome` 中的关键信息。

**方法**：从 `expected_outcome` 提取关键词（去除停用词），计算在 Agent 最终文本中的覆盖率。

**评分规则**：

| 关键词覆盖率 | 分数 |
|-------------|------|
| ≥ 70% | 1.0 |
| ≥ 40% | 0.6 |
| < 40% | 0.2 |

**示例**：

```
expected_outcome: "AgentState now has iteration_count: int field"
关键词: {agentstate, now, iteration_count, int, field}
Agent 回复: "I've added the iteration_count: int field to AgentState"
覆盖率: 3/5 = 60% → 0.6
```

**局限**：关键词匹配是近似方法，无法理解语义。对于需要精确判定的场景，建议改用 LLM-as-Judge 评估器。

#### 5.2.4 no_read_redundancy — 读取去重度

**评估逻辑**：检查 Agent 是否重复读取同一文件。

**评分规则**：

| 最大重复读取次数 | 分数 | 说明 |
|----------------|------|------|
| ≤ 1 | 1.0 | 无重复读取 |
| = 2 | 0.7 | 部分文件读了两次 |
| ≥ 3 | 0.0 | 有文件被读 3 次以上 |

**示例**：

```
读取路径: [main.py, utils.py, main.py]
→ 0.7 "1 file(s) read twice"

读取路径: [main.py, main.py, main.py]
→ 0.0 "File read 3 times: ['main.py']"
```

#### 5.2.5 agent_permission_correctness — 权限正确性

**评估逻辑**：检查 `expected_agent_permissions` 中标记为 `deny` 的工具是否被成功执行。

**评分规则**：

| 权限违反次数 | 分数 | 说明 |
|-------------|------|------|
| 0 | 1.0 | 所有权限正确执行 |
| ≥ 1 | 0.0 | 存在权限违反 |

**示例**：

```
expected_perms: {edit_file: deny, run_shell: deny}
Agent 尝试 edit_file → 收到 "Permission denied" → 1.0 "All permission denials correctly enforced"
Agent 尝试 edit_file → 成功执行 → 0.0 "1 permission violation(s)"
```

#### 5.2.6 tool_result_quality — 工具结果质量

**评估逻辑**：检查工具执行的成功率（排除权限拒绝）。

**评分规则**：

| 成功率 | 分数 | 说明 |
|--------|------|------|
| ≥ 90% | 1.0 | 绝大部分工具执行成功 |
| ≥ 70% | 0.7 | 部分工具失败 |
| < 70% | 0.3 | 频繁失败 |

#### 5.2.7 response_conciseness — 响应简洁度

**评估逻辑**：检查 Agent 的最终响应是否简洁，避免超长文本。

**评分规则**：

| 场景 | 分数 | 条件 |
|------|------|------|
| General Q&A | 1.0 | ≤500 字符且 0 工具调用 |
| General Q&A | 0.8 | ≤1000 字符且 0 工具调用 |
| General Q&A | 0.6 | ≤2000 字符且 0 工具调用 |
| General Q&A | 0.3 | >2000 字符或意外调用工具 |
| Coding Task | 1.0 | ≤800 字符 |
| Coding Task | 0.8 | ≤1500 字符 |
| Coding Task | 0.6 | ≤3000 字符 |
| Coding Task | 0.3 | >3000 字符 |

### 5.3 评估执行

**run_eval.py** 调用 LangSmith `client.evaluate()` API，将 target 函数（构建 Agent 并执行）与评估器组合运行。

**用法**：

```bash
# 使用默认模型评估 file_edit 数据集
python -m evals.run_eval --dataset codepilot-file-edit

# 指定模型评估
python -m evals.run_eval --dataset codepilot-code-search --model deepseek/deepseek-v4-flash

# 评估项目分析
python -m evals.run_eval --dataset codepilot-project-analysis
```

**执行流程**：

```
run_eval.py
    │
    ├── 加载数据集 examples
    │
    ├── 对每个 example:
    │   ├── target(inputs) → 构建 Agent graph → invoke → 返回 messages
    │   ├── tool_selection_accuracy(inputs, outputs, reference_outputs) → score
    │   ├── iteration_efficiency(inputs, outputs, reference_outputs) → score
    │   ├── task_completion(inputs, outputs, reference_outputs) → score
    │   └── no_read_redundancy(inputs, outputs, reference_outputs) → score
    │
    └── 结果上报 LangSmith Experiment
```

**查看结果**：

在 LangSmith UI 的 Experiments 页面，可按 experiment_prefix（如 `codepilot-file-edit`）找到实验，查看每个 example 的 7 个评估器分数。

### 5.4 本地评估运行器 (run_local.py)

`run_local.py` 是一个不依赖 LangSmith API 的本地评估工具，直接在终端运行所有测试用例，输出汇总报告。适合快速迭代验证。

**特点**：
- 无需 LangSmith API Key，完全本地运行
- 支持 `--model` 多模型对比（如 deepseek-v4-flash vs glm-5.1）
- 内置 429 限速重试机制（4次递增延迟：5/15/30/60秒）
- 支持 `--delay` 参数控制用例间延迟，避免触发限速
- 支持 `--scenario` 单独运行某场景
- 输出每个用例的评估分数和最终汇总

**当前测试覆盖（6 个场景，40 个测试用例）**：

| 场景 | 用例数 | 测试内容 |
|------|--------|----------|
| general-question | 10 | 问候、技术概念、书籍推荐、感谢回复 |
| coding-task | 10 | glob/grep/read_file搜索、edit_file、plan权限阻止 |
| error-boundary | 5 | 不存在文件、无效pattern、危险操作、空搜索结果 |
| multi-file | 5 | 跨文件grep、多文件编辑、依赖关系分析 |
| refactoring | 5 | 函数提取、复杂度分析、文档补充、代码拆分 |
| project-nav | 5 | 入口调用链、子模块职责、数据流分析 |

**用法**：

```bash
# 运行全部 40 个用例
python -m evals.run_local --model deepseek/deepseek-v4-flash

# 单独运行某场景
python -m evals.run_local --model deepseek/deepseek-v4-flash --scenario error-boundary

# 限制 API 请求频率（避免限速）
python -m evals.run_local --model openai/glm-5.1 --delay 8
```

**输出示例**：

```
======================================================================
CodePilot Local Evaluation Report
======================================================================

--- Error Handling & Boundary (5 cases) ---

  Example 1:
    Time: 3.7s
    Tools: read_file
    Final: 文件 `nonexistent_file.py` 不存在...
    ✓ tool_selection_accuracy: 1.0 — All expected tools used
    ✓ iteration_efficiency: 1.0 — Very efficient: 1 iterations (budget: 2)
    ✓ response_conciseness: 1.0 — Coding task: 148 chars, 1 tool calls

======================================================================
Overall Average Score: 0.89 (280 evaluations)

Per-Scenario Averages:
  General Q&A (10 cases)                  : 0.99
  Coding Tasks (10 cases)                 : 0.87
  Error Handling & Boundary (5 cases)     : 0.93
  Multi-File Collaboration (5 cases)      : 0.82
  Code Refactoring (5 cases)              : 0.76
  Project Understanding & Navigation (5 cases): 0.87
======================================================================
```

### 5.6 A/B 测试 Prompt 改动

```bash
# 步骤 1：基线评估（当前 prompt:v7）
python -m evals.run_eval --dataset codepilot-file-edit

# 步骤 2：修改 prompts.py（如增强 files_context 提示）
# 同时更新 repl.py 中 tags 的 prompt:v7 → prompt:v8

# 步骤 3：再次评估
python -m evals.run_eval --dataset codepilot-file-edit

# 步骤 4：在 LangSmith UI 对比两次实验的评估器分数
# 或用 compare_runs.py 按 prompt:v7 vs prompt:v8 过滤对比
```

### 5.7 扩展评估器

评估器是普通 Python 函数，签名统一为 `(inputs, outputs, reference_outputs) -> dict`。扩展方式：

**LLM-as-Judge 评估器**（更高精度但更高成本）：

```python
async def response_quality(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """用 LLM 评判回复质量。"""
    from openai import AsyncOpenAI
    client = AsyncOpenAI()

    messages = outputs.get("messages", [])
    final_text = next((m.content for m in reversed(messages)
                       if isinstance(m, AIMessage) and m.content and not m.tool_calls), "")

    prompt = f"""评估以下 AI 回复的质量（0-1分）：
问题: {inputs['messages'][0]['content']}
回复: {final_text}
期望: {reference_outputs.get('expected_outcome', '')}

输出 JSON: {{"score": 0.0-1.0, "reason": "..."}}""

    response = await client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    import json
    result = json.loads(response.choices[0].message.content)
    return {"key": "response_quality", "score": result["score"], "comment": result["reason"]}
```

**工具调用轨迹评估器**（检查工具调用顺序）：

```python
def tool_call_order(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    """检查工具调用顺序是否符合预期。"""
    expected_order = reference_outputs.get("expected_tool_order", [])
    messages = outputs.get("messages", [])

    actual_order = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                actual_order.append(tc["name"])

    if not expected_order:
        return {"key": "tool_call_order", "score": 0.5, "comment": "No expected order defined"}

    # 检查实际顺序是否包含期望顺序作为子序列
    idx = 0
    for tool in actual_order:
        if idx < len(expected_order) and tool == expected_order[idx]:
            idx += 1

    score = idx / len(expected_order)
    return {"key": "tool_call_order", "score": score,
            "comment": f"Matched {idx}/{len(expected_order)} of expected order"}
```

---

## 6. Layer 4: 持续改进闭环

### 6.1 trace_to_eval.py — 问题 trace 转回归测试

将线上发现的问题 trace 一键转为评估数据集 example，防止同类问题再次出现。

**用法**：

```bash
# 转换到已有数据集
python -m evals.trace_to_eval --run-id abc123-def456 --dataset codepilot-file-edit

# 创建新回归数据集
python -m evals.trace_to_eval --run-id abc123-def456 --new-dataset "codepilot-regression-20260607"
```

**执行流程**：

```
1. 读取指定 run_id 的 trace
2. 提取用户输入（第一条 HumanMessage）和 mode
3. 生成 example 模板（expected_tools/expected_outcome 留空）
4. 添加到指定数据集
5. 提示用户在 LangSmith UI 中补充 expected_tools 和 expected_outcome
```

### 6.2 CI 自动评估

`.github/workflows/eval.yml` 在 `codepilot/agent/` 或 `codepilot/agent/prompts.py` 变更时自动触发评估：

```yaml
on:
  push:
    paths:
      - 'codepilot/agent/**'
      - 'codepilot/agent/prompts.py'
```

自动运行 `codepilot-file-edit` 和 `codepilot-code-search` 两个数据集的评估，结果出现在 LangSmith 实验页面。

### 6.3 改进闭环操作手册

```
┌───────────────────────────────────────────────────────┐
│                  持续改进闭环                           │
│                                                        │
│  1. 观察                                               │
│     python -m evals.analyze_traces --days 7            │
│     → 识别最差 task_type（最高 error_rate / avg_iter） │
│                                                        │
│  2. 假设                                               │
│     python -m evals.detect_anomalies --days 7          │
│     → 查看异常 trace，形成假设                          │
│     例："agent 重复读文件 → files_context 提示不够醒目" │
│                                                        │
│  3. 改动                                               │
│     编辑 codepilot/agent/prompts.py                    │
│     更新 repl.py tags 中 prompt:v7 → prompt:v8        │
│                                                        │
│  4. 验证                                               │
│     python -m evals.run_eval --dataset codepilot-file-edit │
│     → 对比改动前后评估分数                              │
│                                                        │
│  5. 固化                                               │
│     分数提升 → 保留改动                                │
│     分数下降 → 回退 + trace_to_eval 固化问题 case       │
│                                                        │
│  6. 迭代 → 回到步骤 1                                  │
└───────────────────────────────────────────────────────┘
```

---

## 7. 评测指标体系总览

### 7.1 线上指标（Layer 2 分析脚本采集）

| 指标 | 采集方式 | 计算方式 | 优化目标 |
|------|----------|----------|----------|
| avg_tokens | LangSmith Run.total_tokens | 所有 run 的平均值 | 降低 |
| avg_latency | LangSmith Run.latency | 所有 run 的平均值 | 降低 |
| error_rate | LangSmith Run.error | 错误 run / 总 run | 降低 |
| avg_iterations | task_metrics.iteration_count | 所有 run 的平均值 | 降低 |
| task_outcome | Feedback score | 平均 feedback score | 提高 |

### 7.2 评估指标（Layer 3 评估器采集）

| 指标 | 评估器 | 分数范围 | 优化目标 |
|------|--------|----------|----------|
| tool_selection_accuracy | 自定义 | 0.0 - 1.0 | 提高 |
| iteration_efficiency | 自定义 | 0.0 - 1.0 | 提高 |
| task_completion | 自定义 | 0.2 - 1.0 | 提高 |
| no_read_redundancy | 自定义 | 0.0 - 1.0 | 提高 |
| agent_permission_correctness | 自定义 | 0.0 / 1.0 | 提高（必须=1.0） |
| tool_result_quality | 自定义 | 0.0 - 1.0 | 提高 |
| response_conciseness | 自定义 | 0.0 - 1.0 | 提高 |

### 7.3 指标关联

```
prompt 改动
    │
    ├── 影响工具选择 → tool_selection_accuracy ↑
    ├── 影响迭代次数 → iteration_efficiency ↑, avg_iterations ↓
    ├── 影响读取去重 → no_read_redundancy ↑
    ├── 影响输出质量 → task_completion ↑
    └── 影响效率 → avg_tokens ↓, avg_latency ↓
```

---

## 8. 目录结构

```
evals/
├── __init__.py                      # 包初始化
├── analyze_traces.py                # Layer 2: 聚合分析
├── compare_runs.py                  # Layer 2: 对比分析
├── detect_anomalies.py              # Layer 2: 异常检测
├── run_local.py                     # Layer 3: 本地评测（6场景40用例，429重试）
├── evaluators.py                    # Layer 3: 7 个自定义评估器
├── run_eval.py                      # Layer 3: LangSmith 评估执行
├── trace_to_eval.py                 # Layer 4: trace→评估用例转换
├── utils.py                         # LangSmith Client 工具
└── datasets/
    ├── __init__.py
    └── create_datasets.py           # Layer 3: 评估数据集创建
```

---

## 9. 常见问题

**Q: 没有线上 trace 数据，如何开始？**

先正常使用 CodePilot 一段时间（确保 LangSmith 追踪开启），积累 trace 后再运行分析脚本。也可直接从 Layer 3 开始，用评估数据集主动测试 Agent。

**Q: 评估需要真实 API 调用，成本如何控制？**

- 评估数据集的 example 数量控制在 1-5 个
- 使用 `max_concurrency=1` 串行执行
- 优先用便宜模型（如 deepseek-v4-flash）跑评估基线
- CI 评估只在 agent/prompts 变更时触发，不是每次 commit

**Q: 如何新增一个评估数据集？**

在 `evals/datasets/create_datasets.py` 中添加一个 `create_xxx_dataset()` 函数，参考现有函数格式，然后在 `main()` 中注册。

**Q: 评估器分数都是 0.5 左右，说明什么？**

可能是 `expected_tools` 或 `expected_outcome` 定义不够准确。检查数据集 example 的 outputs 字段，确保期望值合理且具体。也可在 LangSmith UI 中直接编辑 example。

**Q: 如何对比两个 prompt 版本？**

1. 在 repl.py 中将 tags 的 `prompt:v7` 改为 `prompt:v8`
2. 用 CodePilot 执行若干任务
3. 运行 `compare_runs.py`，用 filter 按 `prompt:v7` 和 `prompt:v8` 对比
4. 或运行 `run_eval.py`，对比两次实验的评估器分数
