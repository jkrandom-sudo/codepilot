# CodePilot

基于 Python + LangChain + LangGraph 的 CLI 编程 Agent，参考 Claude Code、OpenCode、Aider 的产品形态，支持 ReAct、Plan-and-Execute、多 Agent、Skills、MCP、项目指令文件、LangSmith 追踪和 SQLite 会话恢复。

## 快速开始

```bash
cd smart_agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 交互模式
codepilot

# 非交互模式
codepilot -p "列出当前目录文件"

# Plan-and-Execute 工作流
codepilot --agent plan-execute -p "为当前项目添加一个小功能并验证"

# 写操作无需确认
codepilot --no-confirm -p "运行测试并修复失败"

# 只读分析
codepilot --agent plan
```

如需 MCP SDK 支持：

```bash
pip install -e ".[dev,mcp]"
```

## CLI 参数

| 参数 | 缩写 | 说明 |
|------|------|------|
| `--model` | `-m` | 模型规格，格式 `provider/model`，如 `arc/glm-5.1` |
| `--agent` | `-a` | Agent 类型：`build`、`plan`、`plan-execute` |
| `--confirm/--no-confirm` | | 写操作是否需要确认；`--no-confirm` 等价于自动执行允许的写操作 |
| `--prompt` | `-p` | 非交互模式，执行后退出 |
| `--resume` | `-r` | 恢复指定 ID 的会话 |
| `--resume-last` | | 恢复最近一次会话 |
| `--version` | | 显示版本 |
| `--help` | | 显示帮助 |

## 配置

配置文件位于 `~/.codepilot/config.yaml`，首次运行自动生成。

```yaml
providers:
  arc:
    api_key: ""  # 推荐使用环境变量 CODEPILOT_ARC_API_KEY
    base_url: https://example.com/v1
    models: [glm-5.1]
    provider_type: openai_compatible
  deepseek:
    api_key: ""  # 推荐使用环境变量 CODEPILOT_DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com/v1
    models: [deepseek-chat]
    provider_type: openai_compatible

default:
  provider: arc
  model: glm-5.1

langsmith:
  enabled: true
  api_key: ""  # 推荐使用环境变量 CODEPILOT_LANGSMITH_API_KEY
  project: codepilot
  endpoint: https://api.smith.langchain.com

mcp:
  filesystem:
    enabled: true
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env: {}
```

API Key 也可通过环境变量覆盖：

| 环境变量 | 说明 |
|----------|------|
| `CODEPILOT_<PROVIDER>_API_KEY` | Provider API Key，如 `CODEPILOT_ARC_API_KEY` |
| `CODEPILOT_LANGSMITH_API_KEY` | LangSmith API Key |

不要把真实 API Key、LangSmith Key、访问令牌或个人本地路径提交到仓库。生产/本地凭证建议只放在 shell 环境变量、CI Secrets 或 `~/.codepilot/config.yaml` 中。

## Agent 和工作流

CodePilot 以 Agent 为行为中心。权限、提示词、工具集合和执行工作流都由 Agent 定义。

| Agent | 类型 | 工作流 | 说明 | 权限 |
|-------|------|--------|------|------|
| `build` | Primary | ReAct | 默认开发 Agent，边推理边调用工具 | 读允许，写确认 |
| `plan` | Primary | ReAct | 只读分析和方案输出 | 禁止写文件和 shell |
| `plan-execute` | Primary | Plan-and-Execute | 先生成显式执行计划，再进入工具执行循环 | 读允许，写确认 |
| `explore` | Subagent | ReAct | 由 `task` 工具派生，负责快速只读搜索 | 只读 |
| `general` | Subagent | ReAct | 由 `task` 工具派生，负责多步骤执行 | 继承父 Agent 限制 |

`plan-execute` 会在任务开始时先调用一次 planner 节点，生成 3-7 步计划，然后把该计划作为上下文交给正常工具循环执行。它适合改动面较大、需要先拆解再落地的开发任务。

