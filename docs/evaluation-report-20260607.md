# CodePilot 评测基线报告

本文档用于记录当前版本的评测基线和后续复测方法。历史 trace 仅作为趋势参考，当前结论以最新代码和最新 LangSmith 数据为准。

## 评估目标

| 维度 | 关注点 |
|------|--------|
| 任务完成度 | 是否完成用户目标，是否给出可执行结果 |
| 工具选择 | 是否优先使用 `read_file`、`glob`、`grep`、`edit_file` 等专用工具 |
| 执行效率 | 工具调用次数、迭代次数、耗时是否合理 |
| 上下文质量 | 是否避免重复读取，是否在压缩后保留关键事实 |
| 用户体验 | 长任务是否有可见进展，确认交互是否顺畅 |
| 验证闭环 | 修改后是否运行测试、lint 或最小可行验证 |

## 推荐评测集

| 场景 | 建议 Agent | 评测重点 |
|------|------------|----------|
| 代码搜索 | `build` 或 `explore` | `grep`/`glob` 使用率、读取文件数量 |
| 单文件修复 | `build` | edit/test 闭环 |
| 多文件重构 | `plan-execute` | 计划质量、步骤完成率、验证完整性 |
| 项目结构分析 | `plan` 或 `explore` | 结构化总结、引用路径准确性 |
| 文档更新 | `build` | 文档一致性、当前实现对齐 |
| 权限确认 | `build` | 允许后是否继续执行、是否重复打断 |

## LangSmith 指标

每次任务应关注以下字段：

| 字段 | 期望 |
|------|------|
| `agent_name` | 能区分 build/plan/plan-execute/explore/general |
| `task_type` | 能反映任务类别 |
| `tool_call_count` | 搜索和分析任务保持克制，复杂修改任务允许更高预算 |
| `iteration_count` | 与任务复杂度匹配，不能因预算过低提前终止 |
| `denied_count` | 非危险任务应接近 0 |
| `permission_wait_count` | 只在确实需要用户确认时增加 |
| `did_edit` | 修改类任务应为 true |
| `did_test` | 修改类任务应优先为 true |
| `outcome` | success 为主，partial/error 需要进入回归分析 |

## 当前优化方向

1. **复杂任务优先使用 `plan-execute`**：让计划节点先生成执行路线，再进入工具循环。
2. **搜索和读取使用专用工具**：降低 Shell 管道带来的权限误判和上下文丢失。
3. **确认交互减少打断**：用户选择“始终允许”后，同类操作应直接放行。
4. **长任务增强可见状态**：等待模型和工具结果期间持续刷新状态。
5. **线上失败固化为回归样例**：将失败 trace 转成 LangSmith dataset example。

## 复测命令

```bash
pytest tests/ -q
ruff check codepilot evals tests
python -m evals.run_local --scenario code-search
python -m evals.run_local --scenario file-edit
python -m evals.run_local --scenario project-analysis
```

## 报告更新规则

- 每次能力优化后记录最新 commit、模型、Agent、任务场景和结论。
- 如果 LangSmith 数据与本地评测结论不一致，以真实用户 trace 为优先分析对象。
- 报告只保留当前版本可执行的字段、命令和工具名。
