# CodePilot 架构升级计划

> 参考 OpenCode 设计理念，分 5 个 Phase 逐步升级，每个 Phase 独立可测、向后兼容。

## 实施状态: 全部完成 ✅

| Phase | 内容 | 状态 | 新增文件 |
|-------|------|------|----------|
| 1 | 工具 + 权限 | ✅ 完成 | `config/permissions.py`, `tools/context.py` |
| 2 | 持久化 + 消息 | ✅ 完成 | `storage/db.py`, `storage/models.py`, `storage/resume.py` |
| 3 | 三层压缩 + 截断 | ✅ 完成 | `agent/compaction.py`, `tools/truncation.py` |
| 4 | 多 Agent | ✅ 完成 | `agent/registry.py`, `tools/task_tool.py` |
| 5 | 重入 + 高级 | ✅ 完成 | `plugins/hooks.py`, CLI `--resume`/`--agent` |

**验收**: 70 个测试全部通过，ruff lint 通过，无外部依赖新增。

## 设计原则

1. **渐进式**: 每个 Phase 不破坏现有功能，新旧代码共存过渡
2. **接口先行**: 先定义抽象层/协议，再替换实现
3. **测试覆盖**: 每个 Phase 配套测试，确保不回归
4. **对标 OpenCode**: 架构思想对齐，但用 Python 惯用方式实现（不用 Effect-TS 的函数式风格）

---

## Phase 1: 工具系统 + 权限系统重构

**目标**: 让工具拥有执行上下文、参数校验、细粒度权限控制

### 1.1 ToolContext — 工具执行上下文

**现状**: `@tool` 装饰器函数，参数只有业务字段，无法获知当前会话/Agent/权限
**目标**: 每个工具执行时获取 `ToolContext`，包含 session_id、agent_name、abort_signal、权限检查方法

```python
# codepilot/tools/context.py
class ToolContext:
    session_id: str
    agent_name: str
    mode: str
    working_dir: str
    files_context: list[str]
    abort: threading.Event

    def check_permission(self, tool_name: str, args: dict) -> str:
        """返回 'allow' | 'ask' | 'deny'"""
        ...

    def track_file(self, path: str) -> None:
        """追踪已读文件"""
        ...
```

**改造**: LangGraph 的 tool_node 传入 ToolContext，工具函数通过闭包/RunnableBinding 获取

### 1.2 权限规则集引擎

**现状**: 三模式开关 (plan/confirm/auto)，写操作统一管控
**目标**: 规则集引擎，支持 allow/ask/deny + glob 模式匹配

```python
# codepilot/config/permissions.py
class PermissionRule(BaseModel):
    tool: str          # "edit", "bash", "read", "*" (通配)
    pattern: str        # glob 模式匹配路径/命令，如 "src/**", "rm *"
    action: Literal["allow", "ask", "deny"]

class PermissionRuleset(BaseModel):
    rules: list[PermissionRule]  # 有序，最后匹配的规则生效

    def evaluate(self, tool_name: str, args: dict) -> str:
        """评估权限，返回 allow/ask/deny"""
        ...
```

**预设规则集**:
- `build` (全权限，bash-dangerous=deny)
- `plan` (edit=deny, bash=deny, 其余 allow)
- `confirm` (edit=ask, bash=ask, 其余 allow)

**影响文件**: `config/settings.py` (新增 ruleset 字段), `ui/permissions.py` (重写), `agent/graph.py` (tool_node 用规则集)

### 1.3 工具参数 Schema 验证

**现状**: 依赖 LangChain @tool 自动推断 Schema
**目标**: 显式 Pydantic 模型定义参数，增强校验和文档

```python
class ReadFileArgs(BaseModel):
    path: str = Field(description="File path to read")
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
```

---

## Phase 2: 会话持久化 + 消息模型重构

**目标**: 会话可跨重启恢复，消息支持结构化 Part

### 2.1 存储层 (SQLite)

```python
# codepilot/storage/db.py
class Storage:
    """SQLite-based persistent storage for sessions and messages."""

    def create_session(self, session: SessionInfo) -> None: ...
    def get_session(self, session_id: str) -> SessionInfo | None: ...
    def list_sessions(self, limit: int = 50) -> list[SessionInfo]: ...
    def save_message(self, msg: StoredMessage) -> None: ...
    def get_messages(self, session_id: str) -> list[StoredMessage]: ...
    def update_session(self, session_id: str, **kwargs) -> None: ...
```

**新增依赖**: 无外部依赖，使用 Python 内置 `sqlite3`

**数据库路径**: `~/.codepilot/data/codepilot.db`

### 2.2 Part-based 消息结构

**现状**: 消息 = LangChain BaseMessage 列表，文本和工具结果混在 content 字段
**目标**: 消息 = 元数据 + Part 列表 (TextPart, ToolPart, FilePart, CompactionPart)

