"""Live web search and URL content retrieval using the Exa API."""
import asyncio
from typing import Annotated, Optional
from exa_py import Exa
from server.services.settings_service import get_effective_settings
from .sandbox import safe_tool_response


def _get_exa_client() -> Optional[Exa]:
    api_key = get_effective_settings().tools.exa.api_key
    if not api_key:
        return None
    return Exa(api_key=api_key)


@safe_tool_response
async def search_web(
    query: Annotated[str, "Natural language search query"],
) -> str:
    """Search the live web for real-time information, documentation, and facts."""
    exa = _get_exa_client()
    if exa is None:
        return "[TOOL_ERROR] EXA_API_KEY is not configured in Settings. Proceed without web search."

    results = await asyncio.to_thread(
        exa.search,
        query,
        type="auto",
        system_prompt="Prefer official sources and avoid duplicate results",
        num_results=get_effective_settings().tools.exa.max_results,
        contents={
            "highlights": {"numSentences": 2, "highlightsPerUrl": 2},
            "summary": {"query": query},
        },
    )
    if not results.results:
        return f"[SEARCH_RESULT] No relevant sources found for query: '{query}'."
    formatted = []
    for i, r in enumerate(results.results, 1):
        title = getattr(r, "title", "Untitled")
        url = getattr(r, "url", "")
        summary = getattr(r, "summary", "").strip()
        highlights = getattr(r, "highlights", [])
        snippet = f"[{i}] {title}\nURL: {url}"
        if summary:
            snippet += f"\nSummary: {summary}"
        if highlights:
            snippet += f"\nKey points: {' '.join(h.strip() for h in highlights)}"
        formatted.append(snippet)
    return "\n\n---\n\n".join(formatted)


@safe_tool_response
async def read_url_content(
    url: Annotated[str, "URL to fetch and extract text from"],
) -> str:
    """Extract clean text content from a target URL (capped at 3,000 characters)."""
    exa = _get_exa_client()
    if exa is None:
        return "[TOOL_ERROR] EXA_API_KEY is not configured in Settings. Unable to fetch URL content."

    results = await asyncio.to_thread(
        exa.get_contents,
        urls=[url],
        text={"maxCharacters": 3000},
        summary={"query": "Key technical points and summary"},
    )
    if not results.results:
        return f"[FETCH_FAILED] Unable to extract content from {url}."
    page = results.results[0]
    title = getattr(page, "title", "Untitled")
    summary = getattr(page, "summary", "").strip()
    text = getattr(page, "text", "").strip()
    out = f"TITLE: {title}\nURL: {page.url}\n"
    if summary:
        out += f"SUMMARY: {summary}\n\n"
    out += f"CONTENT:\n{text[:3000]}"
    return out