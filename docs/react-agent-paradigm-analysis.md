# ReAct 技术分析：Agent 范式对比与选型

## 1. 引言

大语言模型（LLM）作为 Agent 的"大脑"，需要一种执行框架将语言推理能力转化为实际行动。2022 年，Yao 等人提出 ReAct（Reasoning + Acting）范式，将推理（Thought）与行动（Action）交错执行，成为构建 LLM Agent 的主流模式。

本文从 ReAct 的核心机制出发，深入分析其工作原理、适用场景和局限，并横向对比 Plan-Execute、Reflexion、Multi-Agent、Function-Calling Only 等替代范式，为 Agent 架构选型提供决策依据。

---

## 2. ReAct 核心机制

### 2.1 基本原理

ReAct 的核心思想：**在每一步行动前先推理，根据行动结果再推理**。Agent 在一个循环中交替执行三种操作：

```
┌─────────────────────────────────────────────────┐
│                  ReAct 循环                       │
│                                                   │
│   Question: 用户输入                               │
│       │                                           │
│       ▼                                           │
│   Thought 1: 我需要先读取文件内容 ──────► Action 1: read_file("main.py")  │
│                                           │       │
│                                           ▼       │
│                                      Observation 1: 文件内容...    │
│                                           │       │
│                                           ▼       │
│   Thought 2: 文件中有性能问题... ─────► Action 2: edit_file(...)      │
│                                           │       │
│                                           ▼       │
│                                      Observation 2: Edited main.py  │
│                                           │       │
│                                           ▼       │
│   Thought 3: 修改完成，总结回答 ─────► Answer: 已优化...              │
│                                                   │
└─────────────────────────────────────────────────┘
```

**三要素定义**：

| 要素 | 作用 | 示例 |
|------|------|------|
| **Thought** | 推理当前状态，决定下一步 | "我需要先了解项目结构" |
| **Action** | 调用工具执行具体操作 | `list_dir(".")` |
| **Observation** | 接收工具返回结果 | 目录列表文本 |

### 2.2 与 LangGraph 的映射

在 LangGraph 实现中，ReAct 循环被建模为状态图：

```
Agent 节点 (Thought + Action 选择)  ←→  Tool 节点 (Action 执行 + Observation 返回)
```

一次完整的 ReAct 循环对应 LangGraph 中的两个 superstep：

| ReAct 步骤 | LangGraph 节点 | 消息类型 |
|------------|---------------|----------|
| Thought + Action 选择 | agent | AIMessage(content="Thought...", tool_calls=[...]) |
| Action 执行 | tool_node | ToolMessage(content="Observation...") |
| Observation 传递 | 条件边回 agent | 下一轮 agent 输入 |

**关键实现细节**：

```python
# agent 节点 = Thought + Action 选择
def agent_node(state, llm_with_tools):
    messages = [system_prompt] + state["messages"]
    response = llm_with_tools.invoke(messages)  # LLM 决定 Thought + Action
    return {"messages": [response]}

# tool 节点 = Action 执行 + Observation
def tool_node(state, tools_map):
    # 执行 tool_calls，返回 ToolMessage(Observation)
    ...

# 条件边 = 观察 Observation 后决定继续或终止
def should_continue(state):
    last_msg = state["messages"][-1]
    if last_msg.tool_calls:  # 还有 Action 要执行
        return "tools"
    return END  # Thought 得出结论，终止
```

### 2.3 ReAct 的隐式特性

ReAct 有几个容易被忽视但影响行为的特性：

**1. 单步推理（Myopic Reasoning）**

每一步 Thought 只基于当前 Observation，没有全局规划。Agent 可能：
- 先读 A 文件，再读 B 文件，发现需要回来看 A → 重复读取
- 执行了 5 步后才发现方向错误 → 已消耗大量 token

**2. 上下文窗口约束**

所有 Thought-Action-Observation 都追加到对话历史。长任务下：
- 早期推理被压缩/遗忘
- 重复工具调用（因为"忘了"已经读过）
- 达到 token 上限后性能急剧下降

**3. 工具调用的原子性**

每次只执行一个 Action（或少量并行 Action），无法表达复杂依赖：
- "先读 A 和 B，比较后修改 C" → 至少 3 轮循环
- 无法表达"如果 A > B 则读 C，否则读 D"的条件逻辑

