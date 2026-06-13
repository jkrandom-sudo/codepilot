"""Agent type registry and default definitions.

Defines built-in agent types (build, plan) and their
permissions, tool sets, and iteration limits.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from codepilot.config.permissions import PermissionRuleset


class AgentDef(BaseModel):
    name: str = Field(description="Agent identifier, e.g. 'build', 'plan', 'explore'")
    display_name: str = Field(default="", description="Human-readable name")
    agent_mode: Literal["primary", "subagent"] = Field(
        default="primary",
        description="primary = user-selectable, subagent = invoked via task tool",
    )
    workflow: Literal["react", "plan_execute"] = Field(
        default="react",
        description="Execution workflow used by the graph.",
    )
    prompt: str | None = Field(default=None, description="Custom system prompt override")
    model: str | None = Field(default=None, description="Override model for this agent")
    steps: int = Field(default=25, description="Max iteration steps")
    temperature: float | None = Field(default=None)
    permissions: PermissionRuleset = Field(default_factory=PermissionRuleset.build_ruleset)
    tools: list[str] | None = Field(default=None, description="Allowed tools (None=all)")
    description: str = Field(default="", description="Description shown in agent list")
    confirm: bool = Field(
        default=False,
        description="If true, write operations require user confirmation. "
        "If false, all allowed operations execute immediately.",
    )

    @property
    def is_primary(self) -> bool:
        return self.agent_mode == "primary"

    @property
    def is_subagent(self) -> bool:
        return self.agent_mode == "subagent"

    @property
    def is_readonly(self) -> bool:
        return self.permissions.evaluate("edit_file") == "deny"


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentDef] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(AgentDef(
            name="build",
            display_name="Build Agent",
            agent_mode="primary",
            steps=25,
            confirm=True,
            permissions=PermissionRuleset.build_ruleset(),
            description="Default agent with full tool access for development work",
        ))
        self.register(AgentDef(
            name="plan",
            display_name="Plan Agent",
            agent_mode="primary",
            steps=10,
            confirm=False,
            permissions=PermissionRuleset.plan_ruleset(),
            description="Read-only agent for analysis and code exploration. Denies file edits and shell commands.",
        ))
        self.register(AgentDef(
            name="plan-execute",
            display_name="Plan-and-Execute Agent",
            agent_mode="primary",
            workflow="plan_execute",
            steps=25,
            confirm=True,
            permissions=PermissionRuleset.build_ruleset(),
            description="Creates an explicit plan first, then executes it with normal development tools.",
        ))
        self.register(AgentDef(
            name="explore",
            display_name="Explore Subagent",
            agent_mode="subagent",
            steps=10,
            confirm=False,
            permissions=PermissionRuleset.explore_ruleset(),
            tools=["read_file", "glob", "grep", "web_search", "web_fetch",
                    "git_status", "git_diff", "git_log", "skill_list", "skill_read",
                    "mcp_list_servers", "mcp_list_tools"],
            description="Fast read-only codebase search agent. Used for finding files, searching code, and exploring project structure.",
        ))
        self.register(AgentDef(
            name="general",
            display_name="General Subagent",
            agent_mode="subagent",
            steps=20,
            confirm=False,
            permissions=PermissionRuleset.general_ruleset(),
            description="Multi-step research and execution subagent. Has full tool access for complex tasks.",
        ))

    def register(self, agent: AgentDef) -> None:
        if not agent.display_name:
            agent.display_name = agent.name.title() + " Agent"
        self._agents[agent.name] = agent

    def get(self, name: str) -> AgentDef | None:
        return self._agents.get(name)

    def get_or_default(self, name: str) -> AgentDef:
        return self._agents.get(name, self._agents["build"])

    def list_primary(self) -> list[AgentDef]:
        return [a for a in self._agents.values() if a.is_primary]

    def list_subagents(self) -> list[AgentDef]:
        return [a for a in self._agents.values() if a.is_subagent]

    def list_all(self) -> list[AgentDef]:
        return list(self._agents.values())

    def get_tools_for_agent(self, agent_name: str, all_tools: list[Any]) -> list[Any]:
        agent = self.get_or_default(agent_name)
        if agent.tools is None:
            return list(all_tools)
        tool_names = set(agent.tools)
        return [t for t in all_tools if t.name in tool_names]
