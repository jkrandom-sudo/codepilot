# CodePilot 技术文档

## 1. 项目概览

CodePilot 是一个基于 Python + LangChain + LangGraph 的 CLI 编程 Agent。采用多 Agent 分层架构，支持 ReAct、Plan-and-Execute、子 Agent 编排、三层上下文压缩、细粒度权限规则集、Skills、MCP、项目指令文件、SQLite 会话持久化、插件钩子系统。整体参考 Claude Code 与 OpenCode 的设计理念，用 Python 惯用方式实现。

### 技术栈

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| Python | >=3.11 | 运行时 |
| LangChain Core | >=0.3.0 | 消息抽象、工具定义 |
| LangGraph | >=0.3.0 | Agent 状态图引擎 |
| langchain-openai | >=0.3.0 | OpenAI 兼容 Provider |
| langchain-anthropic | >=0.3.0 | Anthropic Provider |
| langchain-google-genai | >=2.0.0 | Google Gemini Provider |
| LangSmith | >=0.1.0 | 可观测性追踪 |
| prompt-toolkit | >=3.0.0 | REPL 交互输入 |
| Rich | >=13.0.0 | 终端格式化输出 |
| Pydantic | >=2.0.0 | 配置模型、权限规则、存储模型 |
| Click | >=8.0.0 | CLI 参数解析 |
| PyYAML | >=6.0.0 | 配置文件读写 |
| httpx | >=0.27.0 | HTTP 请求（@url） |
| ddgs | >=6.0.0 | DuckDuckGo 网页搜索 |
| mcp | >=1.0.0 (可选 extra) | stdio MCP Client |
| sqlite3 | 内置 | 会话持久化 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌──────────────────────────────────────────────────┐
│                    CLI (Click)                     │
│              codepilot/cli.py                      │
│  --agent --resume --resume-last --model --confirm │
│        _setup_langsmith() → 环境变量配置            │
├──────────────────────────────────────────────────┤
│                    REPL 层                         │
│  ┌─────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │  REPL 循环   │ │  Renderer  │ │  Permission  │ │
│  │  ui/repl.py │ │ui/renderer │ │ui/permission │ │
│  │  Agent切换   │ │            │ │(规则集驱动)   │ │
│  │  会话恢复    │ │            │ │              │ │
│  └──────┬──────┘ └────────────┘ └──────┬───────┘ │
│  ┌─────────────┐ ┌────────────┐                    │
│  │  Commands   │ │  Intent    │                    │
│  │ui/commands  │ │ui/intent   │                    │
│  │斜杠命令处理  │ │意图识别路由 │                    │
│  └─────────────┘ └────────────┘                    │
├─────────┼──────────────────────────────┼──────────┤
│         │       Agent 核心层            │          │
│  ┌──────▼──────┐ ┌──────────────┐     │          │
│  │  LangGraph  │ │ AgentState   │     │          │
│  │  工作流图    │ │ agent/state │     │          │
│  │agent/graph  │ │ +agent_name  │     │          │
│  │  三层压缩    │ │ +session_id  │     │          │
│  └──────┬──────┘ └──────────────┘     │          │
│  ┌──────┴──────┐ ┌──────────────┐     │          │
│  │  Agent      │ │  Compaction  │     │          │
│  │  Registry   │ │  三层压缩     │     │          │
│  │agent/registr│ │agent/compact │     │          │
│  └─────────────┘ └──────────────┘     │          │
│  ┌─────────────┐ ┌──────────────┐     │          │
│  │  Agent      │ │  System      │     │          │
│  │  Prompts    │ │  Prompt      │     │          │
│  │agent/prompts│ │(模型族特化)   │     │          │
│  └─────────────┘ └──────────────┘     │          │
│  ┌─────────────┐ ┌──────────────┐     │          │
│  │  Node       │ │  Agent Utils │     │          │
│  │  Helpers    │ │  消息处理     │     │          │
│  │agent/nodes  │ │agent/_utils  │     │          │
│  └─────────────┘ └──────────────┘     │          │
├─────────┼──────────────────────────────┼──────────┤
│         │         工具层               │          │
│  ┌──────▼──────────────────────────────▼───────┐ │
│  │ file_tools │ shell_tool │ search_tools     │ │
│  │ web_tool   │ git_tool   │ task_tool        │ │
│  │ ToolContext │ TruncationStore              │ │
│  └────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────┤
│               权限 + 配置层                        │
│  ┌──────────────┐ ┌──────────────────┐           │
│  │   Settings   │ │ ProviderRegistry │           │
│  │config/setting│ │config/providers  │           │
│  └──────────────┘ └──────────────────┘           │
│  ┌──────────────┐ ┌──────────────────┐           │
│  │  Permission  │ │ContextWindows   │           │
│  │  Ruleset     │ │config/context   │           │
│  │config/permis │ └──────────────────┘           │
│  └──────────────┘                                │
├──────────────────────────────────────────────────┤
│               存储层 (SQLite)                      │
│  ┌──────────────┐ ┌──────────────┐               │
│  │   Storage    │ │    Models    │               │
│  │ storage/db   │ │storage/models│               │
│  └──────┬───────┘ └──────────────┘               │
│  ┌──────▼───────┐                                │
│  │    Resume    │                                │
│  │storage/resume│                                │
│  └──────────────┘                                │
├──────────────────────────────────────────────────┤
│               插件层                               │
│  ┌──────────────┐ ┌──────────────┐              │
│  │PluginManager │ │  hooks.py    │              │
│  │plugins/manager│ │(re-export)  │              │
│  └──────────────┘ └──────────────┘              │
├──────────────────────────────────────────────────┤
│              可观测性层 (LangSmith)                │
│  环境变量驱动自动追踪 + metadata/tags 过滤         │
└──────────────────────────────────────────────────┘
```

### 2.2 LangGraph 工作流

CodePilot 支持两类工作流：

| 工作流 | Agent | 说明 |
|--------|-------|------|
| `react` | `build`、`plan`、`explore`、`general` | 标准 ReAct 循环：LLM 推理 → 工具调用 → 工具结果回传 → 继续推理 |
| `plan_execute` | `plan-execute` | 先由 planner 节点生成显式执行计划，再进入标准 ReAct 工具循环 |

Plan-and-Execute 的状态图在 `agent` 前新增一次性 `planner` 节点：

```
START
  │
  ▼
planner 节点
  │  生成 [Plan-and-Execute Plan]
  ▼
agent 节点
  │
  ├── tool_calls → tools → agent
  ├── 预算超限 → summarize → END
  └── 无 tool_calls → END
