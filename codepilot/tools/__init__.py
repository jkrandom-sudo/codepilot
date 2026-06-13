from codepilot.tools.file_tools import read_file, write_file, edit_file, glob
from codepilot.tools.shell_tool import run_shell
from codepilot.tools.search_tools import grep
from codepilot.tools.web_tool import web_search
from codepilot.tools.web_fetch_tool import web_fetch
from codepilot.tools.git_tool import git_status, git_diff, git_log
from codepilot.tools.task_tool import task
from codepilot.tools.todo_tool import todo_write
from codepilot.tools.skill_tool import skill_list, skill_read
from codepilot.tools.mcp_tool import mcp_list_servers, mcp_list_tools, mcp_call_tool

ALL_TOOLS = [
    read_file,
    write_file,
    edit_file,
    glob,
    run_shell,
    grep,
    web_search,
    web_fetch,
    git_status,
    git_diff,
    git_log,
    task,
    todo_write,
    skill_list,
    skill_read,
    mcp_list_servers,
    mcp_list_tools,
    mcp_call_tool,
]

WRITE_TOOLS = {"write_file", "edit_file", "run_shell"}

READ_ONLY_TOOLS = {
    "read_file", "glob", "grep", "web_search", "web_fetch",
    "git_status", "git_diff", "git_log",
    "skill_list", "skill_read",
    "mcp_list_servers", "mcp_list_tools",
}


def get_tools_for_agent(agent_name: str, all_tools: list | None = None) -> list:
    from codepilot.agent.registry import AgentRegistry
    registry = AgentRegistry()
    tools = all_tools or ALL_TOOLS
    return registry.get_tools_for_agent(agent_name, tools)