**4. LLM 的决策质量决定上限**

ReAct 将所有决策权交给 LLM。如果 LLM：
- 选错工具 → 浪费一轮
- 参数错误 → 工具报错 → 重试
- 幻觉不存在的工具 → 循环卡死

---

## 3. ReAct 深度分析

### 3.1 优势

| 优势 | 说明 |
|------|------|
| **简洁直观** | 一个循环 + 条件路由，实现简单，调试容易 |
| **强泛化性** | 无需为每个任务定制流程，LLM 自行决定行动序列 |
| **可解释性** | 每步 Thought 可追踪推理过程，比纯 Action 更透明 |
| **错误自纠正** | Observation 提供反馈，LLM 可根据错误调整策略 |
| **工具无关** | 换工具集不影响框架，只需更新 tool 定义 |

### 3.2 劣势

| 劣势 | 根因 | 典型表现 |
|------|------|----------|
| **迭代爆炸** | 无全局规划，逐步探索 | 简单任务 50+ 工具调用 |
| **重复操作** | 上下文遗忘 | 反复读取同一文件 |
| **方向漂移** | 无任务分解 | 执行到一半转向无关操作 |
| **token 浪费** | 每步都带完整历史 | 10 轮后 token 消耗翻倍 |
| **无全局状态** | 只有 messages 列表 | 难以追踪"已完成哪些子任务" |
| **超时风险** | 迭代无上限 | 长任务无限循环直至 API 截断 |

### 3.3 适用的任务模式

ReAct 适合"**探索型**"任务——目标明确但路径未知：

| 适合 | 不适合 |
|------|--------|
| 代码审查：读文件 → 发现问题 → 修复 | 大规模重构：需先规划修改范围和顺序 |
| Bug 调试：读代码 → 搜索日志 → 定位 → 修复 | 批量操作：需对 100 个文件执行相同修改 |
| 信息查询：搜索 → 筛选 → 汇总 | 多步依赖：C 依赖 B 的输出，B 依赖 A 的输出 |
| 小范围编辑：改 1-2 个文件 | 架构决策：需综合评估多种方案后选择 |

### 3.4 工程优化手段

针对 ReAct 的劣势，常见的工程优化（CodePilot 中已采用）：

| 问题 | 优化手段 | 原理 |
|------|----------|------|
| 迭代爆炸 | MAX_ITERATIONS 上限 + summarize_node | 硬性截断 + 优雅终止 |
| 重复操作 | files_context 追踪 + 注入提示 | 让 LLM 知道已读文件 |
| 重复工具调用 | _recent_tool_calls 滑动窗口 + 去重提示 | 3 次以上同调用自动警告 |
| token 浪费 | _compact_messages + _compress_tool_results | 压缩历史、截断大结果 |
| 方向漂移 | System Prompt 效率指令 | "5-10 次调用完成分析，不要 50 次" |
| 无全局规划 | 迭代预算提示 | "你有 ~25 轮，合理分配" |

这些优化是在 ReAct 框架内的**补丁**，而非架构层面的改变。根本性的改进需要换范式。

---

## 4. Agent 范式全景

### 4.1 范式分类

```
Agent 范式
├── 单 Agent
│   ├── ReAct (Reasoning + Acting 交错)
│   ├── Plan-Execute (先规划后执行)
│   ├── Reflexion (自我反思 + 迭代改进)
│   └── Function-Calling Only (纯工具调用，无显式推理)
│
└── 多 Agent
    ├── Supervisor (中心调度)
    ├── Hierarchical (层级委派)
    └── Collaborative (平等协作)
```

### 4.2 各范式详解

---

## 5. Plan-Execute

### 5.1 核心机制

将"规划"和"执行"分离为两个阶段。Planner 先生成完整计划，Executor 按计划逐步执行，执行结果可反馈给 Planner 修订计划。