```

该设计保持 OpenCode 风格的 Agent 中心模型：是否使用 Plan-and-Execute 由 `AgentDef.workflow` 决定。权限由 AgentDef 的 `permissions` 和运行时 `--confirm/--no-confirm` 控制。

### 2.3 LangGraph ReAct 状态图

Agent 采用 ReAct (Reasoning + Acting) 循环模式，含迭代上限保护、三层压缩和优雅终止：

```
         ┌─────────────┐
         │   START     │
         └──────┬──────┘
                │
                ▼
    ┌───────────────────────┐
    │       agent 节点       │
    │  调用 LLM + bind_tools│
    │  注入 files_context   │
    │  动态刷新项目上下文     │
    │  三层压缩检查:         │
    │   overflow(95%) →     │
    │   pruning(80%) →      │
    │   compaction(80%) →   │
    │   截断工具结果(磁盘)   │
    │  验证消息配对不变量     │
    └───────────┬───────────┘
                │
                ▼
        ┌───────────────┐
        │ should_continue│
        │   条件路由      │
        └───┬───┬───┬───┘
            │   │   │
  超过步数  │   │   │ 有 tool_calls
            │   │   │
            ▼   │   ▼
    ┌──────────┐ │  ┌──────────┐
    │summarize │ │  │tools 节点│
    │节点(终止)│ │  │(custom)  │
    └────┬─────┘ │  │权限规则集 │
         │       │  │追踪files │
         │       │  │_context  │
         │       │  │截断+磁盘  │
         │       │  └────┬─────┘
         │       │       │
         │  无    │       │
         │tool_   │       │
         │calls   │       │
         ▼       ▼       ▼
    ┌────────────────────────┐
    │         END            │
    └────────────────────────┘
```

**关键常量**：

| 常量 | 值 | 说明 |
|------|----|------|
| `MAX_ITERATIONS` | 80 | build Agent 最大迭代轮数 |
| `MAX_MESSAGES` | 96 | 消息压缩阈值，避免复杂开发任务过早触发 LLM 压缩 |
| `MAX_TOOL_RESULT_CHARS` | 10000 基线，按上下文窗口动态调整到 4000-128000 | 工具结果截断字符数 |
| `tool_result_line_limit()` | 300-6000 | 工具结果行数截断上限，按上下文窗口自适应 |
| `HARD_ITERATION_LIMIT` | 200 | 总工具调用硬上限（含多工具同一轮） |
| `MAX_RESPONSE_CHARS` | 24000 | Agent 最终响应截断字符数 |
| `FILE_SUMMARY_MAX_SCAN_LINES` | 600 | 文件摘要最大扫描行数 |
| `FILE_SUMMARY_MAX_KEY_LINES` | 20 | 文件摘要最大关键行数 |
| `FILE_SUMMARY_MAX_LINE_LEN` | 220 | 文件摘要单行最大长度 |
| `GRAPH_RECURSION_LIMIT` | 420 | LangGraph 超步上限 |

**执行流程**：
1. 用户输入 → 构造 `HumanMessage` → 注入 `AgentState.messages`
2. `agent` 节点：
   - 检查 overflow (95%) → 紧急降级
   - 检查 pruning (80%) → 轻量擦除较早工具输出
   - 检查 compaction (80%+消息过多) → LLM 总结
   - 截断工具结果 + 保存到磁盘
   - 验证消息配对不变量
   - 注入迭代预算提示（剩余轮数、硬上限警告）
   - 拼接 `SystemMessage` + 历史消息 + files_context + agent 上下文
   - 调用 `llm.bind_tools(tools).invoke()`
   - 响应超长时截断至 `MAX_RESPONSE_CHARS`
3. LLM 返回 `AIMessage`：
   - 包含 `tool_calls` → 路由到 `tools` 节点执行
   - 不包含 `tool_calls` → 路由到 `END`
4. `tools` 节点执行工具 → 权限规则集检查 → 工具去重检查 → 执行工具 → 追踪 `files_context` → 自适应截断+磁盘溢出 → `ToolMessage` 回传
   - **read_file 去重**：已读文件再次全量读取时返回 `[BLOCKED]` 提示
   - **定向补读**：已读文件允许使用 `offset/limit` 做局部补读，便于压缩后恢复精确行
   - **read_file 次数上限**：简单任务超过 24 次、复杂任务超过 80 次读取会阻止继续读取，要求基于已收集信息总结
   - **glob/grep 去重**：简单任务同类工具超过 8 次、复杂任务超过 28 次调用直接阻止；相同 pattern 重复调用也会限制
   - **run_shell 搜索拦截**：检测 grep/find/cat/ls/ack/ag/git grep 等搜索命令，阻止并提示使用专用工具
   - **run_shell 次数上限**：简单任务超过 10 次、复杂任务超过 36 次 run_shell 调用时阻止
5. `should_continue` 检查迭代数（含硬上限 `HARD_ITERATION_LIMIT`）：
   - 超过任务类型有效上限 → 路由到 `summarize` 节点
   - 超过硬上限 → 强制总结
   - 正常 → 继续循环

> 路由判断使用“超过上限才总结”，确保模型已经生成的最后一轮 `tool_calls` 会先进入 `tools` 节点执行，不会在执行前被截断。

---

## 3. 模块详细设计

### 3.1 CLI 入口 (`codepilot/cli.py`)

使用 Click 框架定义命令行接口。

**启动流程**：

```
codepilot [options]
    │
    ├── 设置 CODEPILOT_WORKING_DIR 环境变量 = os.getcwd()
    │
    ├── load_config() → 从 ~/.codepilot/config.yaml 加载配置
    │
    ├── _setup_langsmith(config) → 根据 langsmith 配置设置环境变量
    │
    ├── ProviderRegistry(config) → 创建 Provider 注册表
    │
    ├── 解析模型规格 / confirm 标志 / Agent 类型
    │
    ├── 有 -p 参数?
    │   ├── Yes → _run_non_interactive(agent_name=...)
    │   └── No  → _run_interactive(agent_name=..., session_id=...)
    │             ├── Storage() → 初始化 SQLite
    │             ├── build_agent_graph(llm, agent_name=...) → graph
    │             ├── REPL(graph, ..., storage, session_id)
    │             └── repl.run()
    │
    ├── --resume <id>?
    │   └── 从 Storage 加载会话 → 恢复消息历史
    │
    ├── --resume-last?
    │   └── Storage.get_latest_session() → 加载最近会话
    │
    └── 退出
