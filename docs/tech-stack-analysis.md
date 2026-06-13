# CodePilot 技术与框架分析

> 输入来源：`README.md`、`AGENTS.md`、`pyproject.toml`、`codepilot/` 源码目录树。
> 适用版本：CodePilot `0.1.7`（Python ≥ 3.11）。

## 1. 项目定位

CodePilot 是一个运行在终端的 **AI Coding Agent**，对标 Claude Code、OpenCode、Aider 的 CLI 形态。
核心能力：

- 多模型 Provider（OpenAI 兼容 / Anthropic / Google）
- 多 Agent + 多工作流（ReAct、Plan-and-Execute、子 Agent）
- 工具生态（文件、Shell、Git、Web、搜索、Skills、MCP、Task、Todo）
- 项目指令文件（`AGENTS.md` / `CLAUDE.md`）
- LangSmith 追踪 + SQLite 会话恢复
- REPL 斜杠命令 + `@` 引用 + 权限确认

## 2. 技术栈总览

| 层 | 技术 |
|----|------|
| 语言 / 运行时 | Python 3.11+ |
| 构建 / 打包 | Hatchling（`pyproject.toml`） |
| Agent 编排 | LangGraph（`langgraph>=0.3.0`） |
| LLM 抽象 | LangChain Core / LangChain Community |
| Provider SDK | `langchain-openai`、`langchain-anthropic`、`langchain-google-genai` |
| 终端交互 | `prompt_toolkit`（输入/补全）+ `rich`（渲染） |
| CLI 入口 | `click`（`codepilot.cli:main`） |
| 配置 / 校验 | `pydantic` v2 + `pydantic-settings` + `pyyaml` |
| HTTP / Web | `httpx`、`ddgs`（DuckDuckGo 搜索） |
| 可观测性 | `langsmith` |
| 持久化 | SQLite（`~/.codepilot/data/codepilot.db`） |
| 协议扩展 | MCP（`mcp>=1.0.0`，可选依赖） |
| 测试 / Lint | `pytest`、`pytest-asyncio`、`ruff` |
| 评估 | `agentevals`（可选） + 本地 `evals/` 模块 |

详见 `pyproject.toml:12-42`。

## 3. 代码结构

```
codepilot/
├── cli.py            # click 入口，参数解析与会话装配
├── agent/            # LangGraph 图、节点、路由、状态、prompts
├── tools/            # 13 个工具实现（文件/搜索/Shell/Git/Web/Task/Skill/MCP/Todo …）
├── ui/               # REPL、命令、补全、渲染、意图识别、权限
├── context/          # 项目指令、文件选择器、项目元信息
├── storage/          # SQLite 模型、DB 访问、resume 逻辑
├── config/           # provider/permissions/context_window/settings
├── plugins/          # 插件 manager 与 hook 体系
├── skills/           # 内置 Skills（debug、code-review、testing、refactor、docs）
└── utils/            # diff、token 计算、文本截断
```

## 4. Agent 架构（`codepilot/agent/`）

- **状态机**：`graph.py` + `state.py` 定义 LangGraph 流程，`nodes.py` 实现各节点。
- **路由**：`router.py` 在 `auto` 模式下根据任务复杂度选择 ReAct 或 Plan-and-Execute。
- **注册表**：`registry.py` 管理 Agent 类型（`build`、`plan`、`plan-execute`、`explore`、`general`）及其权限。
- **上下文压缩**：`compaction.py` + `context_manager.py` 控制对话长度，配合 `/compact`、`/clear`。
- **提示词**：`prompts.py` 集中维护系统提示，区分 Primary 与 Subagent。

工作流分工（README §Agent 和工作流）：

| Agent | 工作流 | 作用 |
|-------|--------|------|
| build | ReAct | 默认开发循环（读放行/写需确认） |
| plan | ReAct（只读） | 方案分析，禁止写文件与 Shell |
| plan-execute | Plan→ReAct | 先规划 3-7 步再执行 |
| explore (sub) | ReAct | 由 `task` 派生的只读搜索 |
| general (sub) | ReAct | 由 `task` 派生的多步执行 |

## 5. 工具系统（`codepilot/tools/`）

13 个工具按职责划分：

- 文件类：`file_tools.py`、`search_tools.py`、`truncation.py`
- 执行类：`shell_tool.py`、`git_tool.py`
- 网络类：`web_tool.py`、`web_fetch_tool.py`
- 任务编排：`task_tool.py`（派生子 Agent）、`todo_tool.py`（计划清单）
- 能力扩展：`skill_tool.py`（SKILL.md 发现/读取）、`mcp_tool.py`（stdio MCP）
- 上下文：`context.py` 提供注入到工具调用的运行时上下文

