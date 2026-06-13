# CodePilot - CLI 编程 Agent 设计文档

## Context

开发一个基于 Python + LangChain + LangGraph 的 CLI 编程 Agent 工具，核心定位为 AI 编程助手（类似 Claude Code / Aider / OpenCode），支持多平台 LLM Provider（OpenAI 兼容、Anthropic、Gemini、Bedrock 等），具备文件操作、Shell 执行、代码搜索、网页搜索等能力。

项目名: **codepilot**

## 架构: LangGraph ReAct Agent

采用单一 ReAct (Reasoning + Acting) 循环图，后续可演进为 Multi-Agent。

```
┌─────────┐    tool_calls    ┌─────────┐
│  agent   │ ──────────────► │  tools   │
│ (LLM节点)│                 │(执行节点)│
└─────────┘ ◄────────────── └─────────┘
     │           results           │
     │  no tool_calls             │
     ▼                            │
   END  ◄─────────────────────────┘
```

- `agent` 节点: 调用 LLM（绑定工具），返回 AI 消息
- `tools` 节点: 执行工具调用，根据权限模式决定是否需用户确认
- 条件边: 检查 AI 消息是否有 `tool_calls`，有则路由到 `tools`，无则结束
- Checkpointer: `SqliteSaver` 做会话持久化，支持跨会话恢复

## AgentState

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    working_dir: str
    files_context: list[str]
    mode: str  # "plan" | "confirm" | "auto"
```

## 技术栈

- Python 3.11+
- LangChain Core + LangGraph (Agent 核心)
- langchain-openai / langchain-anthropic / langchain-google-genai (模型 Provider)
- Prompt Toolkit (REPL 交互输入)
- Rich (终端格式化输出)
- Pydantic (配置和状态验证)
- Click (CLI 命令行参数解析)

## 项目结构

```
codepilot/
├── pyproject.toml
├── codepilot/
│   ├── __init__.py
│   ├── cli.py                  # Click CLI 入口
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py            # LangGraph ReAct 状态图
│   │   ├── state.py            # AgentState 类型定义
│   │   └── prompts.py          # System prompt 模板
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py         # Pydantic 配置模型
│   │   └── providers.py        # LLM Provider 注册表
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── file_tools.py       # 文件读/写/编辑
│   │   ├── shell_tool.py       # Shell 命令执行
│   │   ├── search_tools.py     # 代码搜索 + glob
│   │   ├── web_tool.py         # 网页搜索
│   │   └── git_tool.py         # Git 操作
│   ├── context/
│   │   ├── __init__.py
│   │   ├── project.py          # 项目结构分析
│   │   └── selector.py         # 智能上下文选择
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── repl.py             # REPL 交互循环
│   │   ├── renderer.py         # Rich 输出渲染
│   │   └── permissions.py      # 权限确认 UI
│   └── utils/
│       ├── __init__.py
│       └── diff.py             # 文件差异计算与展示
├── tests/
│   ├── test_agent.py
│   ├── test_tools.py
│   └── test_config.py
└── README.md
```

## 模型配置

配置文件: `~/.codepilot/config.yaml`

```yaml
providers:
  openai:
    api_key: ""  # 推荐使用 CODEPILOT_OPENAI_API_KEY
    base_url: https://api.openai.com/v1
    models:
      - gpt-4o
      - gpt-4o-mini
  anthropic:
    api_key: ""  # 推荐使用 CODEPILOT_ANTHROPIC_API_KEY
    models:
      - claude-sonnet-4-20250514
      - claude-haiku-4-5-20251001
  deepseek:
    api_key: ""  # 推荐使用 CODEPILOT_DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com/v1
    models:
      - deepseek-chat
  ollama:
    base_url: http://localhost:11434/v1
    api_key: ollama
    models:
      - codellama

default:
  provider: anthropic
  model: claude-sonnet-4-20250514