```

**非交互模式反馈**：

- `_run_non_interactive()` 会在任务开始时立即输出任务、模型、Agent 和 auto 模式信息。
- 长时间无结果时，`_invoke_graph_with_heartbeat()` 每 15 秒输出一次 `仍在运行...` 心跳，避免用户误以为进程卡死。
- Agent 执行异常统一通过 `_format_non_interactive_error()` 转成短错误；模型配额耗尽、限流等错误不会再向用户暴露 Python traceback。
- LangSmith 追踪开启时，非交互任务结束后会写入 `task_outcome`、`tool_call_count`、`iteration_count` feedback，便于在 LangSmith 中按运行效果筛选。

### 3.2 配置系统

#### 3.2.1 数据模型 (`codepilot/config/settings.py`)

```
AppSettings
├── providers: dict[str, ProviderConfig]
│   └── ProviderConfig
│       ├── api_key: str
│       ├── base_url: str | None
│       ├── models: list[str]
│       ├── provider_type: str
│       └── context_window: int | None  # Provider 级上下文窗口覆盖
├── default: DefaultConfig
│   ├── provider: str
│   └── model: str
├── langsmith: LangSmithConfig
│   ├── enabled: bool
│   ├── api_key: str
│   ├── project: str
│   └── endpoint: str
├── mcp: dict[str, MCPServerConfig]
│   └── MCPServerConfig
│       ├── enabled: bool
│       ├── transport: "stdio" | "http"
│       ├── command: str
│       ├── args: list[str]
│       ├── env: dict[str, str]
│       └── url: str
├── agent: str
└── confirm: bool
```

运行时行为由 `--agent` 与 `--confirm/--no-confirm` 决定，也可通过配置文件设置默认 Agent 和确认策略。

#### 3.2.2 Provider 注册表 (`codepilot/config/providers.py`)

| provider_type | LangChain 类 | 说明 |
|---------------|-------------|------|
| `openai_compatible` | `ChatOpenAI` | OpenAI 官方、DeepSeek、Ollama、vLLM 等 |
| `anthropic` | `ChatAnthropic` | Anthropic 官方 API |
| `google` | `ChatGoogleGenerativeAI` | Google Gemini |
| `bedrock` | `ChatBedrock` | AWS Bedrock |

`RetryableLLM` 负责模型调用重试：

- 普通 429/rate limit 按指数退避重试。
- 500/502/503 服务端错误短重试。
- `quota_exceeded`、`insufficient_quota`、月度配额耗尽等不可重试错误直接抛出，由 CLI 显示“切换模型或补充配额”的友好提示。

#### 3.2.3 权限规则集 (`codepilot/config/permissions.py`)

`PermissionRuleset` 提供细粒度的工具权限控制：

```python
class PermissionRule(BaseModel):
    tool: str          # "edit_file", "bash", "*" (通配)
    pattern: str        # glob 模式: "src/**", "rm *", "**"
    action: Literal["allow", "ask", "deny"]

class PermissionRuleset(BaseModel):
    rules: list[PermissionRule]
    
    def evaluate(self, tool_name, args) -> str:
        # 有序遍历规则，特定性高的优先
        # tool="edit_file" (specificity=1) > tool="*" (specificity=0)
```

**预设规则集**：

| 规则集 | 关键规则 |
|--------|----------|
| `build_ruleset` | `*:ask`, `read_file/glob/grep/web_*:allow`, `run_shell(rm*):deny` |
| `plan_ruleset` | `*:allow`, `edit_file:deny`, `write_file:deny`, `run_shell:deny`, `task:deny` |
| `explore_ruleset` | `read_file/glob/grep/web_*/git_*:allow`, `*:deny` |
| `general_ruleset` | `*:allow`, `run_shell(rm*):deny` |

### 3.3 Agent 核心

#### 3.3.1 状态定义 (`codepilot/agent/state.py`)

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    working_dir: str
    files_context: list[str]
    task_type: str             # "code_search" | "file_edit" | "subagent" | ...
    agent_name: str            # "build" | "plan" | "plan-execute" | "explore" | "general"
    session_id: str            # 会话 ID（持久化用）
```

`agent_name` 是行为选择来源，权限、提示词、工具集合和工作流均由 `AgentRegistry.get(agent_name)` 决定。

#### 3.3.2 Agent 注册表 (`codepilot/agent/registry.py`)

```python
class AgentDef(BaseModel):
    name: str                          # "build", "plan", "plan-execute", "explore", "general"
    display_name: str
    agent_mode: Literal["primary", "subagent"]  # Agent 分类
    workflow: Literal["react", "plan_execute"]  # 状态图工作流
    prompt: str | None                 # 自定义系统提示
    model: str | None                  # 可指定不同模型
    steps: int = 25                    # 最大迭代步数
    temperature: float | None          # 可指定温度
    permissions: PermissionRuleset     # 该 Agent 的权限规则
    tools: list[str] | None            # 可用工具列表 (None=全部)
    description: str                   # @mention 描述
    confirm: bool = False              # 写操作是否需用户确认

    @property
    def is_primary(self) -> bool       # agent_mode == "primary"
    @property
    def is_subagent(self) -> bool      # agent_mode == "subagent"
    @property
    def is_readonly(self) -> bool      # permissions.evaluate("edit_file") == "deny"

class AgentRegistry:
    _agents: dict[str, AgentDef]

    def get(name) -> AgentDef | None
    def get_or_default(name) -> AgentDef  # 未找到时返回 build
    def list_primary() -> list[AgentDef]
    def list_subagents() -> list[AgentDef]
    def list_all() -> list[AgentDef]
    def get_tools_for_agent(name, all_tools) -> list
```

**预设 Agent**：

| Agent | agent_mode | workflow | steps | confirm | tools | 权限 |
|-------|------------|----------|-------|---------|-------|------|
| auto | pseudo | auto | - | True | - | 按任务复杂度选择 build / plan / plan-execute |
| build | primary | react | 80 | True | all | build 规则集 |
| plan | primary | react | 24 | False | all (权限运行时阻止写) | plan 规则集 |
| plan-execute | primary | plan_execute | 120 | True | all | build 规则集 |
| explore | subagent | react | 32 | False | 只读工具 + skill/MCP 只读入口 | explore 规则集 |
| general | subagent | react | 120 | False | all | general 规则集 |

#### 3.3.3 Agent 上下文管理 (`codepilot/agent/context_manager.py`)

`AgentContextManager` 集中管理 Agent 循环中的上下文派生信息，避免 `graph.py` 与 `nodes.py` 继续堆叠低层策略：

| 能力 | 说明 |
|------|------|
| `extract_file_summaries()` | 从历史 `read_file` ToolMessage 中提取已读文件摘要，优先保留 import/class/def/常量/标题等结构性行 |
| `render_files_context()` | 渲染 `FILES ALREADY IN CONTEXT` 系统提示块，阻止重复读取 |
| `tool_result_char_limit()` | 根据 `context_window` 动态计算工具结果截断上限，范围 4000-128000 字符 |
| `tool_result_line_limit()` | 根据 `context_window` 动态计算工具结果行数上限，范围 300-6000 行 |
| `compress_tool_results()` | 截断大型 ToolMessage，并通过 `TruncationStore` 将完整内容落盘 |