```
用户输入: "重构 auth 模块，支持 OAuth2"
    │
    ▼
┌─────────────────────────────────┐
│         Planner (LLM)           │
│                                 │
│  Plan:                          │
│  1. 读取当前 auth 模块代码       │
│  2. 分析现有认证流程             │
│  3. 设计 OAuth2 集成方案         │
│  4. 修改 auth/login.py           │
│  5. 修改 auth/routes.py          │
│  6. 添加 OAuth2 配置             │
│  7. 更新测试                     │
└──────────────┬──────────────────┘
               │ Plan
               ▼
┌─────────────────────────────────┐
│        Executor (LLM/工具)       │
│                                 │
│  Step 1: read_file("auth/")     │
│  Step 2: 分析... (LLM 推理)     │
│  Step 3: 设计方案... (LLM 推理)  │
│  Step 4: edit_file("auth/...")  │
│  ...                            │
│                                 │
│  执行结果 → 反馈给 Planner       │
│  Planner 可修订后续计划          │
└─────────────────────────────────┘
```

### 5.2 LangGraph 实现

```python
from langgraph.graph import StateGraph

class PlanExecuteState(TypedDict):
    input: str
    plan: list[str]
    past_steps: list[tuple[str, str]]  # (step, result)
    response: str

# Planner 节点：生成或修订计划
def plan_step(state):
    prompt = f"目标: {state['input']}\n已完成: {state['past_steps']}\n生成计划:"
    plan = llm.invoke(prompt)
    return {"plan": parse_plan(plan)}

# Executor 节点：执行计划中的下一步
def execute_step(state):
    current_step = state["plan"][0]
    result = agent_with_tools.invoke(current_step)  # 可用 ReAct Agent 执行单步
    return {"past_steps": [(current_step, result)]}

# Replanner 节点：根据执行结果修订计划
def replan_step(state):
    prompt = f"原始计划: {state['plan']}\n已完成: {state['past_steps']}\n是否需要修订?"
    new_plan = llm.invoke(prompt)
    return {"plan": parse_plan(new_plan)}

graph = StateGraph(PlanExecuteState)
graph.add_node("planner", plan_step)
graph.add_node("executor", execute_step)
graph.add_node("replanner", replan_step)

graph.add_edge("planner", "executor")
graph.add_edge("executor", "replanner")
# replanner → executor (继续) 或 END (完成)
```

### 5.3 与 ReAct 对比

| 维度 | ReAct | Plan-Execute |
|------|-------|-------------|
| **规划方式** | 隐式（每步推理） | 显式（先出计划） |
| **全局视野** | 无（逐步看） | 有（计划即全局视图） |
| **错误恢复** | 靠 LLM 自行调整 | Replanner 可修订计划 |
| **适用任务** | 简单、短链路 | 复杂、多步骤 |
| **额外开销** | 无 | Planner/Replanner 的 LLM 调用 |
| **计划质量依赖** | — | 计划错误则执行全偏 |
| **灵活性** | 高（随时改方向） | 中（需 Replan 才能改） |

**典型场景**：大规模重构、多文件修改、需要先分析后执行的任务。

---

## 6. Reflexion

### 6.1 核心机制

在 ReAct 基础上增加"自我反思"环节。Agent 执行完一轮后，评估自己的表现，将反思结果注入下一轮，逐步改进。

```
┌───────────────────────────────────────────────────┐
│              Reflexion 循环 (第 n 轮)               │
│                                                     │
│  1. Actor (ReAct Agent) 执行任务                     │
│     └── 生成轨迹: Thought-Action-Observation 序列    │
│                                                     │
│  2. Evaluator 评估执行结果                           │
│     └── 成功/失败 + 评分 + 原因                      │
│                                                     │
│  3. Self-Reflector 生成反思                          │
│     └── "第 3 步选错了工具，应该用 search_code"       │
│     └── "遗漏了检查 test 文件"                       │
│                                                     │
│  4. 反思注入下一轮 Actor 的上下文                     │
│     └── Actor 基于反思调整策略                        │
│                                                     │
└───────────────────────────────────────────────────┘
```

### 6.2 LangGraph 实现

