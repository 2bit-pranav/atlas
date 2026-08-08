import os
from typing import Annotated
from dotenv import load_dotenv
from exa_py import Exa

load_dotenv()

exa = Exa(api_key=os.environ["EXA_API_KEY"])

async def web_search(
    query: Annotated[str, "Natural language search query"],
) -> str:
    """
    Search the web using Exa and return rich context for the LLM.
    """
    try:
        results = exa.search(
            query,
            type="auto",
            num_results=5,
            contents={
                "text": {
                    "maxCharacters": 2500,
                },
                "highlights": True,
                "summary": {
                    "query": query,
                },
            },
        )

        if not results.results:
            return "No relevant results were found."

        sections = []

        for i, r in enumerate(results.results, 1):

            title = getattr(r, "title", "")
            url = getattr(r, "url", "")
            summary = getattr(r, "summary", "")
            text = getattr(r, "text", "")

            highlights = getattr(r, "highlights", [])
            highlight_text = "\n".join(f"- {h}" for h in highlights)

            sections.append(f"""
            SOURCE {i}
            TITLE: {title}
            URL: {url}
            SUMMARY: {summary}
            HIGHLIGHTS: {highlight_text}
            CONTENT: {text}
            """.strip())

        return "\n\n" + ("=" * 80 + "\n\n").join(sections)

    except Exception as e:
        return f"Search failed.\n\n{e}"


async def web_fetch(
    url: Annotated[str, "URL to fetch"],
) -> str:
    """
    Fetch one page using Exa's cached crawler.
    """
    try:
        results = exa.get_contents(
            urls=[url],
            text={
                "maxCharacters": 6000,
            },
            highlights=True,
            summary={"query": "Summarize this page."},
        )

        if not results.results:
            return "Unable to fetch webpage."

        page = results.results[0]

        return f"""
        TITLE: {page.title}
        URL: {page.url}
        SUMMARY: {getattr(page, "summary", "")}
        CONTENT: {page.text}
        """.strip()

    except Exception as e:
        return f"Fetch failed.\n\n{e}"