该模块是后续引入更强上下文能力的扩展点，例如文件 hash、URL 缓存、跨子 Agent 共享摘要、按模型窗口差异化预算。

#### 3.3.4 Agent 节点辅助 (`codepilot/agent/nodes.py`)

从 `graph.py` 提取的节点辅助函数，使节点逻辑可独立测试：

| 函数/常量 | 说明 |
|-----------|------|
| `MAX_RESPONSE_CHARS` | 响应截断上限 (24000 字符) |
| `FILE_SUMMARY_MAX_*` | 文件摘要常量 (600扫描行/20关键行/220字符) |
| `TASK_ITERATION_LIMITS` | 按任务类型的迭代上限字典 |
| `_extract_file_summaries()` | 文件摘要包装函数，实际委托给 `AgentContextManager` |
| `_tool_round_count()` | 计算 (迭代轮数, 总工具调用数) |
| `compress_for_state()` | 按序应用三层压缩 (overflow→pruning→compaction) |
| `build_system_prompt_with_context()` | 构建完整系统提示 (基础+项目上下文+文件摘要+迭代预算+插件钩子) |
| `truncate_response()` | 按 Agent 类型和工具调用数截断响应 |
| `has_system_message()` | 检查消息列表是否已有 SystemMessage |

**TASK_ITERATION_LIMITS** 当前配置：

| 任务类型 | 上限 |
|----------|------|
| `code_search` | 20 |
| `project_analysis` | 80 |
| `general_question` | 4 |
| `file_edit` | 96 |
| `file_write` | 96 |
| `command_run` | 56 |
| `test_evaluation` | 112 |
| `subagent` | 120 |

`build_system_prompt_with_context()` 接收任务类型解析后的有效预算，而不是直接使用 AgentDef 的默认 `steps`。例如 build Agent 默认 `steps=80`，但 `file_edit` 运行时提示会显示 `96` 轮预算，复杂任务会额外注入 Deep context mode，鼓励 Agent 读取多文件上下文、测试、配置和文档后再下结论。

当前状态评估遵循“报告是证据，不是唯一真相”的规则：当用户要求评估项目效果时，Agent 需要把报告中的问题与当前源码、配置和测试交叉核对，并输出仍然有效的改进项。

#### 3.3.5 消息处理工具 (`codepilot/agent/_utils.py`)

共享消息处理函数，供 `graph.py`、`compaction.py` 和 `repl.py` 使用，避免重复实现漂移：

| 函数 | 说明 |
|------|------|
| `estimate_tokens(messages)` | 粗估 token 数：chars/4 + 工具调用参数开销。无 tokenizer 依赖 |
| `find_tool_call_pairs(messages)` | 返回每组 `[ai_idx, tm_idx, ...]` 的索引列表。单次遍历 O(N) |
| `validate_message_pairs(messages)` | 修复 AIMessage(tool_calls)↔ToolMessage 邻接不变量。处理压缩/恢复后的违规情况 |

#### 3.3.6 三层压缩 (`codepilot/agent/compaction.py`)

| 层级 | 函数 | 触发 | 方式 | 成本 |
|------|------|------|------|------|
| Pruning | `prune_tool_outputs()` | 80% 上下文 | 从后往前擦除较早的工具输出，保留最近 40K tokens | 无 LLM |
| Compaction | `compact_messages()` | 80% + 消息过多 | LLM 总结较早消息，保留最近 2 轮 | 1 次 LLM |
| Overflow | `overflow_compaction()` | 95% 上下文 | 剥离大块内容 + 找 replay 点 + 压缩 | 多次 LLM |

**Compaction 提示词** (`COMPACTION_PROMPT`):
- 保留具体文件路径、函数名、变量名、错误信息
- 不包含最近交互（单独保留）
- 使用用户语言输出

#### 3.3.7 状态图构建 (`codepilot/agent/graph.py`)

`build_agent_graph(llm, agent_name, context_window, custom_permissions, custom_tools, storage, ask_permission_callback)` 函数：

1. 入口层通过 `agent/router.py` 在 `auto` 下选择实际 Agent：简单任务 → `build`，只读分析 → `plan`，复杂多步骤任务 → `plan-execute`
2. 从 AgentRegistry 获取 AgentDef
3. 根据 agent_name 和 custom_tools 确定工具列表
4. 根据 agent_name 选择系统提示（build/plan/explore/general 各有专有提示；plan-execute 复用 build 执行提示并额外启用 planner）
5. 构建三层压缩阈值（compact=80%, overflow=95%）
6. 构建 `StateGraph(AgentState)`：
   - `planner` 节点：仅 `workflow="plan_execute"` 时启用，先生成 `[Plan-and-Execute Plan]`，不绑定工具、不执行写操作
   - `agent` 节点：三层压缩 → 截断+磁盘溢出 → 注入真实任务预算 → 验证配对 → 注入上下文 → 调用 LLM → 响应截断
   - `tools` 节点：权限规则集检查 → read_file/glob/grep 去重 → run_shell 搜索拦截 → 执行工具 → 追踪 files_context → 自适应截断+磁盘溢出
   - `summarize` 节点：任务类型预算/硬上限超限时生成总结后终止
7. 当工作流为 `plan_execute` 时添加 `START → planner → agent`，否则添加 `START → agent`
8. 编译并返回可执行的 `CompiledGraph`

#### 3.3.8 System Prompt (`codepilot/agent/prompts.py`)

由以下部分组成：
1. **基础指令**：定义 Agent 角色、能力、行为准则
2. **响应长度限制**：General Q&A 默认短答；复杂 Coding、Project Analysis、详细评估/方案类请求允许更完整展开，并由 `MAX_RESPONSE_CHARS=24000` 兜底
3. **工具选择规则**：搜索→grep/glob，读取→read_file，run_shell仅用于执行程序
4. **run_shell 禁止规则**：ABSOLUTELY FORBIDDEN 列表（grep/find/cat/ls/ack/ag/git grep等）
5. **搜索停止策略**：grep/glob 被阻止后不 fallback 到 run_shell，从已有结果总结
6. **文件读取策略**：每个文件最多读一次，BLOCKED 时从对话历史获取内容
7. **语言指令**：中文→中文，英文→英文
8. **Agent 特化提示**：plan/explore/general 各有独立提示模板
9. **子 Agent 使用指引**：task 工具 + explore/general 说明
10. **重试策略**：同一操作失败 2 次换策略
11. **项目分析规则**：简单识别 3-5 次调用；详细评估、优化方案、架构分析或实现跟进进入 Deep context mode，最多使用任务预算
12. **Skills / MCP 指引**：通过 `skill_list`/`skill_read` 动态加载技能，通过 `mcp_list_servers`/`mcp_list_tools` 检查外部工具
13. **项目上下文**：动态获取目录结构、Git 状态、`AGENTS.md`/`CLAUDE.md` 项目指令和可用技能摘要