```python
class ReflexionState(TypedDict):
    input: str
    trajectory: list[str]         # 当前轮执行轨迹
    reflections: list[str]        # 历史反思
    evaluation: dict              # 评估结果
    iteration: int
    max_iterations: int

def actor_node(state):
    # ReAct Agent 执行，但 System Prompt 包含历史反思
    reflection_context = "\n".join(state["reflections"])
    prompt = f"反思记录:\n{reflection_context}\n\n任务: {state['input']}"
    trajectory = react_agent.invoke(prompt)
    return {"trajectory": trajectory}

def evaluator_node(state):
    # 评估执行结果
    evaluation = llm.invoke(f"评估以下执行轨迹:\n{state['trajectory']}")
    return {"evaluation": evaluation}

def reflector_node(state):
    # 生成反思
    reflection = llm.invoke(
        f"执行轨迹:\n{state['trajectory']}\n"
        f"评估结果:\n{state['evaluation']}\n"
        f"请反思哪里做得不好，如何改进:"
    )
    return {"reflections": state["reflections"] + [reflection]}

def should_continue(state):
    if state["evaluation"]["success"]:
        return END
    if state["iteration"] >= state["max_iterations"]:
        return END
    return "actor"  # 继续下一轮
```

### 6.3 与 ReAct 对比

| 维度 | ReAct | Reflexion |
|------|-------|-----------|
| **错误处理** | 单步内调整 | 跨轮次反思改进 |
| **学习能力** | 无（每轮独立） | 有（反思累积） |
| **token 消耗** | 单轮 | 多轮 × N 次 |
| **延迟** | 低 | 高（每轮完整执行+评估+反思） |
| **适用场景** | 一次性任务 | 需要迭代改进的任务 |
| **质量上限** | 受限于单次推理 | 随反思轮次提升（理论上） |

**典型场景**：代码生成（生成→测试→修复循环）、方案优化（多次尝试选最优）、竞赛编程。

---

## 7. Function-Calling Only

### 7.1 核心机制

不要求 LLM 输出显式的 Thought 推理过程，直接调用工具。LLM 充当纯工具路由器。

```
用户输入 → LLM → tool_calls → 执行 → 结果 → LLM → 回答
                      ↑                        │
                      └──── 需要更多信息 ────────┘
```

与 ReAct 的区别：LLM 不输出中间推理文本，只输出 tool_calls 和最终回答。

### 7.2 实现对比

```python
# ReAct: LLM 输出 Thought + Action
AIMessage(
    content="我需要先读取文件内容来了解代码结构",  # Thought (显式)
    tool_calls=[{"name": "read_file", "args": {"path": "main.py"}}]
)

# Function-Calling Only: LLM 只输出 Action
AIMessage(
    content="",  # 无推理文本
    tool_calls=[{"name": "read_file", "args": {"path": "main.py"}}]
)
```

### 7.3 与 ReAct 对比

| 维度 | ReAct | Function-Calling Only |
|------|-------|----------------------|
| **推理可见性** | 高（Thought 文本可追踪） | 低（黑箱决策） |
| **token 效率** | 低（Thought 消耗 token） | 高（无额外推理文本） |
| **决策质量** | Thought 引导更准确 | 依赖模型隐式推理能力 |
| **调试难度** | 低（推理链可审计） | 高（无法追踪决策过程） |
| **模型要求** | 中等 | 高（强模型才能隐式推理好） |
| **适用场景** | 需要可解释性 | 简单路由、高性能场景 |

**典型场景**：API 路由（用户问题→调用正确 API）、简单查询（无需多步推理）、token 敏感场景。

---

## 8. Multi-Agent: Supervisor 模式

### 8.1 核心机制

一个中心 Supervisor Agent 负责任务分解和分发，多个专业 Worker Agent 各自执行子任务。

```
用户输入: "为项目添加用户认证功能"
    │
    ▼
┌─────────────────────────────┐
│       Supervisor Agent       │
│                             │
│  分解任务:                    │
│  1. → Coder: 实现认证逻辑     │
│  2. → Reviewer: 审查代码      │
│  3. → Tester: 编写测试        │
│  4. → Coder: 修复问题         │
└──────┬──────┬──────┬────────┘
       │      │      │
       ▼      ▼      ▼
   ┌──────┐┌──────┐┌──────┐
   │Coder ││Review││Tester│
   │Agent ││Agent ││Agent │
   └──┬───┘└──┬───┘└──┬───┘
      │       │       │
      └───────┴───────┘
              │
              ▼
         Supervisor 汇总结果
```

### 8.2 LangGraph 实现