```python
# codepilot/storage/models.py
class TextPart(BaseModel):
    type: Literal["text"] = "text"
    content: str

class ToolPart(BaseModel):
    type: Literal["tool"] = "tool"
    tool_name: str
    tool_call_id: str
    args: dict
    output: str | None = None
    state: Literal["running", "completed", "error"] = "running"
    elapsed_ms: int = 0

class FilePart(BaseModel):
    type: Literal["file"] = "file"
    path: str
    content: str

class CompactionPart(BaseModel):
    type: Literal["compaction"] = "compaction"
    summary: str

MessagePart = TextPart | ToolPart | FilePart | CompactionPart

class StoredMessage(BaseModel):
    id: str              # ULID
    session_id: str
    role: Literal["user", "assistant", "system"]
    parts: list[MessagePart]
    created_at: datetime
    token_count: int = 0
```

### 2.3 SessionInfo 模型

```python
class SessionInfo(BaseModel):
    id: str              # ULID
    parent_id: str | None = None  # 子 Agent 会话
    title: str = ""
    agent: str = "build"
    model: str = ""
    mode: str = "confirm"
    created_at: datetime
    updated_at: datetime
    token_count: int = 0
    cost: float = 0.0
    archived: bool = False
```

### 2.4 消息适配层

保持与 LangChain 的兼容: `to_langchain_messages(parts) -> list[BaseMessage]`

---

## Phase 3: 三层上下文压缩

**目标**: 大幅降低 token 消耗，提升长对话稳定性

### 3.1 Pruning (轻量，无需 LLM)

```python
# codepilot/agent/compaction.py

PRUNE_MINIMUM_TOKENS = 20_000   # 至少省这么多才值得 prune
PRUNE_PROTECT_TOKENS = 40_000   # 保留最近这么多 tokens 的工具输出

def prune_tool_outputs(messages: list[BaseMessage], token_budget: int) -> list[BaseMessage]:
    """从后往前扫描工具输出，保留最近的，擦除旧的。

    不需要 LLM 调用，只修改 ToolMessage.content 为摘要。
    """
    ...
```

### 3.2 Compaction (中等，1 次 LLM 调用)

```python
def compact_messages(
    messages: list[BaseMessage],
    llm: BaseChatModel,
    tail_turns: int = 2,
    token_budget: int | None = None,
) -> list[BaseMessage]:
    """用 LLM 总结旧消息，保留最近 tail_turns 轮。

    替代当前的 _compact_messages()，使用专用 compaction prompt。
    """
    ...

COMPACTION_PROMPT = """You are a conversation compaction assistant.
Summarize the following conversation history, focusing on:
1. What the user asked for (original request)
2. What files were read and what was found
3. What changes were made
4. Any errors encountered and how they were resolved
5. Any pending tasks or unresolved issues

Preserve specific file paths, function names, and error messages.
Do NOT include information about the most recent exchanges — those are preserved separately.
"""
```

### 3.3 Overflow (重度，紧急降级)

```python
def overflow_compaction(
    messages: list[BaseMessage],
    llm: BaseChatModel,
    hard_limit: int,
) -> list[BaseMessage]:
    """当 token 超过 provider 硬限制时的紧急降级:
    1. 剥离大块文件内容
    2. 找到 replay 点
    3. 压缩之前所有内容
    """
    ...
```

### 3.4 工具输出截断 + 磁盘溢出

**现状**: 截断后内容丢失
**目标**: 截断内容保存到 `~/.codepilot/truncations/`，Agent 可重新读取

```python
# codepilot/tools/truncation.py
class TruncationStore:
    """将截断的工具输出保存到磁盘，返回文件路径供后续读取。"""

    def truncate_and_save(self, content: str, tool_call_id: str) -> tuple[str, str]:
        """返回 (截断内容, 文件路径)"""
        ...

    def read_full(self, path: str) -> str | None:
        ...
```

---

## Phase 4: 多 Agent 体系

**目标**: 支持多 Agent 类型、子 Agent 派生、Agent 间协作

### 4.1 Agent 类型定义 + 注册表

```python
# codepilot/agent/registry.py

class AgentDef(BaseModel):
    name: str                          # "build", "plan", "explore", "general"
    display_name: str                  # "Build Agent"
    mode: Literal["primary", "subagent"] = "primary"
    prompt: str | None = None         # 自定义系统提示 (覆盖默认)
    model: str | None = None           # 可指定不同模型
    steps: int = 25                    # 最大迭代步数
    temperature: float | None = None
    permissions: PermissionRuleset      # 该 Agent 的权限规则
    tools: list[str] | None = None     # 可用工具列表 (None=全部)
    description: str = ""              # @mention 时的描述

class AgentRegistry:
    _agents: dict[str, AgentDef]

    def get(self, name: str) -> AgentDef: ...
    def list_primary(self) -> list[AgentDef]: ...
    def list_subagents(self) -> list[AgentDef]: ...
    def register(self, agent: AgentDef) -> None: ...
```

**预设 Agent**:

| Agent | mode | steps | tools | 权限 |
|-------|------|-------|-------|------|
| build | primary | 25 | all | build 规则集 |
| plan | primary | 15 | read-only | plan 规则集 |
| explore | subagent | 10 | read/grep/glob/list/bash(read) | read-only + bash=deny |
| general | subagent | 20 | all | 继承父会话 |

### 4.2 Agent 图构建适配

```python
# codepilot/agent/graph.py 改造

def build_agent_graph(
    llm: BaseChatModel,
    agent: AgentDef,          # 替代 mode 参数
    context_window: int | None = None,
    storage: Storage | None = None,   # 持久化层
) -> StateGraph:
    ...
```

### 4.3 task 工具 — 子 Agent 执行

```python
# codepilot/tools/task_tool.py

@tool
def task(
    prompt: str,
    subagent_type: Literal["explore", "general"] = "general",
    background: bool = False,
) -> str:
    """派生子 Agent 执行复杂任务。

    子 Agent 在独立的子会话中运行，完成后返回结果。
    """
    ...
```

执行流程:
1. 创建子 SessionInfo (parent_id = 当前会话)
2. 从 AgentRegistry 获取 subagent 定义
3. 构建 subagent 的 agent graph
4. 运行子循环
5. 收集最终 AI 回复作为结果返回
6. 保存子会话到 Storage

### 4.4 Agent 切换

REPL 中 Tab 键切换 build ↔ plan，`/agent <name>` 命令切换到任意 Agent。

---

## Phase 5: 会话重入 + 高级特性

### 5.1 会话重入 (Resume)

```python
# codepilot/storage/resume.py

def resume_session(session_id: str) -> tuple[REPL, list[BaseMessage]]:
    """从 Storage 加载会话，恢复消息历史和状态。"""
    ...

# CLI 支持
codepilot --resume <session-id>
codepilot --resume-last   # 恢复最近一次会话
```

### 5.2 模型特化提示

```python
# codepilot/agent/prompts.py 改造

def get_model_family(model_name: str) -> str:
    """返回 "claude" | "gpt" | "gemini" | "deepseek" | "default" """
    ...

PROMPT_VARIANTS = {
    "claude": PROMPT_CLAUDE,    # 适配 Claude 的提示风格
    "gpt": PROMPT_GPT,          # 适配 GPT 的提示风格
    ...
}
```

### 5.3 插件钩子系统

```python
# codepilot/plugins/hooks.py

class HookType(Enum):
    MESSAGE_BEFORE_SAVE = "message_before_save"
    SYSTEM_PROMPT_TRANSFORM = "system_prompt_transform"
    TOOL_EXECUTE_BEFORE = "tool_execute_before"
    TOOL_EXECUTE_AFTER = "tool_execute_after"
    COMPACTION = "compaction"

class PluginHook:
    hook_type: HookType
    handler: Callable

class PluginManager:
    def register(self, hook: PluginHook) -> None: ...
    def emit(self, hook_type: HookType, data: dict) -> dict: ...
```

### 5.4 MCP 集成 (远期)

```python
# 通过 MCP 协议动态注册外部工具
# codepilot/mcp/client.py
```

---

## 实施时间线

| Phase | 内容 | 预计改动 | 新增依赖 |
|-------|------|----------|----------|
| 1 | 工具 + 权限 | ~500 行 | 无 |
| 2 | 持久化 + 消息 | ~600 行 | 无 (sqlite3 内置) |
| 3 | 三层压缩 | ~400 行 | 无 |
| 4 | 多 Agent | ~700 行 | 无 |
| 5 | 重入 + 高级 | ~400 行 | 无 |

**每个 Phase 的验收标准**: 现有测试全部通过 + 新增 Phase 测试通过

---

## 目录结构变化

```
codepilot/
  tools/
    __init__.py        ← 更新: 从注册表获取工具
    context.py         ← 新增: ToolContext
    truncation.py      ← 新增: 截断存储
    task_tool.py       ← 新增: 子 Agent 工具
    file_tools.py      ← 改造: 使用 ToolContext
    shell_tool.py      ← 改造: 使用 ToolContext + 规则集
    ...
  agent/
    __init__.py
    graph.py           ← 改造: 接受 AgentDef, 三层压缩
    state.py           ← 改造: 增加 session_id, agent_name
    prompts.py         ← 改造: 模型特化 + Agent 提示
    registry.py        ← 新增: Agent 注册表
    compaction.py      ← 新增: 三层压缩实现
  config/
    permissions.py     ← 新增: 规则集引擎
    settings.py        ← 改造: 增加 rulesets 配置
    ...
  storage/
    __init__.py        ← 新增
    db.py              ← 新增: SQLite 存储层
    models.py          ← 新增: SessionInfo, StoredMessage, Part 模型
    resume.py          ← 新增: 会话重入
  plugins/
    __init__.py        ← 新增
    hooks.py           ← 新增: 钩子系统
  ui/
    repl.py            ← 改造: Agent 切换, 会话恢复, 规则集权限
    permissions.py     ← 重写: 使用规则集引擎
    ...
```
