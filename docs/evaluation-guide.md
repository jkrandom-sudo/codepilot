# CodePilot Agent 评测方法文档

CodePilot 的评测体系由本地回归测试、LangSmith 线上 trace、自动化评估器和人工复盘共同组成。目标是形成“观察 → 定位 → 优化 → 复测 → 固化”的闭环。

## 1. 评测分层

| 层级 | 作用 | 工具 |
|------|------|------|
| 本地单元测试 | 验证核心模块行为不回归 | `pytest` |
| 本地场景评测 | 验证典型开发任务流程 | `evals.run_local` |
| LangSmith trace 分析 | 评估真实用户运行效果 | `evals.analyze_traces` |
| 对比分析 | 比较模型、Agent、时间窗口表现 | `evals.compare_runs` |
| 异常检测 | 找出高耗时、高工具调用、失败任务 | `evals.detect_anomalies` |
| 回归样例 | 将问题 trace 固化为 dataset | `evals.trace_to_eval` |

## 2. LangSmith 数据结构

### metadata

| 字段 | 说明 |
|------|------|
| `model` | 当前模型，如 `arc/glm-5.1` |
| `session_id` | REPL 会话 ID |
| `agent_name` | 当前 Agent，如 `build`、`plan-execute` |
| `confirm` | 当前确认策略标签 |
| `task_type` | 任务分类 |
| `user_input_preview` | 用户输入预览 |

### tags

| 标签 | 示例 | 用途 |
|------|------|------|
| Agent | `agent:build` | 按 Agent 过滤 |
| 确认策略 | `confirm:confirm` | 按确认策略过滤 |
| 模型 | `model:arc/glm-5.1` | 按模型过滤 |
| 任务类型 | `task_type:file_edit` | 按任务过滤 |
| Prompt 版本 | `prompt:v7` | 按提示词版本对比 |

### task_metrics

| 字段 | 说明 |
|------|------|
| `iteration_count` | 触发工具调用的模型轮次 |
| `tool_call_count` | 工具调用总数 |
| `tool_distribution` | 各工具调用次数 |
| `denied_count` | 权限拒绝次数 |
| `permission_wait_count` | 等待用户确认次数 |
| `total_tokens` | token 消耗 |
| `elapsed_seconds` | 总耗时 |
| `time_to_first_tool` | 首次工具调用耗时 |
| `time_to_first_visible_update` | 首次用户可见更新耗时 |
| `did_edit` | 是否执行写入或编辑 |
| `did_test` | 是否执行测试或校验 |
| `tests_passed` | 测试是否通过 |
| `outcome` | `success`、`partial`、`error` |

## 3. 任务分类

| 分类 | 典型任务 | 评测重点 |
|------|----------|----------|
| `file_edit` | 修复 bug、修改代码、优化实现 | 读取 → 编辑 → 验证闭环 |
| `code_search` | 查找定义、搜索调用点 | `grep`/`glob` 使用率 |
| `project_analysis` | 分析架构、梳理模块 | 结构化输出和路径准确性 |
| `file_write` | 新建文件、生成文档 | 写入范围和内容完整性 |
| `command_run` | 运行测试、构建、脚本 | 命令选择和结果解释 |
| `general_question` | 技术问答、解释概念 | 准确性和上下文关联 |

## 4. 常用命令

```bash
# 单元测试
pytest tests/ -q

# Lint
ruff check codepilot evals tests

# 本地场景评测
python -m evals.run_local
python -m evals.run_local --scenario code-search
python -m evals.run_local --scenario file-edit
python -m evals.run_local --scenario project-analysis

# LangSmith trace 分析
python -m evals.analyze_traces --days 7
python -m evals.analyze_traces --days 30 --task-type file_edit
python -m evals.analyze_traces --model arc/glm-5.1

# 对比两个时间窗口或模型
python -m evals.compare_runs --period1 7 --period2 30
python -m evals.compare_runs --model1 "arc/glm-5.1" --model2 "deepseek/deepseek-v4-flash"

# 异常检测
python -m evals.detect_anomalies --days 7

# 将线上 trace 转成回归样例
python -m evals.trace_to_eval --run-id <run-id> --dataset codepilot-regression
```

## 5. Dataset 示例

```python
{
    "inputs": {
        "messages": [
            {"role": "user", "content": "在 state.py 中添加 session_id 字段"}
        ],
        "agent": "build",
        "task_type": "file_edit",
    },
    "outputs": {
        "expected_tools": ["read_file", "edit_file"],
        "forbidden_tools": ["write_file"],
        "max_iterations": 6,
        "expected_outcome": "AgentState 包含 session_id 字段",
    },
}
```

## 6. 评估器

| 评估器 | 评分重点 |
|--------|----------|
| `tool_selection_accuracy` | 是否使用期望工具并避免禁止工具 |
| `iteration_efficiency` | 是否在合理迭代预算内完成 |
| `completion_quality` | 输出是否满足目标 |
| `safety_compliance` | 是否遵守权限和危险命令约束 |
| `context_efficiency` | 是否避免重复读取和无效工具调用 |
| `test_behavior` | 修改后是否执行验证 |
| `user_experience` | 是否有可见进展和清晰最终反馈 |

## 7. 工具选择评测口径

| 场景 | 期望工具 | 不期望行为 |
|------|----------|------------|
| 读取文件 | `read_file` | 通过 Shell 读取项目文件 |
| 查找文件 | `glob` | 通过 Shell 拼接查找命令 |
| 搜索代码 | `grep` | 通过 Shell 拼接搜索管道 |
| 编辑已有文件 | `edit_file` | 无必要地整体重写 |
| 新建文件 | `write_file` | 多次空写再补丁 |
| 运行测试 | `run_shell` | 修改代码后不验证 |
| 子任务探索 | `task` | 主上下文大量展开无关文件 |

## 8. 复盘模板

```markdown
## 评测对象

- commit:
- model:
- agent:
- scenario:
- LangSmith run:

## 结果

- outcome:
- tool_call_count:
- iteration_count:
- elapsed_seconds:
- did_edit:
- did_test:

## 发现

1. 
2. 
3. 

## 优化动作

1. 
2. 
3. 

## 复测结论

- 
```

## 9. 线上问题处理流程

1. 在 LangSmith 中筛选 `outcome:error` 或 `outcome:partial`。
2. 查看 `tool_distribution`、`denied_count`、`permission_wait_count`。
3. 判断问题属于提示词、权限规则、工具实现、上下文压缩还是用户体验。
4. 使用 `trace_to_eval` 固化为回归样例。
5. 修改代码或提示词后运行本地测试和对应场景评测。
6. 对比优化前后的 trace，确认失败率、工具次数和任务完成度改善。