工具权限通过 `ui/permissions.py` 与 `config/permissions.py` 双层控制，写操作走交互确认（除 `--no-confirm`）。

## 6. UI 与 REPL（`codepilot/ui/`）

- `repl.py`：交互主循环，结合 prompt_toolkit。
- `commands.py`：斜杠命令（`/model`、`/agent`、`/context`、`/compact`、`/diff`、`/undo`、`/trace`、`/sessions`、`/resume`、`/init` 等）。
- `completer.py`：补全（命令、文件、`@` 引用）。
- `intent.py`：解析 `@file`、`@url`、`@git`、`@dir` 等内联引用。
- `renderer.py`：基于 `rich` 的工具调用 / diff / Markdown 渲染。
- `permissions.py`：写操作确认 UI。

## 7. 配置体系（`codepilot/config/`）

- `settings.py` + `~/.codepilot/config.yaml`：默认 provider/model、langsmith、mcp 配置。
- `providers.py`：provider/model 注册与解析（`provider/model` 规格）。
- `context_windows.py`：各模型上下文窗口，用于压缩判定。
- `permissions.py`：读/写/Shell 权限策略。
- 凭证支持 `CODEPILOT_<PROVIDER>_API_KEY`、`CODEPILOT_LANGSMITH_API_KEY` 环境变量覆盖。

## 8. 上下文与项目记忆（`codepilot/context/`）

- `instructions.py`：自动加载 `AGENTS.md` / `agents.md` / `CLAUDE.md` / `claude.md`。
- `project.py`：项目元信息、目录摘要。
- `selector.py`：文件相关性挑选，喂给上下文窗口。

## 9. 持久化与可观测性（`codepilot/storage/` + LangSmith）

- SQLite：`db.py` 连接管理、`models.py` 表结构、`resume.py` 实现 `--resume` / `--resume-last`。
- LangSmith：通过 `langsmith` SDK 自动追踪 Agent、模型、工具调用链、token、延迟。

## 10. 扩展机制

- **Skills**：按 5 级覆盖顺序（项目 → 用户 → 内置）查找 `SKILL.md`，工具 `skill_list` / `skill_read` 暴露给 Agent。内置技能在 `codepilot/skills/builtin/`。
- **MCP**：`mcp_list_servers` / `mcp_list_tools` / `mcp_call_tool`，目前实现 stdio，HTTP/SSE 待扩展。
- **Plugins**：`plugins/manager.py` + `plugins/hooks.py`，提供生命周期 hook，便于第三方注入工具/节点。

## 11. 测试与评估

- 单元/集成测试：`tests/`，`pytest tests/ -q`。
- 静态检查：`ruff check codepilot evals tests`，`line-length=100`、`target-version=py311`。
- 评估：`evals/`（含 `analyze_traces.py`、`_inspect.py`），可选 `agentevals` 集成；本地脚本 `python -m evals.run_local --model ...`。

## 12. 关键设计取舍

- **LangGraph 而非自实现 Agent loop**：拿到状态机抽象、检查点、子图能力，便于 Plan-and-Execute 与子 Agent。
- **多 Provider 解耦**：通过 `provider/model` 规格 + LangChain Provider 适配器，避免锁定单一厂商。
- **工具/权限分层**：读默认放行、写需确认、Shell 受 plan agent 禁用——降低破坏性操作风险。
- **项目指令 + Skills 双轨**：`AGENTS.md` 提供项目级稳定上下文，Skills 提供可复用工作流；二者互补。
- **可观测性内建**：LangSmith + SQLite 双通道，CLI 即可 `--resume` 复盘，方便长任务调试。

## 13. 潜在改进方向（基于结构推断）

1. MCP 仅支持 stdio，HTTP/SSE/OAuth 缺口在 README 已点名。
2. 评估栈较新，`evals/` 与 `docs/evaluation-*.md` 可继续沉淀基线指标。
3. `plugins/` 暴露的 hook 文档化程度可加强，便于外部扩展。
4. `ddgs` 单一搜索后端，未来可抽象为可插拔搜索 provider。
5. 权限模型目前是布尔/角色式，未见细粒度沙箱（如目录白名单），生产化可继续打磨。

---

> 备注：本文未深入到具体函数实现，如需对单个模块（如 `agent/graph.py` 的节点拓扑、`router.py` 的复杂度判定算法）做源码级分析，请进一步指定模块。