```python
from langgraph.graph import StateGraph, MessagesState, START, END

class SupervisorState(MessagesState):
    next_agent: str
    task_description: str

# Supervisor 决定下一步分配给谁
def supervisor_node(state):
    response = llm.invoke(
        f"任务: {state['task_description']}\n"
        f"当前进度: {state['messages']}\n"
        f"下一步应该分配给哪个 Agent? (coder/reviewer/tester/finish)"
    )
    if "finish" in response.content:
        return {"next_agent": "finish"}
    return {"next_agent": parse_agent(response.content)}

# Coder Agent
def coder_node(state):
    result = coder_react_agent.invoke(state["messages"])
    return {"messages": result}

# Reviewer Agent
def reviewer_node(state):
    result = reviewer_react_agent.invoke(state["messages"])
    return {"messages": result}

# Tester Agent
def tester_node(state):
    result = tester_react_agent.invoke(state["messages"])
    return {"messages": result}

graph = StateGraph(SupervisorState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("coder", coder_node)
graph.add_node("reviewer", reviewer_node)
graph.add_node("tester", tester_node)

graph.add_edge(START, "supervisor")
graph.add_edge("coder", "supervisor")
graph.add_edge("reviewer", "supervisor")
graph.add_edge("tester", "supervisor")

# Supervisor 条件路由
graph.add_conditional_edges("supervisor", lambda s: s["next_agent"], {
    "coder": "coder",
    "reviewer": "reviewer",
    "tester": "tester",
    "finish": END,
})
```

### 8.3 与 ReAct 对比

| 维度 | ReAct (单 Agent) | Supervisor Multi-Agent |
|------|-------------------|----------------------|
| **专业度** | 通用（一个 Agent 做所有事） | 专业（每个 Worker 专注一件事） |
| **并发** | 串行 | 可并行（独立子任务） |
| **上下文隔离** | 共享（易干扰） | 隔离（各自维护） |
| **协调开销** | 无 | Supervisor 的 LLM 调用 + 通信 |
| **实现复杂度** | 低 | 中高 |
| **调试难度** | 低 | 高（跨 Agent 追踪） |
| **适用规模** | 小型任务 | 中大型项目级任务 |

**典型场景**：团队协作模拟（Coder+Reviewer+Tester）、复杂项目（前端+后端+DevOps 分工）。

---

## 9. Multi-Agent: Hierarchical 模式

### 9.1 核心机制

多层级 Supervisor 嵌套。顶层 Supervisor 管理中层 Manager，中层 Manager 管理底层 Worker。

```
         Top Supervisor
        /       |       \
   Frontend    Backend   DevOps
   Manager     Manager   Manager
   /    \      /    \       |
 UI    API   Auth   DB    Deploy
Agent  Agent Agent  Agent Agent
```

### 9.2 与 Supervisor 对比

| 维度 | Supervisor (扁平) | Hierarchical (层级) |
|------|-------------------|---------------------|
| **层数** | 2 层（Supervisor + Worker） | 3+ 层（嵌套 Supervisor） |
| **管理复杂度** | Supervisor 管理所有 Worker | 每层只管理直接下级 |
| **扩展性** | Worker 多时 Supervisor 瓶颈 | 可横向扩展 |
| **适用规模** | 中型（3-8 个 Worker） | 大型（10+ Worker） |
| **调试难度** | 中 | 高（多层追踪） |

**典型场景**：企业级项目（多团队、多子系统）、大规模自动化流水线。

---

## 10. Multi-Agent: Collaborative 模式

### 10.1 核心机制

无中心调度，多个 Agent 平等协作，通过共享状态或消息传递协调。

```
┌─────────┐     ┌─────────┐     ┌─────────┐
│ Agent A  │────►│ Agent B  │────►│ Agent C  │
│ (研究)   │     │ (编码)   │     │ (测试)   │
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │
     └────────────────┴────────────────┘
              共享状态 / 消息总线
```

### 10.2 与 Supervisor 对比

| 维度 | Supervisor | Collaborative |
|------|-----------|---------------|
| **控制流** | 中心化 | 去中心化 |
| **决策** | Supervisor 统一决策 | Agent 间协商 |
| **单点故障** | Supervisor 挂则全挂 | 某个 Agent 挂可降级 |
| **一致性** | 强（统一协调） | 弱（需冲突解决机制） |
| **实现复杂度** | 中 | 高（需要通信协议） |