`PLAN_EXECUTE_PLANNER_PROMPT` 是独立的 planner 提示词，只负责产出 3-7 步计划、可能涉及的文件/工具/验证命令，不绑定工具，也不输出实现代码。生成的计划会作为 AIMessage 进入后续执行上下文。

**模型族识别**：`get_model_family(model_name)` 返回 "claude" / "gpt" / "gemini" / "deepseek" / "qwen" / "default"，为后续模型特化提示提供基础。

#### 3.3.9 项目指令文件 (`codepilot/context/instructions.py`)

CodePilot 自动识别当前工作目录下的 `AGENTS.md`、`agents.md`、`CLAUDE.md`、`claude.md`，将其作为 `Project instructions` 注入系统上下文。读取限制为 25KB 或 200 行，防止项目规则文件过大挤占模型上下文。

REPL `/init` 命令调用 `init_agents_file()` 生成 `AGENTS.md` 种子文件。生成内容来自 README 首个标题、`pyproject.toml` 的项目名和顶层目录结构；默认不覆盖已有文件，`/init --force` 才会重写。

### 3.4 工具集

#### 3.4.1 工具注册 (`codepilot/tools/__init__.py`)

**工具分类**：

| 类别 | 工具名 | 说明 |
|------|--------|------|
| 文件读取 | `read_file` | 读取文件+列出目录（双模式），支持行号范围、二进制检测 |
| 文件搜索 | `glob` | Glob 模式搜索文件 |
| 代码搜索 | `grep` | 正则搜索（支持 include glob 过滤） |
| 网络搜索 | `web_search` | DuckDuckGo 搜索 |
| 网络获取 | `web_fetch` | URL→Markdown/HTML→text |
| Git 读取 | `git_status` / `git_diff` / `git_log` | Git 操作 |
| 文件写入 | `write_file` | 写入/创建文件 |
| 文件编辑 | `edit_file` | 精确字符串替换（支持 `replace_all`） |
| Shell | `run_shell` | 执行 Shell 命令（搜索命令被拦截） |
| 子 Agent | `task` | 派生 explore/general 子 Agent |
| 任务列表 | `todo_write` | 会话作用域任务列表 |
| Skills | `skill_list` / `skill_read` | 发现并读取项目、用户、内置 `SKILL.md` |
| MCP | `mcp_list_servers` / `mcp_list_tools` / `mcp_call_tool` | 读取配置、列出 MCP 工具、调用 stdio MCP 工具 |

`get_tools_for_agent(agent_name)` 从 AgentRegistry 获取 Agent 对应的工具列表。

#### 3.4.1.1 Skills (`codepilot/skills/manager.py`, `codepilot/tools/skill_tool.py`)

Skills 采用文件系统约定，按优先级合并同名技能：

1. 项目 `.codepilot/skills/*/SKILL.md`
2. 项目 `.claude/skills/*/SKILL.md`
3. 用户 `~/.codepilot/skills/*/SKILL.md`
4. 用户 `~/.claude/skills/*/SKILL.md`
5. 包内置 `codepilot/skills/builtin/*/SKILL.md`

`skill_list` 返回技能名、来源和描述，`skill_read(name)` 返回完整 `SKILL.md`。当前内置技能包括 `debug`、`code-review`、`testing`、`refactor`、`docs`。

#### 3.4.1.2 MCP (`codepilot/tools/mcp_tool.py`)

MCP 配置位于 `~/.codepilot/config.yaml` 的 `mcp` 字段。当前实现支持 stdio transport：

```yaml
mcp:
  filesystem:
    enabled: true
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
    env: {}
```

`mcp_call_tool` 属于可执行外部动作，在 build/plan-execute 默认 confirm 模式下需要确认；`plan` 和 `explore` 只允许列出 server/tool，不允许调用。

#### 3.4.2 工具上下文 (`codepilot/tools/context.py`)

`ToolContext` 为每个工具执行提供运行时上下文：

```python
class ToolContext:
    session_id: str
    agent_name: str
    working_dir: str
    files_context: list[str]
    abort: threading.Event
    permissions: PermissionRuleset
    seen_patterns: set[str]        # glob/grep 去重追踪（"tool:pattern:path"）
    
    def check_permission(tool_name, args) -> str  # allow/ask/deny
    def track_file(path) -> None
    def is_file_tracked(path) -> bool
```

#### 3.4.3 截断存储 (`codepilot/tools/truncation.py`)

`TruncationStore` 将截断的工具输出保存到磁盘：

```python
class TruncationStore:
    base_dir: Path  # ~/.codepilot/truncations/
    
    def truncate_and_save(content, tool_call_id) -> (truncated, file_path)
    def read_full(path) -> str | None
    def cleanup(max_age_days=7) -> int
```

默认截断规则：2000 行 / 50KB；Agent 循环中会按 `context_window` 使用更具体的自适应行数和字符数上限。截断后 ToolMessage 末尾附加 `[Output truncated: N lines total. Full output saved to <path>]`。

#### 3.4.4 子 Agent 执行 (`codepilot/tools/task_tool.py`)

`task` 工具 + `_run_subagent()` 实现子 Agent 派生：

```
Primary Agent → 调用 task 工具
    │
    ├── 创建子 SessionInfo (parent_id = 当前会话)
    ├── 从 AgentRegistry 获取 subagent 定义
    ├── 构建子 Agent 的 agent graph
    ├── 运行子循环
    ├── 收集最终 AI 回复作为结果
    └── 保存子会话到 Storage
```

### 3.5 存储层

#### 3.5.1 SQLite 存储 (`codepilot/storage/db.py`)

`Storage` 类提供 SQLite 持久化：

| 方法 | 说明 |
|------|------|
| `create_session(session)` | 创建会话 |
| `get_session(session_id)` | 获取会话 |
| `list_sessions(limit)` | 列出会话（按更新时间倒序） |
| `update_session(session_id, **kwargs)` | 更新会话 |
| `delete_session(session_id)` | 删除会话（级联删除消息） |
| `save_message(msg)` | 保存消息 |
| `get_messages(session_id)` | 获取会话所有消息 |
| `get_latest_session()` | 获取最近会话 |
| `get_child_sessions(parent_id)` | 获取子会话列表 |