## Skills

CodePilot 支持 Claude/OpenCode 风格的 Skills。Agent 可通过工具动态发现和读取技能：

| 工具 | 说明 |
|------|------|
| `skill_list` | 列出可用 Skills |
| `skill_read` | 读取指定 `SKILL.md` |

技能发现顺序：

1. 当前项目 `.codepilot/skills/*/SKILL.md`
2. 当前项目 `.claude/skills/*/SKILL.md`
3. 用户目录 `~/.codepilot/skills/*/SKILL.md`
4. 用户目录 `~/.claude/skills/*/SKILL.md`
5. 内置技能 `codepilot/skills/builtin/*/SKILL.md`

内置技能包括 `debug`、`code-review`、`testing`、`refactor`、`docs`。同名技能按上面的顺序覆盖，便于项目定制。

## MCP

CodePilot 支持通过 `~/.codepilot/config.yaml` 配置 stdio MCP Server，并提供三个工具：

| 工具 | 说明 |
|------|------|
| `mcp_list_servers` | 查看已配置 MCP Server |
| `mcp_list_tools` | 查看某个 Server 暴露的工具 |
| `mcp_call_tool` | 调用某个 stdio MCP 工具 |

当前版本实现 stdio MCP。HTTP/SSE、OAuth 等更完整的 MCP 管理能力可作为后续扩展。

## 项目指令文件

CodePilot 会自动加载当前工作目录下的项目指令文件：

| 文件 | 说明 |
|------|------|
| `AGENTS.md` / `agents.md` | OpenCode/Codex 风格项目规则 |
| `CLAUDE.md` / `claude.md` | Claude Code 风格项目记忆 |

REPL 中可使用 `/init` 初始化 `AGENTS.md`：

```text
/init
/init --force
```

`/init` 会根据 README、`pyproject.toml` 和项目目录结构生成一份可编辑的 `AGENTS.md` 种子文件；默认不会覆盖已有文件，`--force` 才会重写。

## REPL 斜杠命令

| 命令 | 说明 |
|------|------|
| `/model [name]` | 查看或切换模型 |
| `/agent [name]` | 切换或查看 Agent：`build`、`plan`、`plan-execute` |
| `/context` | 查看上下文使用情况 |
| `/compact` | 压缩对话历史 |
| `/clear` | 清除对话历史 |
| `/add <file>` | 添加文件到上下文 |
| `/diff` | 查看未提交的文件变更 |
| `/undo` | 撤销上次文件修改 |
| `/trace [on|off]` | 开启/关闭 LangSmith 追踪 |
| `/refresh` | 刷新文件索引 |
| `/sessions` | 列出历史会话 |
| `/resume <id>` | 恢复历史会话 |
| `/init [--force]` | 初始化或覆盖 `AGENTS.md` |
| `/help` | 显示帮助 |
| `/quit` `/exit` | 退出 |

## @ 引用

| 语法 | 说明 | 示例 |
|------|------|------|
| `@file <path>` | 引用文件内容 | `@file src/main.py` |
| `@url <url>` | 引用网页内容 | `@url https://docs.python.org/3/` |
| `@git <commit>` | 引用 commit diff | `@git abc1234` |
| `@dir <path>` | 引用目录结构 | `@dir ./src` |
| `@<path>` | 内联文件引用 | `帮我优化 @src/main.py` |

## 会话和可观测性

所有会话自动保存到 SQLite 数据库 `~/.codepilot/data/codepilot.db`，支持 `--resume`、`--resume-last`、`/sessions` 和 `/resume`。

LangSmith 追踪在 `langsmith.enabled: true` 且 API Key 存在时自动开启。追踪数据包含 Agent、模型、任务类型、工具调用链、token、延迟和非交互任务指标。

## 开发

```bash
pytest tests/ -v
ruff check codepilot evals tests
python -m evals.run_local --model deepseek/deepseek-v4-flash
```