**典型场景**：辩论式推理（多视角讨论后决策）、去中心化系统、角色扮演。

---

## 11. 全景对比

### 11.1 维度对比矩阵

| 维度 | ReAct | Plan-Execute | Reflexion | Func-Call Only | Supervisor | Hierarchical | Collaborative |
|------|-------|-------------|-----------|----------------|------------|-------------|---------------|
| **规划能力** | 无 | 显式规划 | 无 | 无 | Supervisor 规划 | 分层规划 | 协商规划 |
| **反思能力** | 单步内 | Replan | 跨轮反思 | 无 | 无 | 无 | 可有（Agent 互评） |
| **专业度** | 通用 | 通用 | 通用 | 通用 | 专业分工 | 专业分工 | 专业分工 |
| **实现复杂度** | ★☆☆ | ★★☆ | ★★☆ | ★☆☆ | ★★★ | ★★★ | ★★★★ |
| **token 效率** | 中 | 低 | 低 | 高 | 低 | 低 | 低 |
| **延迟** | 低 | 中 | 高 | 低 | 中 | 高 | 高 |
| **可解释性** | 高 | 高 | 高 | 低 | 中 | 中 | 低 |
| **适用任务规模** | 小 | 中大 | 小中 | 小 | 中大 | 大 | 中大 |
| **错误恢复** | 弱 | 中 | 强 | 弱 | 中 | 中 | 弱 |

### 11.2 场景选型决策树

```
任务需求
│
├── 简单查询/路由？
│   └── Yes → Function-Calling Only
│
├── 需要多步推理？
│   ├── 步骤可预规划？
│   │   └── Yes → Plan-Execute
│   └── 需逐步探索？
│       ├── 可一次完成？
│       │   └── Yes → ReAct
│       └── 需迭代改进？
│           └── Reflexion
│
├── 需要专业分工？
│   ├── 3-8 个角色？
│   │   └── Supervisor Multi-Agent
│   ├── 10+ 个角色？
│   │   └── Hierarchical Multi-Agent
│   └── 需要协商/辩论？
│       └── Collaborative Multi-Agent
│
└── 不确定？
    └── ReAct（最通用的起点）
```

### 11.3 成本-收益分析

以"为项目添加用户认证功能"为例：

| 范式 | 预估 LLM 调用次数 | 预估 token | 成功率 | 耗时 |
|------|-------------------|-----------|--------|------|
| ReAct | 15-30 次 | 50-100K | 70% | 2-5 min |
| Plan-Execute | 5-10 次 (Plan) + 10-20 次 (Exec) | 40-80K | 80% | 3-6 min |
| Reflexion (2 轮) | 30-60 次 | 100-200K | 85% | 5-10 min |
| Func-Call Only | 5-10 次 | 20-40K | 50% | 1-2 min |
| Supervisor (3 Workers) | 5 次 (Sup) + 15-30 次 (Workers) | 60-120K | 85% | 3-8 min |

---

## 12. 混合范式：实用主义的演进路径

### 12.1 从 ReAct 到混合范式

实际项目中，纯范式的局限催生了混合方案：

**ReAct + Plan 提示**（CodePilot 当前方案）

在 ReAct 的 System Prompt 中注入规划指令，让 LLM 在推理时自然产生规划意识：

```
System Prompt 中的规划指令：
"在执行复杂任务时，先用 list_dir + read_file 了解项目结构，
 然后制定修改计划，再逐步执行。
 项目分析控制在 5-10 次工具调用内，不要 50 次。"
```

优势：不增加架构复杂度，仅通过 prompt 引导。劣势：软性约束，LLM 可忽略。

**ReAct + Reflexion 增量改进**

在 ReAct 基础上，当迭代达到上限或工具调用重复 3 次时，触发反思：

```python
def should_continue(state):
    iteration = count_iterations(state)
    if iteration >= MAX_ITERATIONS:
        return "reflect"  # 先反思，再决定是否继续
    if has_repeated_calls(state):
        return "reflect"  # 重复调用时反思
    ...
```

**Plan-Execute + ReAct Executor**

