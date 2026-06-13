# CodePilot 能力演进路线

本文档记录 CodePilot 当前已经具备的架构能力，以及后续可持续增强的方向。所有说明均以当前代码实现为准。

## 当前能力基线

| 能力 | 当前状态 | 关键模块 |
|------|----------|----------|
| Agent 注册表 | 已支持主 Agent 与子 Agent 分层 | `codepilot/agent/registry.py` |
| ReAct 工作流 | 已支持推理、工具调用、工具结果回传循环 | `codepilot/agent/graph.py` |
| Plan-and-Execute 工作流 | 已支持先规划再执行 | `codepilot/agent/graph.py` |
| 权限规则集 | 已支持 allow/ask/deny 与路径/命令匹配 | `codepilot/config/permissions.py` |
| 会话持久化 | 已支持 SQLite 会话保存和恢复 | `codepilot/storage/` |
| 上下文压缩 | 已支持 pruning、compaction、overflow 三层处理 | `codepilot/agent/compaction.py` |
| 工具结果截断 | 已支持字符/行数自适应截断和磁盘溢出保存 | `codepilot/tools/truncation.py` |
| Skills | 已支持项目级和内置技能加载 | `codepilot/skills/` |
| MCP | 已支持配置化 MCP Server 和工具接入 | `codepilot/mcp/` |
| 项目指令文件 | 已支持 `AGENTS.md`、`CLAUDE.md` 和 `.claude/` | `codepilot/context/` |
| LangSmith 追踪 | 已支持 tags、metadata、task_metrics 上报 | `codepilot/ui/repl.py`, `codepilot/cli.py` |

## 当前 Agent 体系

| Agent | 分类 | 工作流 | 典型用途 | 默认权限 |
|-------|------|--------|----------|----------|
| `build` | primary | `react` | 日常开发、修复、测试、文档更新 | 读操作放行，写操作确认 |
| `plan` | primary | `react` | 只读分析、方案设计、任务拆解 | 写操作拒绝 |
| `plan-execute` | primary | `plan_execute` | 复杂多步骤开发任务 | 读操作放行，写操作确认 |
| `explore` | subagent | `react` | 独立探索项目结构和资料 | 只读 |
| `general` | subagent | `react` | 通用子任务处理 | 常规安全规则 |

## 设计原则

1. **Agent 决定行为**：工作流、提示词、工具集合、权限规则都从 `AgentDef` 派生。
2. **规则集决定执行边界**：工具是否执行由 `PermissionRuleset` 统一判断。
3. **上下文优先保真**：优先擦除冗余工具输出，必要时再进行 LLM 总结。
4. **真实运行可观测**：每轮任务都应能在 LangSmith 中按 Agent、任务类型、模型和确认策略聚合分析。
5. **能力逐步生产化**：新增能力必须配套测试、文档和可回归的评测样例。

## 后续优化路线

### P0：稳定性与可恢复性

- 强化工具调用预算提示，避免长任务过早中断。
- 对确认交互、工具阻断、异常恢复增加端到端回归测试。
- 扩展会话恢复后的上下文完整性验证。

### P1：Plan-and-Execute 深化

- 增加计划步骤的执行状态标注。
- 将计划变更、跳过、重试写入 trace metadata。
- 为大型重构任务增加“计划复审”节点。

### P2：多 Agent 协作

- 引入 reviewer 子 Agent，用于实现后的风险检查。
- 支持按任务类型自动选择 explore/general/reviewer。
- 为子 Agent 结果增加结构化摘要和引用来源。

### P3：评测闭环

- 将高频线上失败 trace 固化为 LangSmith dataset。
- 对比 `build` 与 `plan-execute` 在多文件任务上的成功率、工具次数、耗时。
- 将本地评测脚本纳入 CI，保证核心场景不回归。

## 验证命令

```bash
pytest tests/ -q
ruff check codepilot evals tests
python -m evals.run_local --scenario file-edit
```
