# CodePilot 当前架构设计

本文档描述 CodePilot 当前架构，用于后续开发和评审。文档内容以当前代码实现为准。

## 目标

CodePilot 是一个面向真实项目开发的 CLI Agent，目标是提供接近 Claude Code、OpenCode 的编程体验：

- 能理解项目指令文件和当前仓库结构。
- 能在 ReAct 与 Plan-and-Execute 两类工作流之间切换。
- 能通过细粒度权限规则控制工具执行。
- 能支持 Skills、MCP、子 Agent 和 LangSmith 可观测性。
- 能在长任务中保持上下文稳定，并向用户持续反馈执行状态。

## 核心模块

| 模块 | 责任 |
|------|------|
| `codepilot/cli.py` | CLI 参数、模型配置、非交互执行入口 |
| `codepilot/ui/repl.py` | 交互循环、斜杠命令、任务运行、LangSmith 上报 |
| `codepilot/ui/renderer.py` | TUI 输出、动态等待提示、任务状态渲染 |
| `codepilot/ui/permission.py` | 权限确认交互和始终允许规则 |
| `codepilot/agent/graph.py` | LangGraph 工作流、工具节点、压缩与终止 |
| `codepilot/agent/registry.py` | Agent 定义、工作流选择、工具集合选择 |
| `codepilot/agent/prompts.py` | 系统提示、Agent 提示、项目上下文注入 |
| `codepilot/tools/` | 文件、Shell、搜索、Git、Web、任务委派等工具 |
| `codepilot/skills/` | 技能发现、加载、项目级技能支持 |
| `codepilot/mcp/` | MCP Server 配置与工具桥接 |
| `codepilot/storage/` | SQLite 会话和消息持久化 |

## AgentState

当前状态只保留运行所需字段：

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    working_dir: str
    files_context: list[str]
    task_type: str
    agent_name: str
    session_id: str
```

`agent_name` 用于从 `AgentRegistry` 读取工作流、提示词、权限规则和工具集合。

## AgentDef

```python
class AgentDef(BaseModel):
    name: str
    display_name: str
    agent_mode: Literal["primary", "subagent"]
    workflow: Literal["react", "plan_execute"]
    prompt: str | None
    model: str | None
    steps: int
    temperature: float | None
    permissions: PermissionRuleset
    tools: list[str] | None
    description: str
    confirm: bool
```

| Agent | 工作流 | 分类 | 用途 |
|-------|--------|------|------|
| `build` | `react` | primary | 默认开发任务 |
| `plan` | `react` | primary | 只读分析和方案 |
| `plan-execute` | `plan_execute` | primary | 复杂任务先规划再执行 |
| `explore` | `react` | subagent | 只读探索 |
| `general` | `react` | subagent | 通用子任务 |

## 工作流

### ReAct

```
START → agent → tools → agent → END
```

`agent` 节点负责构造提示、绑定工具、检查上下文预算、调用模型。`tools` 节点负责权限判断、执行工具、截断工具结果、维护已读文件上下文。

### Plan-and-Execute

```
START → planner → agent → tools → agent → END
```

`planner` 节点先生成显式计划，再由 `agent` 节点按计划执行。该工作流适合多文件修改、长链路排查、测试修复等任务。

## 工具集合

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件，可按行范围读取 |
| `glob` | 按文件模式查找路径 |
| `grep` | 搜索代码和文本 |
| `edit_file` | 基于补丁编辑文件 |
| `write_file` | 写入新文件或整体替换文件 |
| `run_shell` | 执行 Shell 命令 |
| `git_*` | 查看 Git 状态、差异和历史 |
| `web_*` | 读取网页和搜索网络信息 |
| `task` | 派生子 Agent 执行独立任务 |
| `skill` | 加载和执行技能指令 |
| `mcp_call_tool` | 调用 MCP Server 暴露的工具 |

## 权限规则

权限由 `PermissionRuleset` 按工具名和参数匹配：

```python
class PermissionRule(BaseModel):
    tool: str
    pattern: str
    action: Literal["allow", "ask", "deny"]
```

规则用于表达“读操作自动允许”“写操作确认”“危险命令拒绝”“只读 Agent 禁止写入”等策略。

## 项目指令文件

CodePilot 会读取项目中的指令文件，并注入系统提示：

- `AGENTS.md`
- `CLAUDE.md`
- `.claude/` 下的项目约定

`/init` 命令用于初始化 `AGENTS.md`。

## 交互体验

- 长任务运行时显示动态等待提示，避免用户误以为程序卡住。
- 权限确认支持方向键选择和回车确认。
- 任务完成后显示耗时、token、工具调用、步骤、上下文占用。

## 验收

```bash
pytest tests/ -q
ruff check codepilot evals tests
```