mode: confirm
```

Provider 分两类:
- **Anthropic 原生**: 使用 `ChatAnthropic`
- **OpenAI 兼容**: 使用 `ChatOpenAI` 配置 `base_url`（覆盖 DeepSeek、Ollama、vLLM 等）
- **Google Gemini**: 使用 `ChatGoogleGenerativeAI`
- **AWS Bedrock**: 使用 `ChatBedrock`

运行时通过 `/model` 命令切换模型。

## 工具集

| 工具 | 描述 | 关键参数 |
|------|------|----------|
| `read_file` | 读取文件内容 | path, start_line, end_line |
| `write_file` | 写入/创建文件 | path, content |
| `edit_file` | 精确字符串替换编辑 | path, old_str, new_str |
| `list_dir` | 列出目录内容 | path, recursive |
| `glob_files` | Glob 模式搜索文件 | pattern, path |
| `run_shell` | 执行 Shell 命令 | command, timeout |
| `search_code` | grep 搜索代码 | pattern, path, file_type |
| `web_search` | 网页搜索 | query |
| `git_status` | 查看 Git 状态 | 无 |
| `git_diff` | 查看文件差异 | path |
| `git_log` | 查看 Git 日志 | count |

## 权限策略

- **plan 模式**: 只读模式，仅允许 `read_file`, `list_dir`, `glob_files`, `search_code`, `git_status`, `git_diff`, `git_log`, `web_search`；所有写操作被拒绝
- **confirm 模式**: 读取操作自动执行；写操作（`write_file`, `edit_file`, `run_shell`）需用户确认
- **auto 模式**: 所有操作自动执行，无需手动确认

工具安全:
- `run_shell` 设置默认 30 秒超时
- 文件操作限定在工作目录内（防止路径穿越）
- Shell 命令黑名单: `rm -rf /`, `mkfs`, `dd` 等危险命令需额外确认

## CLI 接口

```bash
codepilot                          # 在当前目录启动
codepilot --model gpt-4o           # 指定模型
codepilot --mode plan              # 指定模式
codepilot -p "修复 bug #123"       # 非交互模式，执行后退出
```

## REPL 斜杠命令（对标 Claude Code）

- `/model` — 查看或切换模型
- `/mode` — 切换权限模式（plan/confirm/auto）
- `/add <file>` — 添加文件到上下文
- `/compact` — 压缩对话历史，保留关键信息
- `/clear` — 清除对话历史
- `/diff` — 查看未提交的文件变更
- `/undo` — 撤销上次文件修改
- `/help` — 显示帮助
- `/quit` 或 `/exit` — 退出

## @ 引用命令

- `@file <path>` — 引用文件内容到对话上下文
- `@url <url>` — 引用网页内容到对话上下文
- `@git <commit>` — 引用某个 commit 的变更内容
- `@dir <path>` — 引用目录结构概览
- 在对话中直接使用: `帮我优化 @file src/main.py 的性能` — 自动解析并加载文件

## 输出渲染

- Agent 思考过程: 灰色斜体显示
- 工具调用: 蓝色面板显示工具名和参数
- 工具结果: 绿色/红色显示成功/失败
- 代码块: Rich Syntax 语法高亮
- Markdown: Rich Markdown 渲染
- 文件修改: 显示 diff 格式的变更预览

## System Prompt 策略

- 基础 prompt: 你是一个编程助手，可以读写文件、执行命令、搜索代码
- 动态注入: 项目结构概览、已加载文件内容、当前 Git 状态
- 模式调整: plan 模式下强调先规划再执行；auto 模式下减少确认
- @ 引用注入: 解析用户输入中的 @ 引用，将对应内容注入上下文

## 上下文管理

- 智能上下文: Agent 自动分析项目结构（.gitignore 过滤），根据用户提问选择相关文件
- 手动上下文: 用户通过 `/add` 和 `@file` 手动添加文件
- 上下文窗口管理: 超过 token 限制时自动压缩历史消息（`/compact` 命令）
