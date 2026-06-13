from __future__ import annotations

from langchain_core.tools import tool

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None  # type: ignore[assignment,misc]


@tool
def web_search(query: str) -> str:
    """Search the web for information using DuckDuckGo.

    Returns up to 8 results with title, URL, and snippet.
    For fetching a specific URL's content, use web_fetch instead.

    Args:
        query: Search query string
    """
    if DDGS is None:
        return "Error: ddgs library not installed. Run: pip install ddgs"

    try:
        with DDGS(timeout=15) as ddgs:
            results = list(ddgs.text(query, max_results=8))

        if not results:
            return f"No results found for '{query}'"

        formatted = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            formatted.append(f"- {title}\n  URL: {href}\n  {body}")

        return "\n\n".join(formatted)
    except Exception as e:
        return f"Error: {e}"