**数据库路径**：`~/.codepilot/data/codepilot.db`
**WAL 模式**：启用 `PRAGMA journal_mode=WAL` 提升并发性能

#### 3.5.2 数据模型 (`codepilot/storage/models.py`)

```python
class TextPart(BaseModel):        # 文本内容
class ToolPart(BaseModel):        # 工具调用 (name, call_id, args, output, state, elapsed_ms)
class FilePart(BaseModel):        # 附件文件 (path, content)
class CompactionPart(BaseModel):  # 压缩标记 (summary)

MessagePart = TextPart | ToolPart | FilePart | CompactionPart

class StoredMessage(BaseModel):   # 消息 (id, session_id, role, parts, content, tool_calls, ...)
class SessionInfo(BaseModel):     # 会话 (id, parent_id, title, agent, model, timestamps, ...)
```

#### 3.5.3 会话恢复 (`codepilot/storage/resume.py`)

```python
def stored_to_langchain(messages) -> list[BaseMessage]  # 存储模型 → LangChain 消息
def langchain_to_stored(messages, session_id) -> list[StoredMessage]  # 反向
def save_messages(storage, messages, session_id) -> int  # 批量保存
def load_messages(storage, session_id) -> list[BaseMessage]  # 批量加载
```

### 3.6 插件系统

#### 3.6.1 插件管理器 (`codepilot/plugins/manager.py`)

单例模式的插件管理器，提供钩子注册和触发：

```python
class HookType(Enum):
    MESSAGE_BEFORE_SAVE = "message_before_save"
    SYSTEM_PROMPT_TRANSFORM = "system_prompt_transform"
    TOOL_EXECUTE_BEFORE = "tool_execute_before"
    TOOL_EXECUTE_AFTER = "tool_execute_after"
    COMPACTION = "compaction"

class PluginHook(BaseModel):
    hook_type: HookType
    handler_name: str
    handler: Any

class PluginManager:
    def register(hook: PluginHook) -> None
    def unregister(handler_name, hook_type) -> int
    def emit(hook_type, data: dict) -> dict
    def has_hooks(hook_type) -> bool
    def clear() -> None

def get_plugin_manager() -> PluginManager  # 进程级单例
```

**钩子契约**：

| HookType | 输入 | 输出 |
|----------|------|------|
| `MESSAGE_BEFORE_SAVE` | `{"message": BaseMessage}` | `{"message": ...}` |
| `SYSTEM_PROMPT_TRANSFORM` | `{"prompt": str, "state": AgentState}` | `{"prompt": str}` |
| `TOOL_EXECUTE_BEFORE` | `{"tool_name", "args", "state"}` | same |
| `TOOL_EXECUTE_AFTER` | `{"tool_name", "args", "result", "state"}` | `{"result": str}` |
| `COMPACTION` | `{"messages", "summary"}` | `{"summary": str}` |

处理器必须幂等且异常安全（manager 吞吞异常以保持 Agent 运行）。

#### 3.6.2 Hooks 导出 (`codepilot/plugins/hooks.py`)

`hooks.py` 作为 hooks API 的导出入口，核心实现在 `manager.py` 中：

```python
from codepilot.plugins.manager import (HookType, PluginHook, PluginManager, get_plugin_manager)
```

### 3.7 权限控制 (`codepilot/ui/permissions.py`)

`PermissionHandler` 使用 `PermissionRuleset` 驱动：

```
check_permission(tool_name, tool_args)
    │
    ├── tool_name in allowed_tools → True（白名单）
    │
    ├── ruleset.evaluate() → "allow" → True
    │                     → "deny"  → False
    │                     → "ask"   → _ask_confirmation()
    │
    └── _ask_confirmation()
        ├── 1 → True
        ├── 2 → False
        └── 3 → 加入白名单 + True
```

### 3.8 REPL 交互 (`codepilot/ui/repl.py`)

#### 3.8.1 命令处理器 (`codepilot/ui/commands.py`)

从 REPL 中提取的 `CommandHandler` 类，集中处理所有斜杠命令：

```python
class CommandHandler:
    def __init__(self, repl: REPL) -> None
    def handle(self, cmd: str) -> bool  # True = 应退出

    # 各命令实现: _quit, _help, _model, _add, _clear, _compact,
    # _context, _refresh, _diff, _undo, _trace, _agent, _sessions, _resume, _init
```

`SLASH_COMMANDS` 字典定义所有命令名和说明。

#### 3.8.2 意图识别 (`codepilot/ui/intent.py`)

三层意图路由，避免对简单输入触发完整 Agent 图：

| 函数 | 返回值 | 说明 |
|------|--------|------|
| `classify_intent(input)` | `"greeting"` / `"chat"` / `"coding"` | 主分类：问候→本地固定回复，help/身份类 chat→本地固定回复，编程→完整Agent图 |
| `classify_task(input)` | 任务类型字符串 | 编程意图细分：`code_search`/`file_edit`/`file_write`/`project_analysis`/`command_run`/`general_question` |
| `greeting_response(input)` | 中/英问候语 | 不调用 LLM，直接返回固定问候 |
| `chat_response(input)` | 中/英帮助/身份说明 | 不调用 LLM，直接返回固定帮助或身份说明 |
| `is_greeting(input)` | bool | 判断是否为问候 |

关键词覆盖中英文：编程关键词（file/code/函数/修改/优化...）、非编程话题（天气/电影...）、开发意图词（增加/实现/优化/add/optimize...）。`help`、`你是谁`、`你能做什么`、`介绍一下你自己` 等优先归类为 `chat`，避免进入 LangGraph 消耗 token。

#### 3.8.3 主循环流程

```
REPL.run()
    │
    ├── 初始化 PromptSession（历史记录 + 命令补全）
    │
    └── 循环：[agent_name:confirm_label] > _
        ├── 以 / 开头 → CommandHandler.handle()
        │   ├── /model, /agent, /add, /compact, /clear
        │   ├── /diff, /undo, /trace, /refresh
        │   ├── /sessions, /resume, /init
        │   └── /help, /quit
        │
        └── 普通消息 →
            ├── parse_references() 解析 @ 引用
            ├── classify_intent() 三层意图路由 (intent.py)
            │   ├── greeting → greeting_response() (本地回复，无 LLM)
            │   ├── chat → chat_response() (本地回复，无 LLM)
            │   └── coding → _run_agent() (完整 Agent 图)
            │       └── classify_task() → task_type
            └── _persist_messages() → 保存到 SQLite
```

#### 3.8.4 斜杠命令

