import os
import asyncio
from typing import Annotated
from dotenv import load_dotenv
from exa_py import Exa

load_dotenv(r"C:\Users\prana\Desktop\atlas\agent\.env")

def _get_exa_client() -> Exa:
    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        raise ValueError("Missing EXA_API_KEY in environment variables.")
    return Exa(api_key=api_key)

async def web_search(
    query: Annotated[str, "Natural language search query"],
) -> str:
    """Search the web using Exa and return compressed highlights and summaries."""
    try:
        exa = _get_exa_client()

        # Run synchronous SDK call in thread pool to prevent blocking asyncio loop
        results = await asyncio.to_thread(
            exa.search,
            query,
            type="auto",
            system_prompt="Prefer official sources and avoid duplicate results",
            num_results=5,
            contents={
                "highlights": {"numSentences": 3, "highlightsPerUrl": 3},
                "summary": {"query": query},
            },
        )

        if not results.results:
            return "NO_RESULTS_FOUND: No relevant web sources matched the query."

        formatted_results = []
        for i, r in enumerate(results.results, 1):
            title = getattr(r, "title", "Untitled")
            url = getattr(r, "url", "")
            summary = getattr(r, "summary", "").strip()
            highlights = getattr(r, "highlights", [])
            
            snippet = f"**[{i}] {title}**\nURL: {url}"
            if summary:
                snippet += f"\nSummary: {summary}"
            if highlights:
                hl_str = " ".join(h.strip() for h in highlights)
                snippet += f"\nHighlights: {hl_str}"

            formatted_results.append(snippet)

        return "\n\n---\n\n".join(formatted_results)

    except ValueError as e:
        return f"[AUTH_ERROR]: {e}"
    except (TimeoutError, ConnectionError) as e:
        return f"[NETWORK_ERROR]: Unable to connect to Exa Search API. Check internet connection. Details: {e}"
    except Exception as e:
        err_str = str(e).lower()
        if "connect" in err_str or "timeout" in err_str or "dns" in err_str or "unreachable" in err_str:
            return f"[NETWORK_ERROR]: Connection failed during web search: {e}"
        return f"[API_ERROR]: Exa search request failed: {e}"


async def web_fetch(
    url: Annotated[str, "URL to fetch"],
) -> str:
    """Fetch and extract clean text content from a single webpage."""
    try:
        exa = _get_exa_client()

        results = await asyncio.to_thread(
            exa.get_contents,
            urls=[url],
            text={"maxCharacters": 2500},
            summary={"query": "Key technical points and main concepts"},
        )

        if not results.results:
            return f"FETCH_FAILED: Unable to fetch content from URL: {url}"

        page = results.results[0]
        title = getattr(page, "title", "Untitled")
        summary = getattr(page, "summary", "").strip()
        text = getattr(page, "text", "").strip()

        output = f"**TITLE:** {title}\n**URL:** {page.url}\n"
        if summary:
            output += f"**SUMMARY:** {summary}\n\n"
        output += f"**CONTENT:**\n{text}"

        return output

    except ValueError as e:
        return f"[AUTH_ERROR]: {e}"
    except (TimeoutError, ConnectionError) as e:
        return f"[NETWORK_ERROR]: Network timeout or connection drop while fetching '{url}': {e}"
    except Exception as e:
        err_str = str(e).lower()
        if "connect" in err_str or "timeout" in err_str or "dns" in err_str or "unreachable" in err_str:
            return f"[NETWORK_ERROR]: Failed to connect to '{url}': {e}"
        return f"[API_ERROR]: Failed fetching URL content: {e}"