Plan 阶段生成结构化计划，Execute 阶段每个步骤用 ReAct Agent 执行，兼具全局视野和局部灵活性：

```
Planner → [Step1, Step2, Step3]
              │        │        │
              ▼        ▼        ▼
         ReAct #1  ReAct #2  ReAct #3
         Agent     Agent     Agent
```

### 12.2 推荐演进路径

```
Phase 1: ReAct (当前)
    │   单 Agent，简单可靠
    │   优化：prompt 引导 + 迭代限制 + files_context
    │
    ▼
Phase 2: ReAct + Reflexion
    │   增加自我反思能力
    │   优化：重复调用触发反思，失败后换策略
    │
    ▼
Phase 3: Plan-Execute + ReAct Executor
    │   复杂任务先规划后执行
    │   优化：全局计划 + 局部 ReAct 灵活性
    │
    ▼
Phase 4: Supervisor Multi-Agent
        角色专业化分工
        Coder + Reviewer + Tester 独立运行
```

**演进原则**：
- 每一步只增加一个新维度（反思→规划→分工）
- 确保前一阶段稳定后再升级
- 用 LangSmith 追踪对比每个阶段的效果
- 并非所有项目都需要走到 Phase 4

---

## 13. CodePilot 中的 ReAct 实践与反思

### 13.1 当前架构选择

CodePilot 采用 ReAct + prompt 优化的混合方案，选择理由：

1. **CLI 场景适合 ReAct**：用户交互是短对话，不需要复杂规划
2. **单 Agent 调试友好**：终端用户需要看到每步在做什么
3. **Prompt 优化 ROI 高**：0 架构改动，仅通过 prompt 和工程补丁解决了 80% 的问题
4. **渐进演进**：保持 ReAct 框架，未来可无缝接入 Plan-Execute

### 13.2 实测问题与对应范式

| 实测问题 | ReAct 补丁 | 更适合的范式 |
|----------|-----------|-------------|
| 80 次工具调用探索项目 | 迭代限制 + 效率指令 | Plan-Execute（先规划再执行） |
| 重复读取同一文件 | files_context 追踪 | Plan-Execute（计划中已包含文件信息） |
| 方向漂移不产出总结 | summarize_node | Reflexion（反思"我在做什么"） |
| 中文输入英文回复 | 语言指令 | —（prompt 问题，非架构问题） |
| 大规模重构需要多文件协调 | — | Supervisor（Coder + Reviewer 分工） |

### 13.3 LangSmith 驱动的范式选择

接入 LangSmith 后，可用数据驱动范式升级决策：

1. **建立基线**：收集 ReAct 模式下的迭代次数、token 消耗、成功率
2. **识别瓶颈**：哪些任务类型的迭代次数异常高？哪些任务失败率高？
3. **针对性升级**：
   - 高迭代任务 → Plan-Execute
   - 高失败率任务 → Reflexion
   - 多文件任务 → Supervisor
4. **A/B 对比**：同一任务类型对比不同范式的 LangSmith trace

---

## 14. 总结

ReAct 是 LLM Agent 的**最佳起点**——简单、通用、可调试。但它的单步推理本质决定了在复杂任务中的天花板。

选择 Agent 范式的核心原则：

1. **从简单开始**：ReAct 覆盖 80% 场景，先用起来
2. **数据驱动升级**：用 LangSmith 等观测工具量化问题，而非猜测
3. **渐进式演进**：每次只加一个维度（反思→规划→分工）
4. **场景匹配**：没有万能范式，只有最适合当前任务的范式
5. **混合优于纯种**：ReAct + prompt 引导 + 工程补丁，往往优于切换到纯 Plan-Execute

范式之争不是选 A 还是 B，而是在正确的场景选择正确的工具，并保持架构的演进能力。

---

## 参考文献

- Yao et al. "ReAct: Synergizing Reasoning and Acting in Language Models." ICLR 2023.
- Shinn et al. "Reflexion: Language Agents with Verbal Reinforcement Learning." NeurIPS 2023.
- Liu et al. "Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning by Large Language Models." ACL 2023.
- Park et al. "Generative Agents: Interactive Simulacra of Human Behavior." UIST 2023.
- Wu et al. "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." COLM 2024.
- LangGraph Documentation: https://langchain-ai.github.io/langgraph/