| 命令 | 实现 |
|------|------|
| `/model [name]` | 设置模型 + 更新上下文窗口 |
| `/agent [name]` | 切换 Agent + 重建 graph + 更新权限规则集 + 更新 Storage |
| `/sessions` | 列出 Storage 中的历史会话 |
| `/resume <id>` | 持久化当前会话 + 加载目标会话 |
| `/init [--force]` | 根据当前项目生成或覆盖 `AGENTS.md` |
| `/compact` | 三层压缩 |
| `/add <file>` | 读取文件内容，追加 HumanMessage |
| `/clear` | 清空消息 |
| `/diff` | git diff |
| `/undo` | 恢复上次修改 |
| `/trace [on\|off]` | 切换 LangSmith 追踪 |

#### 3.8.5 会话初始化

`_init_session()` 在 REPL 构造时自动执行：
1. 如果 `session_id` 存在 → 从 Storage 加载会话和消息
2. 如果 `session_id` 不存在 → 创建新会话并保存到 Storage
3. 每次 Agent 执行后自动调用 `_persist_messages()` 保存消息

### 3.9 渲染器 (`codepilot/ui/renderer.py`)

Rich 库封装，统一终端输出格式：

| 方法 | Rich 组件 | 样式 |
|------|-----------|------|
| `render_task_start()` | 文本区块 | 任务边界 + 模型/Agent/模式 |
| `render_waiting()` | 文本状态 | 首个模型事件返回前的运行中提示 |
| `activity()` / `start_activity()` | Rich `Status` | 动态 spinner，显示模型/工具运行中的状态 |
| `update_activity()` / `stop_activity()` | Rich `Status` | 更新或停止动态运行提示 |
| `render_phase_header()` | 文本分隔 | 按阶段去重展示 |
| `render_thinking()` | `Text` | 灰色斜体 |
| `render_tool_call()` | 单行状态 | 阶段 + 工具意图 + 目标 + token |
| `render_tool_result()` | 单行摘要 | 绿色成功/黄色跳过/红色失败，成功结果只显示摘要 |
| `render_code()` | `Syntax` | Monokai 主题 |
| `render_message()` | `Markdown` | Rich Markdown |
| `render_edit_diff()` | `Syntax("diff")` | 差异语法高亮 |
| `render_choice()` | 确认区块 | confirm 模式写操作确认 |
| `render_permission_result()` | 文本状态 | 权限选择结果 |
| `render_task_summary()` | `Table` | success/partial/error + 耗时/token（总量、输入、输出）/工具统计 |

`infer_phase()` 将底层工具映射为用户可读阶段：检查项目与收集上下文、修改文件、执行命令、验证结果、查询外部资料、更新任务计划、执行子任务。

---

## 4. 数据流

### 4.1 交互模式完整数据流

```
用户输入: "帮我优化 @file src/main.py 的性能"
    │
    ▼
REPL.run() 读取输入
    │
    ├── parse_references() 解析 @ 引用
    ├── classify_intent() → "coding" (intent.py 三层路由)
    │
    ▼
_run_agent() → graph.stream(state, config)
    │
    ├── agent 节点
    │   ├── 检查 overflow (95%) → 跳过
    │   ├── 检查 pruning (80%) → 跳过
    │   ├── 检查 compaction → 跳过
    │   ├── _compress_tool_results() → 截断+磁盘溢出
    │   ├── _validate_message_pairs() → 验证不变量
    │   ├── 注入 files_context + agent 上下文
    │   ├── llm_with_tools.invoke()
    │   └── AIMessage(tool_calls: edit_file)
    │       │
    │       ▼
    │   ├── ruleset.evaluate("edit_file") → "ask"
    │   ├── 用户确认 → 通过
    │   ├── tool_node 执行 edit_file
    │   ├── TruncationStore 截断大型结果
    │   ├── files_context 更新
    │   │
    │       ▼
    │   ├── agent 节点再次调用 LLM
    │   └── AIMessage: "我已优化代码..."
    │
    ▼
_persist_messages() → 保存到 SQLite
render_task_summary() → 显示耗时/token/工具调用数
```

### 4.2 会话恢复数据流

```
codepilot --resume <session-id>
    │
    ├── Storage.get_session(id) → SessionInfo
    ├── load_messages(storage, id) → list[BaseMessage]
    ├── REPL(messages=loaded_messages)
    │
    └── 用户继续对话 → 新消息追加 → _persist_messages()
```

### 4.3 子 Agent 执行数据流

```
Primary Agent → task(prompt="找到所有 API 端点", subagent_type="explore")
    │
    ├── AgentRegistry.get("explore") → AgentDef
    ├── new_session_id() → child_session_id (parent_id=当前会话)
    ├── Storage.create_session(child_session)
    │
    ├── build_agent_graph(llm, agent_name="explore", custom_tools=[8个读工具])
    ├── graph.invoke({messages: [HumanMessage(prompt)], ...})
    │   └── explore Agent 在独立循环中执行
    │       └── 最多 10 步，只有读权限
    │
    ├── 收集最终 AIMessage.content → 返回给 Primary Agent
    └── Storage 保存子会话
```

---

## 5. 关键设计决策

### 5.1 多 Agent 分层架构

参考 OpenCode 设计理念，将 Agent 分为 Primary（用户交互）和 Subagent（被 task 工具派生）两层：

- **Primary** (build/plan): 用户直接切换，拥有独立系统提示
- **Subagent** (explore/general): 在独立子会话中运行，不污染主对话
- **优势**: 任务分解、上下文隔离、独立迭代限制、权限隔离

### 5.2 三层上下文压缩

| 层级 | 触发场景 | 处理方式 |
|------|----------|----------|
| Pruning | 消息较多且工具输出占比高 | 无 LLM 调用，擦除较早的工具输出 |
| Compaction | 上下文接近预算且需要保留事实 | 调用 LLM 生成任务摘要 |
| Overflow | 上下文接近硬上限 | 紧急降级，只保留关键消息和摘要 |

Pruning 作为第一道防线节省 token；Compaction 用 LLM 总结保留关键信息；Overflow 处理极端情况。

### 5.3 权限规则集

| 能力 | 说明 |
|------|------|
| 工具级控制 | 按 `read_file`、`edit_file`、`run_shell` 等工具名匹配 |
| 路径级控制 | `pattern: "src/**"` 支持路径级权限 |
| 命令级控制 | `pattern: "rm *"` 支持命令级权限 |
| 动作类型 | 支持 `allow`、`ask`、`deny` |
| 运行时确认 | `ask` 动作进入 TUI 确认流程，用户可单次允许或始终允许 |

### 5.4 SQLite 会话持久化

| 能力 | 说明 |
|------|------|
| 持久化消息 | 保存用户消息、AI 回复和工具结果 |
| 会话恢复 | `--resume`、`--resume-last`、`/resume` 恢复历史会话 |
| 会话管理 | `/sessions` 查看历史会话 |
| 父子关系 | `parent_id` 记录子 Agent 会话来源 |

