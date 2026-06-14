# CodePilot 生产可用性评估与优化方案

> 基于 LangSmith 近 30 天 100 条 trace 的量化分析 + 源码审计
> 分析时间：2026-06-13

---

## 一、总体结论

**当前状态：未达到生产可用级别。**

核心问题不是 Agent 能力不足，而是**可观测性缺失导致无法证明可用**。90% 的"成功"执行没有 outcome 追踪，无法区分"真正完成任务"和"没报错但做错了"。加上 10% 的显式错误率、交互式会话零指标、评测未接入 CI，整体处于"能用但不可靠"的阶段。

预计经过 4-6 周的 P0/P1 优化后可达到生产可用。

---

## 二、LangSmith 数据量化分析

### 2.1 错误率

| 类别 | 数量 | 占比 | 根因 |
|------|------|------|------|
| 网络/连接 | 4 | 4% | 本地代理挂掉 (ECONNREFUSED) |
| 用户中断 | 4 | 4% | KeyboardInterrupt |
| 配额/限流 | 2 | 2% | Coding Plan month quota exceeded |
| **合计** | **10** | **10%** | |

扣除环境问题（代理 + 配额），实际代码层面错误率为 **0%**。但"不报错 ≠ 正确完成任务"——见 2.3。

### 2.2 Token 与延迟

| 指标 | 平均值 | 中位数 | P95 | 最大值 |
|------|--------|--------|-----|--------|
| Token/run | 26,860 | 15,061 | 101,934 | 203,874 |
| 延迟 | 90.6s | 37.7s | 348.6s | 1,135s |

中位数 15K token、38s 延迟表现合理。P95 偏高（102K token / 349s），集中在 `file_edit` 和 `test_evaluation` 任务上，与复杂度匹配，**但缺少产出质量验证**。

### 2.3 关键盲区：Outcome 追踪为空

```
Runs with task_metrics in extra: 0/100
Runs with outcome in metadata:  0/100
Runs with did_edit=True:        0/100
Runs with did_test=True:        0/100
```

**根本原因**：`cli.py:_report_non_interactive_to_langsmith()` 将指标写为 LangSmith **Feedback**（`client.create_feedback`），而非 Run 的 `extra` 字段。`analyze_traces.py` 只读 `run.extra.task_metrics`，所以永远读不到。此外，交互式 REPL 模式完全没有指标上报。

### 2.4 工具使用分布（20 条成功 trace 抽样）

| 工具 | 调用次数 | 占比 | 类别 |
|------|----------|------|------|
| read_file | 95 | 50.5% | 读 |
| run_shell | 27 | 14.4% | Shell |
| glob | 26 | 13.8% | 读 |
| write_file | 15 | 8.0% | 写 |
| grep | 13 | 6.9% | 读 |
| edit_file | 4 | 2.1% | 写 |
| todo_write | 3 | 1.6% | 管理 |
| git_* | 5 | 2.7% | 读 |

`run_shell` 占 14.4%——**偏高**。需要区分合法的程序执行（pytest、pip、git）和不合规的搜索回退（shell grep/find/cat）。

### 2.5 Agent 路由分布

```
build:          87%  ← 绝大多数任务走了 ReAct
plan-execute:   11%  ← 复杂任务未充分利用
plan:            1%
```

`plan-execute` 使用率仅 11%，但 `project_analysis` 占任务的 31%，`file_edit` 占 48%——其中相当比例满足复杂度触发条件但未触发路由。

### 2.6 迭代效率（20 条抽样）

| 指标 | 值 |
|------|-----|
| 平均迭代 | 9.4 |
| 中位数 | 13 |
| 最大 | 21 |
| 最小 | 0 |

迭代次数在合理范围内，未见无限制循环。

---

## 三、源码层面发现的问题

### 3.1 可观测性缺陷（严重）

**问题**：指标写入方式与分析工具不匹配。
- 写入：`cli.py:365` → `client.create_feedback(key=..., score=..., comment=...)` → LangSmith Feedback
- 读取：`analyze_traces.py:100` → `run.extra.get("task_metrics")` → Run extra 字段
- **交互式 REPL**：`ui/repl.py` 完全没有调用 `_report_non_interactive_to_langsmith`

**影响**：所有分析脚本返回空数据，无法建立质量基线。

### 3.2 路由策略保守

`router.py:select_agent_for_task` 对 `project_analysis` 和 `file_edit` 只在 `_looks_complex()` 返回 True 时才升级到 `plan-execute`。实际触发条件：
- 中文关键词（架构/重构/多文件/全局/评估/优化方案/提交/推送 等）命中 ≥ 1 个
- 或输入 ≥ 80 字符
- 或动作词 ≥ 3 个

**问题**："分析当前项目的技术和框架，总结成markdown文档"这种请求，`_looks_complex()` 只命中了"分析""总结""项目""框架"→ 动作词 = 2，sequence = 0，长度 22 字符 → **不触发** → 走 build。

### 3.3 Shell 工具使用偏高

14.4% 的 shell 调用中，需要区分合法 shell（pytest、pip、git commit）和不合规 shell（grep/find/cat 回退）。当前没有在工具层面对 shell 命令内容做分类标记。

### 3.4 评测体系未接入 CI

`evals/` 目录有完整的评测框架，但未在 `.github/` 中配置任何 CI 流程。每次代码变更后没有自动回归。

---

## 四、优化方案

### P0：可观测性修复（1-2 周）

#### 4.1 统一指标写入方式

**目标**：让 `analyze_traces.py` 能读到数据。

