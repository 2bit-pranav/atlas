import os
from pathlib import Path
import asyncio
from typing import Annotated
from dotenv import load_dotenv
from exa_py import Exa
from .sandbox import safe_tool_response

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

def _get_exa_client() -> Exa:
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        raise ValueError("Missing EXA_API_KEY in environment variables.")
    return Exa(api_key=api_key)


@safe_tool_response
async def web_search(
    query: Annotated[str, "Natural language search query"],
) -> str:
    """Searches the live web for real-time information, documentation, and facts."""
    try:
        exa = _get_exa_client()
        results = await asyncio.to_thread(
            exa.search,
            query,
            type="auto",
            system_prompt="Prefer official sources and avoid duplicate results",
            num_results=4,
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
    except Exception as e:
        return f"[SEARCH_ERROR] Search query failed: {e}"


@safe_tool_response
async def web_fetch(
    url: Annotated[str, "URL to fetch"],
) -> str:
    """Fetches and summarizes text content from a web page URL."""
    try:
        exa = _get_exa_client()
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
        out += f"CONTENT:\n{text}"
        return out
    except Exception as e:
        return f"[FETCH_ERROR] Failed to fetch content from {url}: {e}"