### 5.5 工具输出磁盘溢出

| 能力 | 说明 |
|------|------|
| 磁盘保存 | 截断内容保存到 `~/.codepilot/truncations/` |
| 可追溯 | 工具结果包含 truncation id，可按需重新读取 |
| 自适应 | 根据上下文窗口动态调整字符和行数限制 |

---

## 6. 测试

```
tests/
├── test_config.py              # 配置加载、环境变量覆盖、LangSmith 配置
├── test_tools.py               # 文件工具、Shell、搜索、权限规则、Web 搜索
├── test_agent.py               # AgentState、Prompt 生成、@ 引用解析
├── test_message_invariant.py   # AIMessage(tool_calls)→ToolMessage 不变量
├── test_truncate.py            # 文本截断工具
├── test_cli.py                 # CLI 入口参数解析、agent 解析
├── test_intent.py              # 意图识别 (greeting/chat/coding)、任务分类
├── test_plugins.py             # PluginManager 注册/触发/单例
├── test_evals.py               # 评估器功能测试
├── test_scenarios.py           # 端到端场景测试
```

测试覆盖配置、工具、Agent 状态图、消息不变量、CLI、意图识别、插件、评估器和端到端场景。

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## 7. 目录结构

```
codepilot/
├── pyproject.toml              # 项目元数据 & 依赖 (hatchling)
├── README.md                   # 使用说明
├── AGENTS.md                   # Agent 开发指南
├── codepilot/
│   ├── __init__.py             # 版本号
│   ├── cli.py                  # Click CLI 入口 + --agent --confirm/--no-confirm --resume
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py            # LangGraph ReAct/Plan-and-Execute 状态图 + 三层压缩 + 权限 + 工具去重
│   │   ├── context_manager.py  # Agent 上下文管理: 文件摘要、已读上下文提示、工具结果动态截断
│   │   ├── nodes.py            # Agent 节点辅助: 系统提示构建、压缩、响应截断、迭代预算
│   │   ├── _utils.py           # 共享消息处理: estimate_tokens, find_tool_call_pairs, validate_message_pairs
│   │   ├── state.py            # AgentState TypedDict (含 agent_name, session_id)
│   │   ├── prompts.py          # System Prompt + Agent 特化 + 响应长度限制 + 文件读取策略
│   │   ├── registry.py         # AgentDef + AgentRegistry — 5 种预设 Agent
│   │   └── compaction.py       # 三层压缩: prune / compact / overflow
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py         # Pydantic 配置模型 + YAML 加载
│   │   ├── providers.py        # Provider 注册表 + LLM 工厂 + RetryableLLM(429重试)
│   │   ├── permissions.py      # PermissionRuleset — allow/ask/deny + glob + specificity
│   │   └── context_windows.py  # model→context-window 注册
│   ├── tools/
│   │   ├── __init__.py         # 工具注册 + Agent 过滤
│   │   ├── context.py          # ToolContext — 执行上下文 + seen_patterns 去重
│   │   ├── truncation.py       # TruncationStore — 截断+磁盘溢出
│   │   ├── task_tool.py        # task 工具 + _run_subagent()
│   │   ├── file_tools.py       # read_file (文件+目录+二进制检测), write_file, edit_file (replace_all), glob
│   │   ├── shell_tool.py       # run_shell (description, workdir, timeout 120s, 搜索命令拦截)
│   │   ├── search_tools.py     # grep (include glob filter)
│   │   ├── web_tool.py         # web_search (DuckDuckGo)
│   │   ├── web_fetch_tool.py   # web_fetch (URL→Markdown)
│   │   ├── git_tool.py         # git_status, git_diff, git_log
│   │   ├── skill_tool.py       # skill_list, skill_read
│   │   ├── mcp_tool.py         # mcp_list_servers, mcp_list_tools, mcp_call_tool
│   │   └── todo_tool.py        # todo_write (session-scoped)
│   ├── skills/
│   │   ├── manager.py          # SkillManager — 项目/用户/内置技能发现
│   │   └── builtin/            # debug, code-review, testing, refactor, docs
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py               # Storage — SQLite 持久化
│   │   ├── models.py           # SessionInfo, StoredMessage, Part 模型
│   │   └── resume.py           # 消息适配 + 保存/加载
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── manager.py          # PluginManager + PluginHook + HookType + get_plugin_manager 单例
│   │   └── hooks.py            # hooks API re-export
│   ├── context/
│   │   ├── __init__.py
│   │   ├── instructions.py     # AGENTS.md / CLAUDE.md 加载与 /init 生成
│   │   ├── selector.py         # @ 引用解析
│   │   └── project.py          # 项目结构分析
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── repl.py             # REPL 主循环 + Agent 切换 + 会话恢复 + 持久化
│   │   ├── commands.py         # CommandHandler — 斜杠命令处理
│   │   ├── intent.py           # 意图识别 (greeting/chat/coding) + 任务分类
│   │   ├── renderer.py         # Rich 输出渲染
│   │   ├── permissions.py      # 权限控制 (规则集驱动)
│   │   └── completer.py        # 自动补全
│   └── utils/
│       ├── __init__.py
│       ├── diff.py             # diff 计算
│       └── truncate.py         # 文本截断
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_tools.py
│   ├── test_agent.py
│   ├── test_message_invariant.py
│   ├── test_truncate.py
│   ├── test_cli.py
│   ├── test_intent.py
│   ├── test_plugins.py
│   ├── test_evals.py
│   └── test_scenarios.py
├── evals/
│   ├── __init__.py
│   ├── run_eval.py             # LangSmith 评估执行
│   ├── run_local.py            # 本地评估运行器 (6场景40用例, 429重试)
│   ├── evaluators.py           # 7 个自定义评估器
│   ├── _inspect.py             # 评估结果检查辅助
│   ├── analyze_traces.py       # LangSmith trace 聚合分析
│   ├── compare_runs.py         # 对比分析
│   ├── detect_anomalies.py     # 异常检测
│   ├── trace_to_eval.py        # trace→评估用例
│   ├── utils.py                # LangSmith Client 工具
│   └── datasets/
│       ├── __init__.py
│       └── create_datasets.py  # LangSmith 评估数据集创建
└── docs/
    ├── technical-doc.md         # 本文档
    ├── evaluation-guide.md     # 评测方法文档
    ├── evaluation-report-20260607.md  # 当前评测基线报告
    ├── UPGRADE_PLAN.md          # 能力演进路线
    └── superpowers/
        └── specs/
            └── 2026-06-06-*.md  # 设计文档
```