修改 `cli.py:_report_non_interactive_to_langsmith()`：
```python
# 当前做法：写入 Feedback（analyze_traces 读不到）
client.create_feedback(run_id=root_run.id, key="task_outcome", score=1.0, ...)

# 改为：写入 Run extra 字段（analyze_traces 可直接读取）
client.update_run(
    run_id=root_run.id,
    extra={"task_metrics": metrics},  # 与 analyze_traces.py 读取路径对齐
)
```

同时保留 Feedback 写入作为补充（LangSmith UI 中可视化用）。

#### 4.2 补充交互式 REPL 指标

在 `ui/repl.py` 的任务完成路径中，调用同样的 `_report_non_interactive_to_langsmith()`。

#### 4.3 增加 Outcome 判定维度

当前 `_non_interactive_task_metrics` 只判定 `success/partial`。增加：
- `error`：异常退出
- `timeout`：达到迭代上限
- `no_op`：没有任何工具调用（纯对话）

```python
# 在 _non_interactive_task_metrics 中增加
if iteration_count >= task_limit:
    outcome = "timeout"
elif iteration_count == 0:
    outcome = "no_op"
```

---

### P1：质量保障体系（2-3 周）

#### 4.4 建立评测基线 Dataset

从 LangSmith 已有 trace 中选取 20-30 条代表性任务，转为 LangSmith Dataset：

```bash
python -m evals.trace_to_eval --days 30 --sample 30 --output datasets/baseline_v1
```

覆盖场景：
- 代码搜索（5 条）：验证 grep/glob 优先使用
- 单文件编辑（8 条）：验证 edit → test 闭环
- 项目分析（7 条）：验证结构化输出
- 多文件实现（5 条）：验证 plan-execute 步骤完成率
- 异常恢复（5 条）：验证错误处理

#### 4.5 CI 集成

在 `.github/workflows/eval.yml` 中增加：
```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev,eval]"
      - run: python -m evals.run_local --scenario baseline --threshold 0.8
```

#### 4.6 增加 Regression 检测

```python
# 新增 evals/detect_regression.py
# 对比当前 run 与 baseline 的 key metrics 差异
# token 增长 > 50%、错误率增长 > 10%、延迟增长 > 2x → 告警
```

---

### P2：Agent 能力增强（3-4 周）

#### 4.7 路由策略优化

`router.py` 增加更精确的复杂度判定：

```python
# 当前 _looks_complex 只看关键词，改为也考虑任务类型权重
COMPLEX_TASK_WEIGHTS = {
    "project_analysis": 1.5,  # 天然倾向 plan-execute
    "file_edit": 1.2,
    "test_evaluation": 2.0,
}

def select_agent_for_task(user_input, task_type, requested_agent=None):
    ...
    if task_type in {"project_analysis", "file_edit", "test_evaluation"}:
        weight = COMPLEX_TASK_WEIGHTS.get(task_type, 1.0)
        if _looks_complex(text) or weight >= 1.5:
            return "plan-execute"
```

#### 4.8 Shell 命令分类标记

在 `shell_tool.py` 中对命令做分类，写入 trace metadata：

```python
SHELL_CATEGORIES = {
    "test": ["pytest", "unittest", "tox", "coverage"],
    "build": ["pip", "make", "cargo", "go build"],
    "vcs": ["git", "hg"],
    "search_fallback": ["grep", "find", "cat", "ls", "head", "tail", "rg", "ag"],
    "runtime": ["python", "node", "go run"],
}
```

当检测到 `search_fallback` 时，在 trace 中标记 warning。

#### 4.9 Plan-Execute 执行状态追踪

在 `graph.py` 的 plan-execute 节点中，为每个计划步骤增加状态标记：
```python
# 写入 run metadata
{
    "plan_steps": [
        {"step": 1, "desc": "...", "status": "completed", "tools_used": 3},
        {"step": 2, "desc": "...", "status": "skipped", "reason": "..."},
    ]
}
```

---

### P3：持续运营（长期）

- LangSmith 告警规则：错误率 > 15% / P95 延迟 > 600s 时通知
- 周期性评测报告：每周自动生成并对比基线
- 失败 Case 自动入库：将 error trace 转为 dataset example

---

## 五、优先级排序

| 优先级 | 任务 | 工作量 | 影响 |
|--------|------|--------|------|
| P0 | 指标写入改为 run.extra | 0.5d | 消除全部数据盲区 |
| P0 | REPL 模式补指标 | 0.5d | 覆盖交互式场景 |
| P0 | Outcome 判定完善 | 0.5d | 区分"成功"和"没报错" |
| P1 | 建立评测 baseline | 1d | 可量化对比 |
| P1 | CI 集成 | 0.5d | 每次变更自动验证 |
| P1 | Regression 检测 | 1d | 防止能力退化 |
| P2 | 路由策略优化 | 0.5d | plan-execute 使用率提升 |
| P2 | Shell 分类标记 | 0.5d | 暴露搜索回退行为 |
| P2 | Plan 步骤追踪 | 1d | plan-execute 可观测 |

**总计约 6 个工作日**可达生产可用标准。

---

## 六、验证标准

优化完成后，以下指标需达标：

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 错误率（扣除环境） | ~6% | ≤ 5% |
| Outcome 覆盖率 | 0% | ≥ 95% |
| plan-execute 使用率（复杂任务） | 11% | ≥ 40% |
| Shell search_fallback 率 | 未知 | ≤ 3% |
| 评测通过率 | 无基线 | ≥ 80% |
| CI 回归覆盖 | 0 | 每次 PR |
