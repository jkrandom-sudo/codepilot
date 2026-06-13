"""Web page fetching tool.

Fetches and converts web pages to markdown/text
for the agent to read.
"""
from __future__ import annotations

from langchain_core.tools import tool

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment,misc]

try:
    from markdownify import markdownify as md_convert
except ImportError:
    md_convert = None  # type: ignore[assignment,misc]


def _html_to_markdown(html: str) -> str:
    if md_convert is not None:
        return md_convert(html, heading_style="ATX")
    import re
    text = re.sub(r"<head[^>]*>.*?</head>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<h[1-6][^>]*>", "\n## ", text, flags=re.IGNORECASE)
    text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _html_to_text(html: str) -> str:
    import re
    text = re.sub(r"<head[^>]*>.*?</head>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_private_ip(host: str) -> bool:
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    except ValueError:
        return False


def _resolved_addresses_blocked(host: str) -> str | None:
    if not host:
        return None
    if _is_private_ip(host):
        return None
    import socket
    try:
        info = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    for entry in info:
        try:
            addr = entry[4][0]
        except (IndexError, TypeError):
            continue
        if _is_private_ip(addr):
            return f"Blocked: {host} resolves to private/internal address {addr}"
    return None

_BLOCKED_HOSTS = frozenset({
    "169.254.169.254", "metadata.google.internal", "metadata.internal",
    "metadata", "metadata.azure.internal",
})

_BLOCKED_DOMAIN_SUFFIXES = (".internal", ".local", ".localhost")


def _is_blocked_url(url: str) -> str | None:
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except Exception:
        return "Invalid URL"

    host_lower = host.lower()
    if host_lower in _BLOCKED_HOSTS:
        return f"Blocked: {host} is a metadata endpoint"
    if any(host_lower.endswith(s) for s in _BLOCKED_DOMAIN_SUFFIXES):
        return f"Blocked: {host} resolves to internal domain"
    if _is_private_ip(host):
        return f"Blocked: {host} is a private/internal IP address"
    resolved_block = _resolved_addresses_blocked(host)
    if resolved_block:
        return resolved_block
    return None


def web_fetch_impl(url: str, format: str = "markdown", timeout: int = 30) -> str:
    if httpx is None:
        return "Error: httpx library not installed. Run: pip install httpx"

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    if url.startswith("http://"):
        url = "https://" + url[7:]

    block_reason = _is_blocked_url(url)
    if block_reason:
        return f"Error: {block_reason}"

    if timeout > 120:
        timeout = 120

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; CodePilot/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(timeout=timeout, follow_redirects=True, max_redirects=5) as client:
            response = client.get(url, headers=headers)
            # Check redirect target is not internal
            if response.url:
                redirect_block = _is_blocked_url(str(response.url))
                if redirect_block:
                    return f"Error: Redirect blocked — {redirect_block}"

        if response.status_code == 403:
            retry_headers = {"User-Agent": "codepilot"}
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers=retry_headers)

        if response.status_code != 200:
            return f"Error: HTTP {response.status_code} for {url}"

        content_type = response.headers.get("content-type", "")
        body = response.text

        if len(body) > 5_000_000:
            return f"Error: Response too large ({len(body)} bytes, max 5MB)"

        if format == "html":
            return body[:50000]

        if "text/html" in content_type or body.strip().startswith("<"):
            if format == "text":
                result = _html_to_text(body)
            else:
                result = _html_to_markdown(body)
        else:
            result = body

        if len(result) > 50000:
            result = result[:50000] + "\n\n[Content truncated at 50000 chars]"

        return result
    except httpx.TimeoutException:
        return f"Error: Request timed out after {timeout}s"
    except httpx.ConnectError as e:
        return f"Error: Connection failed: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool
def web_fetch(url: str, format: str = "markdown", timeout: int = 30) -> str:
    """Fetch content from a URL and convert to markdown, text, or HTML.

    Automatically upgrades HTTP to HTTPS. Converts HTML to markdown by default.
    Handles Cloudflare 403 by retrying with honest user-agent.

    Args:
        url: The URL to fetch (must start with http:// or https://)
        format: Output format - "markdown" (default), "text", or "html"
        timeout: Timeout in seconds (max 120, default 30)
    """
    return web_fetch_impl(url, format, timeout)
