"""Deep inspect of LangSmith runs — extract tool calls from child runs."""
import os
from collections import Counter
from langsmith import Client

from codepilot.config.settings import load_config
config = load_config()
api_key = config.langsmith.api_key
os.environ["LANGSMITH_API_KEY"] = api_key
os.environ["LANGSMITH_PROJECT"] = config.langsmith.project
os.environ["LANGSMITH_ENDPOINT"] = config.langsmith.endpoint

client = Client(api_key=api_key, api_url=config.langsmith.endpoint)

# Get project id
projects = list(client.list_projects())
project_id = None
for p in projects:
    if p.name == config.langsmith.project:
        project_id = p.id
        break

if not project_id:
    print(f"Project '{config.langsmith.project}' not found!")
    exit(1)

# Get root runs
root_runs = list(client.list_runs(project_id=project_id, is_root=True, limit=50))
print(f"Total root runs: {len(root_runs)}\n")

# For each root run, get child runs to extract tool calls
for r in root_runs:
    meta = r.metadata or {}
    tags = r.tags or []
    model = meta.get("model", "?")
    mode = "?"
    for t in (tags or []):
        if t.startswith("mode:"):
            mode = t.split(":")[1]

    # Get child runs (tool executions and LLM calls)
    child_runs = list(client.list_runs(project_id=project_id, trace_id=r.trace_id or r.id, limit=100))

    # Extract tool calls from child runs
    tool_names = []
    llm_calls = 0
    for cr in child_runs:
        if cr.run_type == "tool":
            tool_names.append(cr.name)
        elif cr.run_type == "llm" or cr.run_type == "chain":
            llm_calls += 1

    tool_dist = dict(Counter(tool_names))
    iteration_count = sum(1 for cr in child_runs if cr.run_type == "tool")

    print(f"=== Run {str(r.id)[:8]} ===")
    print(f"  name={r.name} | status={r.status} | model={model} | mode={mode}")
    print(f"  total_tokens={r.total_tokens or 0:,} | latency={r.latency or 0:.1f}s")
    print(f"  child_runs={len(child_runs)} | llm_calls={llm_calls} | tool_calls={iteration_count}")
    print(f"  tool_distribution={tool_dist}")

    # Show input preview (first human message)
    inputs = r.inputs or {}
    msgs = inputs.get("messages", [])
    user_msg = ""
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            user_msg = m.get("content", "")[:150]
            break
        elif isinstance(m, dict) and m.get("type") == "human":
            user_msg = m.get("content", "")[:150]
            break
    if user_msg:
        print(f"  user_input={user_msg}")

    # Show output preview (last AI text)
    outputs = r.outputs or {}
    out_msgs = outputs.get("messages", [])
    final_text = ""
    for m in reversed(out_msgs):
        if isinstance(m, dict) and m.get("type") == "ai" and m.get("content") and not m.get("tool_calls"):
            final_text = m.get("content", "")[:200]
            break
    if final_text:
        print(f"  final_output={final_text}")

    print()
